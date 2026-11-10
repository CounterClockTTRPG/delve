"""Factions, clocks and quests (plan 6 Task 5; ttrpg2 `tools/factions.py`, `tools/quests.py`). The factions and the
clocks are the DM's: their notes, strength and reputation number, and every clock's `on_complete`. The quest tools
are player-visible, their feed row only. Each tool first seeds a campaign from before plateau 6 from its module."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.schema import ToolSpec, boolean, integer, params, string, strings, tool
from delve.domain.world import QUEST_STATUSES
from delve.play import factions as play_factions
from delve.play import quests as play_quests
from delve.play.context import CampaignContext

SPECS: list[ToolSpec] = []


@tool(
    SPECS,
    "factions",
    params(known_only=boolean("Only the factions the party knows of.")),
    mutates=False,
    player_visible=False,
)
def factions(ctx: CampaignContext, known_only: bool = False) -> dict[str, Any]:
    """The campaign's factions: alignment, goals, scope, whether the party knows of them, strength (0-100), the
    party's reputation (-100 to 100) and its standing word, and your notes."""
    play_factions.ensure_seeded(ctx)
    return {"factions": play_factions.list_factions(ctx, known_only)}


@tool(
    SPECS,
    "update_faction",
    params(
        "id",
        id=string("The faction's id or exact name; a new id with a name makes the faction."),
        name=string("Its name."),
        alignment=string("LE, CN, NG…"),
        goals=string("What they're after, in a line."),
        scope=string("local, regional or continental: it should match the stakes."),
        known=boolean("True once the party has heard of them in the fiction."),
        strength=integer("0-100, % of its original capacity.", minimum=0, maximum=100),
        reputation_change=integer(
            "The change in the party's standing: +5 routine help, +10 a gift or public favour, +20 a significant "
            "favour, +40 saved their leader; -5 a slight, -10 a broken promise, -20 worked against them, -40 killed a "
            "member, -80 ruined them."
        ),
        reason=string("Why the reputation changes, for the log."),
        notes=string("Your notes on them, in Markdown: they replace the old ones."),
    ),
    mutates=True,
    areas=("world",),
    player_visible=False,
)
def update_faction(
    ctx: CampaignContext,
    id: str,
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
    """Make a faction (an organisation, cult, guild, noble house, monster tribe) or change one: only the fields given
    change. The reputation clamps at -100 to 100; it adds reputation / 25 to the reaction of an NPC of the faction
    (±4 at the ends)."""
    play_factions.ensure_seeded(ctx)
    return play_factions.update_faction(
        ctx,
        id,
        name=name,
        alignment=alignment,
        goals=goals,
        scope=scope,
        known=known,
        strength=strength,
        reputation_change=reputation_change,
        reason=reason,
        notes=notes,
    )


@tool(
    SPECS,
    "add_clock",
    params(
        "label",
        label=string("What happens: 'the cult finishes the ritual'."),
        days=integer("A countdown: the days until it happens. It ticks as days pass.", minimum=1),
        segments=integer("A progress clock: its segments, which you fill with advance_clock.", minimum=1),
        faction=string("The faction behind it, by id or exact name."),
        on_complete=string("What happens when it completes, to remind you."),
    ),
    mutates=True,
    areas=("world",),
    player_visible=False,
)
def add_clock(
    ctx: CampaignContext,
    label: str,
    days: int | None = None,
    segments: int | None = None,
    faction: str = "",
    on_complete: str = "",
) -> dict[str, Any]:
    """A clock: give days for 'X happens in N days unless…' (a ritual, a siege, a ransom deadline), which counts down
    as days pass, or segments for progress you move yourself. Exactly one of the two. A completed clock comes back
    with its on_complete from the call that completed it; nothing fires by itself."""
    play_factions.ensure_seeded(ctx)
    return play_factions.add_clock(ctx, label, days=days, segments=segments, faction=faction, on_complete=on_complete)


@tool(
    SPECS,
    "advance_clock",
    params(
        "id",
        id=integer("The clock's id, from clocks."),
        segments=integer("Segments to fill; negative to empty them (a setback)."),
    ),
    mutates=True,
    areas=("world",),
    player_visible=False,
)
def advance_clock(ctx: CampaignContext, id: int, segments: int = 1) -> dict[str, Any]:
    """Fill a progress clock's segments. When it is full it completes, and its on_complete comes back. Countdowns
    tick with the days instead."""
    return play_factions.advance_clock(ctx, id, segments)


@tool(
    SPECS,
    "remove_clock",
    params("id", id=integer("The clock's id, from clocks.")),
    mutates=True,
    areas=("world",),
    player_visible=False,
)
def remove_clock(ctx: CampaignContext, id: int) -> dict[str, Any]:
    """Remove a clock: the party stopped the threat, or it became moot."""
    return play_factions.remove_clock(ctx, id)


@tool(SPECS, "clocks", params(), mutates=False, player_visible=False)
def clocks(ctx: CampaignContext) -> dict[str, Any]:
    """The running clocks, the countdowns with the fewest days left first, then the progress clocks; and the
    completed ones. Every new day, from advance_time, advance_days, rest or travel, returns the countdowns that
    completed and those within a week."""
    play_factions.ensure_seeded(ctx)
    return play_factions.clocks(ctx)


@tool(
    SPECS,
    "add_quest",
    params(
        "id",
        "title",
        id=string("Its id: 'rescue-old-henrik'."),
        title=string("Its title."),
        giver=string("Who gave it, or empty for one the party found."),
        scope=string("local, regional or continental.", enum=["local", "regional", "continental"]),
        stakes=string("What happens if the party fails or ignores it, in a line."),
        related=strings("What it concerns, as refs: npc:miller, faction:cult, a place."),
    ),
    mutates=True,
    areas=("world",),
)
def add_quest(
    ctx: CampaignContext,
    id: str,
    title: str,
    giver: str = "",
    scope: str = "local",
    stakes: str = "",
    related: list[str] | None = None,
) -> dict[str, Any]:
    """A quest the party takes up: active and known from today. Its scope should match the party's level: local for
    levels 1-3, regional from 4, continental from 8; a mismatch comes back as a warning. The module's quests are
    already there (available, not yet known): take those up with update_quest."""
    play_factions.ensure_seeded(ctx)
    return play_quests.add_quest(ctx, id, title, giver=giver, scope=scope, stakes=stakes, related=related or ())


@tool(
    SPECS,
    "update_quest",
    params(
        "id",
        id=string("The quest's id or exact title."),
        status=string("available, active, paused, complete or failed.", enum=list(QUEST_STATUSES)),
        note=string("A line for its log: progress, an outcome, a reason it failed."),
        note_known=boolean("False for a note the characters don't know."),
        known=boolean("Whether the characters know of it."),
    ),
    mutates=True,
    areas=("world",),
)
def update_quest(
    ctx: CampaignContext,
    id: str,
    status: str | None = None,
    note: str | None = None,
    note_known: bool = True,
    known: bool | None = None,
) -> dict[str, Any]:
    """Change a quest's status or add a note to its log. Active makes it known to the characters; complete and
    failed end it today. The players see known quests and their known notes."""
    play_factions.ensure_seeded(ctx)
    return play_quests.update_quest(ctx, id, status=status, note=note, note_known=note_known, known=known)


@tool(
    SPECS,
    "quests",
    params(status=string("Only those of one status.", enum=["", *QUEST_STATUSES])),
    mutates=False,
    player_visible=False,
)
def quests(ctx: CampaignContext, status: str = "") -> dict[str, Any]:
    """The campaign's quests (or those of one status) with their log and your notes, each open one with a warning
    when its scope is above the party's level, and the party's average level."""
    play_factions.ensure_seeded(ctx)
    return play_quests.list_quests(ctx, status)
