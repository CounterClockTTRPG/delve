"""What every kind's extraction shares: the SRD copy's Markdown read without its front matter and cleaned of the
conversion's escapes, its sections by heading, its tables (pandoc's simple tables, pipe tables and HTML tables), slugs,
and JSON written the same way every time."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class SourceMissing(Exception):
    """A file the extraction needs isn't in the SRD folder."""


def read(src: Path, relative: str) -> str:
    """The file's Markdown, without its front matter; `SourceMissing` when it isn't there."""
    path = src / relative
    if not path.is_file():
        raise SourceMissing(relative)
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :]
    return text


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "").replace("’", "")).strip("-")


def clean(text: str) -> str:
    """The conversion's text as plain Markdown: its escapes undone, `--5` the minus it stands for, `---` a dash,
    wiki links as their words, and runs of blank lines as one."""
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\\([\[\]*_#`|>~-])", r"\1", text)
    text = text.replace("---", "—")
    text = re.sub(r"(?<![\w-])--(?=[\d½])", "–", text)
    text = re.sub(r"(?<=\w)--(?=\w)", "–", text)
    text = re.sub(r"\[([^\]]*)\]\{[^}]*\}", r"\1", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def inline(text: str) -> str:
    """One cell or field as one line: cleaned, emphasis and links dropped, whitespace collapsed."""
    text = re.sub(r"\^[\d*]+\^", "", clean(text))  # footnote marks ("Weight^1^")
    text = re.sub(r"\*\*|__|(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)", "", text)
    return " ".join(text.split()).strip()


@dataclass(frozen=True)
class Section:
    title: str
    body: str
    level: int
    parents: tuple[str, ...] = field(default=())


_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def sections(text: str, level: int) -> list[Section]:
    """The sections headed at `level` (2 for `##`), each with the text up to the next heading at that level or
    above, and the titles of the headings above it."""
    found: list[Section] = []
    stack: dict[int, str] = {}
    current: tuple[str, list[str], tuple[str, ...]] | None = None
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match and len(match.group(1)) <= level:
            depth, title = len(match.group(1)), match.group(2).strip()
            if current is not None:
                found.append(Section(current[0], "\n".join(current[1]).strip(), level, current[2]))
                current = None
            stack = {d: t for d, t in stack.items() if d < depth}
            if depth == level:
                current = (title, [], tuple(stack[d] for d in sorted(stack)))
            stack[depth] = title
        elif current is not None:
            current[1].append(line)
    if current is not None:
        found.append(Section(current[0], "\n".join(current[1]).strip(), level, current[2]))
    return found


@dataclass(frozen=True)
class Table:
    caption: str
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def dicts(self) -> list[dict[str, str]]:
        return [dict(zip(self.header, row, strict=False)) for row in self.rows]


def _simple_tables(text: str) -> list[Table]:
    """Pandoc's simple tables: a rule of dash runs above the header and below the last row, the columns where the
    runs are, and the caption (`: Table: …`) after."""
    lines = text.splitlines()
    rule = re.compile(r"^\s*-{3,}(\s+-{3,})+\s*$")
    found = []
    i = 0
    while i < len(lines):
        if not rule.match(lines[i]):
            i += 1
            continue
        spans = [(m.start(), m.end()) for m in re.finditer(r"-{3,}", lines[i])]
        end = next((j for j in range(i + 1, len(lines)) if rule.match(lines[j])), None)
        if end is None:
            break
        inner = lines[i + 1 : end]
        caption = ""
        for after in lines[end + 1 : end + 4]:
            if after.strip().startswith(":"):
                caption = inline(after.strip()[1:])
                break

        def cells(line: str, spans: list[tuple[int, int]] = spans) -> tuple[str, ...]:
            out = []
            for n, (start, _stop) in enumerate(spans):
                until = spans[n + 1][0] if n + 1 < len(spans) else len(line)
                out.append(inline(line[start:until]))
            return tuple(out)

        # Styling junk the conversion left between the rule and the header: lines with nothing in the first column.
        while inner and not cells(inner[0])[0].strip('"'):
            inner = inner[1:]
        body = [line for line in inner if line.strip()]

        def joined(block: list[str]) -> tuple[str, ...]:
            columns = zip(*(cells(line.replace("\\", " ")) for line in block), strict=False)
            return tuple(inline(" ".join(column)) for column in columns)

        multiline = any(not line.strip() for line in inner) and len(body) > 1
        if multiline:  # pandoc's multiline tables: a row per block of lines, blank lines between
            blocks: list[list[str]] = [[]]
            for line in inner:
                if line.strip():
                    blocks[-1].append(line)
                elif blocks[-1]:
                    blocks.append([])
            rows = [joined(b) for b in blocks if b and not any("{style" in line or "[]" in line for line in b)]
            if rows:
                found.append(Table(caption, rows[0], tuple(rows[1:])))
        elif body:
            found.append(Table(caption, cells(body[0]), tuple(cells(line) for line in body[1:])))
        i = end + 1
    return found


def _pipe_tables(text: str) -> list[Table]:
    found = []
    block: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.strip().startswith("|"):
            block.append(line.strip())
            continue
        if len(block) >= 2:
            rows = [
                tuple(inline(c) for c in row.strip("|").split("|"))
                for row in block
                if not re.fullmatch(r"\|?[\s:|-]+\|?", row)
            ]
            if rows:
                found.append(Table("", rows[0], tuple(rows[1:])))
        block = []
    return found


class _HtmlTables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[tuple[str, list[list[str]]]] = []
        self._caption: list[str] | None = None
        self._rows: list[list[str]] | None = None
        self._cell: list[str] | None = None
        self._span = 1

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._rows, self._caption_text = [], ""
        elif tag == "caption":
            self._caption = []
        elif tag == "tr" and self._rows is not None:
            self._rows.append([])
        elif tag in ("td", "th") and self._rows is not None:
            self._cell = []
            self._span = int(dict(attrs).get("colspan") or 1)

    def handle_endtag(self, tag):
        if tag == "caption" and self._caption is not None:
            self._caption_text = " ".join("".join(self._caption).split())
            self._caption = None
        elif tag in ("td", "th") and self._cell is not None and self._rows:
            text = inline(html.unescape("".join(self._cell)))
            self._rows[-1].extend([text] + [""] * (self._span - 1))
            self._cell = None
        elif tag == "table" and self._rows is not None:
            self.tables.append((self._caption_text, self._rows))
            self._rows = None

    def handle_data(self, data):
        if self._caption is not None:
            self._caption.append(data)
        elif self._cell is not None:
            self._cell.append(data)


def _html_tables(text: str) -> list[Table]:
    parser = _HtmlTables()
    for block in re.findall(r"<table.*?</table>", text, flags=re.DOTALL):
        parser.feed(block)
    found = []
    for caption, rows in parser.tables:
        rows = [r for r in rows if any(c for c in r)]
        header_at = next((n for n, r in enumerate(rows) if r and r[0].lower() == "level"), 0)
        if rows:
            header = tuple(rows[header_at])
            found.append(Table(inline(caption), header, tuple(tuple(r) for r in rows[header_at + 1 :])))
    return found


def tables(text: str) -> list[Table]:
    """Every table of the text, in all three forms the conversion uses."""
    return [*_simple_tables(text), *_html_tables(text), *_pipe_tables(text)]


def bullets(body: str) -> list[str]:
    """The text of each top-level bullet, its wrapped lines joined."""
    items: list[list[str]] = []
    for line in body.splitlines():
        if re.match(r"^\s{0,3}[-*]\s+", line):
            items.append([re.sub(r"^\s{0,3}[-*]\s+", "", line)])
        elif items and line.startswith(" ") and line.strip():
            items[-1].append(line.strip())
        elif not line.strip() and items:
            items.append([])
    return [inline(" ".join(item)) for item in items if item]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def by_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows sorted by id; a second row with an id already taken is a parser error, not data to keep."""
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["id"] in seen:
            raise ValueError(f"two entries with the id {row['id']!r}: {seen[row['id']]['name']!r} and {row['name']!r}")
        seen[row["id"]] = row
    return [seen[key] for key in sorted(seen)]
