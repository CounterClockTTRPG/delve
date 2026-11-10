"""Map sketches (plan 5 Task 3): a schematic map in the map language, drawn by Claude from a room key.

Claude writes one map with a room per key, named `r<key>` and labelled with the key's heading (`C3. Shrine`), so the
keyed headings link to their rooms by themselves (`source.derive` matches a label against the whole heading). Delve
parses the answer and runs the map's own validation; on an error it asks once more, with the error and its line. A
sketch that still doesn't parse gives no map and a `map-not-drawn` warning; one that parses gives a `map-sketched`
warning, since a map drawn from words is an invented layout, to be compared with the book's page.

Plan 7 adds two more ways, each a draft the organiser keeps or discards: `describe_map` draws a map from a description
(with the module's room key, when it has one, so the rooms link), and `draw_from_page` redraws the book's own map
page, which Claude sees through a vision call (`look`). Both parse and retry as `sketch_map` does.

Faithful modules (Task 4): `draw_from_page` draws one map per level the page shows (a house's floors, cellar and caves;
a ship's decks), each for one of the parts given (`Part`, a text and its keyed headings), with the printed scale and
an `exit` at each stair, hatch or ladder that leads to another level. Claude names the levels `<name>-1`, `<name>-2`…;
Delve renames them after their level and rewrites the exits' targets to match.

Includes resolve only against the built-in libraries (`maps.sources.parse_source`), so a map Claude writes never reads
a file. The prompts carry the map language as `prompts/dsl-reference.md`, built from `docs/maps/` by `dsl_reference`
(`make dsl-reference`); `test_the_dsl_reference_is_current` keeps it in step.
"""

from __future__ import annotations

import io
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from PIL import Image

from delve.maps.dsl import DmapParseError, validate
from delve.maps.sources import parse_source
from delve.maps.vision import Look, fit_for_vision
from delve.modules.books.convert import Complete, text_id
from delve.modules.dscn.text import parse_heading
from delve.modules.source import Warning
from delve.modules.text import unique

DSL_DOCS = ("dsl.md", "dsl-map.md", "dsl-geometry.md", "dsl-reference.md")
"""The pages of `docs/maps/` the prompts carry, in this order: the file structure, the header, the geometry, and every
keyword. The features' glyphs, the tooling and the `.dscn` format are left out: a sketch needs none of them."""

_REFERENCE_HEADER = "<!-- Built from docs/maps/ by `make dsl-reference`: don't edit it here. -->\n\n"
_DOC_LINK = re.compile(r"\[([^\]]+)\]\((?:/docs/[^)]*|#[^)]*)\)")
_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_MAP_START = re.compile(r"(include|map)\b")
_ROOM_NAME = re.compile(r"[^A-Za-z0-9_-]")
_LEVEL_LINE = re.compile(r"#\s*(level|part)\s*:\s*(.*?)\s*$", re.IGNORECASE)

DESCRIBED = "# Drawn from a description."
"""The first line of a map drawn from a description."""
FROM_BOOK = "# Drawn from the book's map"
"""The first line of a map drawn from the book's map page, followed by ` asset:map-page-<n>.`"""
NO_ROOM_KEY = "The module has no room key for this map: invent the rooms the description asks for."

_RETRY = """

---

Your map:

```dmap
{answer}
```

The map parser refused it: {error}

Write the whole map again, with that fixed. Answer with the map only.
"""


def prompt(name: str) -> str:
    """The prompt file `name` of `prompts/`, as packaged."""
    return resources.files("delve.modules.books").joinpath("prompts", name).read_text("utf-8")


GAME = "OSRIC 3.0"
"""The game a generated module is written for when the install names none (`{{game}}` in the generation prompts):
the ruleset Delve ships (DEL-307)."""


def fill(template: str, **values: str) -> str:
    """`template` with each `{{name}}` replaced by its value."""
    for name, value in values.items():
        template = template.replace("{{" + name + "}}", value)
    return template


def dsl_reference(docs: Path) -> str:
    """The map language reference the prompts carry, built from the `DSL_DOCS` pages of `docs` (`docs/maps/`):
    without their "Ported from" and "Part of" lines, and with the links between the pages as plain text."""
    parts = []
    for name in DSL_DOCS:
        lines = (docs / name).read_text("utf-8").splitlines()
        kept = [line for line in lines if not line.startswith(("> Ported from", "Part of the ["))]
        parts.append(_DOC_LINK.sub(r"\1", "\n".join(kept)).strip())
    return _REFERENCE_HEADER + "\n\n---\n\n".join(parts) + "\n"


def write_dsl_reference(docs: Path) -> Path:
    """Rebuild `prompts/dsl-reference.md` from `docs` (`make dsl-reference`), and return its path."""
    path = Path(__file__).parent / "prompts" / "dsl-reference.md"
    path.write_text(dsl_reference(docs), "utf-8")
    return path


DSL_REFERENCE = prompt("dsl-reference.md")


def room_name(key: str) -> str:
    """The map name of the room keyed `key`: `r<key>`, with anything a name can't hold as `_`."""
    return "r" + _ROOM_NAME.sub("_", key)


def _label(key: str, text: str) -> str:
    """The room's label: its heading as the text writes it (`C3. Shrine`), else the key before the first line."""
    first = text.strip().splitlines()[0] if text.strip() else ""
    heading, _, found, _ = parse_heading(first.lstrip("#").strip())
    return heading if found == key else f"{key}. {heading}".strip()


def _rooms(keyed: list[tuple[str, str]]) -> str:
    return "\n\n".join(
        f'### room "{room_name(key)}", label "{_label(key, text)}"\n\n{text.strip()}' for key, text in keyed
    )


def _map_source(answer: str) -> str:
    """The map in Claude's answer: the first fenced block, else everything from its first `include` or `map` line."""
    fenced = _FENCE.search(answer)
    if fenced:
        return fenced.group(1)
    lines = answer.strip().splitlines()
    start = next((i for i, line in enumerate(lines) if _MAP_START.match(line)), 0)
    return "\n".join(lines[start:]) + "\n"


def _at(message: str, line: int, source: str) -> str:
    lines = source.splitlines()
    if 0 < line <= len(lines):
        return f"{message} (line {line}: `{lines[line - 1].strip()}`)"
    return message


def map_error(source: str) -> str | None:
    """Why `source` isn't a map Delve can play, at its line; None when it parses and validates."""
    try:
        dmap = parse_source(source)
    except DmapParseError as error:
        return _at(error.message, error.line, source)
    errors = [d for d in validate(dmap) if d.severity == "error"]
    if errors:
        return _at(errors[0].message, errors[0].line, source)
    if not dmap.rooms:
        return "the map has no rooms"
    return None


async def _draw(first: str, ask: Callable[[str], Awaitable[str]]) -> tuple[str, str | None]:
    """The map `ask(first)` answers, asked once more with the error when it doesn't parse; the map and its error,
    None when it parses."""
    source = _map_source(await ask(first))
    error = map_error(source)
    if error is not None:
        source = _map_source(await ask(first + _RETRY.format(answer=source.rstrip("\n"), error=error)))
        error = map_error(source)
    return source, error


async def sketch_map(
    name: str, keyed: list[tuple[str, str]], complete: Complete, *, page: int | None = None
) -> tuple[str | None, list[Warning]]:
    """A map named `name` sketched from `keyed`, its `(key, text)` pairs (each text its heading and paragraphs), with
    its warning. `page` is the book's page to compare it with, when there is one. No keys, no sketch."""
    if not keyed:
        return None, []
    first = fill(prompt("sketch.md"), name=name, rooms=_rooms(keyed), reference=DSL_REFERENCE)
    source, error = await _draw(first, complete)
    ref = f"map:{name}"
    if error is not None:
        return None, [Warning("map-not-drawn", f"The map couldn't be drawn from the room key: {error}", ref)]
    compare = f"; compare it with page {page}." if page is not None else "."
    return source, [Warning("map-sketched", f"Sketched from the room key: an invented layout{compare}", ref)]


DUNGEON = "An underground dungeon level."
"""What `design_map` is told of a place when nothing more is known."""


async def design_map(
    name: str, keyed: list[tuple[str, str]], complete: Complete, *, kind: str = DUNGEON
) -> tuple[str | None, list[Warning]]:
    """A generated module's map named `name`, drawn from `keyed` as `sketch_map` draws a book's, but as the module's
    only map (`design-map.md`, DEL-349): room shapes, renderer, outdoor ground and furniture that fit `kind`, a line or
    two on what the place is, rather than a schematic of boxes to compare with a book's page."""
    if not keyed:
        return None, []
    first = fill(
        prompt("design-map.md"), name=name, kind=kind.strip() or DUNGEON, rooms=_rooms(keyed), reference=DSL_REFERENCE
    )
    source, error = await _draw(first, complete)
    ref = f"map:{name}"
    if error is not None:
        return None, [Warning("map-not-drawn", f"The map couldn't be drawn from the room key: {error}", ref)]
    return free_labels(source), [Warning("map-sketched", "Drawn from the room key: an invented layout.", ref)]


_LABEL_ON = re.compile(r"room '([^']+)' label at \([^)]*\) sits on")


def free_labels(source: str) -> str:
    """`source` with the `at` dropped from each room label the validator finds on top of a feature, so the renderer
    finds the label a clear spot itself (as its warning says)."""
    try:
        diagnostics = validate(parse_source(source))
    except Exception:  # noqa: BLE001 (a map that doesn't parse is `map_error`'s to report, not this)
        return source
    rooms = {m.group(1) for d in diagnostics if (m := _LABEL_ON.search(d.message))}
    for room in rooms:
        block = re.compile(
            r'(room "' + re.escape(room) + r'"[^\n]*\{(?:[^{}]|\{[^{}]*\})*?label "[^"]*")\s+at\s+[-\d.]+,[-\d.]+'
        )
        source = block.sub(r"\1", source, count=1)
    return source


async def describe_map(
    name: str, description: str, keyed: list[tuple[str, str]], complete: Complete
) -> tuple[str | None, list[Warning]]:
    """A map named `name` drawn from `description`, with its warning. `keyed` is the module's room key for it, when it
    has one: its rooms are `r<key>`, labelled with their headings, so the headings link to them."""
    rooms = _rooms(keyed) if keyed else NO_ROOM_KEY
    first = fill(
        prompt("describe-map.md"), name=name, description=description.strip(), rooms=rooms, reference=DSL_REFERENCE
    )
    source, error = await _draw(first, complete)
    ref = f"map:{name}"
    if error is not None:
        return None, [Warning("map-not-drawn", f"The map couldn't be drawn from the description: {error}", ref)]
    return source, [Warning("map-described", "Drawn from a description: an invented layout.", ref)]


@dataclass(frozen=True)
class Part:
    """A part of the module a page's levels may be for: a text, by its id and title, and its keyed headings as
    `(key, "7. Dining Room")`. Headings only, never their paragraphs: the page holds the layout."""

    id: str
    title: str
    rooms: list[tuple[str, str]]


@dataclass(frozen=True)
class DraftLevel:
    """One level of a page drawn as a map: its name in the module, its title (the page's words for it), its source,
    and the part it is for (None when Claude named no part that was given)."""

    name: str
    title: str
    source: str
    part: str | None


NO_PARTS = "The module has no room key for this page: name each room the page keys `r<key>`, labelled with the key."

_RETRY_LEVELS = """

---

Your levels:

{answer}

The map parser refused some of them:

{errors}

Write every level again, with those fixed, each in its own ```dmap block with its `# level:` and `# part:` lines.
"""


def _parts(parts: list[Part]) -> str:
    if not parts:
        return NO_PARTS
    return "\n\n".join(
        f"### part: {part.id} ({part.title})\n\n"
        + "\n".join(f'- room "{room_name(key)}", label "{heading}"' for key, heading in part.rooms)
        for part in parts
    )


def _levels(answer: str) -> list[tuple[str | None, str | None, str]]:
    """The levels of Claude's answer, `(level, part, source)`: each fenced block, else the whole answer as one map,
    its leading `# level:` and `# part:` lines read and taken off."""
    blocks = _FENCE.findall(answer) or [_map_source(answer)]
    levels = []
    for block in blocks:
        lines = block.splitlines()
        said: dict[str, str] = {}
        while lines and (not lines[0].strip() or _LEVEL_LINE.fullmatch(lines[0].strip())):
            found = _LEVEL_LINE.fullmatch(lines.pop(0).strip())
            if found:
                said.setdefault(found.group(1).lower(), found.group(2))
        levels.append((said.get("level") or None, said.get("part") or None, "\n".join(lines) + "\n"))
    return levels


def _errors(levels: list[tuple[str | None, str | None, str]]) -> list[str | None]:
    return [map_error(source) for _, _, source in levels] if levels else ["the answer holds no map"]


def _level_names(name: str, levels: list[tuple[str | None, str | None, str]]) -> list[str]:
    """Each level's name in the module: `name` for a page of one level, else `<name>-<level>`, each unique."""
    if len(levels) == 1:
        return [name]
    used: set[str] = set()
    names = []
    for n, (level, _, _) in enumerate(levels, start=1):
        names.append(unique(text_id(f"{name} {level or f'level {n}'}"), used))
    return names


async def draw_from_page(
    name: str, page: bytes, media_type: str, parts: list[Part], look: Look
) -> tuple[list[DraftLevel], list[Warning]]:
    """The book's map page `page` (its bytes and `media_type`) redrawn as one map per level it shows, by Claude, who
    sees it through `look`, scaled down for it as a PNG (Pillow reads the stored type from the bytes). `parts` are the
    parts a level may be for, their rooms `r<key>` where the book puts them. Each level is parsed and validated; the
    page is sent once more with every error, and a level still broken is left out with a `map-not-drawn` warning.

    A level's `# part:` that isn't a part given is None (a `map-no-part` warning); with one part given, a level that
    names none is that part's. Each validation warning of a level is a `map-warning`, `map:<level>`."""
    with Image.open(io.BytesIO(page)) as picture:
        image, image_type = fit_for_vision(picture)
    first = fill(prompt("book-map.md"), name=name, parts=_parts(parts), reference=DSL_REFERENCE)
    answer = await look(first, image, image_type)
    levels = _levels(answer)
    errors = _errors(levels)
    if any(errors):
        listed = (
            "\n".join(
                f"- level {n} ({level or 'untitled'}): {error}"
                for n, ((level, _, _), error) in enumerate(zip(levels, errors, strict=False), start=1)
                if error
            )
            or f"- {errors[0]}"
        )
        answer = await look(first + _RETRY_LEVELS.format(answer=answer.strip(), errors=listed), image, image_type)
        levels = _levels(answer)
        errors = _errors(levels)

    names = _level_names(name, levels)
    targets = {f"{name}-{n}": new for n, new in enumerate(names, start=1)}
    exits = re.compile('"(' + "|".join(re.escape(old) for old in targets) + ')"') if targets else None
    given = {part.id for part in parts}
    drawn: list[DraftLevel] = []
    warnings: list[Warning] = []
    # With no level, `errors` holds the one saying so, and there is nothing to draw: the zip ends at once.
    for level_name, (level, part, source), error in zip(names, levels, errors, strict=False):
        ref = f"map:{level_name}"
        if error is not None:
            message = f"The map couldn't be drawn from the book's map: {error}"
            warnings.append(Warning("map-not-drawn", message, ref if len(levels) > 1 else f"map:{name}"))
            continue
        if exits is not None:
            source = exits.sub(lambda m: f'"{targets[m.group(1)]}"', source)
        if part is None and len(parts) == 1:
            part = parts[0].id
        part = part if part in given else None
        title = level or level_name
        drawn.append(DraftLevel(level_name, title, source, part))
        for diagnostic in validate(parse_source(source)):
            if diagnostic.severity == "warning":
                warnings.append(Warning("map-warning", f"{title}: {diagnostic.message}", ref))
        if part is None:
            message = f"{title} is for no part of the module: its rooms aren't checked against a room key or linked."
            warnings.append(Warning("map-no-part", message, ref))
    if drawn:
        message = "Drawn by Claude from the book's map: compare it with the page."
        warnings.insert(0, Warning("map-from-book", message, f"map:{name}"))
    return drawn, warnings
