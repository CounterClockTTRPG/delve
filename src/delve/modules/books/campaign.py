"""Generating a campaign in steps (DEL-134): a request for a campaign-sized, multi-level dungeon becomes a module.

One answer can't hold a campaign: the owner's request took one call 682 s and 87k tokens, and still gave one keyed
text and one map. So the request is first scoped (`scope_request`, `prompts/generate-scope.md`): its `scale`,
`module` (today's one call, `generate.generate_module`) or `campaign`, and the questions the organiser answers before
anything is written, each with what Claude would assume. Their answers go into every prompt (`with_answers`).

A campaign is then written in calls each well under a conversion's limit (`generate_campaign`):

1. **The outline** (`generate-outline.md`): title, summary, party, history, the campaign's thread, the factions and
   how they relate, 2 to `MAX_LEVELS` levels (a letter, a name, a range of character levels, how many rooms), and the
   connections between levels, room to room by key (`A14 → B1`).
2. **The campaign's texts** (`generate-campaign.md`): history, factions, thread, trade, magic items, surprises, the
   end, as `gm` texts, and the campaign's NPCs, factions and quests as entities.
3. **One call per level** (`generate-level.md`), `concurrency` at once: its keyed rooms (`A1`, `A2`…, the level's
   letter first), its wandering monster table (a section of its text and an `encounter` record) and its encounters.
   A level that can't be read twice is left out with a `level-not-written` warning; the others stand.
4. **One sketched map per level**, `level-<letter>`, the first the module's default; each level's text links to its
   own. Delve then adds the exits between levels itself, at the centres of the rooms a connection joins, both ways
   (`join_levels`), so no coordinates are guessed. A connection whose room or map is missing is a `exit-not-joined`
   warning.

The progress steps are `planning` (the outline), `campaign`, `levels` (n of N) and `maps` (n of N). An outline
that can't be read twice fails the job with `GenerationError`.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from delve.dice import Rng, SystemRng
from delve.domain.modules import ModuleMap
from delve.maps.dsl.geometry import node_centroid
from delve.maps.sources import parse_source
from delve.modules.books.calls import all_of
from delve.modules.books.convert import Complete, Converted, Progress, Question, take_questions, text_id
from delve.modules.books.generate import (
    GenerationError,
    Room,
    Unreadable,
    party_of,
    plan_entities,
    read_room,
    rolled_names,
    section,
)
from delve.modules.books.repair import repair_refs
from delve.modules.books.sketch import GAME, design_map, fill, prompt, room_name
from delve.modules.dscn.text import add_anchors
from delve.modules.source import ModuleSource, TextDoc, Warning
from delve.modules.text import unique

Scale = Literal["module", "campaign", "sandbox"]
SCALES: tuple[Scale, ...] = ("module", "campaign", "sandbox")

MAX_LEVELS = 10
"""The most levels an outline may give; more are left out."""
MAX_ROOMS = 30
"""The most rooms a level is asked for."""
MAX_QUESTIONS = 5
CONCURRENCY = 3
"""How many levels, and maps, are written at once."""

CAMPAIGN_KINDS = (("npcs", "npc"), ("factions", "faction"), ("quests", "quest"))
"""The campaign texts' entity lists, as the manifest's kinds, with their schema `$defs`."""
LEVEL_KINDS = (("encounters", "encounter"),)

_FENCE = re.compile(r"^```(?:json)?[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_LETTER = re.compile(r"^[A-Z]$")
_KEY = re.compile(r"^([A-Z])(\d+[a-z]?)$")

ANSWERS_HEADING = "## The organiser's answers"
_RETRY = """

---

Your answer:

{answer}

It couldn't be read: {reason}. Answer again with the whole of it as one JSON object, and nothing else.
"""


@dataclass(frozen=True)
class Scope:
    """How big a request is, and what to ask the organiser before it is written."""

    scale: Scale
    questions: list[Question] = field(default_factory=list)


@dataclass(frozen=True)
class Answer:
    """A scope question as the organiser answered it: their `answer`, or "" to keep Claude's `default`."""

    text: str
    default: str
    answer: str = ""


@dataclass(frozen=True)
class Level:
    letter: str
    name: str
    levels: Any
    rooms: int
    summary: str

    @property
    def map_name(self) -> str:
        return f"level-{self.letter.lower()}"

    @property
    def title(self) -> str:
        return f"Level {self.letter}: {self.name}"


@dataclass(frozen=True)
class Connection:
    start: str
    end: str
    how: str


@dataclass(frozen=True)
class Outline:
    title: str
    summary: str
    party: dict[str, Any]
    history: str
    thread: str
    factions: list[dict[str, Any]]
    levels: list[Level]
    connections: list[Connection]
    questions: list[Question]


@dataclass(frozen=True)
class _Written:
    """A level as written: its rooms, its text's other parts, and its encounter records."""

    level: Level
    intro: str
    rooms: list[Room]
    wandering: dict[str, Any]
    entities: dict[str, Any]


# ----- reading answers -----


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _object(answer: str) -> dict[str, Any]:
    """The JSON object in an answer: its first fenced block, else from its first `{` to its last `}`."""
    fenced = _FENCE.search(answer)
    body = fenced.group(1) if fenced else answer[answer.find("{") : answer.rfind("}") + 1]
    try:
        raw = json.loads(body)
    except json.JSONDecodeError as error:
        raise Unreadable(f"it isn't JSON ({error.msg})") from None
    if not isinstance(raw, dict):
        raise Unreadable("it isn't a JSON object")
    return raw


async def _asked[T](first: str, complete: Complete, read: Any) -> T:
    """`read` of the answer to `first`, asked once more with the reason when it can't be read; `Unreadable` then."""
    answer = await complete(first)
    try:
        return read(answer)
    except Unreadable as unreadable:
        retry = first + _RETRY.format(answer=answer.strip(), reason=unreadable)
    return read(await complete(retry))


def _names(rng: Rng) -> str:
    return "\n".join(f"- {race}: {', '.join(rolled)}" for race, rolled in rolled_names(rng).items())


# ----- the scope -----


def _read_scope(answer: str) -> Scope:
    raw = _object(answer)
    scale = raw.get("scale")
    if scale not in SCALES:
        raise Unreadable(f"its scale is {scale!r}, not module, campaign or sandbox")
    questions = []
    for item in raw.get("questions") or []:
        text = _text(item.get("text")) if isinstance(item, dict) else ""
        if text:
            questions.append(Question(f"s{len(questions) + 1}", text, _text(item.get("default"))))
    return Scope(scale, questions[:MAX_QUESTIONS])


async def scope_request(request: str, complete: Complete, *, game: str = "") -> Scope:
    """The request's scale and the questions to ask first (`s1`, `s2`…, at most `MAX_QUESTIONS`). An answer that
    can't be read twice is a module's scale with no questions: today's one call is never worse than before."""
    first = fill(prompt("generate-scope.md"), request=request.strip(), game=game or GAME)
    try:
        return await _asked(first, complete, _read_scope)
    except Unreadable:
        return Scope("module")


def with_answers(request: str, answers: list[Answer]) -> str:
    """The request, followed by the organiser's answers to the scope questions (an empty one keeps the assumption)."""
    if not answers:
        return request.strip()
    lines = [
        f"- {a.text} **{a.answer.strip()}**" if a.answer.strip() else f"- {a.text} {a.default} (assumed)"
        for a in answers
    ]
    return f"{request.strip()}\n\n{ANSWERS_HEADING}\n\n" + "\n".join(lines)


# ----- the outline -----


def _level(raw: Any) -> Level:
    if not isinstance(raw, dict):
        raise Unreadable("a level isn't a JSON object")
    letter = _text(raw.get("letter")).upper()
    if not _LETTER.match(letter):
        raise Unreadable(f"the level letter {raw.get('letter')!r} isn't one capital letter")
    name = _text(raw.get("name"))
    if not name:
        raise Unreadable(f"level {letter} has no name")
    rooms = raw.get("rooms")
    count = max(4, min(MAX_ROOMS, rooms)) if isinstance(rooms, int) else 15
    return Level(letter, name, raw.get("levels"), count, _text(raw.get("summary")))


def _read_outline(answer: str) -> Outline:
    answer, questions = take_questions(answer)
    raw = _object(answer)
    title = _text(raw.get("title"))
    if not title:
        raise Unreadable("the outline has no title")
    if not isinstance(raw.get("levels"), list) or len(raw["levels"]) < 1:
        raise Unreadable("the outline has no levels")
    levels = [_level(level) for level in raw["levels"][:MAX_LEVELS]]
    letters = [level.letter for level in levels]
    if len(set(letters)) != len(letters):
        raise Unreadable("two levels have the same letter")
    connections = []
    for item in raw.get("connections") or []:
        if not isinstance(item, dict):
            continue
        start, end = _text(item.get("from")).upper(), _text(item.get("to")).upper()
        joined = [_KEY.match(start), _KEY.match(end)]
        if all(joined) and joined[0].group(1) != joined[1].group(1) and {start[0], end[0]} <= set(letters):  # type: ignore[union-attr]
            connections.append(Connection(start, end, _text(item.get("how"))))
    factions = [f for f in raw.get("factions") or [] if isinstance(f, dict)]
    return Outline(
        title,
        _text(raw.get("summary")),
        party_of(raw.get("party")),
        _text(raw.get("history")),
        _text(raw.get("thread")),
        factions,
        levels,
        connections,
        questions,
    )


def _range(levels: Any) -> str:
    if isinstance(levels, int):
        return f"level {levels}"
    if isinstance(levels, dict) and isinstance(levels.get("min"), int) and isinstance(levels.get("max"), int):
        return f"levels {levels['min']}–{levels['max']}"
    return ""


def outline_text(outline: Outline) -> str:
    """The outline as the later prompts read it, in Markdown."""
    parts = [f"# {outline.title}", outline.summary]
    if outline.history:
        parts.append(f"## History\n\n{outline.history}")
    if outline.thread:
        parts.append(f"## The thread\n\n{outline.thread}")
    if outline.factions:
        lines = [
            f"- **{_text(f.get('name')) or _text(f.get('id'))}** (`faction:{_text(f.get('id'))}`, levels "
            f"{', '.join(map(str, f.get('levels') or [])) or 'any'}): {_text(f.get('summary'))} "
            f"{_text(f.get('relations'))}".rstrip()
            for f in outline.factions
        ]
        parts.append("## Factions\n\n" + "\n".join(lines))
    parts.append("## Levels\n\n" + "\n".join(_level_line(level) for level in outline.levels))
    if outline.connections:
        parts.append("## Between the levels\n\n" + "\n".join(_connection_line(c) for c in outline.connections))
    return "\n\n".join(p for p in parts if p)


def _level_line(level: Level) -> str:
    span = _range(level.levels)
    return f"- **{level.title}**" + (f" ({span})" if span else "") + f", {level.rooms} rooms: {level.summary}"


def _connection_line(connection: Connection) -> str:
    return f"- {connection.start} ↔ {connection.end}" + (f": {connection.how}" if connection.how else "")


# ----- the campaign's texts -----


def _read_campaign(answer: str) -> dict[str, Any]:
    raw = _object(answer)
    texts = raw.get("texts")
    if not isinstance(texts, list) or not texts:
        raise Unreadable("it has no texts")
    return raw


def _campaign_texts(raw: dict[str, Any], used: set[str]) -> list[TextDoc]:
    docs = []
    for item in raw.get("texts") or []:
        title = _text(item.get("title")) if isinstance(item, dict) else ""
        body = _text(item.get("markdown")) if isinstance(item, dict) else ""
        if title and body:
            docs.append(TextDoc(unique(text_id(title), used), title, "gm", None, _anchored(f"# {title}\n\n{body}")))
    return docs


# ----- the levels -----


def _read_level(level: Level) -> Any:
    def read(answer: str) -> _Written:
        raw = _object(answer)
        if not isinstance(raw.get("rooms"), list) or not raw["rooms"]:
            raise Unreadable("the level has no rooms")
        rooms = [read_room(lettered(room, level.letter)) for room in raw["rooms"]]
        keys = [room.key for room in rooms]
        if len(set(keys)) != len(keys):
            raise Unreadable("two rooms have the same key")
        wandering = raw.get("wandering") if isinstance(raw.get("wandering"), dict) else {}
        entities = {kind: raw.get(kind) for kind, _ in LEVEL_KINDS}
        return _Written(level, _text(raw.get("intro")), rooms, wandering, entities)

    return read


def lettered(raw: Any, letter: str) -> Any:
    """A room whose key is only a number gets its level's (or a sandbox site's) letter: `3` on level B is `B3`."""
    if isinstance(raw, dict) and isinstance(raw.get("key"), str | int) and str(raw["key"]).strip().isdigit():
        return {**raw, "key": f"{letter}{str(raw['key']).strip()}"}
    return raw


def _connections_for(level: Level, connections: list[Connection]) -> str:
    lines = []
    for c in connections:
        if c.start[0] == level.letter:
            lines.append(f"- **{c.start}** leads to {c.end}" + (f": {c.how}" if c.how else ""))
        if c.end[0] == level.letter:
            lines.append(f"- **{c.end}** leads to {c.start}" + (f": {c.how}" if c.how else ""))
    return "\n".join(lines) or "- (none: this level joins no other)"


def _wandering(level: Level, wandering: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """The level's wandering monsters as a section of its text, and as an `encounter` record (None without a
    table)."""
    rows = [
        (str(row.get("roll")).strip(), _text(row.get("result")))
        for row in wandering.get("table") or []
        if isinstance(row, dict) and str(row.get("roll") or "").strip() and _text(row.get("result"))
    ]
    if not rows:
        return "", None
    check = _text(wandering.get("check"))
    table = "| Roll | Encounter |\n| --- | --- |\n" + "\n".join(f"| {roll} | {result} |" for roll, result in rows)
    text = "## Wandering monsters\n\n" + (f"Check {check}.\n\n" if check else "") + table
    record = {
        "id": f"{level.map_name}-wandering",
        "name": f"{level.title}: wandering monsters",
        "kind": "dungeon",
        "wandering": True,
        "where": [f"map:{level.map_name}"],
        "table": [{"roll": roll, "result": result} for roll, result in rows],
    }
    if check:
        record["summary"] = f"Check {check}."
    return text, record


def _level_text(written: _Written, used: set[str]) -> tuple[TextDoc, list[str]]:
    """The level's text, linked to its map, and its rooms' sections, in order."""
    level = written.level
    span = _range(level.levels)
    head = f"# {level.title}" + (f"\n\n*For characters of {span}.*" if span else "")
    sections = [section(room) for room in written.rooms]
    wandering, _ = _wandering(level, written.wandering)
    parts = [head, written.intro, *sections, wandering]
    markdown = _anchored("\n\n".join(p for p in parts if p))
    return TextDoc(unique(text_id(level.title), used), level.title, "gm", level.map_name, markdown), sections


# ----- the exits between levels -----


def join_levels(
    maps: dict[str, str], rooms: dict[str, str], connections: list[Connection]
) -> tuple[dict[str, str], list[Warning]]:
    """`maps` (by name) with an `exit` both ways for each connection, at the centres of the rooms it joins; `rooms`
    names each room key's map. A connection whose room or map is missing is left out with an `exit-not-joined`
    warning."""
    parsed = {name: parse_source(source) for name, source in maps.items()}
    added: dict[str, list[str]] = {name: [] for name in maps}
    warnings: list[Warning] = []
    for c in connections:
        ends = []
        for key in (c.start, c.end):
            name = rooms.get(key)
            centre = node_centroid(parsed[name], f"room.{room_name(key)}") if name in parsed else None
            ends.append((name, key, centre))
        if any(centre is None for _, _, centre in ends):
            missing = ", ".join(key for _, key, centre in ends if centre is None)
            message = f"The way between {c.start} and {c.end} isn't on the maps: {missing} wasn't drawn."
            warnings.append(Warning("exit-not-joined", message, f"key:{c.start}"))
            continue
        for (here, _, at), (there, other, land) in ((ends[0], ends[1]), (ends[1], ends[0])):
            assert here is not None and at is not None and land is not None
            added[here].append(
                f'exit at {round(at[0], 1)},{round(at[1], 1)} {{\n  to "{there}" at {round(land[0], 1)},'
                f'{round(land[1], 1)}\n  label "{other}" size 0.5\n  description "{_quoted(c.how or f"To {other}.")}"\n}}'
            )
    joined = {
        name: source.rstrip() + "\n\n# The ways to the other levels.\n" + "\n".join(added[name]) + "\n"
        if added[name]
        else source
        for name, source in maps.items()
    }
    return joined, warnings


def _level_kind(level: Level) -> str:
    """What the map of `level` is told of the place: a dungeon level, and what the outline says of it."""
    return f"A level of a campaign-sized dungeon: {level.title}. {level.summary}".strip()


def _quoted(text: str) -> str:
    return text.replace("\\", "/").replace('"', "'").replace("\n", " ")


# ----- the whole -----


def _anchored(markdown: str) -> str:
    return add_anchors(markdown.rstrip() + "\n", read_aloud_marker=None)[0]


async def each_at_once[T, R](
    items: Sequence[T], call: Callable[[T], Awaitable[R]], step: str, progress: Progress, limit: asyncio.Semaphore
) -> list[R]:
    """`call` of each item, in order, `limit` of them at once, `progress` counting the `step`'s done. The first that
    fails cancels the others (`all_of`), so none goes on writing a level or drawing a map for a job that failed."""
    done = 0
    progress(step, 0, len(items))

    async def one(item: T) -> R:
        nonlocal done
        async with limit:
            result = await call(item)
        done += 1
        progress(step, done, len(items))
        return result

    return await all_of([one(item) for item in items])


def _overview(outline: Outline) -> str:
    parts = [f"# {outline.title}", outline.summary]
    parts.append("## Levels\n\n" + "\n".join(_level_line(level) for level in outline.levels))
    if outline.connections:
        parts.append("## Between the levels\n\n" + "\n".join(_connection_line(c) for c in outline.connections))
    return "\n\n".join(p for p in parts if p)


def _numbered(*groups: list[Question]) -> list[Question]:
    return [Question(f"q{n}", q.text, q.default) for n, q in enumerate((q for g in groups for q in g), start=1)]


async def generate_campaign(
    request: str,
    complete: Complete,
    progress: Progress,
    *,
    rng: Rng | None = None,
    concurrency: int = CONCURRENCY,
    game: str = "",
) -> Converted:
    """A campaign-sized module from `request` (with the organiser's answers already in it, `with_answers`): an
    overview, the campaign's texts, a keyed text and a sketched map per level, joined by exits. Raises
    `GenerationError` when the outline can't be read after one retry."""
    rng = rng or SystemRng()
    names = _names(rng)
    progress("planning", 0, 1)
    first = fill(
        prompt("generate-outline.md"),
        request=request.strip(),
        names=names,
        max_levels=str(MAX_LEVELS),
        max_rooms=str(MAX_ROOMS),
    )
    try:
        outline: Outline = await _asked(first, complete, _read_outline)
    except Unreadable as unreadable:
        raise GenerationError(f"The campaign couldn't be outlined: {unreadable}.") from None
    progress("planning", 1, 1)
    agreed = outline_text(outline)
    warnings: list[Warning] = []

    progress("campaign", 0, 1)
    asked = fill(prompt("generate-campaign.md"), request=request.strip(), outline=agreed, names=names)
    try:
        campaign: dict[str, Any] = await _asked(asked, complete, _read_campaign)
    except Unreadable as unreadable:
        campaign = {}
        message = f"The campaign's own texts couldn't be written: {unreadable}. The outline stands in for them."
        warnings.append(Warning("campaign-not-written", message, None))
    progress("campaign", 1, 1)

    limit = asyncio.Semaphore(concurrency)

    async def write(level: Level) -> _Written | None:
        text = fill(
            prompt("generate-level.md"),
            request=request.strip(),
            game=game or GAME,
            outline=agreed,
            level=_level_line(level),
            letter=level.letter,
            slug=level.map_name,
            rooms=str(level.rooms),
            connections=_connections_for(level, outline.connections),
            names=names,
        )
        try:
            return await _asked(text, complete, _read_level(level))
        except Unreadable as unreadable:
            message = f"{level.title} couldn't be written: {unreadable}. It is left out."
            warnings.append(Warning("level-not-written", message, None))
            return None

    levels = [w for w in await each_at_once(outline.levels, write, "levels", progress, limit) if w is not None]
    if not levels:
        raise GenerationError("The campaign couldn't be generated: no level could be written.")

    used: set[str] = set()
    overview = TextDoc(unique(text_id(outline.title), used), outline.title, "gm", None, _anchored(_overview(outline)))
    texts = [overview, *_campaign_texts(campaign, used)]
    entity_lists: dict[str, list[Any]] = {}
    for kind, _ in CAMPAIGN_KINDS:
        if isinstance(campaign.get(kind), list):
            entity_lists[kind] = list(campaign[kind])
    if "factions" not in entity_lists and outline.factions:
        entity_lists["factions"] = [
            {k: v for k, v in f.items() if k in ("id", "name", "summary")} for f in outline.factions
        ]
    encounters: list[Any] = []
    keyed_levels: list[tuple[Level, list[tuple[str, str]]]] = []
    rooms: dict[str, str] = {}
    for written in levels:
        doc, sections = _level_text(written, used)
        texts.append(doc)
        keyed_levels.append((written.level, [(room.key, s) for room, s in zip(written.rooms, sections, strict=True)]))
        rooms.update({room.key: written.level.map_name for room in written.rooms})
        raw = written.entities.get("encounters")
        encounters.extend(raw if isinstance(raw, list) else [])
        _, record = _wandering(written.level, written.wandering)
        if record is not None:
            encounters.append(record)
    entity_lists["encounters"] = encounters
    entities, dropped = plan_entities(entity_lists, (*CAMPAIGN_KINDS, *LEVEL_KINDS))

    async def draw(keyed_level: tuple[Level, list[tuple[str, str]]]) -> tuple[str | None, list[Warning]]:
        level, keyed = keyed_level
        return await design_map(level.map_name, keyed, complete, kind=_level_kind(level))

    sketches = await each_at_once(keyed_levels, draw, "maps", progress, limit)
    sources = {level.map_name: s for (level, _), (s, _) in zip(keyed_levels, sketches, strict=True) if s is not None}
    sketched = [w for _, ws in sketches for w in ws]
    sources, unjoined = join_levels(sources, rooms, outline.connections)
    maps = [
        ModuleMap(level.map_name, "map", sources[level.map_name], n == 0)
        for n, (level, _) in enumerate((lv, k) for lv, k in keyed_levels if lv.map_name in sources)
    ]
    module, repaired = repair_refs(ModuleSource(texts=texts, entities=entities), maps=maps)
    return Converted(
        source=module,
        pictures=[],
        warnings=warnings + dropped + sketched + unjoined + repaired,
        maps=maps,
        metadata={"party": outline.party} if outline.party else {},
        questions=_numbered(outline.questions[:MAX_QUESTIONS]),
    )
