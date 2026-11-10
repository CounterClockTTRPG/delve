"""Generating a module from a request (plan 5 Task 3): "a dungeon with kobolds, no plot" becomes a small module.

One call asks Claude for a JSON plan `{title, summary, party, rooms: [{key, name, read_aloud, dm_text, monsters,
treasure}], npcs, encounters}`, with as much story as the request asks for. Its people are named from 12 names rolled
per race (`rolled_names`), and its `party` (`{size, levels, notes}`, as much as the request says) becomes the module's
metadata. A plan that can't be read is asked for once more, with
the reason; then the generation fails with "The module couldn't be generated: <reason>." The plan becomes one keyed
text (`## <key>. <name>`, its read-aloud as a blockquote, every heading anchored by `dscn.add_anchors`) and its NPC
and encounter records, each checked against the format's schema: an invalid one is left out with an `entity-dropped`
warning. Then `design_map` draws the map from the rooms' texts, so the rooms link by themselves, and the refs the plan
leaves dangling are rewritten or dropped (`repair.repair_refs`), so the module always exports.

Treasure is what the request and the plan say; the ruleset's treasure tables are not called (the DM rolls in play).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from delve.dice import Rng, SystemRng
from delve.domain.modules import ModuleMap
from delve.modules.books.convert import (
    Complete,
    Converted,
    Progress,
    Question,
    players_warning,
    take_questions,
    text_id,
)
from delve.modules.books.repair import repair_refs
from delve.modules.books.sketch import DSL_REFERENCE, design_map, fill, prompt
from delve.modules.dscn import slugify
from delve.modules.dscn.text import add_anchors, parse_heading
from delve.modules.dscn.validate import schema
from delve.modules.source import ModuleSource, TextDoc, Warning
from delve.rules.classic.names import RACES, generate

MAP_NAME = "map"
"""The generated module's one map, its default (the name an empty module's map has)."""

ENTITY_KINDS = (("npcs", "npc"), ("encounters", "encounter"))
"""The plan's entity lists, as the manifest's kinds, with the schema's `$defs` each record is checked against."""

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
NAMES_PER_RACE = 12
"""How many names `generate.md` gets for each race."""

_RETRY = """

---

Your plan:

{answer}

It couldn't be read: {reason}. Answer again with the whole plan as one JSON object, and nothing else.
"""


class GenerationError(ValueError):
    """The plan couldn't be read, twice: "The module couldn't be generated: <reason>." """


class Unreadable(ValueError):
    """An answer that isn't the plan asked for, and why."""


@dataclass(frozen=True)
class Room:
    key: str
    name: str
    read_aloud: str
    dm_text: str
    monsters: list[str]
    treasure: list[str]


@dataclass(frozen=True)
class _Plan:
    title: str
    summary: str
    rooms: list[Room]
    entities: dict[str, Any]
    party: dict[str, Any]
    questions: list[Question]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _texts(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [s for s in (_text(item) for item in items) if s]


def read_room(raw: Any) -> Room:
    if not isinstance(raw, dict):
        raise Unreadable("a room isn't a JSON object")
    key = str(raw["key"]).strip() if isinstance(raw.get("key"), str | int) else ""
    if not key:
        raise Unreadable("a room has no key")
    name = _text(raw.get("name"))
    if not name:
        raise Unreadable(f"room {key} has no name")
    if parse_heading(f"{key}. {name}")[2] != key:
        raise Unreadable(f"the key “{key}” isn't a room key")
    return Room(
        key=key,
        name=name,
        read_aloud=_text(raw.get("read_aloud")),
        dm_text=_text(raw.get("dm_text")),
        monsters=_texts(raw.get("monsters")),
        treasure=_texts(raw.get("treasure")),
    )


def _read_plan(answer: str) -> _Plan:
    """The plan in Claude's answer, without its `questions` block: the first fenced block, else from its first `{` to
    its last `}`."""
    answer, questions = take_questions(answer)
    fenced = _FENCE.search(answer)
    body = fenced.group(1) if fenced else answer[answer.find("{") : answer.rfind("}") + 1]
    try:
        raw = json.loads(body)
    except json.JSONDecodeError as error:
        raise Unreadable(f"the plan isn't JSON ({error.msg})") from None
    if not isinstance(raw, dict):
        raise Unreadable("the plan isn't a JSON object")
    title = _text(raw.get("title"))
    if not title:
        raise Unreadable("the plan has no title")
    if not isinstance(raw.get("rooms"), list) or not raw["rooms"]:
        raise Unreadable("the plan has no rooms")
    rooms = [read_room(room) for room in raw["rooms"]]
    seen: set[str] = set()
    for room in rooms:
        if room.key in seen:
            raise Unreadable(f"two rooms have the key {room.key}")
        seen.add(room.key)
    entities = {kind: raw.get(kind) for kind, _ in ENTITY_KINDS}
    return _Plan(title, _text(raw.get("summary")), rooms, entities, party_of(raw.get("party")), questions)


def party_of(raw: Any) -> dict[str, Any]:
    """The plan's `party`, with only the fields the manifest's schema takes; empty when the plan gives none."""
    if not isinstance(raw, dict):
        return {}
    fields = schema()["properties"]["party"]["properties"]
    defs = schema()["$defs"]
    return {
        name: value
        for name, value in raw.items()
        if name in fields and not best_match(Draft202012Validator({**fields[name], "$defs": defs}).iter_errors(value))
    }


EPITHET_RACES = frozenset({"halforc", "orc", "goblin", "hobgoblin", "bugbear", "kobold", "gnoll", "lizardfolk"})
"""The races whose rolled names carry a stock epithet ("Drush Hide-Wearer", "Krang the Cleaver", "Zashz of the
Shadow Wolf"): a generated module names them by the first word alone, and the text gives them a byname if it wants
one (DEL-349)."""


def plain_name(race: str, name: str) -> str:
    """`name` without its stock epithet, for the `EPITHET_RACES`: "Krik Throat-Slitter" is "Krik"."""
    return name.split()[0] if race in EPITHET_RACES and name.split() else name


def rolled_names(rng: Rng) -> dict[str, list[str]]:
    """`NAMES_PER_RACE` names for each race of the name generator, every other one a woman's, those of the
    `EPITHET_RACES` without their epithets (`plain_name`)."""
    return {
        race: [plain_name(race, generate(rng, race, female=n % 2 == 1)) for n in range(NAMES_PER_RACE)]
        for race in RACES
    }


@cache
def _validator(defname: str) -> Draft202012Validator:
    whole = {key: value for key, value in schema().items() if key in ("$schema", "$id", "$defs")}
    return Draft202012Validator(whole | {"$ref": f"#/$defs/{defname}"})


def plan_entities(
    lists: dict[str, Any], kinds: tuple[tuple[str, str], ...] = ENTITY_KINDS
) -> tuple[dict[str, list[dict[str, Any]]], list[Warning]]:
    """The records of a plan's entity `lists` that the schema takes, by `kinds` (`ENTITY_KINDS`: its NPCs and
    encounters), an id made from the name where it has none."""
    entities: dict[str, list[dict[str, Any]]] = {}
    warnings: list[Warning] = []
    for kind, defname in kinds:
        raw = lists.get(kind)
        if raw is None:
            continue
        if not isinstance(raw, list):
            warnings.append(Warning("entity-dropped", f"The plan's {kind} weren't a list, and were left out.", kind))
            continue
        kept: list[dict[str, Any]] = []
        ids: set[str] = set()
        for record in raw:
            if not isinstance(record, dict):
                warnings.append(Warning("entity-dropped", f"One of the plan's {kind} wasn't a record.", kind))
                continue
            record = dict(record)
            given = record.get("id")
            if not (isinstance(given, str) and _SLUG.match(given)):
                record["id"] = slugify(str(given or record.get("name") or defname))
            base, n = record["id"], 2
            while record["id"] in ids:
                record["id"], n = f"{base}-{n}", n + 1
            error = best_match(_validator(defname).iter_errors(record))
            if error is not None:
                name = record.get("name") or record["id"]
                message = f"The {defname} “{name}” was left out: {error.message}."
                warnings.append(Warning("entity-dropped", message, kind))
                continue
            ids.add(record["id"])
            kept.append(record)
            if record.get("audience") == "player":
                warnings.append(players_warning(f"{defname}:{record['id']}"))
        if kept:
            entities[kind] = kept
    return entities, warnings


def _list(label: str, items: list[str]) -> str:
    if len(items) == 1:
        return f"**{label}:** {items[0]}"
    return f"**{label}:**\n\n" + "\n".join(f"- {item}" for item in items)


def section(room: Room) -> str:
    """The room's keyed section: its heading, its read-aloud as a blockquote, then the DM's text."""
    parts = [f"## {room.key}. {room.name}"]
    if room.read_aloud:
        parts.append("\n".join(f"> {line}".rstrip() for line in room.read_aloud.splitlines()))
    if room.dm_text:
        parts.append(room.dm_text)
    if room.monsters:
        parts.append(_list("Monsters", room.monsters))
    if room.treasure:
        parts.append(_list("Treasure", room.treasure))
    return "\n\n".join(parts)


async def _plan(request: str, complete: Complete, rng: Rng) -> _Plan:
    names = "\n".join(f"- {race}: {', '.join(rolled)}" for race, rolled in rolled_names(rng).items())
    first = fill(prompt("generate.md"), request=request.strip(), names=names, reference=DSL_REFERENCE)
    answer = await complete(first)
    try:
        return _read_plan(answer)
    except Unreadable as unreadable:
        retry = first + _RETRY.format(answer=answer.strip(), reason=unreadable)
    try:
        return _read_plan(await complete(retry))
    except Unreadable as unreadable:
        raise GenerationError(f"The module couldn't be generated: {unreadable}.") from None


async def generate_module(request: str, complete: Complete, progress: Progress, *, rng: Rng | None = None) -> Converted:
    """A small module from `request`: one keyed text, its NPCs and encounters, and a map sketched from its rooms, its
    people named from names rolled with `rng`. Raises `GenerationError` when the plan can't be read after one retry."""
    progress("generating", 0, 1)
    plan = await _plan(request, complete, rng or SystemRng())
    progress("generating", 1, 1)
    entities, warnings = plan_entities(plan.entities)
    sections = [section(room) for room in plan.rooms]

    progress("maps", 0, 1)
    source, sketched = await design_map(
        MAP_NAME,
        [(room.key, text) for room, text in zip(plan.rooms, sections, strict=True)],
        complete,
        kind=f"{plan.title}. {plan.summary}".strip(),
    )
    progress("maps", 1, 1)

    head = f"# {plan.title}" + (f"\n\n{plan.summary}" if plan.summary else "")
    markdown = add_anchors("\n\n".join([head, *sections]) + "\n", read_aloud_marker=None)[0]
    text = TextDoc(text_id(plan.title), plan.title, "gm", None, markdown)
    maps = [ModuleMap(MAP_NAME, "map", source, True)] if source is not None else []
    module, repaired = repair_refs(ModuleSource(texts=[text], entities=entities), maps=maps)
    return Converted(
        source=module,
        pictures=[],
        warnings=warnings + sketched + repaired,
        maps=maps,
        metadata={"party": plan.party} if plan.party else {},
        questions=plan.questions,
    )
