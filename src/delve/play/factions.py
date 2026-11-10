"""Factions, their clocks and the party's standing with them (plan 6 Task 5, Decision 6; ttrpg2 `tools/factions.py`).

A campaign's factions, clocks and quests are seeded from its module (`seed`): when the campaign is created, when the
host upgrades it (adding only what is new, never overwriting play state), and on first use for a campaign from before
plateau 6, which has none of them yet (`ensure_seeded`: the DM's tools, the primer and each new day call it).

A `countdown` clock loses a day with each new day (the new-day hook `clocks`) and completes once, at 0. A `progress`
clock (the `.dscn` `segments`/`filled` kind) moves only when the DM advances it; ttrpg2 treated segments as days.

The notes, the strength, the reputation number and every clock are the DM's (Decision 7). Players see a known
faction's standing word (`standing`), ttrpg2's disposition bands. The party's reputation with an NPC's faction is a
reaction modifier (`reputation_of`).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from delve.domain.world import CLOCK_KINDS, Clock, Faction
from delve.modules.source import ModuleSource, pinned_source
from delve.play import days, quests
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.rules.classic import checks

__all__ = [
    "add_clock",
    "advance_clock",
    "clock_json",
    "clocks",
    "day_number",
    "ensure_seeded",
    "faction_json",
    "get",
    "list_factions",
    "nearest_countdowns",
    "remove_clock",
    "reputation_of",
    "seed",
    "shaped_clock",
    "slug",
    "standing",
    "update_faction",
]

# ttrpg2's disposition bands, from the most positive: the floor of each band and its standing word.
_STANDING = ((61, "Devoted"), (21, "Friendly"), (6, "Cordial"), (-5, "Neutral"), (-20, "Wary"), (-60, "Hostile"))

URGENT_DAYS = 7
"""A countdown with this many days left or fewer is urgent: a week, pressure rising."""

PROGRESS_SEGMENTS = 4
"""The segments of a module's progress clock that names none."""


def standing(reputation: int) -> str:
    """The party's standing with a faction, in a word: "Devoted" … "Sworn enemy"."""
    return next((word for floor, word in _STANDING if reputation >= floor), "Sworn enemy")


def slug(name: str) -> str:
    """An id made of a name: lowercase, its spaces as hyphens."""
    return "-".join(name.strip().lower().split())


def day_number(ctx: CampaignContext) -> int:
    """The campaign's day as a number (`days.today` is its date): 1 before its state is stored."""
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    return state.day if state is not None else 1


# --- seeding -----------------------------------------------------------------------------------------------------


def seed(ctx: CampaignContext, source: ModuleSource) -> dict[str, int]:
    """Add the module's factions, their clocks and its quests that the campaign doesn't have yet; what it has keeps
    its play state. How many of each were added."""
    added = {"factions": 0, "clocks": 0, "quests": 0}
    with ctx.storage.transaction():
        have = {f.id for f in ctx.storage.factions.list(ctx.campaign_id)}
        ticking = {(c.faction_id, c.label) for c in ctx.storage.clocks.list(ctx.campaign_id)}
        for record in source.entities.get("factions", []):
            if not isinstance(record, dict) or not record.get("id"):
                continue
            faction_id = str(record["id"])
            if faction_id not in have:
                ctx.storage.factions.put(_faction_of(ctx.campaign_id, record))
                have.add(faction_id)
                added["factions"] += 1
            for raw in record.get("clocks") or []:
                clock = _clock_of(ctx, faction_id, raw)
                if clock is not None and (faction_id, clock.label) not in ticking:
                    ctx.storage.clocks.add(clock)
                    ticking.add((faction_id, clock.label))
                    added["clocks"] += 1
        added["quests"] = quests.seed(ctx, source)
    return added


def ensure_seeded(ctx: CampaignContext) -> None:
    """Seed a campaign that has no faction, clock or quest yet from its pinned revision: one from before plateau 6."""
    campaign_id = ctx.campaign_id
    if ctx.storage.factions.list(campaign_id) or ctx.storage.clocks.list(campaign_id):
        return
    if ctx.storage.quests.list(campaign_id):
        return
    campaign = ctx.storage.campaigns.get(campaign_id)
    source = pinned_source(ctx.storage, campaign.module_id, campaign.revision) if campaign is not None else None
    if source is not None:
        seed(ctx, source)


def _faction_of(campaign_id: str, record: dict[str, Any]) -> Faction:
    goals = record.get("goals") or ""
    notes = (record.get("summary") or "", record.get("description") or "")
    return Faction(
        campaign_id=campaign_id,
        id=str(record["id"]),
        name=str(record.get("name") or record["id"]),
        alignment=str(record.get("alignment") or ""),
        goals="; ".join(map(str, goals)) if isinstance(goals, list) else str(goals),
        scope=str(record.get("scope") or ""),
        notes_md="\n\n".join(str(n).strip() for n in notes if n),
        source_ref=f"faction:{record['id']}",
    )


def _clock_of(ctx: CampaignContext, faction_id: str, raw: Any) -> Clock | None:
    """A module faction's clock: a countdown when it has `days`, else a progress clock."""
    if not isinstance(raw, dict) or not raw.get("name"):
        return None
    common = {
        "id": 0,
        "campaign_id": ctx.campaign_id,
        "label": str(raw["name"]),
        "faction_id": faction_id,
        "on_complete": str(raw.get("on_complete") or ""),
        "started_day": day_number(ctx),
    }
    if isinstance(raw.get("days"), int):
        return Clock(kind="countdown", days_remaining=max(0, raw["days"]), **common)
    segments = raw.get("segments") if isinstance(raw.get("segments"), int) else PROGRESS_SEGMENTS
    filled = raw.get("filled") if isinstance(raw.get("filled"), int) else 0
    return Clock(kind="progress", segments=max(1, segments), filled=max(0, min(filled, segments)), **common)


# --- factions ----------------------------------------------------------------------------------------------------


def faction_json(faction: Faction) -> dict[str, Any]:
    """A faction as the DM sees it, with its standing word."""
    return {
        "id": faction.id,
        "name": faction.name,
        "alignment": faction.alignment,
        "goals": faction.goals,
        "scope": faction.scope,
        "known": faction.known,
        "strength": faction.strength,
        "reputation": faction.reputation,
        "standing": standing(faction.reputation),
        "notes_md": faction.notes_md,
    }


def _candidates(listed: list[Faction]) -> list[dict[str, str]]:
    return [{"id": f.id, "name": f.name} for f in listed]


def _find(ctx: CampaignContext, ref: str) -> Faction | None:
    wanted = ref.strip()
    listed = ctx.storage.factions.list(ctx.campaign_id)
    return next(
        (f for f in listed if wanted in (f.id, slug(f.id)) or slug(wanted) == f.id),
        next((f for f in listed if f.name.casefold() == wanted.casefold()), None),
    )


def get(ctx: CampaignContext, ref: str) -> Faction:
    """The faction with this id or exact name (any case); an unknown one is refused with every faction."""
    found = _find(ctx, ref)
    if found is None:
        listed = ctx.storage.factions.list(ctx.campaign_id)
        raise NotFound(f"No faction '{ref}'.", _candidates(listed), "" if listed else "Make one with update_faction.")
    return found


def reputation_of(ctx: CampaignContext, faction_id: str) -> int:
    """The party's reputation with the faction; 0 for none or an unknown one."""
    found = ctx.storage.factions.get(ctx.campaign_id, faction_id) if faction_id else None
    return found.reputation if found is not None else 0


def list_factions(ctx: CampaignContext, known_only: bool = False) -> list[dict[str, Any]]:
    return [faction_json(f) for f in ctx.storage.factions.list(ctx.campaign_id, known=True if known_only else None)]


def update_faction(
    ctx: CampaignContext,
    id: str,
    *,
    name: str | None = None,
    alignment: str | None = None,
    goals: str | None = None,
    scope: str | None = None,
    known: bool | None = None,
    strength: int | None = None,
    reputation_change: int | None = None,
    reason: str = "",
    notes: str | None = None,
) -> dict[str, Any]:
    """Change the fields given. An unknown id with a `name` makes the faction (strength 100, reputation 0); without
    one it is refused with the factions there are. The strength clamps at 0…100 and the reputation at ±100; a
    reputation change is logged as `reputation_change`."""
    faction = _find(ctx, id)
    if faction is None:
        if not (name or "").strip():
            get(ctx, id)  # refuses, with the candidates
        if not slug(id):
            raise PlayError("A new faction needs an id.", "Give it one: 'thieves-guild'.")
        faction = Faction(campaign_id=ctx.campaign_id, id=slug(id), name=(name or "").strip())
    changes: dict[str, Any] = {}
    for field, value in (("name", name), ("alignment", alignment), ("goals", goals), ("scope", scope)):
        if value is not None and value.strip():
            changes[field] = value.strip()
    if known is not None:
        changes["known"] = bool(known)
    if strength is not None:
        changes["strength"] = max(0, min(100, int(strength)))
    if notes is not None:
        changes["notes_md"] = notes
    out: dict[str, Any] = {}
    if reputation_change is not None:
        before = faction.reputation
        after = max(-100, min(100, before + int(reputation_change)))
        changes["reputation"] = after
        ctx.log(
            "reputation_change",
            faction=faction.id,
            before=before,
            after=after,
            notes=reason or f"reputation {before:+d} → {after:+d}",
        )
        out = {"before": before, "after": after, "modifier_applied_to_reaction": checks.reputation_modifier(after, rules=ctx.rules)}
    faction = replace(faction, **changes)
    ctx.storage.factions.put(faction)
    return {"faction": faction_json(faction), **out}


# --- clocks ------------------------------------------------------------------------------------------------------


def clock_json(clock: Clock) -> dict[str, Any]:
    """A clock as the DM sees it."""
    return {
        "id": clock.id,
        "label": clock.label,
        "kind": clock.kind,
        "faction": clock.faction_id,
        "days_remaining": clock.days_remaining,
        "segments": clock.segments,
        "filled": clock.filled,
        "on_complete": clock.on_complete,
        "started_day": clock.started_day,
        "done_day": clock.done_day,
    }


def _clock(ctx: CampaignContext, id: int) -> Clock:
    found = ctx.storage.clocks.get(int(id))
    if found is None or found.campaign_id != ctx.campaign_id:
        running = ctx.storage.clocks.list(ctx.campaign_id, running=True)
        raise NotFound(f"No clock {id}.", [{"id": c.id, "name": c.label} for c in running])
    return found


def _running_order(clock: Clock) -> tuple[int, int, int]:
    """Countdowns first, the nearest first; then the progress clocks, in the order they were made."""
    if clock.kind == "countdown":
        return (0, clock.days_remaining or 0, clock.id)
    return (1, 0, clock.id)


def clocks(ctx: CampaignContext) -> dict[str, Any]:
    """The running clocks, the nearest countdowns first, then the progress clocks; and the completed ones."""
    listed = ctx.storage.clocks.list(ctx.campaign_id)
    running = sorted((c for c in listed if c.done_day is None), key=_running_order)
    return {
        "clocks": [clock_json(c) for c in running],
        "completed": [clock_json(c) for c in listed if c.done_day is not None],
    }


def nearest_countdowns(ctx: CampaignContext, limit: int = 5) -> list[dict[str, Any]]:
    """The running countdowns with the fewest days left, for the primer."""
    running = ctx.storage.clocks.list(ctx.campaign_id, running=True)
    countdowns = sorted((c for c in running if c.kind == "countdown"), key=_running_order)
    return [clock_json(c) for c in countdowns[:limit]]


def add_clock(
    ctx: CampaignContext,
    label: str,
    *,
    days: int | None = None,
    segments: int | None = None,
    faction: str = "",
    on_complete: str = "",
) -> dict[str, Any]:
    """A countdown of `days`, or a progress clock of `segments`: exactly one of them."""
    if (days is None) == (segments is None):
        raise PlayError(
            "A clock counts down days or fills segments: give exactly one of them.",
            "days for 'X happens in N days unless…', segments for progress the DM moves with advance_clock.",
        )
    blank = Clock(id=0, campaign_id=ctx.campaign_id, label="", kind="countdown", started_day=day_number(ctx))
    fields = {"label": label, "faction": faction, "on_complete": on_complete}
    if days is not None:
        fields |= {"kind": "countdown", "days_remaining": int(days)}
    else:
        fields |= {"kind": "progress", "segments": int(segments or 0), "filled": 0}
    clock = ctx.storage.clocks.add(shaped_clock(ctx, blank, fields))
    return {"clock": clock_json(clock), **({"completed": True} if clock.done_day is not None else {})}


def shaped_clock(ctx: CampaignContext, clock: Clock, changes: dict[str, Any]) -> Clock:
    """`clock` with `changes` (its fields by name, `faction` an id or name, empty for none), checked: a countdown needs
    its days (0 or more), a progress clock its segments (1 or more). One with nothing left, a countdown at 0 days or a
    full progress clock, is complete, on today's day unless it already was; ticking down to 0 on a new day completes
    one the same way. The DM's `add_clock` and the organisers' clocks route both shape clocks here."""
    kind = changes.get("kind") or clock.kind
    if kind not in CLOCK_KINDS:
        raise PlayError(f"Unknown kind '{kind}'.", f"Use one of: {', '.join(CLOCK_KINDS)}.")
    label = (changes.get("label") or clock.label).strip()
    if not label:
        raise PlayError("A clock needs a label.")
    faction_id = clock.faction_id
    if "faction" in changes:
        faction_id = get(ctx, changes["faction"]).id if (changes["faction"] or "").strip() else None
    days_remaining, segments, filled = (
        changes.get(key, getattr(clock, key)) for key in ("days_remaining", "segments", "filled")
    )
    if kind == "countdown":
        if days_remaining is None:
            raise PlayError("A countdown needs its days.", "Give days_remaining.")
        if days_remaining < 0:
            raise PlayError("A countdown can't have fewer than 0 days left.")
        segments = filled = None
        complete = days_remaining == 0
    else:
        if segments is None:
            raise PlayError("A progress clock needs its segments.", "Give segments.")
        if segments < 1:
            raise PlayError("A progress clock has at least 1 segment.")
        days_remaining = None
        filled = max(0, min(filled or 0, segments))
        complete = filled >= segments
    on_complete = changes.get("on_complete")
    return replace(
        clock,
        label=label,
        kind=kind,
        faction_id=faction_id,
        days_remaining=days_remaining,
        segments=segments,
        filled=filled,
        on_complete=on_complete if on_complete is not None else clock.on_complete,
        done_day=(clock.done_day or day_number(ctx)) if complete else None,
    )


def advance_clock(ctx: CampaignContext, id: int, segments: int = 1) -> dict[str, Any]:
    """Fill (or, with a negative number, empty) a progress clock's segments. Full, it completes: its `on_complete`
    comes back."""
    clock = _clock(ctx, id)
    if clock.kind != "progress":
        raise PlayError(
            f"'{clock.label}' counts down days: it ticks as days pass.", "Pass days with advance_days, or remove it."
        )
    if clock.done_day is not None:
        raise PlayError(f"'{clock.label}' is already complete.", "Add a new clock, or remove this one.")
    total = clock.segments or 0
    filled = max(0, min(total, (clock.filled or 0) + int(segments)))
    clock = replace(clock, filled=filled, done_day=day_number(ctx) if filled >= total else None)
    ctx.storage.clocks.put(clock)
    return {"clock": clock_json(clock), **({"completed": True} if clock.done_day is not None else {})}


def remove_clock(ctx: CampaignContext, id: int) -> dict[str, Any]:
    """Remove a clock: the party stopped the threat, or it became moot."""
    clock = _clock(ctx, id)
    ctx.storage.clocks.delete(clock.id)
    return {"removed": clock_json(clock)}


def _new_day(ctx: CampaignContext, day: int) -> dict[str, Any]:
    """Every running countdown loses a day. `completed`: those that reach 0 today, once. `urgent`: those with 1 to 7
    days left, as a tuple, which `days.pass_days` keeps from the last day only, so a pass of many days names each
    urgent clock once, as it stands at the end. A day with no running countdown reports nothing."""
    ensure_seeded(ctx)
    running = [c for c in ctx.storage.clocks.list(ctx.campaign_id, running=True) if c.kind == "countdown"]
    if not running:
        return {}
    completed, urgent = [], []
    for clock in running:
        left = max(0, (clock.days_remaining or 0) - 1)
        clock = replace(clock, days_remaining=left, done_day=day if left == 0 else None)
        ctx.storage.clocks.put(clock)
        if left == 0:
            completed.append(clock_json(clock))
        elif left <= URGENT_DAYS:
            urgent.append(clock_json(clock))
    return {**({"completed": completed} if completed else {}), "urgent": tuple(urgent)}


days.register("clocks", _new_day)
