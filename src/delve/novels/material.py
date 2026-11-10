"""What a novel's writer reads (novelization Task 3): a campaign's record with its module, or a module alone.

A campaign's material is, in this order: the characters with their fates; per session in range, its title, its recap
and its story; the NPCs met; the DM's `secret` and `room` notes, revealed or not; and last, the module revision the
campaign plays, the rooms never reached included (owner decision 8). The story is every audience's: a private act is
marked "(in secret)" and a `tell` "(told only to <names>)". Tool rows and `dm_error`s are mechanics, and are left out,
as is the `dm_log`. A history (`delve.histories.material`) reads it without the module, and its table version with
the `table` audience, which leaves out at the source everything the whole table wasn't told.

Story entries have no session: an entry belongs to the last session that started at or before it, and an entry from
before session 1 to session 1 (plan decision 5).

A module's material is its pinned revision's texts in order, the read-aloud boxes marked, its key, its NPCs,
encounters and factions, and its pregens, who are its party.

Reading writes nothing: not the campaign, not the module, not even the source a legacy revision lacks (which
`pinned_source` would store). `condense` shortens material longer than `MAX_PROMPT_CHARS`, one side call per session
(a module's: per text), and no prompt it sends is longer than that either.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from delve.domain.campaigns import Character, Session, StoryEntry
from delve.modules.dscn import DEFAULT_LIMITS, Bundle
from delve.modules.dscn.text import split_front_matter
from delve.modules.source import SOURCE_BUNDLE, ModuleSource, derive, from_bundle
from delve.rules.classic.life import DEAD_AT
from delve.storage import Storage

__all__ = [
    "MAX_PROMPT_CHARS",
    "MODULE_HEADING",
    "Complete",
    "Material",
    "MaterialTooLong",
    "Part",
    "Progress",
    "SessionRangeError",
    "campaign_material",
    "condense",
    "module_material",
    "render",
]

MAX_PROMPT_CHARS = 400_000
"""The longest prompt a novel job sends: about 100,000 tokens, well inside the writer's context."""

MODULE_HEADING = "The module: what was there, played or not"

Complete = Callable[[str], Awaitable[str]]
Progress = Callable[[str, int, int], None]
"""`(step, done, total)`, as the books' steps report it."""

CONDENSE_CONCURRENCY = 3


@dataclass(frozen=True)
class Part:
    heading: str
    text: str
    session: int | None
    summarise: bool = False
    """A module's text (in a campaign, the module): `condense` may replace it by a summary, after the sessions."""


@dataclass(frozen=True)
class Material:
    title: str
    kind: Literal["campaign", "module"]
    party: list[str]
    parts: list[Part] = field(default_factory=list)


class SessionRangeError(ValueError):
    """A session range that is reversed, starts below 1, or goes past the campaign's last session."""

    def __init__(self, hint: str) -> None:
        self.hint = hint
        super().__init__(hint)


class MaterialTooLong(ValueError):
    """Material still longer than `MAX_PROMPT_CHARS` once everything that may be condensed is."""


# ----- a campaign -----


def campaign_material(
    storage: Storage,
    campaign_id: str,
    sessions: tuple[int, int] | None,
    *,
    audience: Literal["all", "table"] = "all",
    with_module: bool = True,
) -> Material:
    """The campaign's record for the sessions `sessions` (both included; None: all of them), and its module.
    `KeyError` for no such campaign, `SessionRangeError` for a bad range.

    `audience="table"` (a history's table version, carry-the-party-on Task 4) is filtered here, before any writer
    sees it: only the story entries every seat saw (`audience` None), without private acts, `told_to` lines, table
    talk or Ask; the NPCs without their `notes_md`, and with a faction only when it is known; no DM's secrets and
    notes. `with_module=False` leaves the module out. Novels keep the defaults."""
    campaign = storage.campaigns.get(campaign_id)
    if campaign is None:
        raise KeyError(campaign_id)
    played = storage.sessions.list(campaign_id)
    first, last = _range(sessions, len(played))
    characters = storage.characters.list(campaign_id)
    pcs = [c for c in characters if c.kind == "pc"]
    names = {c.id: c.name for c in characters}
    seats = {s.id: s.name for s in storage.seats.list(campaign_id)}
    table = audience == "table"
    story = storage.story.list(campaign_id)
    entries = _by_session([e for e in story if _for_the_table(e)] if table else story, played)
    told = sessions is not None and last < len(played)
    parts = [Part("The characters", _characters(storage, campaign_id, pcs, last if told else None), None)]
    for number in range(first, last + 1):
        session = played[number - 1] if number <= len(played) else None
        lines = [_story_line(e, names, seats) for e in entries.get(number, [])]
        parts.append(_session_part(number, session, [line for line in lines if line]))
    npcs = [c for c in characters if c.kind == "npc"]
    if table:
        known = {f.id: f.name for f in storage.factions.list(campaign_id, known=True)}
        npcs = [_for_the_table_npc(npc, known) for npc in npcs]
    parts.append(Part("The NPCs met", _npcs(npcs), None))
    if not table:
        parts.append(Part("The DM's secrets and notes", _notes(storage, campaign_id), None))
    if with_module:
        module = module_material(storage, campaign.module_id, campaign.revision)
        parts.append(Part(MODULE_HEADING, _render_parts(module.parts, "###"), None, summarise=True))
    return Material(campaign.name, "campaign", [c.name for c in pcs], parts)


TABLE_KINDS = ("player_act", "dm_text", "image", "scene")
"""The story kinds the table's material keeps: what happened in the game, not talk or Ask around it."""


def _for_the_table(entry: StoryEntry) -> bool:
    """Whether the whole table saw the entry: no audience, a kind of the game, not private and told to all."""
    payload = entry.payload
    return (
        entry.audience is None
        and entry.kind in TABLE_KINDS
        and not payload.get("private")
        and not payload.get("told_to")
    )


def _for_the_table_npc(npc: Character, known: dict[str, str]) -> Character:
    """The NPC without its DM's notes, its faction named only when the table knows that faction."""
    faction = known.get(npc.sheet.faction, "")
    return replace(npc, sheet=replace(npc.sheet, notes_md="", faction=faction))


def _range(sessions: tuple[int, int] | None, count: int) -> tuple[int, int]:
    """The first and last session to read; a campaign without sessions still has its story as session 1."""
    if sessions is None:
        return 1, max(count, 1)
    first, last = sessions
    if first < 1 or last < 1:
        raise SessionRangeError("Sessions are numbered from 1.")
    if first > last:
        raise SessionRangeError(f"The range {first}–{last} is reversed: give the first session first.")
    if last > count:
        held = "no sessions yet" if count == 0 else f"{count} session{'s' if count != 1 else ''}"
        raise SessionRangeError(f"The campaign has {held}: choose a range within them.")
    return first, last


def _by_session(entries: Sequence[StoryEntry], played: Sequence[Session]) -> dict[int, list[StoryEntry]]:
    """The entries of each session, by time: the last session that started at or before the entry, else session 1."""
    out: dict[int, list[StoryEntry]] = {}
    for entry in entries:
        number = 1
        for session in played:
            if session.started_at and session.started_at <= entry.at:
                number = session.number
        out.setdefault(number, []).append(entry)
    return out


def _session_part(number: int, session: Session | None, lines: list[str]) -> Part:
    title = session.title if session is not None and session.title else ""
    head = []
    if session is not None and session.recap_md:
        head.append(f"Recap: {session.recap_md.strip()}")
    text = "\n\n".join([*head, *lines]) if head or lines else "(nothing was played)"
    return Part(f"Session {number}: {title}" if title else f"Session {number}", text, number)


def _story_line(entry: StoryEntry, names: dict[str, str], seats: dict[str, str]) -> str:
    """One story entry as the writer reads it; "" for mechanics (tool rows, errors) and the session recap, which
    the session's own recap gives."""
    payload = entry.payload
    text = str(payload.get("text") or "").strip()
    if entry.kind == "player_act":
        acting = [names[i] for i in payload.get("character_ids") or [] if i in names]
        who = ", ".join(acting) or str(payload.get("name") or seats.get(str(payload.get("seat_id")), "")) or "A player"
        secret = " (in secret)" if payload.get("private") else ""
        return f"{who}{secret}: {text}" if text else ""
    if entry.kind == "dm_text":
        if not text:
            return ""
        if payload.get("told_to"):
            to = ", ".join(names.get(i, i) for i in payload["told_to"])
            return f"The DM (told only to {to}): {text}"
        if entry.audience and "seats" in entry.audience:
            return f"The DM (a note for the host, out of the game): {text}"
        return f"The DM: {text}"
    if entry.kind == "talk":
        return f"{payload.get('name') or 'A player'} (table talk, out of the game): {text}" if text else ""
    if entry.kind == "ask":
        return f"A player asked the DM, out of the game: {text}" if text else ""
    if entry.kind == "answer":
        return f"The DM answered, out of the game: {text}" if text else ""
    if entry.kind in ("image", "scene"):
        caption = str(payload.get("caption") or "").strip()
        return f"(A picture is shown: {caption})" if caption else ""
    return ""


def _characters(storage: Storage, campaign_id: str, pcs: Sequence[Character], last: int | None) -> str:
    """Each PC with who they are and their fate: alive, downed or dead, with the session it happened. Reading only
    up to session `last`, a fate that came later is told as "alive at the end of session <last>"."""
    hurt: dict[str, list[tuple[int, int]]] = {}
    for event in storage.events.list(campaign_id, types=["damage"]):
        after = event.data.get("hp_after")
        if isinstance(after, int):
            hurt.setdefault(str(event.data.get("character_id")), []).append((event.session, after))
    lines = []
    for pc in pcs:
        sheet = pc.sheet
        levels = "/".join(str(n) for n in sheet.levels.values())
        who = " ".join(part for part in (sheet.race, sheet.cls, levels) if part)
        fate = _fate(pc, hurt.get(pc.id, []), last)
        about = f" ({who})" if who else ""
        background = f" {sheet.background.strip()}" if sheet.background.strip() else ""
        lines.append(f"- {pc.name}{about}: {fate}.{background}")
    return "\n".join(lines) if lines else "(no characters)"


def _fate(pc: Character, hurt: list[tuple[int, int]], last: int | None) -> str:
    hp = pc.state.hp
    if hp <= DEAD_AT:
        fate, at = "dead", [s for s, after in hurt if after <= DEAD_AT]
    elif hp <= 0 or "downed" in pc.state.conditions:
        fate, at = "downed", [s for s, after in hurt if after <= 0]
    else:
        return f"alive at the end of session {last}" if last is not None else "alive"
    session = at[-1] if at else None
    if last is not None and (session is None or session > last):
        return f"alive at the end of session {last}"
    return f"{fate} (in session {session})" if session is not None else fate


def _npcs(npcs: Sequence[Character]) -> str:
    lines = []
    for npc in npcs:
        sheet = npc.sheet
        facts = [part for part in (sheet.race, sheet.gender, sheet.faction and f"of {sheet.faction}") if part]
        about = f" ({', '.join(facts)})" if facts else ""
        story = " ".join(part.strip() for part in (sheet.background, sheet.notes_md) if part.strip())
        dead = " Dead." if npc.state.hp <= DEAD_AT and sheet.hp_max else ""
        lines.append(f"- {npc.name}{about}: {story}{dead}".rstrip(": "))
    return "\n".join(lines) if lines else "(no NPCs met)"


def _notes(storage: Storage, campaign_id: str) -> str:
    lines = []
    for note in storage.notes.list(campaign_id):
        if note.kind == "secret":
            lines.append(f"- Secret ({'revealed' if note.revealed else 'never revealed'}): {note.text}")
        elif note.kind == "room":
            lines.append(f"- In {note.map_name or 'the map'}, room {note.node or '?'}: {note.text}")
    return "\n".join(lines) if lines else "(no notes)"


# ----- a module -----


def module_material(storage: Storage, module_id: str, revision: int) -> Material:
    """The module at revision `revision`: its texts, key, NPCs, encounters, factions and pregens, the pregens as the
    party. `KeyError` for no such module or revision."""
    pinned = storage.revisions.get(module_id, revision)
    if pinned is None:
        raise KeyError((module_id, revision))
    source = _pinned_source(storage, module_id, revision)
    parts = []
    details = {k: v for k, v in pinned.metadata.items() if v not in (None, "", [], {})}
    if details:
        parts.append(Part("The module's details", _fields(details), None))
    parts += [Part(t.title or t.id, _text(t.markdown), None, summarise=True) for t in source.texts]
    key = _key(source, pinned.maps)
    if key:
        parts.append(Part("The key", key, None))
    for kind, heading in (
        ("npcs", "The NPCs"),
        ("encounters", "The encounters"),
        ("factions", "The factions"),
        ("pregens", "The party (the module's pregens)"),
    ):
        records = source.entities.get(kind) or []
        if records:
            parts.append(Part(heading, "\n".join(_record(r) for r in records), None))
    party = [_name(r) for r in source.entities.get("pregens") or []]
    return Material(pinned.title, "module", party, parts)


def _pinned_source(storage: Storage, module_id: str, number: int) -> ModuleSource:
    """`delve.modules.source.pinned_source` without its write: a revision from before sources existed reads the
    source its module's bundle gives, which is not stored."""
    pinned = storage.module_sources.revision(module_id, number)
    if pinned is not None:
        return pinned
    for role, sha in storage.blobs.links(module_id):
        if role == SOURCE_BUNDLE and (data := storage.blobs.get(sha)) is not None:
            return from_bundle(Bundle.load(data, limits=DEFAULT_LIMITS))
    return ModuleSource()


_ANCHOR = re.compile(r"^(#{1,6}\s.*?)\s*\{#[A-Za-z0-9][A-Za-z0-9._-]*\}\s*$")


def _text(markdown: str) -> str:
    """A text's Markdown for the writer: no front matter, no `{#anchor}`s, and each read-aloud box (a blockquote)
    marked "(read aloud)"."""
    _, body, _ = split_front_matter(markdown)
    out: list[str] = []
    quote: list[str] = []

    def flush() -> None:
        if quote:
            out.append("(read aloud) " + "\n".join(quote).strip())
            quote.clear()

    for line in body.splitlines():
        if line.startswith(">"):
            quote.append(line[1:].strip())
            continue
        flush()
        out.append(_ANCHOR.sub(r"\1", line))
    flush()
    return "\n".join(out).strip()


def _key(source: ModuleSource, maps: Sequence[Any]) -> str:
    links = derive(source, list(maps)).links
    lines = [f"- {link.key}: {link.label} (map {link.map}, {link.node})" for link in links]
    return "\n".join(lines)


def _name(record: dict[str, Any]) -> str:
    return str(record.get("name") or record.get("title") or record.get("id") or "?")


def _record(record: dict[str, Any]) -> str:
    rest = {k: v for k, v in record.items() if k not in ("id", "name", "title", "audience")}
    return f"- {_name(record)}" + (f"\n{_fields(rest, '  ')}" if rest else "")


def _fields(values: dict[str, Any], indent: str = "") -> str:
    return "\n".join(
        f"{indent}{k}: {v if isinstance(v, str | int | float) else json.dumps(v, ensure_ascii=False)}"
        for k, v in values.items()
    )


# ----- rendering and condensing -----


def render(material: Material) -> str:
    """The material as one Markdown text: the title, the party, then each part under its heading."""
    head = [f"# {material.title}"]
    if material.party:
        head.append(f"The party: {', '.join(material.party)}")
    return "\n\n".join([*head, _render_parts(material.parts, "##")]).rstrip() + "\n"


def _render_parts(parts: Sequence[Part], level: str) -> str:
    return "\n\n".join(f"{level} {part.heading}\n\n{part.text.strip()}" for part in parts)


CONDENSE_PROMPT = """You are condensing the record of a {kind} so that a novelist can retell it. Summarise the part
below in plain prose, at most about {words} words. Keep the names (characters, NPCs, places), who was there, the
deaths and the wounds that mattered, the finds and treasure, the secrets revealed, and what was decided, in the order
they happened. Leave out dice, game terms and table talk. Answer with the summary only.

The {kind}: {title}. The party: {party}.

{heading}{piece}

{text}
"""

SUMMARY_WORDS = 400


async def condense(material: Material, complete: Complete, progress: Progress | None = None) -> Material:
    """The material as it is when `render` fits in `MAX_PROMPT_CHARS`. Otherwise each session's part is replaced by
    one side call's summary (a part too long for one prompt, in pieces), and then, if it still doesn't fit, each
    module text's. `MaterialTooLong` when even that doesn't fit. Progress is reported as the step "condensing"."""
    if len(render(material)) <= MAX_PROMPT_CHARS:
        return material
    for chosen in (lambda p: p.session is not None, lambda p: p.summarise):
        indexes = [i for i, part in enumerate(material.parts) if chosen(part)]
        if not indexes:
            continue
        summaries = await _summarise(material, [material.parts[i] for i in indexes], complete, progress)
        parts = list(material.parts)
        for i, text in zip(indexes, summaries, strict=True):
            parts[i] = replace(parts[i], text=text, summarise=False)
        material = replace(material, parts=parts)
        if len(render(material)) <= MAX_PROMPT_CHARS:
            return material
    raise MaterialTooLong("The material is too long to write from, even condensed.")


async def _summarise(
    material: Material, parts: Sequence[Part], complete: Complete, progress: Progress | None
) -> list[str]:
    flat: list[tuple[int, int, str, int]] = []
    for n, part in enumerate(parts):
        pieces = _pieces(material, part)
        flat += [(n, i, text, len(pieces)) for i, text in enumerate(pieces)]
    total = len(flat)
    done = 0
    limit = asyncio.Semaphore(CONDENSE_CONCURRENCY)
    if progress is not None:
        progress("condensing", 0, total)

    async def one(n: int, i: int, text: str, count: int) -> str:
        nonlocal done
        async with limit:
            answer = (await complete(_prompt(material, parts[n], text, i, count))).strip()
        done += 1
        if progress is not None:
            progress("condensing", done, total)
        return answer

    answers = await asyncio.gather(*(one(*call) for call in flat))
    out: list[list[str]] = [[] for _ in parts]
    for (n, _, _, _), answer in zip(flat, answers, strict=True):
        out[n].append(answer)
    return ["\n\n".join(texts) for texts in out]


def _prompt(material: Material, part: Part, text: str, index: int, count: int) -> str:
    piece = f" (piece {index + 1} of {count})" if count > 1 else ""
    return CONDENSE_PROMPT.format(
        kind=material.kind,
        words=SUMMARY_WORDS,
        title=material.title,
        party=", ".join(material.party) or "not named",
        heading=part.heading,
        piece=piece,
        text=text,
    )


def _pieces(material: Material, part: Part) -> list[str]:
    """The part's text in pieces that each fit one prompt, cut between paragraphs where it can."""
    budget = MAX_PROMPT_CHARS - len(_prompt(material, part, "", 0, 2)) - 100
    pieces: list[str] = []
    current = ""
    for paragraph in part.text.split("\n\n"):
        while len(paragraph) > budget:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(paragraph[:budget])
            paragraph = paragraph[budget:]
        if current and len(current) + 2 + len(paragraph) > budget:
            pieces.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current or not pieces:
        pieces.append(current)
    return pieces
