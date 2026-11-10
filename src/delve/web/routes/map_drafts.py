"""Dungeon-map drafts (plan 7 Task 13): Claude draws a module's map from a description, or from the book's map page,
as a conversion in the background. Organisers only.

A start answers 202 with the conversion, whose progress arrives as `conversion` events; 409 while a conversion runs.
The open drafts are listed from all the module's conversions, never only the last 20. Nothing is saved in the module
until a draft is kept: a description draft as a new map, a book draft over the map it was drawn for, or as a new map.
Keep refuses a book draft whose rooms don't match its part with 409 and the problems, unless forced. Keeping and
discarding publish `modules`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.responses import Response

from delve.conversions import ConversionRunning, conversion_json
from delve.conversions.dungeon_maps import (
    DraftMismatch,
    discard_draft,
    drafts,
    keep_draft,
    start_book_map,
    start_dungeon_map,
)
from delve.web.auth import Organiser
from delve.web.routes.conversions import _running, conversions
from delve.web.routes.maps import MapName, get_map, map_detail
from delve.web.routes.modules import changed, get_module

router = APIRouter()

NO_DRAFT = "No such draft."


class DescribeIn(BaseModel):
    description: str
    name: MapName | None = None


class FromBookIn(BaseModel):
    map: str | None = None
    page: str
    part: str | None = None


class KeepIn(BaseModel):
    name: MapName | None = None
    force: bool = False


async def _started(start: Any) -> dict:
    try:
        return conversion_json(await start)
    except ConversionRunning as error:
        raise _running(error) from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.post("/api/modules/{module_id}/map-drafts", status_code=202)
async def describe(request: Request, principal: Organiser, module_id: str, body: DescribeIn) -> dict:
    """Draw a map from the description; 422 for an empty one."""
    get_module(request, module_id)
    return await _started(start_dungeon_map(conversions(request.app), module_id, body.name, body.description))


@router.post("/api/modules/{module_id}/map-drafts/from-book", status_code=202)
async def from_book(request: Request, principal: Organiser, module_id: str, body: FromBookIn) -> dict:
    """Draw the map `map` (else a new map) from the book's picture `page`, a map page or a full-page picture, with the
    rooms of the text `part`; 422 for another picture, 404 for an unknown map or part."""
    module = get_module(request, module_id)
    if body.map is not None:
        get_map(module, body.map)
    try:
        start = start_book_map(conversions(request.app), module_id, body.map, body.page, part=body.part)
        return await _started(start)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such text.") from None


@router.get("/api/modules/{module_id}/map-drafts")
def list_drafts(request: Request, principal: Organiser, module_id: str) -> list[dict]:
    """The open drafts, newest first: done, and neither kept nor discarded."""
    get_module(request, module_id)
    return drafts(request.app.state.storage, module_id)


@router.post("/api/modules/{module_id}/map-drafts/{conversion_id}/keep", status_code=201)
def keep(request: Request, principal: Organiser, module_id: str, conversion_id: str, body: KeepIn) -> dict:
    """Save the draft in the module; the module's map it made or replaced. 409 with `problems` for a draft whose rooms
    don't match its part, unless `force`."""
    get_module(request, module_id)
    storage = request.app.state.storage
    try:
        kept = keep_draft(storage, module_id, conversion_id, body.name, force=body.force)
    except KeyError:
        raise HTTPException(status_code=404, detail=NO_DRAFT) from None
    except DraftMismatch as error:
        raise HTTPException(status_code=409, detail={"error": str(error), "problems": error.problems}) from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    changed(request, module_id)
    module = get_module(request, module_id)
    return map_detail(module, get_map(module, kept.name))


@router.delete("/api/modules/{module_id}/map-drafts/{conversion_id}", status_code=204)
def discard(request: Request, principal: Organiser, module_id: str, conversion_id: str) -> Response:
    get_module(request, module_id)
    try:
        discard_draft(request.app.state.storage, module_id, conversion_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=NO_DRAFT) from None
    return Response(status_code=204)
