"""Sessions, the clock, and the primer that picks a session up (ttrpg2 `tools/log.py` and `session_primer`).

A campaign starts in session 1 at dawn of day 1. `new_session` starts the campaign's current session when it hasn't
been started yet, and the next one otherwise; `end_session` stores its recap, which plateau 2b's DM writes. The primer
is ttrpg2's `session_primer` without strongholds or light, and with the module the campaign plays: ttrpg2's DM
read that from the campaign's files, and Delve's DM reads no files.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from delve.domain.campaigns import CampaignState, Character, Event, Session
from delve.domain.characters import Item, pronouns_of
from delve.domain.data import to_dict
from delve.maps.dsl import DmapError, node_label, party_start_node
from delve.maps.sources import parsed_map
from delve.maps.state import from_json, groups
from delve.modules.books.convert import FRONT_MATTER
from delve.modules.dscn import parse_text
from delve.modules.source import ModuleSource, pinned_source
from delve.modules.text import ModuleText, TextSection
from delve.play import combat, factions, quests, weather
from delve.play.campaign_maps import own_names, played_revision
from delve.play.characters import party
from delve.play.context import CampaignContext, PlayError
from delve.play.days import answer, pass_days, today
from delve.play.inventory import weigh
from delve.rules.classic.encumbrance import collapse_inventory

__all__ = ["advance_days", "advance_time", "end_session", "new_session", "primer", "session_summary", "set_time"]

RECENT_EVENTS = 8
PRIMER_FACTS = 30
"""The newest of the campaign's facts in the primer: debts, vows, gifts and deaths, read before settling one (DEL-328)."""
PRIMER_NOTES = 10
NOTE_CHARS = 240
"""The newest of the DM's secret notes in the primer, each cut to this many characters (DEL-328)."""
SUMMARY_TYPES = (
    "log_note",
    "fact",
    "quest_added",
    "quest_update",
    "npc_met",
    "disposition_change",
    "combat_started",
    "departure",
    "xp_awarded",
    "treasure_awarded",
    "loot_claimed",
    "purchase",
    "coin",
    "item_added",
    "item_removed",
    "transfer",
    "possession",
    "secret_revealed",
    "ruling",
    "travel",
    "days",
    "rest",
)
"""What a session's summary keeps of its event log: what happened and what changed hands, not the clock's ticks, the
moves, the rounds or the pictures."""
SUMMARY_LINES = 200
MODULE_SECTIONS = 60
"""At most this many headings of the module's text in the primer; `sections_more` counts the rest."""
OPENING_CHARS = 4000
"""At most this much of the module's opening in the primer (DEL-79: a whole first chapter was 40 KB); `opening_more`
then says how to read the rest."""


def _state(ctx: CampaignContext) -> CampaignState:
    return ctx.storage.campaign_states.get(ctx.campaign_id)


def _session_json(session: Session) -> dict[str, Any]:
    return {"session": session.number, "title": session.title}


def new_session(ctx: CampaignContext, title: str) -> dict[str, Any]:
    """Start a session: the next one, or the campaign's first. Logged as `session_start`, in the new session."""
    if not title.strip():
        raise PlayError("A session needs a title.")
    state = _state(ctx)
    number = state.session if ctx.storage.sessions.get(ctx.campaign_id, state.session) is None else state.session + 1
    today = datetime.now(UTC).date().isoformat()
    with ctx.storage.transaction():
        ctx.storage.campaign_states.put(replace(state, session=number))
        session = ctx.storage.sessions.start(ctx.campaign_id, number, title.strip())
        ctx.log("session_start", session=number, title=session.title, date=today)
    return _session_json(session)


def end_session(ctx: CampaignContext, recap_md: str) -> dict[str, Any]:
    """End the current session with its recap (Markdown). A session that was never started is started first, as
    "Session N"."""
    number = _state(ctx).session
    with ctx.storage.transaction():
        if ctx.storage.sessions.get(ctx.campaign_id, number) is None:
            ctx.storage.sessions.start(ctx.campaign_id, number, f"Session {number}")
        session = ctx.storage.sessions.end(ctx.campaign_id, number, recap_md.strip())
        ctx.log("session_end", session=number, title=session.title)
    return {**_session_json(session), "recap_md": session.recap_md}


def session_summary(ctx: CampaignContext, number: int | None = None) -> dict[str, Any]:
    """What session `number` (the current one by default) recorded, oldest first, one line each (`SUMMARY_TYPES`):
    the log notes, the facts, the quests, the people met, the fights and deaths, the XP, the treasure, the coin and what
    changed hands, the rulings, the journeys and the days. The recap is written from it, so it covers the whole session
    and not only what the DM still has in mind (DEL-328). At most `SUMMARY_LINES`, the newest kept."""
    number = _state(ctx).session if number is None else number
    session = ctx.storage.sessions.get(ctx.campaign_id, number)
    events = [e for e in ctx.storage.events.list(ctx.campaign_id, types=SUMMARY_TYPES) if e.session == number]
    lines = [_summary_line(e) for e in events]
    out: dict[str, Any] = {
        "session": number,
        "title": session.title if session else None,
        "lines": lines[-SUMMARY_LINES:],
    }
    if len(lines) > SUMMARY_LINES:
        out["earlier"] = f"{len(lines) - SUMMARY_LINES} earlier lines left out; search_campaign finds them."
    return out


def _summary_line(event: Event) -> str:
    """One event as a line: the type and what it says, short values only."""
    data = event.data
    if event.type in ("log_note", "fact"):
        return f"{event.type}: {data.get('text', '')}"
    if event.type == "xp_awarded":
        return f"xp: {data.get('name')} +{data.get('amount')} ({data.get('xp_total')})"
    if event.type == "combat_started":
        foes = sorted({c.get("name", "") for c in data.get("combatants", []) if c.get("side") == "enemy"})
        return f"fight: {', '.join(foes)}" + (f" on {data['map']}" if data.get("map") else "")
    parts = [
        f"{key}={value}"
        for key, value in data.items()
        if not key.endswith("_id")
        and key not in ("id", "position")
        and isinstance(value, (str, int, float))
        and value not in ("", None)
    ]
    return f"{event.type}: " + ", ".join(parts)[:300]


def period(hour: int) -> str:
    """The part of the day, for narrative cues."""
    if hour < 5:
        return "night"
    if hour < 8:
        return "dawn"
    if hour < 12:
        return "morning"
    if hour < 14:
        return "midday"
    if hour < 18:
        return "afternoon"
    if hour < 21:
        return "evening"
    return "night"


def _time(state: CampaignState) -> str:
    return f"{state.hour:02d}:{state.minute:02d}"


def advance_time(ctx: CampaignContext, minutes: int) -> dict[str, Any]:
    """Move the clock on by `minutes`, into the next day at hour 24. Searching a room is 10 minutes, a short rest 30;
    long rests are `rest`, which heals."""
    state = _state(ctx)
    total = state.hour * 60 + state.minute + int(minutes)
    days_passed = total // (24 * 60)
    rest = total % (24 * 60)
    with ctx.storage.transaction():
        ctx.storage.campaign_states.put(replace(state, hour=rest // 60, minute=rest % 60))
        passed = pass_days(ctx, days_passed)
        moved = _state(ctx)
        ctx.log("time", day=moved.day, time=_time(moved), minutes=int(minutes))
    out: dict[str, Any] = {
        "minutes_advanced": minutes,
        "day": moved.day,
        "time": _time(moved),
        "period": period(moved.hour),
        "date": passed["date"].label,
    }
    if days_passed:
        out.update(answer(passed))
    return out


def advance_days(ctx: CampaignContext, days: int, reason: str = "") -> dict[str, Any]:
    """Let whole days pass, keeping the time of day: waiting, a journey told in one line, a long recovery."""
    if int(days) < 1:
        raise PlayError("At least one day must pass.", "For hours, use advance_time.")
    passed = answer(pass_days(ctx, days, reason))
    state = _state(ctx)
    return {**passed, "day": state.day, "time": _time(state)}


def set_time(ctx: CampaignContext, hour: int, minute: int = 0) -> dict[str, Any]:
    """Set the clock without changing the day, for narrative jumps: "they wake at dawn" is set_time(6)."""
    state = _state(ctx)
    moved = replace(state, hour=max(0, min(23, int(hour))), minute=max(0, min(59, int(minute))))
    with ctx.storage.transaction():
        ctx.storage.campaign_states.put(moved)
        ctx.log("time", day=moved.day, time=_time(moved))
    return {"day": moved.day, "time": _time(moved), "period": period(moved.hour)}


# ----- the primer -----


def _live_combat(ctx: CampaignContext) -> dict[str, Any] | None:
    """The live fight's `combat_status`, None when there is none."""
    if ctx.storage.combats.live(ctx.campaign_id) is None:
        return None
    return combat.combat_status(ctx)


def _digest(ctx: CampaignContext, character: Character) -> dict[str, Any]:
    sheet, state = character.sheet, character.state
    return {
        "id": character.id,
        "name": character.name,
        # How the story speaks of the PC and the god it serves (DEL-327): the narration drifted without them.
        **{k: v for k, v in {"pronouns": pronouns_of(sheet), "deity": sheet.deity.strip()}.items() if v},
        "race": sheet.race,
        "cls": sheet.cls,
        "levels": dict(sheet.levels),
        "hp": state.hp,
        "hp_max": sheet.hp_max,
        "ac": sheet.ac,
        "thac0": sheet.thac0,
        "attacks": [to_dict(a) for a in sheet.attacks],
        "conditions": list(state.conditions),
        "effects": [to_dict(e) for e in state.effects],
        "spells": {
            "memorized": [s.name for s in state.memorized],
            "uncast": [s.name for s in state.memorized if not s.cast],
        },
        "inventory": _inventory(state.inventory),
        # What only the DM knows of the items (DEL-181), apart from the inventory, which Ask the DM reads.
        **_item_dm_notes(state.inventory),
        "encumbrance": weigh(ctx, character)["band"],
        "possessions": [
            f"{p.name} ({p.kind})" for p in ctx.storage.possessions.list(ctx.campaign_id, owner_id=character.id)
        ],
    }


def _item_dm_notes(items: Iterable[Item]) -> dict[str, list[str]]:
    """`{"dm_notes": ["Glass phial: potion of neutralize poison"]}` for the items with a DM note; nothing without."""
    noted = [f"{item.name}: {item.dm_notes}" for item in items if item.dm_notes]
    return {"dm_notes": noted} if noted else {}


def _inventory(items: Iterable[Item]) -> str:
    """The inventory in one line: items without notes collapsed (`Torch x6`), then each item with notes as
    `name xN (notes)`, so what the notes say (a talking sword's name, say) reaches the DM and Ask the DM."""
    items = list(items)
    plain = collapse_inventory(f"{i.name} x{i.qty}" for i in items if not i.notes.strip())
    noted = [f"{i.name} x{i.qty} ({i.notes.strip()})" for i in items if i.notes.strip()]
    return ", ".join(plain + noted)


def positions(ctx: CampaignContext, seen: set[str] | None = None) -> list[dict[str, Any]]:
    """Where each group of characters is, map by map; with `seen`, only the groups that hold one of those
    characters (a player's own). A PC who left the party (died, retired, left) is in no group: Leoric, dead in the
    Mound of Ooze, showed as a group of his own, an empty "3:" on the play screen. His place stays in the map state,
    for when he is raised and rejoins."""
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    revision = played_revision(ctx.storage, campaign) if campaign else None
    names = {c.id: c.name for c in ctx.storage.characters.list(ctx.campaign_id) if c.departure is None}
    out = []
    for name, raw in ctx.storage.map_states.list(ctx.campaign_id).items():
        state = from_json(raw)
        placed = groups(state, [cid for cid in names if cid in state.characters])
        if not placed:
            continue
        try:
            dmap = parsed_map(revision.module_id, revision.number, revision.maps, name)[0] if revision else None
        except (DmapError, KeyError):
            dmap = None
        for location, members in placed:
            if seen is not None and not seen & set(members):
                continue
            out.append(
                {
                    "map": name,
                    "location": location,
                    "label": node_label(dmap, location) if dmap is not None else None,
                    "characters": [names[cid] for cid in names if cid in members],
                }
            )
    return out


def _event(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "type": event.type,
        "session": event.session,
        "beat": event.beat,
        "data": event.data,
        "at": event.at,
    }


def _map_start(revision, name: str) -> dict[str, Any]:
    """Where the party starts on a map: its `party_start`, else its lowest-keyed room (`_first_room`); None on a map
    without rooms."""
    try:
        dmap = parsed_map(revision.module_id, revision.number, revision.maps, name)[0]
    except (DmapError, KeyError):
        return {"start": None, "offline": True}
    node = party_start_node(dmap) or _first_room(dmap)
    return {"start": {"id": node, "label": node_label(dmap, node)} if node else None}


def _first_room(dmap) -> str | None:
    """The room a map without a `party_start` begins at: the one with the lowest key number (its label's, else its
    name's: "1", "r1", "A3"), else the first drawn. A traced map draws its rooms in any order: Thracia's level 1 drew
    room 15 first, and the DM started the party there instead of at the Entry Hall, room 1 (DEL-187)."""

    def key(item: tuple[int, tuple[str, Any]]) -> tuple[float, int]:
        order, (room_name, room) = item
        text = room.label.text if room.label is not None else room_name
        number = re.search(r"\d+", text) or re.search(r"\d+", room_name)
        return (int(number.group()) if number else math.inf, order)

    rooms = list(enumerate(dmap.rooms.items()))
    return f"room.{min(rooms, key=key)[1][0]}" if rooms else None


def _text_of(section: TextSection) -> str:
    return section.anchor.split("#", 1)[0]


def _unmapped(revision, source: ModuleSource | None, text: ModuleText) -> list[dict[str, Any]]:
    """The parts with keyed headings of which none has a room on a played map that parses: `{text, title, keys}`,
    `keys` the number of its keyed headings. The DM runs them from their text and asks the host for a map."""
    if source is None:
        return []
    playable = set()
    for m in revision.maps:
        if m.role != "map":
            continue
        try:
            parsed_map(revision.module_id, revision.number, revision.maps, m.name)
        except (DmapError, KeyError):
            continue
        playable.add(m.name)
    mapped = {
        key.text_anchor.split("#", 1)[0]
        for key in text.keys
        if key.text_anchor and key.node and key.node.removeprefix("map:").split("#", 1)[0] in playable
    }
    out = []
    for doc in source.texts:
        keyed = len(parse_text(doc.markdown).keyed())
        if keyed and doc.id not in mapped:
            out.append({"text": doc.id, "title": doc.title, "keys": keyed})
    return out


def _module(ctx: CampaignContext) -> dict[str, Any] | None:
    """The module the campaign plays, at its pinned revision: the title, the opening (the first text that isn't the
    front matter, with its read-aloud), the headings `module_lookup` searches, each map with where the party starts,
    the images `show_image` may show, `{id, description}`, and the parts that have no map (`_unmapped`). A module may
    have no maps, or no text yet."""
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    revision = played_revision(ctx.storage, campaign) if campaign else None
    if revision is None:
        return None
    own = own_names(ctx.storage, ctx.campaign_id)
    raw = ctx.storage.module_texts.revision(revision.module_id, revision.number)
    text = ModuleText.from_json(raw) if raw else ModuleText()
    opened = next((s for s in text.sections if _text_of(s) != FRONT_MATTER), None)
    opening = [
        part
        for section in text.sections
        if opened is not None and _text_of(section) == _text_of(opened)
        for part in (section.read_aloud, section.markdown)
        if part
    ]
    headings = [" > ".join(section.heading_path) for section in text.sections]
    source = pinned_source(ctx.storage, revision.module_id, revision.number)
    images = source.player_images() if source is not None else []
    opening_text = "\n\n".join(opening)
    block: dict[str, Any] = {
        "title": revision.title,
        "opening": _cut(opening_text, OPENING_CHARS),
        "sections": headings[:MODULE_SECTIONS],
        "maps": [
            {
                "name": m.name,
                "default": m.is_default,
                **_map_start(revision, m.name),
                **({"own": True} if m.name in own else {}),
            }
            for m in revision.maps
            if m.role == "map"
        ],
        "images": [{"id": a.id, "description": a.description} for a in images],
        "unmapped": _unmapped(revision, source, text),
    }
    if len(headings) > MODULE_SECTIONS:
        block["sections_more"] = len(headings) - MODULE_SECTIONS
    if len(opening_text) > OPENING_CHARS and opened is not None:
        block["opening_more"] = (
            f"The opening goes on for {len(opening_text) - OPENING_CHARS:,} more characters: "
            f"module_lookup '{opened.heading_path[-1] if opened.heading_path else revision.title}' reads it."
        )
    return block


def _cut(text: str, limit: int) -> str:
    """`text` up to `limit` characters, cut at the last paragraph (else line) break before it, with an ellipsis."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    for brk in ("\n\n", "\n"):
        at = head.rfind(brk)
        if at > limit // 2:
            return head[:at].rstrip() + " …"
    return head.rstrip() + " …"


def primer(ctx: CampaignContext, *, roll_weather: bool = True) -> dict[str, Any]:
    """What the DM needs to pick a session up, in one call: the day, the date and time, today's weather, the session
    and the last recap, the party (hit points, AC, THAC0, attacks, levels, conditions, memorized and uncast spells,
    inventory and encumbrance), the marching order, where each group is, the last 8 events, the live fight, the
    module, the active quests, the five nearest countdowns, and the party's earlier history (the DM's text of the
    history, whatever its status, else None). The weather is rolled when today has none; without `roll_weather` (a
    seat's read) it is today's last rolled, or None, and a campaign from before plateau 6 isn't seeded with its
    module's factions, clocks and quests. Then what is easy to lose late in a long session (`_continuity`, DEL-328):
    the newest facts, the possessions and where they are, and the newest secret notes."""
    state = _state(ctx)
    forecast = weather.weather(ctx) if roll_weather else weather.current(ctx)
    if roll_weather:
        factions.ensure_seeded(ctx)
    current = ctx.storage.sessions.get(ctx.campaign_id, state.session)
    recapped = [s for s in ctx.storage.sessions.list(ctx.campaign_id) if s.recap_md]
    pcs = party(ctx)
    return {
        "day": state.day,
        "date": today(ctx).to_dict(),
        "time": _time(state),
        "period": period(state.hour),
        "weather": forecast.to_dict() if forecast is not None else None,
        "session": {"number": state.session, "title": current.title if current else None},
        "last_recap": {**_session_json(recapped[-1]), "recap_md": recapped[-1].recap_md} if recapped else None,
        "party": [_digest(ctx, c) for c in pcs],
        "marching_order": [c.name for c in pcs],
        "positions": positions(ctx),
        "recent_events": [_event(e) for e in ctx.storage.events.recent(ctx.campaign_id, RECENT_EVENTS)],
        "combat": _live_combat(ctx),
        "module": _module(ctx),
        "quests": quests.active(ctx),
        "clocks": factions.nearest_countdowns(ctx),
        "history": _history(ctx),
        **_continuity(ctx),
    }


def _continuity(ctx: CampaignContext) -> dict[str, Any]:
    """What the DM settled earlier and loses when its context is cut (DEL-328): the campaign's newest facts (debts,
    vows, gifts, deaths), every possession with its owner and where it is (a boat left at a stair), and the newest of
    the DM's secret notes, cut short. Empty ones are left out."""
    names = {c.id: c.name for c in ctx.storage.characters.list(ctx.campaign_id)}
    facts = ctx.storage.campaign_facts.list(ctx.campaign_id)[-PRIMER_FACTS:]
    possessions = ctx.storage.possessions.list(ctx.campaign_id)
    notes = [n for n in ctx.storage.notes.list(ctx.campaign_id, kind="secret") if not n.revealed][-PRIMER_NOTES:]
    out: dict[str, Any] = {
        "facts": [f"day {f.day}{f' ({f.category})' if f.category else ''}: {f.text}" for f in facts],
        "possessions": [
            f"{p.name} ({p.kind}, {names.get(p.owner_id or '', 'the party')})"
            + (f": {p.location}" if p.location else "")
            for p in possessions
        ],
        "dm_notes": [_cut(n.text, NOTE_CHARS) for n in notes],
    }
    return {key: value for key, value in out.items() if value}


def _history(ctx: CampaignContext) -> str | None:
    """The DM's text of the campaign's history, whenever it has one: where a carried party has been. A Write again
    that failed, was orphaned or still runs keeps the texts it had, and those are read."""
    history = ctx.storage.histories.get(ctx.campaign_id)
    return history.dm_md if history is not None and history.dm_md.strip() else None


def level_fit(ctx: CampaignContext) -> dict[str, Any] | None:
    """`{"min", "max", "party"}` when the party's average level (`avg_party_level`) is outside the levels the
    module is written for (its metadata's `party.levels`); None when it fits, the module doesn't say, or there is no
    party yet. Thracia is for levels 3 to 8, and a party of level 1 learned it only from the DM's note (DEL-187).

    Only at the start of play: once the game has awarded XP, a party that levelled past the module is the game's own
    doing, not a party to pick again ("written for levels 1 to 1; the party is level 1.2" on a level up)."""
    if not party(ctx) or ctx.storage.events.list(ctx.campaign_id, types=("xp_awarded",), limit=1):
        return None
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    revision = played_revision(ctx.storage, campaign) if campaign else None
    levels = ((revision.metadata.get("party") or {}).get("levels") if revision else None) or None
    if isinstance(levels, (int, float)):
        levels = {"min": levels, "max": levels}
    if not isinstance(levels, dict) or not {"min", "max"} <= levels.keys():
        return None
    level = round(quests.avg_party_level(ctx), 1)
    if levels["min"] <= level <= levels["max"]:
        return None
    return {"min": levels["min"], "max": levels["max"], "party": level}
