"""Glyphs the text layer lost, read from the page's picture (faithful modules D3).

A book's text layer often drops a glyph its font draws as a picture: the ½ of "HD ½", a table cell holding only "½".
What is left is a stat field with no value or an empty table cell (`GAP`). Each page that holds such a line is sent to
Claude once, through an injected `Look`, with its picture and the lines, numbered (`prompts/fill-gaps.md`). An answer
is taken only when it fills the gaps and changes nothing else (`_only_filled`); anything else, a failed call, or no
`look` leaves the line as it is, with a `text-gap` warning. A line is never assumed right as printed: filling a lost
glyph restores what is printed, and isn't a correction.
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from importlib import resources
from typing import Any

from PIL import Image

from delve.maps.vision import Look, fit_for_vision
from delve.modules.books.fences import unfenced
from delve.modules.books.pdf import PdfBook
from delve.modules.source import ModuleSource, Warning

GAP = re.compile(r"(?<!\w)(?:HD|AC|MV|hp|THAC0|#AT)\s+[;,]|\|[ \t]+\|")
"""A stat field with no value ("HD ;"), or an empty table cell ("|  |")."""
MAX_GAP_PAGES = 12
"""At most this many pages are sent; the gaps of the others are warned."""
MAX_FILL = 6
"""A gap is filled by at most this many characters, whitespace aside."""
FRACTIONS = "½¼¾"
"""The glyphs an answer may add anywhere on a line sent."""
CONTEXT_WORDS = 3
"""The words before and after a gap that find it again in an entity record."""

Progress = Callable[[str, int, int], None]
"""`progress(step, done, total)`, as the converter's."""

_SEPARATOR = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_FRACTION = f"[{FRACTIONS}]*"
_FILL = rf"[^\s|;,](?:\s*[^\s|;,]){{0,{MAX_FILL - 1}}}"


@dataclass(frozen=True)
class _Line:
    text: int
    """The index of its text in the source."""
    line: int
    """The index of the line in its text's Markdown."""
    gap: bool
    """Whether it holds a gap; a table row sent with one doesn't need to."""


async def fill_gaps(
    source: ModuleSource,
    book: PdfBook,
    look: Look | None,
    page_image: Callable[[int], Awaitable[bytes]],
    *,
    progress: Progress | None = None,
) -> tuple[ModuleSource, list[Warning]]:
    """`source` with each line that holds a `GAP` read again from its page's picture (`page_image(number)`, a PNG),
    and the warnings: `text-filled` for each gap filled, `text-gap` for each line left as it was. A line's page is the
    one whose text holds its longest run of three or more words without a gap. A table row goes with every row of its
    table. At most `MAX_GAP_PAGES` pages are sent, one vision call each, in page order; `progress("gaps", done,
    total)` counts them. With no gap, nothing is sent."""
    lines = [markdown.split("\n") for markdown in (text.markdown for text in source.texts)]
    pages: dict[int, list[_Line]] = {}
    lost: list[_Line] = []
    for t, text_lines in enumerate(lines):
        for n, line in enumerate(text_lines):
            if not GAP.search(line):
                continue
            page = _page_of(line, book)
            if page is None:
                lost.append(_Line(t, n, True))
                continue
            sent = pages.setdefault(page, [])
            for row in _table_rows(text_lines, n):
                item = _Line(t, row, bool(GAP.search(text_lines[row])))
                if item not in sent:
                    sent.append(item)
    if not pages and not lost:
        return source, []
    entities = source.entities
    warnings: list[Warning] = []
    numbers = sorted(pages)
    sending = numbers[:MAX_GAP_PAGES] if look is not None else []
    for done, number in enumerate(sending, start=1):
        if progress is not None:
            progress("gaps", done - 1, len(sending))
        items = pages[number]
        answers = await _read(look, number, [lines[i.text][i.line] for i in items], page_image)
        for k, item in enumerate(items, start=1):
            before = lines[item.text][item.line]
            ref = f"text:{source.texts[item.text].id}"
            after = answers.get(k)
            if after is None or not _only_filled(before, after):
                if item.gap:
                    warnings.append(_gap_warning(before, ref, number))
                continue
            lines[item.text][item.line] = after
            matches, fills = list(GAP.finditer(before)), _fills(before, after) or []
            if not matches:
                warnings.append(_filled_warning(before.strip(), after.strip(), ref, number))
            for m, fill in zip(matches, fills, strict=True):
                warnings.append(_filled_warning(m.group(), fill, ref, number))
            entities = _fill_records(entities, before, matches, fills)
    if progress is not None and sending:
        progress("gaps", len(sending), len(sending))
    for number in numbers[len(sending) :]:
        warnings += [_gap_warning(lines[i.text][i.line], _ref(source, i), number) for i in pages[number] if i.gap]
    warnings += [_gap_warning(lines[i.text][i.line], _ref(source, i), None) for i in lost]
    texts = [
        replace(text, markdown="\n".join(text_lines)) for text, text_lines in zip(source.texts, lines, strict=True)
    ]
    return replace(source, texts=texts, entities=entities), warnings


def _ref(source: ModuleSource, item: _Line) -> str:
    return f"text:{source.texts[item.text].id}"


def _gap_warning(line: str, ref: str, page: int | None) -> Warning:
    if page is None:
        return Warning(
            "text-gap", f"The text layer lost a character here: “{line.strip()}”. Check it against the book.", ref
        )
    return Warning(
        "text-gap", f"Page {page}'s text layer lost a character here: “{line.strip()}”. Check it against the page.", ref
    )


def _filled_warning(before: str, after: str, ref: str, page: int) -> Warning:
    return Warning("text-filled", f"Read from page {page}'s picture: “{before}” → “{after}”. Check it.", ref)


# ----- finding the page and the lines -----


def _plain(text: str) -> str:
    return " ".join(text.replace("*", "").split())


def _page_of(line: str, book: PdfBook) -> int | None:
    """The first page whose text holds the line's longest run of three or more words without a gap (trying the
    shorter runs when it isn't found); None when no page holds any."""
    runs = [words for words in (segment.replace("|", " ").split() for segment in GAP.split(line)) if len(words) >= 3]
    texts = [(page.number, _plain(page.text)) for page in book.pages]
    for run in sorted((_plain(" ".join(words)) for words in runs), key=len, reverse=True):
        found = next((number for number, text in texts if run in text), None)
        if found is not None:
            return found
    return None


def _table_rows(lines: list[str], n: int) -> list[int]:
    """Line `n`, or every row of its table when it is a table row (the separator row aside)."""
    if not lines[n].lstrip().startswith("|"):
        return [n]
    start, end = n, n
    while start > 0 and lines[start - 1].lstrip().startswith("|"):
        start -= 1
    while end + 1 < len(lines) and lines[end + 1].lstrip().startswith("|"):
        end += 1
    return [row for row in range(start, end + 1) if not _SEPARATOR.match(lines[row])]


# ----- asking -----


def _prompt(number: int, lines: list[str]) -> str:
    template = resources.files("delve.modules.books").joinpath("prompts", "fill-gaps.md").read_text("utf-8")
    numbered = "\n".join(f"{n}. {line.strip()}" for n, line in enumerate(lines, start=1))
    return template.replace("{{number}}", str(number)).replace("{{lines}}", numbered)


async def _read(
    look: Look | None, number: int, lines: list[str], page_image: Callable[[int], Awaitable[bytes]]
) -> dict[int, str]:
    """The answer's lines by number; none when the call fails or its answer can't be read."""
    if look is None:
        return {}
    try:
        with Image.open(io.BytesIO(await page_image(number))) as opened:
            image, media_type = fit_for_vision(opened)
        answer = json.loads(unfenced(await look(_prompt(number, lines), image, media_type)))
    except Exception:  # noqa: BLE001 (a failed call or an unreadable answer leaves the lines, warned)
        return {}
    if not isinstance(answer, list):
        return {}
    read: dict[int, str] = {}
    for entry in answer:
        if not isinstance(entry, dict) or not isinstance(entry.get("n"), int) or not isinstance(entry.get("line"), str):
            continue
        if "\n" not in entry["line"]:
            read[entry["n"]] = entry["line"]
    return read


# ----- checking the answer -----


def _loose(text: str) -> str:
    """A pattern for `text`, whitespace aside, that lets `FRACTIONS` in anywhere."""
    parts = [r"\s*" if c.isspace() else _FRACTION + re.escape(c) for c in re.sub(r"\s+", " ", text)]
    return "".join(parts) + _FRACTION


def _gap_pattern(gap: str) -> str:
    """A pattern for `gap` filled: its field name or cell's bar, one to `MAX_FILL` characters, its `;`, `,` or bar."""
    label, end = gap[:-1].strip(), gap[-1]
    return re.escape(label) + r"\s*" + _FILL + r"\s*" + re.escape(end)


def _fills(before: str, after: str) -> list[str] | None:
    """What fills each gap of `before` in `after` (each gap as `after` prints it), when `after` is `before` with each
    gap filled by at most `MAX_FILL` characters and only `FRACTIONS` added elsewhere, whitespace aside; else None."""
    parts, pos = [], 0
    for m in GAP.finditer(before):
        parts += [_loose(before[pos : m.start()]), f"({_gap_pattern(m.group())})"]
        pos = m.end()
    parts.append(_loose(before[pos:]))
    matched = re.fullmatch(r"\s*" + "".join(parts) + r"\s*", after)
    return list(matched.groups()) if matched else None


def _only_filled(before: str, after: str) -> bool:
    """Whether `after` only fills `before`'s gaps (and adds `FRACTIONS`), and changes it."""
    return after != before and _fills(before, after) is not None


# ----- the entity records -----


def _fill_records(entities: dict[str, Any], before: str, matches: list[re.Match[str]], fills: list[str]) -> Any:
    """`entities` with each gap's `CONTEXT_WORDS` words before and after, as `before` has them, replaced by the same
    words with the gap filled, wherever a record's string holds them verbatim."""
    words = list(re.finditer(r"\S+", before))
    for m in matches:
        ahead = [w for w in words if w.end() <= m.start()][-CONTEXT_WORDS:]
        behind = [w for w in words if w.start() >= m.end()][:CONTEXT_WORDS]
        start = ahead[0].start() if ahead else m.start()
        end = behind[-1].end() if behind else m.end()
        # A neighbouring gap the window cuts into is taken whole, so it can be filled in the window too.
        for other in matches:
            if other.start() < end < other.end():
                end = other.end()
            if other.start() < start < other.end():
                start = other.start()
        old = before[start:end]
        new, pos = "", start
        for other, fill in zip(matches, fills, strict=True):
            if start <= other.start() and other.end() <= end:
                new += before[pos : other.start()] + fill
                pos = other.end()
        new += before[pos:end]
        entities = _replaced(entities, old, new)
    return entities


def _replaced(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, dict):
        return {key: _replaced(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_replaced(item, old, new) for item in value]
    return value
