"""An SRD text as the Markdown the Rulesets pages draw and the DM reads (DEL-394): paragraphs on one line each,
bullet lists one item to a line, and every table of the conversion (pandoc's simple, multiline and grid tables, the
HTML tables and the pipe tables) as a pipe table, its caption and title in bold above it and its footnotes as
paragraphs under it. The words are the conversion's own; only their layout changes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from itertools import pairwise

from srd35_extract.common import clean

_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_RULE = re.compile(r"^\s*-{3,}(\s+-{3,})*\s*$")
_GRID_BORDER = re.compile(r"^\s*\+(?:[-=:]+\+)+\s*$")
_PIPE_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")
_NOTE = re.compile(r"^(?:\d{1,2}|[⁰¹²³⁴⁵⁶⁷⁸⁹]{1,2}|\*{1,3}|†)\s?[A-Z][\w'’,-]*(?:\s+\S+){2,}")
"""A table's footnote: its mark (a number, stars or a dagger), then a sentence."""
_HEADING = re.compile(r"^#{1,6}\s")
_ITEM = re.compile(r"^\s{0,3}[-*+](?:\s+(.*))?$")
_TAG = re.compile(r"</?(?:div|span|p|br|colgroup|col)\b[^>]*>", re.IGNORECASE)


def _mark(text: str) -> str:
    """A superscript's text: digits as superscript digits, anything else (a star) as it is."""
    return text.translate(_SUPERSCRIPT) if re.fullmatch(r"[\d,]+", text) else text


def superscripts(text: str) -> str:
    """`^1^` and `<sup>1</sup>` (bold or not) as ¹."""
    text = re.sub(r"\*\*\s*(<sup>.*?</sup>)\s*\*\*", r"\1", text)
    text = re.sub(r"<sup>\s*(.*?)\s*</sup>", lambda m: _mark(m.group(1)), text, flags=re.DOTALL)
    return re.sub(r"\^([^\s^]{1,6})\^", lambda m: _mark(m.group(1)), text)


def _cell(raw: str) -> str:
    """A table cell's text on one line, its markup but the emphasis dropped; a `|` in it as `/`."""
    text = clean(superscripts(_TAG.sub(" ", raw)))
    text = re.sub(r"^:::.*$", "", text, flags=re.MULTILINE)
    text = text.replace("\\", " ")
    return " ".join(text.split()).replace("|", "/")


@dataclass
class _Table:
    rows: list[list[str]]
    caption: str = ""
    groups: dict[int, str] = field(default_factory=dict)
    """The labels of a header row above the header (an HTML table's "Spells per Day"), by the column they start at."""
    notes: list[str] = field(default_factory=list)


def _is_note(row: list[str]) -> bool:
    filled = [c for c in row if c]
    return len(filled) == 1 and row[0] == filled[0] and bool(_NOTE.match(filled[0]))


def _render(table: _Table) -> str:
    """The table as Markdown: its caption and any title rows in bold, the pipe table, then its footnotes."""
    rows = [list(r) for r in table.rows if any(c.strip() for c in r)]
    width = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [n for n in range(width) if any(r[n] for r in rows)]
    groups = {keep.index(n): label for n, label in table.groups.items() if n in keep}
    rows = [[r[n] for n in keep] for r in rows]
    titles = []
    while len(rows) > 1 and len(keep) > 1 and rows[0][0] and not any(rows[0][1:]) and not _is_note(rows[0]):
        titles.append(rows.pop(0)[0])
    notes = list(table.notes)
    at = next((n for n, r in enumerate(rows) if n and _is_note(r)), None)
    if at is not None:
        for row in rows[at:]:
            text = " ".join(c for c in row if c)
            if notes and not _NOTE.match(text):
                notes[-1] += " " + text
            else:
                notes.append(text)
        rows = rows[:at]
    blocks = [f"**{line}**" for line in (table.caption, *titles) if line]
    if rows:
        header, *body = rows
        header = [f"{groups[n]}: {cell}" if n in groups else cell for n, cell in enumerate(header)]
        lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
        lines += ["| " + " | ".join(row) + " |" for row in body]
        blocks.append("\n".join(lines))
    blocks += notes
    return "\n\n".join(blocks)


# Pandoc's simple and multiline tables.


def _simple_cells(line: str, starts: list[int]) -> list[str]:
    """A simple table's line in its columns: each run of text (words a single space apart) in the column it overlaps
    most, split where it crosses a column's start at a space."""
    out = [""] * len(starts)
    bounds = [*starts[1:], 10**6]
    for match in re.finditer(r"\S+(?: \S+)*", line):
        pieces, begin = [], match.start()
        for cut in starts[1:]:
            if begin < cut - 1 < match.end() and line[cut - 1] == " ":
                pieces.append((begin, cut - 1))
                begin = cut
        pieces.append((begin, match.end()))
        for start, stop in pieces:
            overlap = [max(0, min(stop, b) - max(start, a)) for a, b in zip(starts, bounds, strict=True)]
            column = overlap.index(max(overlap))
            out[column] = f"{out[column]} {line[start:stop]}".strip()
    return out


def _gutters(lines: list[str]) -> list[int]:
    """Where the columns of `lines` start, by their text: after a gap of two spaces or more on every line. A table
    whose rule doesn't match its text (Bag of Tricks: three rules over six columns) has twice as many of these as
    rules or more, and is split by them instead."""
    filled = [False] * max((len(line) for line in lines), default=0)
    for line in lines:
        for n, ch in enumerate(line):
            filled[n] = filled[n] or ch != " "
    starts, gap = [], 2
    for n, full in enumerate(filled):
        if full and gap >= 2:
            starts.append(n)
        gap = 0 if full else gap + 1
    return starts


def _simple(inner: list[str], starts: list[int], caption: str) -> _Table:
    starts = [min(starts[0], *(len(line) - len(line.lstrip()) for line in inner if line.strip())), *starts[1:]]
    # Styling junk the conversion left between the rule and the header: lines with nothing in the first column.
    while inner and (not inner[0].strip() or not _simple_cells(inner[0], starts)[0].strip('"')):
        inner = inner[1:]
    multiline = any(not line.strip() for line in inner)
    blocks: list[list[str]] = [[]]
    for line in inner:
        if line.strip() and multiline:
            blocks[-1].append(line)
        elif line.strip():
            blocks.append([line])
        elif blocks[-1]:
            blocks.append([])
    rows, notes, data = [], [], []
    for block in (b for b in blocks if b):
        text = " ".join(line.strip() for line in block)
        if notes or (_NOTE.match(text) and "   " not in text):
            if notes and not _NOTE.match(text):
                notes[-1] += " " + _cell(text)
            else:
                notes.append(_cell(text))
            continue
        data.append(block)
    by_text = _gutters([line for block in data for line in block])
    if len(by_text) >= 2 * len(starts):
        starts = by_text
    for block in data:
        columns = zip(*(_simple_cells(line, starts) for line in block), strict=True)
        rows.append([_cell(" ".join(c for c in column if c)) for column in columns])
    # A header over two rows or more: the first columns' headings, then rows without a first cell, the last of them
    # the other columns' headings and those above it their groups ("New Attitude (DC to achieve)" over Hostile to
    # Helpful).
    under = 0
    while under + 1 < len(rows) and not rows[under + 1][0]:
        under += 1
    groups: dict[int, str] = {}
    if under and rows[0][0] and not any(a and b for a, b in zip(rows[0], rows[under], strict=True)):
        header = [a or b for a, b in zip(rows[0], rows[under], strict=True)]
        groups = {n: cell for above in rows[1:under] for n, cell in enumerate(above) if cell}
        rows = [header, *rows[under + 1 :]]
    return _Table(rows, caption, groups, notes)


# Grid tables.


def _grid(lines: list[str], words: _Words) -> _Table:
    border = lines[0]
    cuts = [n for n, ch in enumerate(border) if ch == "+"]
    groups: list[list[str]] = []
    for line in lines:
        if _GRID_BORDER.match(line):
            groups.append([])
        elif groups:
            groups[-1].append(line)
    rows = []
    for group in (g for g in groups if g):
        merged = [c for c in cuts[1:-1] if not all(len(line) > c and line[c] in "|+" for line in group)]
        columns = [c for c in cuts if c not in merged]
        row = []
        for left, right in pairwise(columns):
            row.append(_cell(_joined([line[left + 1 : right] for line in group], words)))
            row += [""] * (sum(1 for c in merged if left < c < right))
        rows.append(row)
    return _Table(rows)


@dataclass(frozen=True)
class _Words:
    """The words of a text's prose, and their beginnings: what a grid cell's broken words are joined against."""

    words: frozenset[str]
    prefixes: frozenset[str]

    @classmethod
    def of(cls, text: str) -> _Words:
        prose = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("|", "+")))
        words = frozenset(re.findall(r"[a-z]+", prose.lower()))
        return cls(words, frozenset(w[:n] for w in words for n in range(2, len(w))))

    def broken(self, before: str, after: str) -> bool:
        """Whether `before` and `after` are one word broken in two ("Gau" / "ntlet", "B" / "ludge"): together a word
        of the prose or the start of one, and not two words of it."""
        whole = (before + after).lower()
        if before.lower() in self.words and after in self.words:
            return False
        return whole in self.words or whole in self.prefixes


def _joined(fragments: list[str], words: _Words) -> str:
    """A grid cell's lines as one text, without the conversion's styling (`::: {style="…"}` broken over lines, and
    `<div>`): a word it broke over lines ("spe" / "llcasting", "Weig" / "ht", "1" / "d2") joined again."""
    text = re.sub(r":::\s*\{[^}]*\}", "", "\n".join(f.strip() for f in fragments), flags=re.DOTALL)
    out = ""
    for fragment in (f.strip() for f in text.split("\n")):
        if not fragment or fragment in ("<div>", "</div>") or fragment.startswith(":::"):
            continue
        out = out + fragment if _glued(out, fragment, words) else f"{out} {fragment}".strip()
    return out


def _glued(before: str, fragment: str, words: _Words) -> bool:
    """Whether a grid cell's next line goes on without a space: after a slash ("class/"), a range's dash ("19--"),
    a die's count ("1" / "d2"), or as the rest of a broken word."""
    if (
        before.endswith("/")
        or re.search(r"\d--$", before)
        or (re.search(r"\d$", before) and re.match(r"d\d", fragment))
    ):
        return True
    tail, head = re.search(r"[A-Za-z]+$", before), re.match(r"[a-z]+", fragment)
    return bool(tail and head and words.broken(tail.group(0), head.group(0)))


# Pipe tables.


def _pipe_row(line: str) -> list[str]:
    return [_cell(c) for c in line.strip().strip("|").split("|")]


def _pipes(lines: list[str]) -> _Table:
    return _Table([_pipe_row(line) for line in lines if line.strip() and not _PIPE_SEPARATOR.match(line.strip())])


# HTML tables.


class _Html(HTMLParser):
    """One `<table>`: its caption and its rows of `(text, colspan)`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.caption = ""
        self.rows: list[list[tuple[str, int]]] = []
        self._text: list[str] | None = None
        self._span = 1
        self._in_caption = False

    def handle_starttag(self, tag, attrs):
        if tag == "caption":
            self._in_caption, self._text = True, []
        elif tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            self._text, self._span = [], int(dict(attrs).get("colspan") or 1)
        elif tag == "sup" and self._text is not None:
            self._text.append("<sup>")

    def handle_endtag(self, tag):
        if tag == "sup" and self._text is not None:
            self._text.append("</sup>")
        elif tag == "caption" and self._text is not None:
            self.caption, self._text, self._in_caption = _cell("".join(self._text)), None, False
        elif tag in ("td", "th") and self._text is not None and self.rows:
            self.rows[-1].append((_cell("".join(self._text)), self._span))
            self._text = None

    def handle_data(self, data):
        if self._text is not None:
            self._text.append(data)


def _html(block: str) -> _Table:
    parser = _Html()
    parser.feed(block)
    rows = []
    for cells in parser.rows:
        row: list[str] = []
        for text, span in cells:
            row += [text] + [""] * (span - 1)
        rows.append(row)
    rows = [r for r in rows if any(r)]
    at = next((n for n, r in enumerate(rows) if r and r[0]), 0)
    groups = {n: text for above in rows[:at] for n, text in enumerate(above) if text}
    return _Table(rows[at:], parser.caption, groups)


# The text.


def _caption(lines: list[str], at: int) -> tuple[str, int]:
    """A pandoc caption (`: Table: …`) in the few lines from `at`: its text and the line after it, or ("", at)."""
    for n in range(at, min(at + 3, len(lines))):
        if lines[n].strip().startswith(":"):
            return _cell(lines[n].strip()[1:]), n + 1
        if lines[n].strip():
            break
    return "", at


_STYLING = re.compile(
    r'\[\]\{style="|"\}(?=\[)|^\s*"\}\s*$|(?<!\S)(?:display: block;|position: absolute;|right: 0;|top: 50%;|left: 0px;'
    r"|border-top: 1px solid currentColor;)"
)
"""The pieces of the rule the conversion draws through a header's group label, spread over the table's lines."""


def _behind_pipes(lines: list[str]) -> bool:
    """Whether a simple table's lines are its columns behind a `|` (Bag of Tricks), not a pipe table's rows: their
    first cell is wider than a pipe table's ever is."""
    widths = sorted(len(line.lstrip()[1:].split("|", 1)[0]) for line in lines)
    return widths[len(widths) // 2] > 60


def _unstyled(text: str) -> str:
    """The table text without the conversion's styling: the drawn rule's pieces blanked and a styled label
    (`[Coins ]{style="…"}`) as its words, each where it stood; a line that held nothing but styling goes."""
    out = []
    for line in text.split("\n"):
        plain = _STYLING.sub(lambda m: " " * len(m.group(0)), line)
        plain = re.sub(r'\[([^\]]*)\]\{style="[^"]*"\}', lambda m: f" {m.group(1)}".ljust(len(m.group(0))), plain)
        if plain.strip() or not line.strip():
            out.append(plain.rstrip() if plain != line else line)
    return "\n".join(out)


def _tables(text: str, words: _Words, found: list[str]) -> str:
    """The text with each table a placeholder line, its Markdown in `found`."""

    def hold(table: _Table) -> str:
        found.append(_render(table))
        return f"\n\n\x00{len(found) - 1}\x00\n\n"

    def html(match: re.Match[str]) -> str:
        table = _html(match.group(1))
        table.caption = table.caption or _cell((match.group(2) or "").strip())
        return hold(table)

    # An HTML table's pandoc caption after it, as well as its own, is said once.
    text = re.sub(r"(<table.*?</table>)(?:[ \t]*\n\s*^\s*:\s([^\n]*))?", html, text, flags=re.DOTALL | re.MULTILINE)
    lines = _unstyled(text).split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _RULE.match(line) and len(re.findall(r"-{3,}", line)) >= 1:
            end = next((j for j in range(i + 1, len(lines)) if _RULE.match(lines[j])), None)
            if end is not None and end > i + 1:
                inner = lines[i + 1 : end]
                caption, after = _caption(lines, end + 1)
                filled = [x for x in inner if x.strip() and not _PIPE_SEPARATOR.match(x.strip())]
                starts = [m.start() for m in re.finditer(r"-{3,}", line)]
                if filled and all(x.lstrip().startswith("|") for x in filled):
                    if _behind_pipes(filled):
                        lines_in = [x.replace("|", " ") for x in filled]
                        table = _simple([x for x in lines_in if x.strip()], starts, caption)
                    else:
                        table = _pipes(inner)
                        table.caption = caption
                else:
                    table = _simple(inner, starts, caption)
                out.append(hold(table))
                i = after if caption else end + 1
                continue
        if _GRID_BORDER.match(line):
            end = i
            while end + 1 < len(lines) and (
                _GRID_BORDER.match(lines[end + 1]) or lines[end + 1].lstrip().startswith("|")
            ):
                end += 1
            table = _grid(lines[i : end + 1], words)
            table.caption, after = _caption(lines, end + 1)
            out.append(hold(table))
            i = after if table.caption else end + 1
            continue
        if line.strip().startswith("|"):
            end = i
            while end + 1 < len(lines) and lines[end + 1].strip().startswith("|"):
                end += 1
            if end > i:
                table = _pipes(lines[i : end + 1])
                table.caption, after = _caption(lines, end + 1)
                out.append(hold(table))
                i = after if table.caption else end + 1
                continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _blocks(text: str) -> list[str]:
    """The text's paragraphs, each on one line; its headings; its bullet lists, an item to a line (an item's
    paragraphs joined); and its table placeholders."""
    blocks: list[str] = []
    para: list[str] = []
    items: list[str] | None = None
    blank = after_table = False

    def flush() -> None:
        nonlocal items, after_table
        if para:
            after_table = after_table and bool(_NOTE.match(para[0]))
            blocks.append(" ".join(para))
            para.clear()
        if items is not None:
            shown = [" ".join(item.split()) for item in items if item.strip()]
            if shown:
                blocks.append("\n".join(f"- {item}" for item in shown))
            items = None

    for line in text.split("\n"):
        stripped = line.strip().removesuffix("\\").strip()
        if not stripped:
            if para:
                flush()
            blank = True
            continue
        if stripped.startswith("\x00") or _HEADING.match(stripped):
            flush()
            blocks.append(stripped)
            after_table = stripped.startswith("\x00")
            blank = False
            continue
        if item := _ITEM.match(line):
            if para:
                flush()
            if items is None:
                items = []
            items.append((item.group(1) or "").strip())
        elif items is not None and (not blank or line.startswith("  ")):
            items[-1] += " " + stripped
        else:
            if items is not None or (para and after_table and _NOTE.match(stripped)):
                flush()  # a table's footnotes, printed after it, are a paragraph each
            para.append(stripped)
        blank = False
    flush()
    return blocks


def markdown(text: str) -> str:
    """The SRD text as the Rulesets' Markdown: see the module's docstring."""
    words = _Words.of(text) if re.search(r"(?m)^\s*\+-", text) else _Words(frozenset(), frozenset())
    found: list[str] = []
    text = _tables(text, words, found)
    text = re.sub(r"(?m)^\s*:::.*$", "", _TAG.sub("", text))
    text = clean(superscripts(text))
    text = re.sub(r"\*\*[—–-]+\s*([^*]+?)\s*[—–-]+\*\*", r"**\1**", text)
    blocks = _blocks(text)
    shown = []
    for block in blocks:
        held = re.fullmatch(r"\x00(\d+)\x00", block)
        shown.append(found[int(held.group(1))] if held else block)
    out = "\n\n".join(b for b in shown if b)
    return _deduplicated(out)


def _deduplicated(text: str) -> str:
    """A table's footnote that the conversion also prints as a paragraph right after it is kept once."""
    parts = text.split("\n\n")
    out: list[str] = []
    for part in parts:
        if out and part in out[-6:] and _NOTE.match(part):
            continue
        out.append(part)
    return "\n\n".join(out)
