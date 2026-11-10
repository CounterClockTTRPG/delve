"""Quests (plan 6 Task 5, Decisions 6 and 7; ttrpg2 `tools/quests.py`).

A module's quests are seeded `available` and not yet known (`seed`, called by `factions.seed`); one the DM adds is
`active` and known, since the party has taken it up. A quest becomes known when it turns `active`. Players see a known
quest's title, status, giver, stakes and the notes of its log marked known; its `notes_md` and the rest are the DM's.

ttrpg2's scope rule comes over as a warning: regional is for an average party level of 4 and up, continental for 8.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from delve.domain.world import QUEST_STATUSES, Quest, QuestNote
from delve.modules.dscn.refs import parse_ref
from delve.modules.source import ModuleSource
from delve.play import characters
from delve.play.context import CampaignContext, NotFound, PlayError

__all__ = [
    "SCOPES",
    "active",
    "add_quest",
    "avg_party_level",
    "get",
    "list_quests",
    "quest_json",
    "scope_warning",
    "seed",
    "update_quest",
]

SCOPES = ("local", "regional", "continental")
ENDED = ("complete", "failed")


def _slug(name: str) -> str:
    return "-".join(name.strip().lower().split())


def _day(ctx: CampaignContext) -> int:
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    return state.day if state is not None else 1


def seed(ctx: CampaignContext, source: ModuleSource) -> int:
    """Add the module's quests the campaign doesn't have yet, `available` and not known; how many were added."""
    have = {q.id for q in ctx.storage.quests.list(ctx.campaign_id)}
    npcs = {str(n.get("id")): str(n.get("name") or n.get("id")) for n in source.entities.get("npcs", []) if n}
    added = 0
    for record in source.entities.get("quests", []):
        if not isinstance(record, dict) or not record.get("id") or str(record["id"]) in have:
            continue
        related = record.get("related") or []
        ctx.storage.quests.put(
            Quest(
                campaign_id=ctx.campaign_id,
                id=str(record["id"]),
                title=str(record.get("name") or record.get("title") or record["id"]),
                giver=_giver(record.get("giver"), npcs),
                scope=str(record.get("scope") or "local"),
                stakes=str(record.get("stakes") or ""),
                related=tuple(str(r) for r in related) if isinstance(related, list) else (),
                notes_md="\n\n".join(str(n).strip() for n in (record.get("summary"), record.get("description")) if n),
                source_ref=f"quest:{record['id']}",
            )
        )
        have.add(str(record["id"]))
        added += 1
    return added


def _giver(raw: Any, npcs: dict[str, str]) -> str:
    """A quest's giver: the name of the module NPC it refers to, else the ref's id, else the text."""
    if not isinstance(raw, str) or not raw.strip():
        return ""
    ref = parse_ref(raw)
    if ref is None:
        return raw.strip()
    return npcs.get(ref.id, ref.id) if ref.kind == "npc" else ref.id


def quest_json(quest: Quest) -> dict[str, Any]:
    """A quest as the DM sees it."""
    return {
        "id": quest.id,
        "title": quest.title,
        "giver": quest.giver,
        "scope": quest.scope,
        "stakes": quest.stakes,
        "status": quest.status,
        "known": quest.known,
        "started_day": quest.started_day,
        "ended_day": quest.ended_day,
        "related": list(quest.related),
        "log": [note.to_dict() for note in quest.log],
        "notes_md": quest.notes_md,
    }


def avg_party_level(ctx: CampaignContext) -> float:
    """The PCs' average level (a multi-class character's highest); 1.0 without PCs."""
    levels = [max(pc.sheet.levels.values(), default=1) for pc in characters.party(ctx)]
    return sum(levels) / len(levels) if levels else 1.0


def scope_warning(scope: str, level: float) -> str:
    """ttrpg2's scope rule: regional quests are for level 4 and up, continental ones for level 8 and up."""
    if scope == "regional" and level < 4:
        return f"Regional scope on a party averaging level {level:.1f}: regional is for level 4 and up."
    if scope == "continental" and level < 8:
        return (
            f"Continental scope on a party averaging level {level:.1f}: continental is for level 8 and up. "
            "Demote the scope, or wait for the party to engage."
        )
    return ""


def get(ctx: CampaignContext, ref: str) -> Quest:
    """The quest with this id or exact title (any case); an unknown one is refused with every quest."""
    wanted = ref.strip()
    listed = ctx.storage.quests.list(ctx.campaign_id)
    found = next((q for q in listed if q.id in (wanted, _slug(wanted))), None)
    found = found or next((q for q in listed if q.title.casefold() == wanted.casefold()), None)
    if found is None:
        raise NotFound(f"No quest '{ref}'.", [{"id": q.id, "name": q.title} for q in listed])
    return found


def list_quests(ctx: CampaignContext, status: str = "") -> dict[str, Any]:
    """Every quest, or those of one status, each open one with its scope warning; and the party's average level.
    Without a status, an ended quest (complete or failed) is only its id, title, status and the day it ended: their
    logs and notes made the whole list 25 KB in a long campaign (DEL-79). Asked for by status, they come whole."""
    if status and status not in QUEST_STATUSES:
        raise PlayError(f"Unknown status '{status}'.", f"Use one of: {', '.join(QUEST_STATUSES)}.")
    level = avg_party_level(ctx)
    out = []
    for quest in ctx.storage.quests.list(ctx.campaign_id, status=status or None):  # type: ignore[arg-type]
        if not status and quest.status in ENDED:
            out.append({key: quest_json(quest)[key] for key in ("id", "title", "status", "ended_day")})
            continue
        entry = quest_json(quest)
        warning = scope_warning(quest.scope, level) if quest.status not in ENDED else ""
        out.append({**entry, "scope_warning": warning} if warning else entry)
    return {"quests": out, "avg_party_level": level}


def active(ctx: CampaignContext) -> list[dict[str, Any]]:
    """The active quests, for the primer."""
    return [quest_json(q) for q in ctx.storage.quests.list(ctx.campaign_id, status="active")]


def add_quest(
    ctx: CampaignContext,
    id: str,
    title: str,
    *,
    giver: str = "",
    scope: str = "local",
    stakes: str = "",
    related: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """A quest the party takes up: active and known from today. A scope above the party's level adds a warning."""
    if scope not in SCOPES:
        raise PlayError(f"Unknown scope '{scope}'.", f"Use one of: {', '.join(SCOPES)}.")
    if not title.strip() or not _slug(id):
        raise PlayError("A quest needs an id and a title.")
    quest_id = _slug(id)
    if ctx.storage.quests.get(ctx.campaign_id, quest_id) is not None:
        raise PlayError(f"Quest '{quest_id}' already exists.", "Use update_quest.")
    quest = Quest(
        campaign_id=ctx.campaign_id,
        id=quest_id,
        title=title.strip(),
        giver=giver.strip(),
        scope=scope,
        stakes=stakes,
        status="active",
        known=True,
        started_day=_day(ctx),
        related=tuple(related),
    )
    ctx.storage.quests.put(quest)
    ctx.log("quest_added", quest=quest.id, name=quest.title, notes=f"{scope} — {stakes}" if stakes else scope)
    warning = scope_warning(scope, avg_party_level(ctx))
    return {"quest": quest_json(quest), **({"warning": warning} if warning else {})}


def update_quest(
    ctx: CampaignContext,
    id: str,
    *,
    status: str | None = None,
    note: str | None = None,
    note_known: bool = True,
    known: bool | None = None,
) -> dict[str, Any]:
    """Change a quest's status, add a note to its log (one the characters don't know when `note_known` is false), or
    make it known or not. It becomes known when it turns active; it ends on today's day when complete or failed."""
    if status is not None and status not in QUEST_STATUSES:
        raise PlayError(f"Unknown status '{status}'.", f"Use one of: {', '.join(QUEST_STATUSES)}.")
    quest = get(ctx, id)
    today = _day(ctx)
    changes: dict[str, Any] = {}
    if status is not None:
        changes["status"] = status
        if status == "active":
            changes["known"] = True
            if quest.started_day is None:
                changes["started_day"] = today
        changes["ended_day"] = today if status in ENDED else None
    if note:
        changes["log"] = (*quest.log, QuestNote(today, note, bool(note_known)))
    if known is not None:
        changes["known"] = bool(known)
    quest = replace(quest, **changes)
    ctx.storage.quests.put(quest)
    ctx.log("quest_update", quest=quest.id, status=quest.status, notes=note or "")
    return {"quest": quest_json(quest)}
