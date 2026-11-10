"""`delve dm-bridge`: the DM's tools as a stdio MCP server, forwarded to the running Delve (spec §6.2).

`claude -p` starts it from the MCP config Delve writes, as the server `delve`, so the DM sees each tool as
`mcp__delve__<name>`. It lists the tool host's tools from `GET /internal/dm/tools` once, and forwards every call to
`POST /internal/dm/<campaign>/call` with the per-process secret in `X-Delve-Bridge`. A result is one text content,
its JSON; a refusal (`{"error", …}`) is marked `isError`. It writes nothing to stdout but the MCP protocol: logs go to
stderr. This is the only module that imports `mcp`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

__all__ = ["BRIDGE_HEADER", "SECRET_ENV", "SERVER_NAME", "DelveClient", "build_server", "main", "serve"]

SERVER_NAME = "delve"
SECRET_ENV = "DELVE_BRIDGE_SECRET"
BRIDGE_HEADER = "X-Delve-Bridge"
# A tool call is fast (plan 2a: under 50 ms at p95); this only stops a wedged Delve from hanging the DM.
CALL_TIMEOUT = 120

log = logging.getLogger(__name__)


class DelveUnavailable(Exception):
    """The running Delve didn't answer, or answered something that isn't JSON."""


class DelveClient:
    """The internal endpoint of the Delve at `url`, for one campaign. Never through a proxy: it is on this machine."""

    def __init__(self, url: str, campaign_id: str, secret: str) -> None:
        self.url = url.rstrip("/")
        self.campaign_id = campaign_id
        self._secret = secret
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._tools: list[dict[str, Any]] | None = None

    async def tools(self) -> list[dict[str, Any]]:
        """`[{name, description, inputSchema}]`, fetched once."""
        if self._tools is None:
            status, body = await asyncio.to_thread(self._request, "GET", "/internal/dm/tools")
            if status != 200 or not isinstance(body, list):
                raise DelveUnavailable(f"Delve answered {status} for the tool list: {_error_of(body)}")
            self._tools = body
        return self._tools

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """The tool's answer; `{"error": …}` when it refused, or Delve did."""
        try:
            status, body = await asyncio.to_thread(
                self._request, "POST", f"/internal/dm/{self.campaign_id}/call", {"name": name, "args": args}
            )
        except DelveUnavailable as error:
            return {"error": str(error)}
        if not isinstance(body, dict):
            return {"error": f"Delve answered {status} without a result"}
        return body

    def _request(self, method: str, path: str, payload: Any = None) -> tuple[int, Any]:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(f"{self.url}{path}", data=data, method=method)
        request.add_header(BRIDGE_HEADER, self._secret)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self._opener.open(request, timeout=CALL_TIMEOUT) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as answer:
            status, raw = answer.code, answer.read()
        except (urllib.error.URLError, OSError) as error:
            raise DelveUnavailable(f"Delve is not reachable at {self.url}: {error}") from None
        try:
            return status, json.loads(raw)
        except ValueError:
            raise DelveUnavailable(f"Delve answered {status} with something that isn't JSON") from None


def _error_of(body: Any) -> str:
    return str(body.get("error", body)) if isinstance(body, dict) else str(body)


def build_server(delve: DelveClient) -> Server:
    """The MCP server `delve` over `delve`'s internal endpoint. Arguments are checked by the tool host, whose answers
    say how to call the tool, not by the SDK."""
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=tool["name"], description=tool["description"], inputSchema=tool["inputSchema"])
            for tool in await delve.tools()
        ]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        result = await delve.call(name, arguments or {})
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            isError="error" in result,
        )

    return server


async def serve(url: str, campaign_id: str, secret: str) -> None:
    """Serve the DM's tools over this process's stdin and stdout until the client closes them."""
    server = build_server(DelveClient(url, campaign_id, secret))
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(url: str, campaign_id: str, secret: str) -> int:
    logging.basicConfig(level=logging.WARNING, format="delve dm-bridge: %(message)s")  # stderr, never stdout
    asyncio.run(serve(url, campaign_id, secret))
    return 0
