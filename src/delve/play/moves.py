"""Moving on the map (spec §7.4): the characters' positions and discovery through `delve.maps.state`, rooms split
into what the characters perceive and what only the DM knows, doors, and the DM's notes about rooms.

A move updates the map state in code, so the map can't be forgotten (feature review, "must not regress"). Maps are
those of the campaign's pinned revision. A character is on one map at a time: moving it to another clears its
position on the first and keeps what it knew there. Without `map`, characters move on the map they are on, or on the
module's default map before they are on any. Rooms come from dungml's `room_context`, the one place that decides what
is secret; this module only files its two halves under `perceived` and `dm_only`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from delve.domain.campaigns import Character
from delve.domain.data import to_dict
from delve.domain.modules import Revision
from delve.maps import state as map_state
from delve.maps.dsl import DmapError, DungeonMap, candidates, node_label, resolve_node, room_context
from delve.maps.dsl.graph import Graph
from delve.maps.dsl.room_context import near
from delve.maps.dsl.secrets import Secret, list_secrets
from delve.maps.sources import parsed_map
from delve.maps.state import MapState
from delve.play.campaign_maps import played_revision
from delve.play.characters import get, party
from delve.play.context import CampaignContext, NotFound, PlayError

__all__ = ["door", "locate", "move", "note_room", "room"]

MAP_OFFLINE = "map offline"
_DOOR_KEY = re.compile(r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?(#\d+)?$")
# The secrets `door(found=True)` reveals: what the characters can find by searching.
_FOUND_SECRETS = ("exit", "feature")


# ----- the campaign's maps -----


def _revision(ctx: CampaignContext) -> Revision:
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    revision = played_revision(ctx.storage, campaign) if campaign else None
    if revision is None:
        raise PlayError("The campaign's module revision is missing.")
    return revision


def _played(revision: Revision) -> list[str]:
    return [m.name for m in revision.maps if m.role == "map"]


def _map_named(revision: Revision, name: str) -> str:
    played = _played(revision)
    found = [m for m in played if m == name] or [m for m in played if m.casefold() == name.strip().casefold()]
    if len(found) != 1:
        raise NotFound(
            f"No map '{name}' in this campaign.", [{"name": m} for m in played], hint="Name one of its maps."
        )
    return found[0]


def _default_map(revision: Revision) -> str:
    played = [m for m in revision.maps if m.role == "map"]
    if not played:
        raise PlayError("The campaign's module has no map.")
    return next((m.name for m in played if m.is_default), played[0].name)


def _parse(revision: Revision, name: str) -> tuple[DungeonMap, Graph]:
    try:
        return parsed_map(revision.module_id, revision.number, revision.maps, name)
    except DmapError:
        raise PlayError(MAP_OFFLINE, hint=f"The map '{name}' doesn't parse; fix it in the editor.") from None


def _states(ctx: CampaignContext) -> dict[str, MapState]:
    return {name: map_state.from_json(raw) for name, raw in ctx.storage.map_states.list(ctx.campaign_id).items()}


def _load(ctx: CampaignContext, name: str) -> MapState:
    raw = ctx.storage.map_states.get(ctx.campaign_id, name)
    return MapState.empty() if raw is None else map_state.from_json(raw)


def _save(ctx: CampaignContext, name: str, state: MapState) -> None:
    ctx.storage.map_states.put(ctx.campaign_id, name, map_state.to_json(state))


def _located(states: dict[str, MapState], ids: Iterable[str]) -> dict[str, str]:
    """The map each of the characters has a position on."""
    at: dict[str, str] = {}
    for name, state in states.items():
        for cid in ids:
            view = state.characters.get(cid)
            if view is not None and view.location is not None:
                at[cid] = name
    return at


def _current_map(ctx: CampaignContext, revision: Revision, ids: list[str], name: str | None) -> str:
    """The map named, else the one the characters are on, else the default map."""
    if name:
        return _map_named(revision, name)
    located = _located(_states(ctx), ids)
    maps = sorted(set(located.values()))
    if len(maps) > 1:
        # Who is where, so the DM can name them or bring the rest along (DEL-331).
        names = {c.id: c.name for c in ctx.storage.characters.list(ctx.campaign_id)}
        where = "; ".join(
            f"{m}: {', '.join(names.get(cid, cid) for cid, at in located.items() if at == m)}" for m in maps
        )
        raise PlayError(
            f"The characters are on different maps ({where}).",
            hint="Name the characters (or the map), or move_party the others to join them.",
        )
    return maps[0] if maps else _default_map(revision)


def _who(ctx: CampaignContext, refs: list[str] | None) -> list[Character]:
    """The characters named, or the whole party."""
    chosen = party(ctx) if refs is None else [get(ctx, ref) for ref in refs]
    unique = list({c.id: c for c in chosen}.values())
    if not unique:
        raise PlayError("No characters to move.", hint="Create the party, or name the characters.")
    return unique


def _resolve(dmap: DungeonMap, graph: Graph, name: str, query: str) -> str:
    node = resolve_node(dmap, graph, query)
    if node is None:
        raise NotFound(
            f"No room '{query}' on the map '{name}'.",
            candidates(dmap, graph, query) or near(dmap, graph, query),
        )
    return node


# ----- what a room is -----


def _room_notes(ctx: CampaignContext, name: str, node: str) -> list[dict[str, Any]]:
    notes = ctx.storage.notes.list(ctx.campaign_id, kind="room", map_name=name, node=node)
    return [{"id": n.id, "text": n.text, "session": n.session, "at": n.created_at} for n in notes]


def _groups(ctx: CampaignContext, dmap: DungeonMap, state: MapState) -> list[dict[str, Any]]:
    names = {c.id: c.name for c in ctx.storage.characters.list(ctx.campaign_id)}
    order = list(names)
    return [
        {
            "location": location,
            "label": node_label(dmap, location),
            "characters": [{"id": cid, "name": names[cid]} for cid in sorted(members, key=order.index)],
        }
        for location, members in map_state.groups(state, [cid for cid in order if cid in state.characters])
    ]


def _room(
    ctx: CampaignContext, name: str, dmap: DungeonMap, graph: Graph, state: MapState, node: str, ids: list[str]
) -> dict[str, Any]:
    """The room as these characters know it: all of `room_context`'s `perceived` when they have discovered it, with
    its id and label; nothing perceived when they haven't, and the room itself DM-only."""
    context = room_context(dmap, graph, node, map_state.view(state, ids))
    room = {"room": context["id"], "label": context["label"], "kind": context["kind"]}
    dm_only = dict(context["dm_only"])
    if context["discovered"]:
        perceived = {**room, **context["perceived"]}
    else:
        perceived = {}
        dm_only["room"] = {**room, "perceived_once_found": context["perceived"]}
    return {"perceived": perceived, "dm_only": dm_only, "room_notes": _room_notes(ctx, name, node)}


# ----- the operations -----


def move(
    ctx: CampaignContext, *, to: str, characters: list[str] | None = None, map: str | None = None
) -> dict[str, Any]:
    """The characters (the whole party when None) go to the room `to`, adjacent or not (a chute is a move too), and
    discover it with its visible doors. With `map` they go to that map, and leave the one they were on.

    Returns the room as they perceive it and what is DM-only, the DM's notes on the room, and where every group on
    the map now is. An unknown room moves nobody and lists the rooms it could mean."""
    movers = _who(ctx, characters)
    ids = [c.id for c in movers]
    revision = _revision(ctx)
    name = _current_map(ctx, revision, ids, map)
    dmap, graph = _parse(revision, name)
    with ctx.storage.transaction():
        for other, state in _states(ctx).items():
            if other != name and any(state.characters.get(cid) and state.characters[cid].location for cid in ids):
                _save(ctx, other, map_state.leave(state, ids))
        node = _resolve(dmap, graph, name, to)
        moved = map_state.move(_load(ctx, name), dmap, ids, node)
        _save(ctx, name, moved)
        label = node_label(dmap, node)
        ctx.log("moved", map=name, node=node, label=label, characters=ids, names=[c.name for c in movers])
    return {"map": name, **_room(ctx, name, dmap, graph, moved, node, ids), "groups": _groups(ctx, dmap, moved)}


def locate(ctx: CampaignContext, query: str) -> tuple[str, str]:
    """The map and node a room query names, resolved as `move` resolves `to`: on the map the party is on, or the
    default map before it is on one. An unknown room raises `NotFound` with the rooms it could mean."""
    revision = _revision(ctx)
    name = _current_map(ctx, revision, [c.id for c in party(ctx)], None)
    dmap, graph = _parse(revision, name)
    return name, _resolve(dmap, graph, name, query)


def _here(state: MapState, ids: list[str]) -> list[str]:
    return sorted({state.characters[cid].location for cid in ids if cid in state.characters} - {None})


def leave_maps(ctx: CampaignContext, ids: Iterable[str]) -> list[str]:
    """The characters leave every map of the module they have a place on (they set off overland, DEL-331): their
    positions clear, what they know of each map stays. The maps they left, in order."""
    ids = list(ids)
    left = []
    for name, state in sorted(_states(ctx).items()):
        if any(state.characters.get(cid) and state.characters[cid].location for cid in ids):
            _save(ctx, name, map_state.leave(state, ids))
            left.append(name)
    return left


def party_place(ctx: CampaignContext) -> tuple[str | None, str | None]:
    """Where the party is: the map all of it is on and the room all of it is in, each None when there is no one (no
    position yet, or the party is split)."""
    ids = [c.id for c in party(ctx)]
    maps = sorted(set(_located(_states(ctx), ids).values()))
    if len(maps) != 1:
        return None, None
    here = _here(_load(ctx, maps[0]), ids)
    return maps[0], here[0] if len(here) == 1 else None


def room(ctx: CampaignContext, query: str = "", characters: list[str] | None = None) -> dict[str, Any]:
    """A room of the characters' map (the whole party's when None), as they know it: the one they are in, or any by
    id, bare name or label. Read-only: for "what's through that door", or the room again after a break."""
    who = _who(ctx, characters)
    ids = [c.id for c in who]
    revision = _revision(ctx)
    name = _current_map(ctx, revision, ids, None)
    dmap, graph = _parse(revision, name)
    state = _load(ctx, name)
    if query:
        node = _resolve(dmap, graph, name, query)
    else:
        here = _here(state, ids)
        if not here:
            raise PlayError("The characters aren't in a room yet.", hint="move_party first, or name the room.")
        if len(here) > 1:
            raise PlayError(
                f"The characters are in different rooms: {', '.join(here)}.", hint="Name the room, or the characters."
            )
        node = here[0]
    return {"map": name, **_room(ctx, name, dmap, graph, state, node, ids)}


def _authored(graph: Graph, key: str) -> tuple[str, list[str]] | None:
    """The door's authored state and the nodes it touches."""
    for edge in graph.edges:
        if edge.key == key:
            return edge.state, [edge.a, edge.b]
    for exit in graph.boundary:
        if exit.key == key:
            return exit.state, [exit.node]
    return None


def _reveal(ctx: CampaignContext, name: str, current: MapState, secret: Secret) -> dict[str, Any]:
    """A secret exit or feature found: revealed for everyone, as the DM's map view reveals one."""
    with ctx.storage.transaction():
        _save(ctx, name, map_state.reveal_secret(current, secret.key))
        ctx.log("door", map=name, door=secret.key, state="", found=True, secret=secret.key)
    return {"map": name, "secret": secret.key, "kind": secret.kind, "node": secret.node, "revealed": True}


def door(ctx: CampaignContext, door: str, state: str = "", found: bool = False) -> dict[str, Any]:
    """Record what happened to a door of the party's map: opened, forced, locked, barred (`state`), or a secret door
    found (`found`). The state is the world's, for everyone; a door is found by the characters standing at it, and
    those with them.

    `door` is a door key ("14,9", from a room's exits) or the room it leads to from the party's room. With `found`, it
    may also be the key of a secret exit or feature of the map (a room's `dm_only` `secrets`), which is then revealed
    for everyone."""
    if not state and not found:
        raise PlayError("Nothing to record.", hint="Pass state= or found=True.")
    pcs = [c.id for c in party(ctx)]
    revision = _revision(ctx)
    name = _current_map(ctx, revision, pcs, None)
    dmap, graph = _parse(revision, name)
    current = _load(ctx, name)
    key = door.strip()
    secret = next((s for s in list_secrets(dmap) if s.key == key and s.kind in _FOUND_SECRETS), None)
    if secret is not None:
        if state:
            raise PlayError(f"'{key}' is a secret {secret.kind}, not a door.", hint="Pass found=True alone.")
        return _reveal(ctx, name, current, secret)
    if not _DOOR_KEY.match(key):
        here = _here(current, pcs)
        if not here:
            raise PlayError("The party isn't in a room yet.", hint="move_party first, or name the door by its key.")
        far = _resolve(dmap, graph, name, key)
        hits = [e for e in graph.edges if far in (e.a, e.b) and ({e.a, e.b} - {far}) & set(here)]
        if len(hits) != 1:
            candidates = [{"door": e.key, "between": [e.a, e.b]} for e in hits]
            raise NotFound(f"No single door from the party's room to '{door}'.", candidates, hint="Name the door key.")
        key = hits[0].key
    authored = _authored(graph, key)
    if authored is None:
        raise NotFound(f"No door '{door}' on the map '{name}'.", hint="Door keys are in a room's exits.")
    authored_state, touches = authored
    placed = [cid for cid, view in current.characters.items() if view.location is not None]
    finders = [cid for cid in placed if current.characters[cid].location in touches] or placed
    with ctx.storage.transaction():
        changed = current
        if found or state:
            changed = map_state.discover_door(changed, finders, key)
        if state:
            changed = map_state.set_door(changed, key, state.strip())
        _save(ctx, name, changed)
        ctx.log("door", map=name, door=key, state=state.strip(), found=found)
    return {
        "map": name,
        "door": key,
        "between": touches,
        "state": changed.door_states.get(key, authored_state),
        "discovered": bool(finders),
        "found_by": finders,
    }


def note_room(ctx: CampaignContext, text: str, query: str = "") -> dict[str, Any]:
    """Remember what the party changed in a room: cleared it, left the horse, barricaded a door, looted the chest. A
    DM-only note, returned by `move` and `room` every time. The party's room by default; `query` names another."""
    if not text.strip():
        raise PlayError("A note needs text.")
    pcs = [c.id for c in party(ctx)]
    revision = _revision(ctx)
    name = _current_map(ctx, revision, pcs, None)
    dmap, graph = _parse(revision, name)
    if query:
        node = _resolve(dmap, graph, name, query)
    else:
        here = _here(_load(ctx, name), pcs)
        if len(here) != 1:
            raise PlayError(
                "The party isn't in one room." if here else "The party isn't in a room yet.", hint="Name the room."
            )
        node = here[0]
    session = ctx.storage.campaign_states.get(ctx.campaign_id).session
    note = ctx.storage.notes.create(ctx.campaign_id, "room", text.strip(), map_name=name, node=node, session=session)
    return {"map": name, "room": node, "note": to_dict(note)}
