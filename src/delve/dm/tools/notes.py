"""Notes, secrets, sessions, time and the weather (ttrpg2 `tools/secrets.py`, `tools/log.py`, `tools/weather.py` and
`session_primer`). The DM's notes and secrets are DM-only; a log note is the public chronicle."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.party import CLOCKS
from delve.dm.tools.schema import ToolSpec, boolean, integer, params, string, strings, tool
from delve.play import days, notes, sessions, weather
from delve.play.context import CampaignContext
from delve.play.days import MAX_DAYS

SPECS: list[ToolSpec] = []


@tool(
    SPECS,
    "dm_note",
    params(
        "text",
        text=string("The note."),
        tags=strings("Free-form: motive, rumour, foreshadow, plot."),
        related_to=string("The NPC, place or quest it concerns."),
    ),
    mutates=True,
    areas=(),
    player_visible=False,
)
def dm_note(ctx: CampaignContext, text: str, tags: list[str] | None = None, related_to: str = "") -> dict[str, Any]:
    """Record a hidden, DM-only note: a motive, a plan, foreshadowing. Never narrated; find it again with
    dm_secrets."""
    return notes.dm_note(ctx, text, tags or (), related_to)


@tool(
    SPECS,
    "dm_secrets",
    params(
        tag=string("Part of a tag."),
        related_to=string("Whom or what it concerns."),
        contains=string("Part of its text."),
    ),
    mutates=False,
    player_visible=False,
)
def dm_secrets(ctx: CampaignContext, tag: str = "", related_to: str = "", contains: str = "") -> dict[str, Any]:
    """Your hidden notes, filtered by tag, subject or text (every one without filters)."""
    return notes.dm_secrets(ctx, tag, related_to, contains)


@tool(
    SPECS,
    "dm_secret_update",
    params(
        "secret_id",
        secret_id=string("The note's id, from dm_secrets."),
        text=string("Its new text."),
        tags=strings("Its new tags."),
        related_to=string("Whom or what it concerns now."),
        revealed=boolean("True when the players have learned it: it becomes a public event."),
    ),
    mutates=True,
    areas=(),
    player_visible=False,
)
def dm_secret_update(
    ctx: CampaignContext,
    secret_id: str,
    text: str | None = None,
    tags: list[str] | None = None,
    related_to: str | None = None,
    revealed: bool | None = None,
) -> dict[str, Any]:
    """Edit a hidden note, or mark it revealed once the players learn it. Only the fields given change."""
    return notes.dm_secret_update(ctx, secret_id, text, tags, related_to, revealed)


@tool(SPECS, "log_note", params("text", text=string("The line.")), mutates=True, areas=())
def log_note(ctx: CampaignContext, text: str) -> dict[str, Any]:
    """A public line of the session's chronicle: what happened, as the players know it."""
    return notes.log_note(ctx, text)


@tool(SPECS, "new_session", params("title", title=string("The session's title.")), mutates=True, areas=("state",))
def new_session(ctx: CampaignContext, title: str) -> dict[str, Any]:
    """Start a session of play: the campaign's first, or the next."""
    return sessions.new_session(ctx, title)


@tool(
    SPECS,
    "session_summary",
    params(session=integer("The session's number; the current one when left out.", minimum=1)),
    mutates=False,
    player_visible=False,
)
def session_summary(ctx: CampaignContext, session: int | None = None) -> dict[str, Any]:
    """What the session recorded, oldest first, one line each: log notes, facts, quests, people met, fights and deaths,
    XP, treasure, coin and what changed hands, rulings, journeys and days. Read it before end_session, and write the
    recap from it: the whole session, not only its last scenes."""
    return sessions.session_summary(ctx, session)


@tool(
    SPECS,
    "end_session",
    params("recap", recap=string("The session's recap, in Markdown: the whole session, from session_summary.")),
    mutates=True,
    areas=("state",),
)
def end_session(ctx: CampaignContext, recap: str) -> dict[str, Any]:
    """End the session with its recap: what happened in the whole session (session_summary has it), for the next
    session's primer."""
    return sessions.end_session(ctx, recap)


@tool(
    SPECS,
    "advance_time",
    params(
        "minutes",
        minutes=integer("Minutes: a search is 10 (a turn), a short rest 30.", minimum=0, maximum=MAX_DAYS * 1440),
    ),
    mutates=True,
    areas=("world",),
    dm_only_keys=CLOCKS,
)
def advance_time(ctx: CampaignContext, minutes: int) -> dict[str, Any]:
    """Move the clock on, into the next day past midnight. Long rests are rest, which heals."""
    return sessions.advance_time(ctx, minutes)


@tool(
    SPECS,
    "set_time",
    params(
        "hour",
        hour=integer("0-23.", minimum=0, maximum=23),
        minute=integer("0-59.", minimum=0, maximum=59),
    ),
    mutates=True,
    areas=("world",),
)
def set_time(ctx: CampaignContext, hour: int, minute: int = 0) -> dict[str, Any]:
    """Set the clock without changing the day, for narrative jumps: 'they wake at dawn' is set_time(6)."""
    return sessions.set_time(ctx, hour, minute)


@tool(
    SPECS,
    "advance_days",
    params(
        "days",
        days=integer("Whole days, at least 1.", minimum=1, maximum=MAX_DAYS),
        reason=string("Why they pass: waiting for the caravan, a week of study."),
    ),
    mutates=True,
    areas=("world",),
    dm_only_keys=CLOCKS,
)
def advance_days(ctx: CampaignContext, days: int, reason: str = "") -> dict[str, Any]:
    """Let whole days pass, keeping the time of day, as every new day does: the clocks tick and the weather turns.
    For hours use advance_time; a journey is travel, a party's rest is rest."""
    return sessions.advance_days(ctx, days, reason)


@tool(
    SPECS,
    "weather_check",
    params(terrain=string("dungeon, wilderness, road, urban, forest, hills, plains, mountain, swamp, desert…")),
    mutates=True,
    areas=("world",),
)
def weather_check(ctx: CampaignContext, terrain: str = "") -> dict[str, Any]:
    """Today's weather in a terrain (the last one asked, else wilderness), rolled once a day and terrain and kept for
    the day, on the date's season. Apply its effect to missile fire, travel pace and encounter checks; pace is the
    multiplier on a day's travel (0: the day is lost)."""
    rolled = weather.weather(ctx, terrain)
    date = days.today(ctx)
    return {
        "date": date.label,
        "season": date.season,
        "terrain": rolled.terrain,
        "weather": rolled.label,
        "effect": rolled.effect,
        "pace": rolled.pace,
    }


@tool(SPECS, "calendar", params(), mutates=False)
def calendar(ctx: CampaignContext) -> dict[str, Any]:
    """Today's date on the setting's calendar, its season, whether it is a festival, and the campaign day. The date
    is derived from the day: days pass with advance_time, advance_days, rest and travel."""
    date = days.today(ctx)
    return {
        "date": date.label,
        "season": date.season,
        "festival": date.festival,
        "day": ctx.storage.campaign_states.get(ctx.campaign_id).day,
    }


@tool(SPECS, "session_primer", params(), mutates=False, player_visible=False)
def session_primer(ctx: CampaignContext) -> dict[str, Any]:
    """What you need to pick the session up, in one call: the day, date and time, today's weather, the session and the
    last recap, the party (hit points, AC, THAC0, attacks, levels, conditions, spells, inventory, encumbrance), the
    marching order, where each group is, the last 8 events, the live fight, the module this campaign plays (title,
    opening, the headings of its text, and each map with the room where the party starts), and `history`: where a
    party carried on from an earlier campaign has been, or null."""
    return sessions.primer(ctx)
