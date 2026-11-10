"""The DM's tools for `delve dm-bridge` (spec §6.2): the tool host over localhost, behind a per-process secret.

The guard lets these routes through only for a loopback client that sends `X-Delve-Bridge: <secret>`, the secret of
this process (`app.state.bridge_secret`); the owner token alone never reaches them. A call runs in the campaign's
running beat. After a mutating call that wasn't refused, the table is told what may have changed, in one `changed`
event (DEL-168): `{campaign_id, areas, maps}`, the areas its `ToolSpec` names (a batch's, those of the steps that
ran), with every map of the campaign when `map_state` is among them; a call that changes nothing a seat reads (a roll,
a DM note) tells nothing. The story entries a call makes are told by the table as they are made. A picture the call
requested is painted from then on, in the background (`delve.play.images`), so the answer never waits for it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from delve.dice import SystemRng
from delve.dm.tools import ToolHost
from delve.dm.tools.composites import BATCH
from delve.dm.tools.schema import AREAS
from delve.play import images
from delve.play.table import current_beat
from delve.web.routes.preferences import image_paid

router = APIRouter()

NO_BEAT = {"error": "no beat is running"}


def tool_host(request: Request) -> ToolHost:
    """The app's tool host, made on first use over its storage, with the system's dice and the app's clock."""
    host = getattr(request.app.state, "tool_host", None)
    if host is None:
        app = request.app
        host = ToolHost(
            app.state.storage,
            SystemRng,
            image_paid=lambda job: image_paid(app, job),
            catalogs=app.state.registries.catalogs,
            clock=app.state.clock,
        )
        request.app.state.tool_host = host
    return host


class CallIn(BaseModel):
    name: str
    args: dict[str, Any] = {}


@router.get("/internal/dm/tools")
def list_tools(request: Request) -> list[dict]:
    return [
        {"name": spec.name, "description": spec.description, "inputSchema": spec.params}
        for spec in tool_host(request).specs()
    ]


@router.post("/internal/dm/{campaign_id}/call")
async def call_tool(request: Request, campaign_id: str, body: CallIn) -> dict:
    storage = request.app.state.storage
    beat = current_beat(storage, campaign_id)
    if beat is None or beat.status != "running":
        raise HTTPException(status_code=409, detail=NO_BEAT)
    host = tool_host(request)
    result = await run_in_threadpool(host.call, campaign_id, beat.id, body.name, body.args)
    spec = host.spec(body.name)
    if spec is not None and spec.mutates and "error" not in result:
        _changed(request, campaign_id, areas_of(host, body.name, result))
        # A picture tool answered at once; its painting runs now, in the background, never in the beat's way.
        from delve.web.routes.play import table_of  # it imports this module's `tool_host`

        images.schedule_waiting(table_of(request.app), campaign_id)
    return result


def areas_of(host: ToolHost, name: str, result: dict[str, Any]) -> set[str]:
    """What a call that wasn't refused may have changed: its tool's areas, every area for a tool that names none, and
    for a batch those of the steps that ran and weren't refused."""
    if name == BATCH:
        steps = [r for r in result.get("results") or [] if isinstance(r, dict) and isinstance(r.get("result"), dict)]
        return set().union(
            *(areas_of(host, step["tool"], step["result"]) for step in steps if "error" not in step["result"])
        )
    spec = host.spec(name)
    if spec is None or not spec.mutates:
        return set()
    return set(AREAS if spec.areas is None else spec.areas)


def _changed(request: Request, campaign_id: str, areas: set[str]) -> None:
    """One event for the call, however much it changed, so that each seat reads the state again once (DEL-168)."""
    if not areas:
        return
    maps = request.app.state.storage.map_states.list(campaign_id) if "map_state" in areas else []
    data = {"campaign_id": campaign_id, "areas": [a for a in AREAS if a in areas], "maps": list(maps)}
    request.app.state.events.publish("changed", data, scope="table", campaign_id=campaign_id)
