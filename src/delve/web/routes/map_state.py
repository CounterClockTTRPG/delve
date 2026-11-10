"""A campaign's map state per map, against its pinned revision: positions and discovery per character (spec §7.4).

Organisers only, but for the characters' view, which a seat reads for its own characters, and the host for any
(plateau 4). The characters' view
and the DM view are separate routes (spec §7.5): `view` has no parameter that turns it into the DM view, and when it
can't draw the fog view it answers 409 "map offline", never the full map. So does every route that needs a pinned map that doesn't parse. Every change publishes the event `map_state`.

Both views draw the tokens of the campaign's live fight on this map (plateau 2a). They are markers anchored in their
node, so the fog view, like every marker, shows only those in nodes the characters have discovered. A view is drawn
once for what it shows (`delve.maps.state`, DEL-166): every seat asks for it again after every map event.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from delve.domain.modules import Revision
from delve.maps import state as map_state
from delve.maps.dsl import DmapError, DungeonMap
from delve.maps.dsl.secrets import list_secrets
from delve.maps.sources import graph_of, parsed_map
from delve.maps.state import MapState, NoPosition, UnknownNode
from delve.maps.tokens import Token
from delve.play import combat
from delve.play.audience import seat_controls
from delve.web.auth import Organiser
from delve.web.routes.campaigns import get_campaign, map_state_changed, pinned_revision, played_maps
from delve.web.seats import TableSeat

router = APIRouter()

MAP_OFFLINE = {"error": "map offline"}
NOT_YOURS = "You can only see what your own characters know."
PATH = "/api/campaigns/{campaign_id}/maps/{name}"


def state_json(state: MapState) -> dict[str, Any]:
    """The DM side of a map state: every character's position and knowledge, the world's facts, and the groups."""
    groups = map_state.groups(state, state.characters)
    return {
        **map_state.to_json(state),
        "groups": [{"location": location, "characters": sorted(ids)} for location, ids in groups],
    }


def _revision(request: Request, campaign_id: str, name: str) -> Revision:
    """The campaign's pinned revision, if `name` is one of its maps."""
    revision = pinned_revision(request, get_campaign(request, campaign_id))
    if name not in played_maps(revision):
        raise HTTPException(status_code=404, detail="No such map.")
    return revision


def _fight(request: Request, campaign_id: str, name: str) -> list[Token]:
    """The live fight's tokens on the map."""
    return combat.tokens(request.app.state.storage, campaign_id, name)


async def _parsed(revision: Revision, name: str) -> DungeonMap:
    try:
        dmap, _ = await run_in_threadpool(parsed_map, revision.module_id, revision.number, revision.maps, name)
        return dmap
    except DmapError:
        raise HTTPException(status_code=409, detail=MAP_OFFLINE) from None


def _load(request: Request, campaign_id: str, name: str) -> MapState:
    raw = request.app.state.storage.map_states.get(campaign_id, name)
    return MapState.empty() if raw is None else map_state.from_json(raw)


def _save(request: Request, campaign_id: str, name: str, state: MapState) -> dict[str, Any]:
    request.app.state.storage.map_states.put(campaign_id, name, map_state.to_json(state))
    map_state_changed(request, campaign_id, name)
    return state_json(state)


def _characters(request: Request, campaign_id: str, ids: list[str]) -> list[str]:
    """`ids`, if they are some of the campaign's characters."""
    known = {c.id for c in request.app.state.storage.characters.list(campaign_id)}
    strangers = [cid for cid in ids if cid not in known]
    if not ids or strangers:
        detail = "Name some of the campaign's characters." if not ids else f"Not in this campaign: {', '.join(strangers)}."
        raise HTTPException(status_code=400, detail=detail)
    return ids


async def _change(
    request: Request, campaign_id: str, name: str, operation: Callable[[MapState, DungeonMap], MapState]
) -> dict[str, Any]:
    """Apply `operation` to the stored state with the parsed pinned map, save it and answer the new state."""
    dmap = await _parsed(_revision(request, campaign_id, name), name)
    try:
        state = await run_in_threadpool(operation, _load(request, campaign_id, name), dmap)
    except UnknownNode as error:
        raise HTTPException(status_code=404, detail={"error": str(error), "candidates": error.candidates}) from None
    return _save(request, campaign_id, name, state)


class CharactersIn(BaseModel):
    characters: list[str]


class MoveIn(CharactersIn):
    to: str


class RevealIn(CharactersIn):
    node: str
    reveal_doors: bool = True


class DoorIn(BaseModel):
    door: str
    state: str


class SecretIn(BaseModel):
    key: str


@router.get(f"{PATH}/state")
def read_state(request: Request, principal: Organiser, campaign_id: str, name: str) -> dict:
    _revision(request, campaign_id, name)
    return state_json(_load(request, campaign_id, name))


@router.get(f"{PATH}/doors-and-secrets")
async def doors_and_secrets(request: Request, principal: Organiser, campaign_id: str, name: str) -> dict:
    """The pinned map's doors and secrets, revealed or not, for the host's pickers: the DM view's knowledge, so
    organisers only."""
    graph = graph_of(dmap := await _parsed(_revision(request, campaign_id, name), name))
    return {
        "doors": [{"key": e.key, "type": e.type, "nodes": [e.a, e.b]} for e in graph.edges]
        + [{"key": b.key, "type": b.type, "nodes": [b.node]} for b in graph.boundary],
        "secrets": [{"key": s.key, "kind": s.kind, "label": s.label, "node": s.node} for s in list_secrets(dmap)],
    }


@router.post(f"{PATH}/start")
async def start(request: Request, principal: Organiser, campaign_id: str, name: str, body: CharactersIn) -> dict:
    """The characters go to the map's party start; on a map without one, nothing changes."""
    _revision(request, campaign_id, name)
    ids = _characters(request, campaign_id, body.characters)
    return await _change(request, campaign_id, name, lambda state, dmap: map_state.start(state, dmap, ids))


@router.post(f"{PATH}/move")
async def move(request: Request, principal: Organiser, campaign_id: str, name: str, body: MoveIn) -> dict:
    """The characters go to a node, adjacent or not (a chute), and discover it."""
    _revision(request, campaign_id, name)
    ids = _characters(request, campaign_id, body.characters)
    return await _change(request, campaign_id, name, lambda state, dmap: map_state.move(state, dmap, ids, body.to))


@router.post(f"{PATH}/reveal")
async def reveal(request: Request, principal: Organiser, campaign_id: str, name: str, body: RevealIn) -> dict:
    """The characters discover a node without going there."""
    _revision(request, campaign_id, name)
    ids = _characters(request, campaign_id, body.characters)

    def operation(state: MapState, dmap: DungeonMap) -> MapState:
        return map_state.reveal(state, dmap, ids, body.node, reveal_doors=body.reveal_doors)

    return await _change(request, campaign_id, name, operation)


@router.post(f"{PATH}/door")
async def door(request: Request, principal: Organiser, campaign_id: str, name: str, body: DoorIn) -> dict:
    """How a door of the map stands now, for everyone."""

    def operation(state: MapState, dmap: DungeonMap) -> MapState:
        graph = graph_of(dmap)
        if body.door not in {e.key for e in graph.edges} | {b.key for b in graph.boundary}:
            raise HTTPException(status_code=404, detail=f"unknown door {body.door!r}")
        return map_state.set_door(state, body.door, body.state)

    return await _change(request, campaign_id, name, operation)


@router.post(f"{PATH}/secret")
async def secret(request: Request, principal: Organiser, campaign_id: str, name: str, body: SecretIn) -> dict:
    """Reveal one of the map's secrets, for everyone."""

    def operation(state: MapState, dmap: DungeonMap) -> MapState:
        if body.key not in {s.key for s in list_secrets(dmap)}:
            raise HTTPException(status_code=404, detail=f"unknown secret {body.key!r}")
        return map_state.reveal_secret(state, body.key)

    return await _change(request, campaign_id, name, operation)


@router.get(f"{PATH}/view")
async def characters_view(
    request: Request, seat: TableSeat, campaign_id: str, name: str, characters: Annotated[str, Query()] = ""
) -> dict:
    """The fog view of what these characters know, with a party disc per group. Nothing turns it into the DM view.
    A seat views its own characters only (403 for others'); the host may view any group (spec §7.4)."""
    ids = [cid for cid in characters.split(",") if cid]
    if seat.role != "host":
        others = sorted(set(ids) - seat_controls(request.app.state.storage, seat))
        if others:
            raise HTTPException(status_code=403, detail=NOT_YOURS)
    dmap = await _parsed(_revision(request, campaign_id, name), name)
    state, tokens = _load(request, campaign_id, name), _fight(request, campaign_id, name)
    try:
        svg = await run_in_threadpool(map_state.render_view, state, dmap, ids, tokens)
    except NoPosition:
        raise HTTPException(status_code=409, detail=MAP_OFFLINE) from None
    return {"svg": svg}


@router.get(f"{PATH}/dm-view")
async def dm_view(request: Request, principal: Organiser, campaign_id: str, name: str) -> dict:
    """The whole map, secrets included, with every group's party disc and the fight's tokens: for the host, not for
    play."""
    dmap = await _parsed(_revision(request, campaign_id, name), name)
    state, tokens = _load(request, campaign_id, name), _fight(request, campaign_id, name)
    return {"svg": await run_in_threadpool(map_state.render_dm, state, dmap, tokens)}
