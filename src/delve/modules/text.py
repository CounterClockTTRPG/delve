"""A module's text for the DM (plan 2b Task 1): the sections of a `.dscn`'s Markdown, its keys and its entities.

`modules.source.derive` makes it from the module's working source with the copied `dscn` parsers (`parse_text`, the
manifest's `keys[]`), so it can be stored in the module's working copy, snapshotted with every revision, and searched
by `module_lookup`. A section is one heading's own text, up to the next heading of any level; its anchor is
`<text id>#<anchor>`, which is a key's `text:` reference without the `text:`. Audiences follow the format's rule R7: what isn't marked `player` is the DM's.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from delve.modules.dscn import parse_text, slugify
from delve.modules.dscn.text import TextDoc as ParsedText
from delve.modules.dscn.text import split_front_matter

Audience = Literal["gm", "player"]


@dataclass(frozen=True)
class TextSection:
    anchor: str
    """`<text id>#<anchor>`: the heading's `{#anchor}`, its key's slug, or the slug of its heading text."""
    heading_path: list[str]
    """The text's title, then every heading down to this one."""
    markdown: str
    """The section's own DM text, without its read-aloud and without its sub-sections."""
    audience: Audience
    read_aloud: str | None
    """The boxed text for the players: in a keyed section every blockquote of its own text, in order, else the
    blockquotes right after the heading; None when there is none."""


@dataclass(frozen=True)
class Key:
    """A `keys[]` entry: a room key joining a map node to its text, NPCs, encounter and assets, as references."""

    key: str
    title: str
    node: str | None
    """`map:<map>#<node id>`, or None for a key with no room on a map."""
    text_anchor: str | None
    """The anchor of its `TextSection`."""
    npcs: list[str] = field(default_factory=list)
    encounter: str | None = None
    assets: list[str] = field(default_factory=list)
    part: str | None = None
    """The part of the text its heading is in (`source.part_slug`, or the text's id when two parts share a slug), set
    by `derive` for every key with a `text_anchor`. A key two parts share is written `<part>-<key>`."""


@dataclass(frozen=True)
class ModuleText:
    sections: list[TextSection] = field(default_factory=list)
    keys: list[Key] = field(default_factory=list)
    entities: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    """The entity records by manifest kind (`npcs`, `encounters`, `secrets`…), as the bundle's YAML holds them."""

    @property
    def empty(self) -> bool:
        return not (self.sections or self.keys or self.entities)

    def section(self, anchor: str) -> TextSection | None:
        return next((s for s in self.sections if s.anchor == anchor), None)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> ModuleText:
        return cls(
            sections=[TextSection(**s) for s in raw.get("sections", [])],
            keys=[Key(**k) for k in raw.get("keys", [])],
            entities={kind: list(records) for kind, records in raw.get("entities", {}).items()},
        )


def _audience(value: Any) -> Audience:
    return "player" if value == "player" else "gm"


def sections_of(
    tid: str, title: str, audience: Audience, source: str, parsed: ParsedText | None = None
) -> list[TextSection]:
    """The sections of the text `tid`, whose Markdown (front matter and all) is `source`; `parsed` is that Markdown
    already parsed, when the caller has it (DEL-166)."""
    doc = parsed if parsed is not None else parse_text(source)
    lines = doc.body.splitlines()
    # Where each heading is in the body: `Section.line` counts from the top of the file, front matter included.
    front = split_front_matter(source)[2]
    starts = [sec.line - 1 - front for sec in doc.sections]
    out: list[TextSection] = []
    used: set[str] = set()

    preamble = "\n".join(lines[: starts[0] if starts else len(lines)]).strip()
    if preamble:
        used.add(tid)
        out.append(TextSection(tid, [title], preamble, audience, None))

    path: list[tuple[int, str]] = []
    for n, sec in enumerate(doc.sections):
        while path and path[-1][0] >= sec.level:
            path.pop()
        path.append((sec.level, sec.heading))
        anchor = unique(sec.anchor or slugify(sec.heading) or "section", used)
        own = lines[starts[n] + 1 : starts[n + 1] if n + 1 < len(starts) else len(lines)]
        markdown, read_aloud = _without_read_aloud(own), sec.read_aloud
        if sec.keyed:
            markdown, read_aloud = _boxed_apart(own)
        out.append(
            TextSection(
                anchor=f"{tid}#{anchor}",
                heading_path=[title, *(heading for _, heading in path)],
                markdown=markdown,
                audience=audience,
                read_aloud=read_aloud or None,
            )
        )
    return out


def _without_read_aloud(lines: list[str]) -> str:
    """A section's own lines without the blockquotes that open it: those are its read-aloud (`parse_text`'s rule)."""
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith(">")):
        i += 1
    return "\n".join(lines[i:]).strip()


def _boxed_apart(lines: list[str]) -> tuple[str, str]:
    """A keyed section's own lines as its DM text and its read-aloud: every blockquote outside a fence is boxed text,
    in order, its markers removed as `parse_text` removes them, the quotes joined by a blank line; the DM text is the
    rest, its runs of blank lines collapsed (faithful modules Task 11, Delve's reading of R13)."""
    kept: list[str] = []
    quotes: list[list[str]] = []
    fence: str | None = None
    quoting = False
    for line in lines:
        if (opened := _FENCE.match(line)) is not None:
            mark = opened.group(1)[0]
            fence = mark if fence is None else (None if fence == mark else fence)
        if fence is None and opened is None and line.lstrip().startswith(">"):
            if not quoting:
                quotes.append([])
            quotes[-1].append(line.lstrip()[1:].removeprefix(" "))
            quoting = True
            continue
        quoting = False
        if line.strip() or (kept and kept[-1].strip()):
            kept.append(line)
    boxed = "\n\n".join(text for quote in quotes if (text := "\n".join(quote).strip()))
    return "\n".join(kept).strip(), boxed


_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def unique(base: str, used: set[str]) -> str:
    """`base`, or `base-2`, `base-3`… when it is taken: the first of them not in `used`, which then holds it. Every
    id a module's making gives (a text's, a picture's, a map's, an anchor) is kept apart this way."""
    candidate, n = base, 2
    while candidate in used:
        candidate, n = f"{base}-{n}", n + 1
    used.add(candidate)
    return candidate


def key_of(raw: dict[str, Any]) -> Key:
    """A manifest `keys[]` entry as a `Key`."""
    text = raw.get("text")
    encounter = raw.get("encounter")
    return Key(
        key=str(raw["key"]),
        title=str(raw.get("title") or ""),
        node=raw.get("node") or None,
        text_anchor=text[len("text:") :] if isinstance(text, str) and text.startswith("text:") else None,
        npcs=[str(r) for r in raw.get("npcs") or []],
        encounter=str(encounter) if encounter else None,
        assets=[str(r) for r in raw.get("assets") or []],
    )
