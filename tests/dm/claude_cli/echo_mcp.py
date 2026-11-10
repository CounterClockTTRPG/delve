"""A tiny stdio MCP server named `delve`, standing in for `delve dm-bridge` in the provider tests.

`echo` answers its arguments as JSON; `fail` answers an error result. Every call is appended to the file named by
`ECHO_MCP_LOG`, so a test can see that the fake `claude` really called it.
"""

from __future__ import annotations

import asyncio
import json
import os

import mcp.server.stdio
from mcp import types
from mcp.server.lowlevel import Server

server = Server("delve")
OPEN_SCHEMA = {"type": "object", "additionalProperties": True}


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(name="echo", description="Answer the arguments.", inputSchema=OPEN_SCHEMA),
        types.Tool(name="fail", description="Answer an error.", inputSchema=OPEN_SCHEMA),
    ]


def _log(name: str, arguments: dict) -> None:
    log = os.environ.get("ECHO_MCP_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"name": name, "args": arguments, "secret": os.environ.get("DELVE_BRIDGE_SECRET")}))
            fh.write("\n")


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
    _log(name, arguments)
    if name == "fail":
        text = json.dumps({"error": "it failed", "candidates": ["the hidden vault"]})
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)], isError=True)
    text = json.dumps({"echo": arguments})
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], isError=False)


async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
