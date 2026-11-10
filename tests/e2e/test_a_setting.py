"""A setting end to end (settings plan Task 15), the owner's hand checks 2 and 4 over the API: `create_app` on the tiny
reference, with a fake DM whose tool calls run through the app's tool host, as the bridge runs the real one's.

An organiser adds a page, Oakhollow (a homebrew village, with a DM-only section), and a DM-only fact, overrides
Hardby, and reverts it to the shipped page. Campaign A's beat proposes a fact; A's seat finds it in its Setting tab and
in Ask the DM's prompt, while campaign B's seat doesn't, until the organiser accepts it. The beat also proposes a public
edit of a DM-only page, which stays DM-only. No seat ever gets the DM-only fact, page or section.
"""

from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from delve.dice import SystemRng
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.dm.provider import ToolCall, ToolResult
from delve.dm.tools import ToolHost
from delve.domain.backends import Registry
from delve.domain.modules import ModuleMap
from delve.play import seats
from delve.play.table import current_beat
from delve.rules.catalog import register_rulesets
from delve.setting.catalog import register_settings
from delve.storage import open_storage
from delve.web.app import create_app
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.rulesets import osric_catalogs
from tests.web.conftest import BASE_URL, make_registries, playing

SECRET = "SECRET-XYZZY"
MILL = "The Oakhollow mill burned in 576 CY."
OAKHOLLOW = f"A homebrew village on the [[Hardby]] road.\n\n::: dm\n{SECRET}: the miller hides a cult.\n:::\n"
HIDDEN_FACT = f"{SECRET}: the Oakhollow reeve is a doppelganger."
OVERRIDE = "Hardby, as this install tells it: the Despotrix has a new harbour."
QUESTION = "Did the Oakhollow mill burn?"
CELLAR = "The mill cellar"
CELLAR_EDIT = f"{SECRET}: the party found the cult's door in the cellar."
"""The DM's edit of a DM-only page, proposed without `dm_only`: it reaches no seat either."""


class BridgedDM(FakeDM):
    """The fake DM, each of whose tool calls runs through the app's tool host in the campaign's running beat, as
    `delve dm-bridge` runs the real DM's; the call is followed by its result."""

    host: ToolHost | None = None

    async def open(self, spec):
        conversation = await super().open(spec)
        send, dm = conversation.send, self

        async def bridged(text):
            async for event in send(text):
                yield event
                if isinstance(event, ToolCall):
                    beat = current_beat(dm.host.storage, spec.campaign_id)
                    result = await asyncio.to_thread(dm.host.call, spec.campaign_id, beat.id, event.name, event.args)
                    yield ToolResult(event.id, "error" not in result, json.dumps(result))

        conversation.send = bridged
        return conversation


@pytest.fixture
def config(reference_config):
    return reference_config


@pytest.fixture
def dm():
    return BridgedDM(
        [
            [
                ToolCall("p1", "propose_fact", {"text": MILL}),
                ToolCall("p2", "propose_page", {"title": CELLAR, "text": CELLAR_EDIT}),
            ]
        ]
    )


@pytest.fixture
def registries(dm):
    """The web fakes with the bridged DM, OSRIC and the settings over the tiny reference."""
    registries = make_registries()
    registries.dm = Registry()
    registries.dm.register(FAKE_DM_CAPABILITIES, lambda: dm)
    registries.rulesets = Registry()
    registries.catalogs = osric_catalogs()
    register_rulesets(registries.rulesets, registries.catalogs.rulesets)
    registries.settings_ = Registry()
    register_settings(registries.settings_, registries.catalogs.settings)
    return registries


@pytest.fixture
def storage(config):
    storage = open_storage(config)
    yield storage
    storage.close()


@pytest.fixture
def app(config, storage, registries):
    return create_app(config, storage, registries)


@pytest.fixture
def local(app):
    """The organiser's browser, on this machine."""
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as client:
        yield client


@pytest.fixture
def host(app, storage, dm):
    app.state.tool_host = dm.host = ToolHost(storage, SystemRng, catalogs=app.state.registries.catalogs)
    return dm.host


def make_campaign(storage, name: str) -> str:
    module = storage.modules.create(f"The crypt of {name}")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    made = storage.campaigns.create(name, module.id, revision.number, setting="greyhawk", ruleset="osric")
    seats.owner_seat(storage, made.id)
    playing(storage, made.id)  # the session under way (DEL-199): the player's seat doesn't hold the host's acts up
    return made.id


@pytest.fixture
def table(app, storage):
    """Campaigns A and B in Greyhawk, each with a player seat in a browser of its own on the LAN."""
    made, clients = {}, []
    for name, player in (("A", "Ana"), ("B", "Bo")):
        cid = make_campaign(storage, name)
        token = new_seat_token()
        storage.seats.create(cid, player, "en", "player", token_hash=token_hash(token))
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        made[name] = (cid, client)
    yield made
    for client in clients:
        client.__exit__(None, None, None)


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def settings_page(title: str) -> str:
    return f"/api/settings/greyhawk/pages/{quote(title, safe='')}"


def table_page(cid: str, title: str) -> str:
    return f"/api/campaigns/{cid}/setting/pages/{quote(title, safe='')}"


def settle(local, cid: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if local.get(f"/api/campaigns/{cid}/play/state").json()["beat"] is None:
            return
        time.sleep(0.02)
    raise AssertionError("the beat is still running")


def facts_of(seat, cid: str) -> dict[str, str]:
    """The seat's Setting tab's facts that aren't the book's, by text: their origin."""
    found = ok(seat.get(f"/api/campaigns/{cid}/setting/facts"))["facts"]
    return {fact["text"]: fact["origin"] for fact in found if fact["origin"] != "shipped"}


def asked(local, dm, seat, cid: str) -> str:
    """The side pass's prompt for the seat's Ask the DM."""
    before = len(dm.side_prompts)
    ok(seat.post(f"/api/campaigns/{cid}/ask", json={"question": QUESTION}))
    [prompt] = dm.side_prompts[before:]
    return prompt


def everything_a_seat_reads(seat, cid: str) -> str:
    """Every Setting tab route a seat can call about Oakhollow, Hardby and the hidden words, as one text (a search
    for the secret itself would echo it in its `query`)."""
    answers = [
        seat.get(f"/api/campaigns/{cid}/setting"),
        seat.get(f"/api/campaigns/{cid}/setting/facts"),
        seat.get(table_page(cid, "Oakhollow")),
        seat.get(table_page(cid, "Hardby")),
        seat.get(table_page(cid, CELLAR)),
        *(
            seat.get(f"/api/campaigns/{cid}/setting/search", params={"q": q})
            for q in ("Oakhollow", "reeve", "cult", "cellar")
        ),
        seat.get(f"/api/campaigns/{cid}/setting/kinds/place", params={"q": "oak"}),
    ]
    return "\n".join(answer.text for answer in answers)


def test_a_page_added_and_overridden_a_proposal_in_one_campaign_then_all(local, storage, dm, host, table):
    (a, ana), (b, bo) = table["A"], table["B"]

    # The organiser adds a homebrew village, with a DM-only section, and a DM-only fact.
    added = ok(local.put(settings_page("Oakhollow"), json={"kind": "place", "text": OAKHOLLOW}), 201)
    assert (added["origin"], added["revertible"]) == ("addition", False)
    hidden = ok(local.post("/api/settings/greyhawk/facts", json={"text": HIDDEN_FACT, "dm_only": True}), 201)
    assert hidden["dm_only"] is True
    cellar = ok(local.put(settings_page(CELLAR), json={"text": "Under the mill.", "dm_only": True}), 201)
    assert cellar["dm_only"] is True
    for seat, cid in ((ana, a), (bo, b)):
        page = ok(seat.get(table_page(cid, "Oakhollow")))
        assert (page["title"], page["origin"]) == ("Oakhollow", "addition")
        assert page["text"].startswith("A homebrew village") and SECRET not in page["text"]
    assert SECRET in ok(local.get(settings_page("Oakhollow")))["text"], "the organiser reads the DM's section"

    # Hardby overridden, then reverted: the shipped page comes back, for the organiser and the seats.
    shipped = ok(local.get(settings_page("Hardby")))
    assert shipped["origin"] == "shipped"
    override = ok(local.put(settings_page("Hardby"), json={"kind": shipped["kind"], "text": OVERRIDE}), 201)
    assert (override["origin"], override["revertible"], override["text"]) == ("override", True, OVERRIDE)
    assert ok(ana.get(table_page(a, "Hardby")))["text"] == OVERRIDE
    assert local.request("DELETE", settings_page("Hardby"), json={}).status_code == 204
    reverted = ok(local.get(settings_page("Hardby")))
    assert (reverted["origin"], reverted["text"]) == ("shipped", shipped["text"])
    assert ok(bo.get(table_page(b, "Hardby")))["text"] == shipped["text"]

    # Campaign A's beat: the DM proposes a fact, which holds in A at once.
    ok(local.post(f"/api/campaigns/{a}/act", json={"text": "We ask about the mill."}), 202)
    settle(local, a)
    proposal, edit = ok(local.get("/api/settings/greyhawk/proposals"))
    assert (edit["kind"], edit["title"], edit["dm_only"]) == ("edit", CELLAR, True), "an edit of a DM-only page"
    for seat, cid in ((ana, a), (bo, b)):
        assert seat.get(table_page(cid, CELLAR)).status_code == 404
    assert (proposal["kind"], proposal["text"], proposal["campaign_id"], proposal["status"]) == (
        "fact",
        MILL,
        a,
        "pending",
    )
    assert facts_of(ana, a) == {MILL: "campaign"}
    assert "576 CY" in asked(local, dm, ana, a)
    assert facts_of(bo, b) == {}
    assert "576 CY" not in asked(local, dm, bo, b)
    assert MILL not in everything_a_seat_reads(bo, b)

    # Accepted, it is the install's: B's seat finds it too.
    accepted = ok(local.post(f"/api/settings/greyhawk/proposals/{proposal['id']}/accept", json={}))
    assert accepted["proposal"]["status"] == "accepted" and accepted["fact"]["text"] == MILL
    assert [p["id"] for p in ok(local.get("/api/settings/greyhawk/proposals", params={"status": "pending"}))] == [
        edit["id"]
    ]
    assert facts_of(bo, b) == {MILL: "install"}
    assert facts_of(ana, a) == {MILL: "install"}
    assert "576 CY" in asked(local, dm, bo, b)

    # Accepted, the cellar's edit stays the DM's.
    ok(local.post(f"/api/settings/greyhawk/proposals/{edit['id']}/accept", json={}))
    cellar = ok(local.get(settings_page(CELLAR)))
    assert cellar["dm_only"] is True and CELLAR_EDIT in cellar["text"]

    # No seat ever got the DM-only fact, page or section, by any route or through Ask's prompt.
    for seat, cid in ((ana, a), (bo, b)):
        assert seat.get(table_page(cid, CELLAR)).status_code == 404
        assert SECRET not in everything_a_seat_reads(seat, cid)
        assert SECRET not in asked(local, dm, seat, cid)
        assert SECRET not in json.dumps(ok(seat.get(f"/api/campaigns/{cid}/story")))
    assert HIDDEN_FACT in {fact["text"] for fact in ok(local.get("/api/settings/greyhawk/facts"))["own"]}
