"""Keyed module text (spec §5).

A text file is CommonMark with optional YAML front matter. A *keyed
section* is a heading carrying a room key — `## W101. Dwarven Guard Post`,
optionally with an explicit `{#w101}` anchor. The blockquote(s) straight
after the heading are the read-aloud (boxed) text; everything else in the
section is GM text.

This is a line-level parser on purpose: it only needs headings, fences and
leading blockquotes, and it must agree byte-for-byte with what an author
sees in their editor — no Markdown dialect quirks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from .refs import slugify
from .yamlsafe import load_yaml

# The closing `#`s and the spaces around them are stripped in `_heading`, not here: a lazy group before them took
# cubic time on a long run of spaces (DEL-152). Neither pattern starts with a repeat a failed search retries.
_HEADING_RX = re.compile(r"^(#{1,6})[ \t]+(.*)$")
_ANCHOR_RX = re.compile(r"\{#([A-Za-z0-9][A-Za-z0-9._-]*)\}\s*$")
_FENCE_RX = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
# A key is the heading text before the first ". " or ": ", or before a
# final "." or ":" ("## 31.", a key with no title) — but only when it looks
# like a key: no spaces, ≤ 12 chars, at least one digit (W101, 12, A3, 1a,
# L2-7). That keeps "Dr. Who", "Note: …" and "Treasure:" out.
_KEY_RX = re.compile(r"^([^\s.:]{1,12})[.:](?:\s+(.*))?$")


@dataclass
class Section:
    heading: str            # heading text with the anchor stripped
    level: int
    line: int               # 1-based line of the heading
    anchor: str | None      # explicit {#…} or derived from the key
    key: str | None         # "W101" when keyed
    title: str              # heading text after the key ("Dwarven Guard Post")
    read_aloud: str = ""    # blockquote text with the "> " markers removed
    gm_md: str = ""         # the rest of the section (Markdown)
    explicit_anchor: bool = False

    @property
    def keyed(self) -> bool:
        return self.key is not None


@dataclass
class TextDoc:
    front_matter: dict = field(default_factory=dict)
    body: str = ""
    sections: list[Section] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)

    def anchors(self) -> dict[str, Section]:
        return {s.anchor: s for s in self.sections if s.anchor}

    def keyed(self) -> list[Section]:
        return [s for s in self.sections if s.keyed]

    def section(self, anchor: str) -> Section | None:
        return self.anchors().get(anchor)


def split_front_matter(text: str) -> tuple[dict, str, int]:
    """(front matter, body, number of lines the front matter took)."""
    if not text.startswith("---"):
        return {}, text, 0
    lines = text.splitlines(keepends=True)
    if lines[0].strip() != "---":
        return {}, text, 0
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            raw = "".join(lines[1:i])
            try:
                fm = load_yaml(raw) or {}
            except yaml.YAMLError:
                fm = {}
            return (fm if isinstance(fm, dict) else {}), "".join(lines[i + 1:]), i + 1
    return {}, text, 0


def _heading_text(rest: str) -> str:
    """A heading line's text after its `#`s, without the closing `#`s and the spaces around them ("Title ##" is
    "Title", as is "Title" itself)."""
    return rest.rstrip(" \t").rstrip("#").rstrip(" \t")


def parse_heading(raw: str, level: int = 2) -> tuple[str, str | None, str | None, str]:
    """(heading text, anchor, key, title) for one heading's text. A level-1
    heading is a document title ("# B2: The Keep"), never a key."""
    anchor = None
    m = _ANCHOR_RX.search(raw)
    if m:
        anchor = m.group(1)
        raw = raw[: m.start()].rstrip()
    key = None
    title = raw
    km = _KEY_RX.match(raw) if level >= 2 else None
    if km and any(c.isdigit() for c in km.group(1)):
        key, title = km.group(1), (km.group(2) or "").strip()
    return raw, anchor, key, title


def is_key_heading(raw: str, level: int = 2) -> bool:
    return parse_heading(raw, level)[2] is not None


def parse_text(text: str) -> TextDoc:
    fm, body, offset = split_front_matter(text)
    doc = TextDoc(front_matter=fm, body=body)
    lines = body.splitlines()

    heads: list[tuple[int, int, str]] = []  # (index, level, raw text)
    fence: str | None = None
    for i, line in enumerate(lines):
        fm_ = _FENCE_RX.match(line)
        if fm_:
            mark = fm_.group(1)[0]
            if fence is None:
                fence = mark
            elif fence == mark:
                fence = None
            continue
        if fence is not None:
            continue
        hm = _HEADING_RX.match(line)
        if hm:
            heads.append((i, len(hm.group(1)), _heading_text(hm.group(2))))

    seen: dict[str, int] = {}
    for n, (idx, level, raw) in enumerate(heads):
        end = len(lines)
        for idx2, level2, _ in heads[n + 1:]:
            if level2 <= level:
                end = idx2
                break
        heading, anchor, key, title = parse_heading(raw, level)
        explicit = anchor is not None
        if anchor is None and key is not None:
            anchor = slugify(key)
        sec = Section(
            heading=heading, level=level, line=idx + 1 + offset,
            anchor=anchor, key=key, title=title, explicit_anchor=explicit,
        )
        # Leading blockquote(s) = read-aloud; blank lines between them are fine.
        j = idx + 1
        quote: list[str] = []
        while j < end:
            ln = lines[j]
            if ln.strip() == "":
                j += 1
                continue
            if ln.lstrip().startswith(">"):
                while j < end and lines[j].lstrip().startswith(">"):
                    q = lines[j].lstrip()[1:]
                    quote.append(q[1:] if q.startswith(" ") else q)
                    j += 1
                quote.append("")
                continue
            break
        sec.read_aloud = "\n".join(quote).strip()
        # A section runs to the next heading of the same or higher level,
        # so sub-headings (e.g. "#### Treasure") belong to its GM text.
        sec.gm_md = "\n".join(lines[j:end]).strip()
        if anchor:
            if anchor in seen:
                doc.errors.append(
                    (sec.line, f"duplicate anchor #{anchor} (first at line {seen[anchor]})")
                )
            else:
                seen[anchor] = sec.line
        doc.sections.append(sec)
    return doc


def add_anchors(text: str, *, read_aloud_marker: str | None = "(read aloud)") -> tuple[str, int]:
    """Give every keyed heading an explicit `{#anchor}` (what
    `convert-module` does to a ttrpg2 module.md). Returns (text, count).

    With `read_aloud_marker`, a heading containing that marker has the plain
    paragraphs directly under it turned into a blockquote, so they become
    read-aloud text by the §5.2 rule.
    """
    fm, body, _ = split_front_matter(text)
    prefix = text[: len(text) - len(body)]
    lines = body.splitlines()
    out: list[str] = []
    count = 0
    fence: str | None = None
    used: set[str] = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        fm_ = _FENCE_RX.match(line)
        if fm_:
            mark = fm_.group(1)[0]
            fence = mark if fence is None else (None if fence == mark else fence)
            out.append(line)
            i += 1
            continue
        hm = _HEADING_RX.match(line) if fence is None else None
        if hm:
            heading, anchor, key, _title = parse_heading(_heading_text(hm.group(2)), len(hm.group(1)))
            if key is not None and anchor is None:
                anchor = slugify(key)
                n = 2
                base = anchor
                while anchor in used:
                    anchor = f"{base}-{n}"
                    n += 1
                line = f"{hm.group(1)} {heading} {{#{anchor}}}"
                count += 1
            if anchor:
                used.add(anchor)
            out.append(line)
            i += 1
            if read_aloud_marker and read_aloud_marker.lower() in heading.lower():
                # Quote the paragraphs up to the next heading.
                while i < len(lines) and not _HEADING_RX.match(lines[i]):
                    ln = lines[i]
                    out.append(ln if not ln.strip() or ln.lstrip().startswith(">") else f"> {ln}")
                    i += 1
            continue
        out.append(line)
        i += 1
    result = prefix + "\n".join(out)
    if body.endswith("\n"):
        result += "\n"
    return result, count
