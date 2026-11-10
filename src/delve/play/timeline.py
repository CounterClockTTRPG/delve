"""The initiative timeline (table voice and fixes, workstream B2): what the table sees of a fight's rounds, from the
rounds `delve.play.combat` records in `storage.combat_rounds`, redacted per seat, and when a round's outcomes are
released to it (once the DM's text for that round has arrived).

What a seat sees (`timeline_for`, Task B2.1): the round's order along the initiative counts and its ongoing actions,
as soon as its initiative is rolled; who acted, went down, died or fled, and which actions completed or broke, only
once the round is released. The redaction is the fourth wall's:
- an enemy (any combatant not of the party) is named, and keyed by its id, only when the party can see it: the fight
  has no map, or the enemy stands in a node the party's characters have discovered on it. Otherwise it is
  `unseen-<n>`, numbered in the order it joined the fight;
- an enemy's ongoing action shows only for a named one, and only by its kind and its span: never what it casts, nor
  why it broke (Decision 10). A party member's shows whole;
- no hit points, armour class, THAC0, node or declared action of anyone: a slot has only the keys below.

When outcomes show (Task B2.2): the beat runner (`delve.play.table`) calls the two hooks below. A tool's result that
changed the live fight's latest round (its initiative rolled, or it resolved) publishes `initiative`; the table's
`dm_text` stored after it releases the rounds resolved before a result the runner has handled
(`combat_rounds.release`) and publishes `outcomes`; a result after which the fight is no longer live publishes
`ended`. A text stored as a tool's call arrives ends the words before that call: it releases nothing that call
resolved, even when the tool's writes landed first. A beat that closes done or cancelled releases what no text
released; a failed one releases nothing, as Retry (or the next beat) narrates it. The events carry no content
(Decision 9): each browser reads `GET /api/campaigns/{id}/timeline` again, as its own seat.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from delve.dm.provider import DMEvent, ToolResult
from delve.domain.campaigns import Beat, CombatRound, Seat, StoryEntry
from delve.maps import state as map_state
from delve.play import monster_pictures, seats
from delve.rules.classic import combat as rules
from delve.rules.classic.initiative import ROUND_END
from delve.storage import Storage

if TYPE_CHECKING:
    from delve.play.table import AppServices

__all__ = ["after_beat", "after_event", "timeline_for"]

NO_FIGHT: dict[str, Any] = {"fight": None}

# The latest round of each campaign's live fight as last published, `(combat id, round, rolled_at, resolved_at)`:
# a tool's result publishes `initiative` when it changed, and `ended` when the fight is no longer live.
_published: dict[str, tuple[str, int | None, str | None, str | None]] = {}

# The resolved rounds of each campaign that wait for the DM's text, `(combat id, round)`: those resolved before a tool
# result the runner has handled. Only these does a text release. Kept in memory: after a restart, the next beat that
# ends done releases them.
_awaiting: dict[str, set[tuple[str, int]]] = {}


def timeline_for(storage: Storage, campaign_id: str, seat: Seat) -> dict[str, Any]:
    """The live fight's timeline as `seat` may see it: `{"fight": null}` when there is none, for an observer, and for
    a player none of whose characters fights in it (as `play/state`'s `combat`)."""
    if seat.role == "observer" or seat.left_at is not None:
        return NO_FIGHT
    live = storage.combats.live(campaign_id)
    if live is None:
        return NO_FIGHT
    combat_id, raw = live
    fight = rules.from_json(raw)
    fighting = {c.character_id for c in fight.combatants.values() if c.character_id}
    if seat.role not in seats.TABLE_RIGHTS and seats.controls(storage, seat.id).isdisjoint(fighting):
        return NO_FIGHT
    rows = storage.combat_rounds.list(combat_id)
    # The oldest round the table hasn't been told of yet, so a later round's order tells nothing ahead of the DM;
    # else the latest. A fight from before the rounds were recorded is read from itself.
    row = next((r for r in rows if r.resolved_at and r.released_at is None), rows[-1] if rows else None)
    if row is None:
        row = CombatRound(combat_id, fight.round, campaign_id, fight.mode, tuple(rules.slots(fight)))
    released = row.released_at is not None and row.outcomes is not None
    outcomes = row.outcomes if released else None
    dead_before = {
        id for r in rows if r.round < row.round and r.released_at and r.outcomes for id in r.outcomes["dead"]
    }
    seen = _seen_nodes(storage, campaign_id, fight.map, fighting)
    joined = {id: n for n, id in enumerate(fight.combatants)}
    hidden = sorted(
        (s["id"] for s in row.slots if s["side"] != "party" and not _visible(s, seen)),
        key=lambda id: joined.get(id, len(joined)),
    )
    slots = [_faced(storage, fight, s, _slot(s, row.round, seen, hidden, outcomes, dead_before)) for s in row.slots]
    counts = [s["count"] for s in slots if s["count"] is not None]
    ends = [s["ongoing"]["to"] for s in slots if s["ongoing"] is not None]
    return {
        "fight": {
            "combat_id": combat_id,
            "round": row.round,
            "mode": row.mode,
            "released": released,
            "max_count": max([ROUND_END, *counts, *ends]),
            "slots": slots,
        }
    }


def _faced(storage: Storage, fight: Any, raw: dict[str, Any], slot: dict[str, Any]) -> dict[str, Any]:
    """The slot with its face (DEL-275): an ally that is a character (an NPC) gets its `character_id`, for its
    portrait; any other combatant of the DM's, once seen, its `monster`: its kind, as the DM added it, and the slug and
    version of that kind's picture (`delve.play.monster_pictures`), null for none, and whether one is being painted."""
    if slot["side"] == "party" or slot["name"] is None:
        return slot
    if raw.get("character_id"):
        return {**slot, "character_id": raw["character_id"]}
    combatant = fight.combatants.get(raw["id"])
    kind = (combatant.group if combatant is not None else "") or slot["name"]
    picture = monster_pictures.find(storage, slot["name"], kind)
    asked = storage.monster_pictures.get(monster_pictures.slug(kind))
    return {
        **slot,
        "monster": {
            "kind": kind,
            "picture": picture.slug if picture is not None else None,
            "version": picture.updated_at if picture is not None else None,
            "painting": asked is not None and asked.status == "painting",
        },
    }


def _seen_nodes(
    storage: Storage, campaign_id: str, map_name: str | None, party: Iterable[str]
) -> frozenset[str] | None:
    """The nodes the party's characters have discovered on the fight's map; None when the fight has no map (then
    every enemy is in sight)."""
    if map_name is None:
        return None
    raw = storage.map_states.get(campaign_id, map_name)
    if raw is None:
        return frozenset()
    return map_state.view(map_state.merge(map_state.from_json(raw)), party).discovered_nodes


def _visible(slot: dict[str, Any], seen: frozenset[str] | None) -> bool:
    return seen is None or (slot.get("node") is not None and slot["node"] in seen)


def _slot(
    slot: dict[str, Any],
    round: int,
    seen: frozenset[str] | None,
    hidden: list[str],
    outcomes: dict[str, Any] | None,
    dead_before: set[str],
) -> dict[str, Any]:
    id, party = slot["id"], slot["side"] == "party"
    named = party or id not in hidden
    return {
        "key": id if named else f"unseen-{hidden.index(id) + 1}",
        "name": slot["name"] if named else None,
        "side": slot["side"],
        "character_id": slot["character_id"] if party else None,
        "count": slot["count"],
        "state": _state(id, slot["count"], outcomes, dead_before),
        "ongoing": _ongoing(id, slot.get("ongoing"), round, outcomes, whole=party) if named else None,
    }


def _state(id: str, count: int | None, outcomes: dict[str, Any] | None, dead_before: set[str]) -> str:
    """`waiting` until the round is released; then `dead`, `down`, `fled` or `acted`. A combatant with no count was
    down (or dead) when the round began."""
    if count is None:
        return "dead" if id in dead_before else "down"
    if outcomes is None:
        return "waiting"
    for state, key in (("dead", "dead"), ("down", "downed"), ("fled", "fled"), ("acted", "acted")):
        if id in outcomes.get(key, ()):
            return state
    return "waiting"


def _ongoing(
    id: str, ongoing: dict[str, Any] | None, round: int, outcomes: dict[str, Any] | None, *, whole: bool
) -> dict[str, Any] | None:
    """An ongoing action as a span on the round's axis: from the count it started on (1 when it carries over from an
    earlier round) to the count it completes on, or off the end (`next_round`) when it runs past the round. How it
    ended shows once the round is released."""
    if ongoing is None:
        return None
    state, reason = "ongoing", None
    if outcomes is not None:
        broke = next((e for e in outcomes.get("interrupted", ()) if e["id"] == id), None)
        if broke is not None:
            state, reason = "interrupted", broke.get("reason")
        elif any(e["id"] == id for e in outcomes.get("completed", ())):
            state = "completed"
    next_round = ongoing["completes_round"] > round
    end = ongoing.get("completes_count")
    to = ROUND_END if next_round or end is None else end
    start = ongoing.get("started_count") if ongoing["started_round"] == round else None
    return {
        "kind": ongoing["kind"],
        "what": ongoing["what"] if whole else None,
        "from": min(start or 1, to),
        "to": to,
        "next_round": next_round,
        "state": state,
        "reason": reason if whole else None,
    }


# ----- the hooks of the beat runner -----


def after_event(
    services: AppServices, campaign_id: str, beat_id: str, event: DMEvent, stored: list[StoryEntry]
) -> None:
    """After the runner fed one DM event of the beat into the story (`stored` are the entries it put): a fight's
    initiative rolled, a round's outcomes to release once the DM's text arrives, the fight's end."""
    # The text stored with an event was written before it: it releases what waited before this event's result.
    if any(entry.kind == "dm_text" and entry.audience is None for entry in stored):
        _release(services, campaign_id)
    if isinstance(event, ToolResult):
        _fight_changed(services, campaign_id)


def after_beat(services: AppServices, beat: Beat) -> None:
    """After a beat closed (done, failed or cancelled, or closed by the start of Delve): the outcomes no text
    released, unless it failed: then nobody has told them yet, and the beat that does (Retry) releases them."""
    if beat.status == "failed":
        return
    _release(services, beat.campaign_id, everything=True)


def _publish(services: AppServices, campaign_id: str, combat_id: str, round: int | None, change: str) -> None:
    data = {"campaign_id": campaign_id, "combat_id": combat_id, "round": round, "change": change}
    services.publish("timeline", data, scope="table", campaign_id=campaign_id)


def _fight_changed(services: AppServices, campaign_id: str) -> None:
    storage = services.storage
    resolved = {(row.combat_id, row.round) for row in storage.combat_rounds.unreleased(campaign_id)}
    if resolved:
        _awaiting.setdefault(campaign_id, set()).update(resolved)
    before = _published.get(campaign_id)
    live = storage.combats.live(campaign_id)
    if before is not None and (live is None or live[0] != before[0]):
        del _published[campaign_id]
        _publish(services, campaign_id, before[0], before[1], "ended")
    if live is None:
        return
    row = storage.combat_rounds.latest(live[0])
    mark = (live[0], row.round, row.rolled_at, row.resolved_at) if row is not None else (live[0], None, None, None)
    if mark != _published.get(campaign_id):
        _published[campaign_id] = mark
        if row is not None:
            _publish(services, campaign_id, live[0], row.round, "initiative")


def _release(services: AppServices, campaign_id: str, *, everything: bool = False) -> None:
    """Release the resolved rounds that wait for the DM's text (`everything`: every resolved round the table hasn't
    been told of), and say so once, for the latest of them. A text with nothing waiting reads nothing (DEL-241)."""
    awaiting = _awaiting.pop(campaign_id, set())
    if not awaiting and not everything:
        return
    now = services.clock.now().isoformat()
    rows = [
        row
        for row in services.storage.combat_rounds.unreleased(campaign_id)
        if everything or (row.combat_id, row.round) in awaiting
    ]
    released = [row for row in rows if services.storage.combat_rounds.release(row.combat_id, row.round, now)]
    if released:
        _publish(services, campaign_id, released[-1].combat_id, released[-1].round, "outcomes")
