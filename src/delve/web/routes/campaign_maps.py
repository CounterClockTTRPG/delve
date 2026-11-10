"""A campaign's own maps (campaign maps, 2026-10-23), in the shapes the map editor uses for a module's: list, make,
read, save, rename, delete, render, feature names, simplify; under `/api/campaigns/{id}/own-maps`, since
`/maps/{name}` there is the map state's.

Organisers only. An own map is always a playable `map`, never a library or the default, and never the module's: it
is stored with the campaign (`delve.play.campaign_maps`) and includes from the libraries of the revision the campaign
pinned. A name the campaign already plays (its module's maps and its own) is refused (409), as is a source that
doesn't parse (400 `{error, line, column}`). Once the table has played on an own map it keeps its name, and it isn't
removed while a character stands on it (409). Every change publishes the event `campaigns`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from delve.domain.campaigns import Campaign
from delve.domain.modules import ModuleMap, Revision
from delve.maps import state as map_state
from delve.maps.dsl import DmapError
from delve.maps.sources import library_sources, parse_map, parse_source
from delve.web.auth import Organiser
from delve.web.routes.campaigns import get_campaign, pinned_revision
from delve.web.routes.dsl import parse_error, render_json
from delve.web.routes.maps import MapName, RenderIn, SimplifyIn, SourceIn, _origins, _simplify, feature_groups

router = APIRouter()

PATH = "/api/campaigns/{campaign_id}/own-maps"


class OwnMapIn(BaseModel):
    name: MapName


class OwnMapUpdate(BaseModel):
    source: str | None = None
    new_name: MapName | None = None


def own_detail(campaign: Campaign, own: ModuleMap) -> dict[str, Any]:
    return {
        "campaign_id": campaign.id,
        "module_id": campaign.module_id,
        "name": own.name,
        "role": "map",
        "is_default": False,
        "own": True,
        "updated_at": None,
        "source": own.source,
    }


def _own(request: Request, campaign_id: str, name: str) -> tuple[Campaign, ModuleMap]:
    campaign = get_campaign(request, campaign_id)
    found = request.app.state.storage.campaign_maps.get(campaign_id, name)
    if found is None:
        raise HTTPException(status_code=404, detail="No such map of this campaign's own.")
    return campaign, found


def _changed(request: Request, campaign_id: str) -> None:
    request.app.state.events.publish("campaigns", {"id": campaign_id})


def _stood_on(request: Request, campaign_id: str, name: str) -> tuple[bool, bool]:
    """Whether the table has played on the map, and whether a character stands on it now."""
    raw = request.app.state.storage.map_states.get(campaign_id, name)
    if raw is None:
        return False, False
    state = map_state.from_json(raw)
    return True, any(c.location is not None for c in state.characters.values())


async def _check_parses(revision: Revision, name: str, source: str) -> None:
    try:
        await run_in_threadpool(parse_source, source, library_sources(revision.maps, exclude=name))
    except DmapError as error:
        raise parse_error(error) from None


@router.get(PATH)
def list_own_maps(request: Request, principal: Organiser, campaign_id: str) -> list[dict]:
    campaign = get_campaign(request, campaign_id)
    return [own_detail(campaign, m) for m in request.app.state.storage.campaign_maps.list(campaign_id)]


@router.post(PATH, status_code=201)
def create_own_map(request: Request, principal: Organiser, campaign_id: str, body: OwnMapIn) -> dict:
    """A new, empty map of the campaign's own."""
    campaign = get_campaign(request, campaign_id)
    if any(m.name == body.name for m in pinned_revision(request, campaign).maps):
        raise HTTPException(status_code=409, detail="The campaign already plays a map with this name.")
    storage = request.app.state.storage
    storage.campaign_maps.put(campaign_id, body.name, "")
    _changed(request, campaign_id)
    return own_detail(campaign, storage.campaign_maps.get(campaign_id, body.name))


@router.get(PATH + "/{name}")
def read_own_map(request: Request, principal: Organiser, campaign_id: str, name: str) -> dict:
    campaign, found = _own(request, campaign_id, name)
    return own_detail(campaign, found)


@router.put(PATH + "/{name}")
async def update_own_map(
    request: Request, principal: Organiser, campaign_id: str, name: str, body: OwnMapUpdate
) -> dict:
    """Save the source, or the name; a source that doesn't parse is left as it was (400)."""
    campaign, found = _own(request, campaign_id, name)
    revision = pinned_revision(request, campaign)
    new_name = body.new_name if body.new_name is not None else name
    if new_name != name:
        if any(m.name == new_name for m in revision.maps):
            raise HTTPException(status_code=409, detail="The campaign already plays a map with this name.")
        if _stood_on(request, campaign_id, name)[0]:
            raise HTTPException(status_code=409, detail="The table has played on this map, so it keeps its name.")
    source = found.source if body.source is None else body.source
    if body.source is not None:
        await _check_parses(revision, name, source)
    storage = request.app.state.storage
    with storage.transaction():
        if new_name != name:
            storage.campaign_maps.delete(campaign_id, name)
        storage.campaign_maps.put(campaign_id, new_name, source)
    _changed(request, campaign_id)
    return own_detail(campaign, storage.campaign_maps.get(campaign_id, new_name))


@router.delete(PATH + "/{name}", status_code=204)
def delete_own_map(request: Request, principal: Organiser, campaign_id: str, name: str) -> Response:
    _own(request, campaign_id, name)
    if _stood_on(request, campaign_id, name)[1]:
        raise HTTPException(status_code=409, detail="A character is on this map; move the party off it first.")
    request.app.state.storage.campaign_maps.delete(campaign_id, name)
    _changed(request, campaign_id)
    return Response(status_code=204)


@router.post(PATH + "/{name}/render")
async def render_own_map(request: Request, principal: Organiser, campaign_id: str, name: str, body: RenderIn) -> dict:
    """`{svg, diagnostics}` for the editor's buffer (`source`), or the stored source; includes from the revision."""
    campaign, _ = _own(request, campaign_id, name)
    revision = pinned_revision(request, campaign)
    try:
        dmap = await run_in_threadpool(parse_map, revision.maps, name, body.source)
    except DmapError as error:
        raise parse_error(error) from None
    return await run_in_threadpool(render_json, dmap, body.renderer)


@router.post(PATH + "/{name}/feature-names")
async def own_feature_names(
    request: Request, principal: Organiser, campaign_id: str, name: str, body: SourceIn
) -> dict:
    campaign, found = _own(request, campaign_id, name)
    revision = pinned_revision(request, campaign)
    source = found.source if body.source is None else body.source
    origins = await run_in_threadpool(_origins, source, library_sources(revision.maps, exclude=name))
    return feature_groups(origins)


@router.post(PATH + "/{name}/simplify")
async def simplify_own_map(
    request: Request, principal: Organiser, campaign_id: str, name: str, body: SimplifyIn
) -> dict:
    """The simplified source with every change, applied or left alone. Nothing is saved: the editor applies it."""
    campaign, found = _own(request, campaign_id, name)
    revision = pinned_revision(request, campaign)
    source = found.source if body.source is None else body.source
    try:
        result = await run_in_threadpool(
            _simplify, source, library_sources(revision.maps, exclude=name), body.door_spurs
        )
    except DmapError as error:
        raise parse_error(error) from None
    return {**result.as_dict(), "saved": False}
