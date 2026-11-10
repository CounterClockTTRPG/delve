"""`delve dm-bridge` over stdio (plan 2b Task 4): the MCP SDK's own client talks to the bridge as a subprocess, and the
bridge to a running Delve on a free high port. No `claude` is involved."""

import asyncio
import itertools
import json
import os
import socket
import sys
import threading
import time

import pytest
import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

from delve.config import Config
from delve.dice import SeededRng
from delve.dm.tools import ToolHost, all_specs
from delve.domain.modules import ModuleMap
from delve.play import seats
from delve.play.table import open_beat
from delve.storage import open_storage
from delve.web.app import create_app
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.web.conftest import INDEX_HTML, make_registries

# Ports in use on the owner's machine, and Delve's own default: never ours.
FORBIDDEN_PORTS = {5000, 7777, 7790, 8000, 7810}


def free_socket() -> socket.socket:
    """A socket bound on loopback to a free port the system picks (an ephemeral, high one)."""
    for _ in range(10):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        if sock.getsockname()[1] > 10000 and sock.getsockname()[1] not in FORBIDDEN_PORTS:
            return sock
        sock.close()
    raise RuntimeError("no free high port")


@pytest.fixture
def delve(tmp_path):
    """A running Delve with one campaign in a running beat: `(url, app, storage, campaign, beat)`."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(INDEX_HTML)
    config = Config(data_dir=tmp_path / "data")
    storage = open_storage(config)
    app = create_app(config, storage, make_registries(), static_dir=static)
    seeds = itertools.count(1)
    app.state.tool_host = ToolHost(storage, lambda: SeededRng(next(seeds)), catalogs=over(PlayReference()))
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    beat = open_beat(storage, campaign.id, {"player": seats.owner_seat(storage, campaign.id).id, "character_ids": [], "kind": "act", "text": "Go."})

    sock = free_socket()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[1]}", app, storage, campaign, beat
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        storage.close()


def bridge_params(url: str, campaign_id: str, secret: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "delve", "dm-bridge", "--url", url, "--campaign", campaign_id],
        env={"DELVE_BRIDGE_SECRET": secret, "PATH": os.environ.get("PATH", "")},
    )


async def session_run(params: StdioServerParameters, work):
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        initialized = await session.initialize()
        return initialized, await work(session)


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=60))


def test_bridge_lists_and_calls_over_stdio(delve):
    url, app, storage, campaign, beat = delve

    async def work(session: ClientSession):
        tools = (await session.list_tools()).tools
        rolled = await session.call_tool("roll", {"notation": "1d20", "purpose": "the lever"})
        again = await session.call_tool("roll", {"notation": "1d20", "purpose": "the lever"})
        refused = await session.call_tool("roll", {"notation": "999999d6"})
        unknown = await session.call_tool("no_such_tool", {})
        return tools, rolled, again, refused, unknown

    initialized, (tools, rolled, again, refused, unknown) = run(
        session_run(bridge_params(url, campaign.id, app.state.bridge_secret), work)
    )
    assert initialized.serverInfo.name == "delve"
    assert [t.name for t in tools] == [s.name for s in all_specs()]
    roll = next(t for t in tools if t.name == "roll")
    assert roll.inputSchema == app.state.tool_host.spec("roll").params and roll.description

    assert rolled.isError is False and len(rolled.content) == 1 and rolled.content[0].type == "text"
    result = json.loads(rolled.content[0].text)
    assert 1 <= result["total"] <= 20
    assert json.loads(again.content[0].text) == result  # the stored roll: no re-roll in a beat
    (logged,) = storage.rolls.list(campaign.id)
    assert logged.key.beat == beat.id

    assert refused.isError is True and "error" in json.loads(refused.content[0].text)
    assert unknown.isError is True and json.loads(unknown.content[0].text)["error"] == "Unknown tool 'no_such_tool'."


def test_bridge_with_a_wrong_secret_gets_errors(delve):
    url, _, storage, campaign, _ = delve

    async def work(session: ClientSession):
        with pytest.raises(McpError) as listed:  # the bridge's error response
            await session.list_tools()
        return listed.value, await session.call_tool("roll", {"notation": "1d20"})

    _, (listed, called) = run(session_run(bridge_params(url, campaign.id, "not-the-secret"), work))
    assert "403" in str(listed)
    assert called.isError is True and storage.rolls.list(campaign.id) == []


def test_bridge_needs_its_secret(monkeypatch, capsys):
    from delve.__main__ import main

    monkeypatch.delenv("DELVE_BRIDGE_SECRET", raising=False)
    assert main(["dm-bridge", "--url", "http://127.0.0.1:1", "--campaign", "cmp_000000000000"]) == 2
    out, err = capsys.readouterr()
    assert out == "" and "DELVE_BRIDGE_SECRET" in err
