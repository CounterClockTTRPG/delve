"""The text checker (thorough conversion Task 3): each keyed section of a cleaned text compared with the book's entry for
that key in the text layer. Generalised from the WGR1 QA's `ocrkeys.py` and `textcheck.py`: the key scheme is
a part's `key_pattern` (written by the sort agent into `parts.json`), and the pages are the part's.

**The book's entries** (`book_keys`): a line of the text layer that starts with a key of the pattern and a full stop
("12. KITCHEN", "W501.", "Z130-Z133.", "Z518 and Z519.") starts the entry of its first key, which runs to the next such
line. A key the text layer misread as `l2`, `PlO8` or `WBlO` (`l`, `I` for 1, `O`, `o` for 0) is read as the key it is,
when it holds a digit or is two characters or more (so a line "I." is no key 1).

**The checks** (`check_text`), per text: the keys the book has for the text's part that the text lacks; the sections
whose words cover less than `MIN_COVERAGE` of the book's entry (text lost); the sections with over `MAX_FOREIGN` of
their words not in the book's entry (text from elsewhere), when they have over `FOREIGN_MIN_WORDS` words; and the
headings not in the form `## <KEY>. <title> {#<key in lower case>}`. An entry can run long where the text layer missed
the next key: the page is the truth.

**The text's part:** the part whose id is the file's name (`clean/house.md` is part `house`), so keys that repeat across
parts (rooms 1, 2, 3 of a house and of a ship) are checked against their own part's pages only. A file named after no
part is checked against every part whose pattern its headings match.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from delve.conversions.qa.pages import page_text

MIN_COVERAGE = 0.85
MAX_FOREIGN = 0.25
FOREIGN_MIN_WORDS = 40

_OCR_DIGITS = str.maketrans({"l": "1", "I": "1", "O": "0", "o": "0"})
_KEY_TOKEN = re.compile(r"[0-9A-Za-z]{1,8}")
_WORD = re.compile(r"[a-z]{3,}")
_PAGE_MARK = "\n@@PAGE {}\n"
_PAGE_MARKS = re.compile(r"\n@@PAGE \d+\n")


def _bare(pattern: str) -> str:
    """A part's `key_pattern` without its anchors, grouped, to set inside a longer expression."""
    return f"(?:{pattern.removeprefix('^').removesuffix('$')})"


def _key(token: str, pattern: re.Pattern[str]) -> str | None:
    """`token` as a key of `pattern`, its OCR misreadings mended; None when it isn't one."""
    if pattern.fullmatch(token):
        return token
    if len(token) < 2 and not token.isdigit():
        return None
    for mended in (token[0] + token[1:].translate(_OCR_DIGITS), token.translate(_OCR_DIGITS)):
        if pattern.fullmatch(mended):
            return mended
    return None


def book_keys(
    pages: Path,
    pattern: str,
    *,
    first: int | None = None,
    last: int | None = None,
    stops: Sequence[str] = (),
) -> dict[str, list[tuple[int, str]]]:
    """Every entry of the text layer in `pages` (`ocr-NNN.txt`), from page `first` to `last` (every page there by
    default), by key: `(page, text)` for each place the key starts an entry. A key of one of the `stops` patterns (the
    other parts' schemes) ends an entry too, but starts none."""
    numbers = sorted(int(p.stem.removeprefix("ocr-")) for p in pages.glob("ocr-[0-9][0-9][0-9]*.txt"))
    numbers = [n for n in numbers if (first is None or n >= first) and (last is None or n <= last)]
    full = "".join(_PAGE_MARK.format(n) + (pages / page_text(n)).read_text() for n in numbers)
    key = re.compile(_bare(pattern))
    others = [re.compile(_bare(stop)) for stop in stops]
    token = r"[0-9A-Za-z]{1,8}"
    line = re.compile(rf"^[ \t]*({token})(?:[ \t]*(?:-|–|and|,)[ \t]*{token})*[ \t]*\.", re.MULTILINE)
    marks: list[tuple[re.Match[str], str | None]] = []
    for m in line.finditer(full):
        if (k := _key(m.group(1), key)) is not None:
            marks.append((m, k))
        elif any(_key(m.group(1), other) for other in others):
            marks.append((m, None))
    out: dict[str, list[tuple[int, str]]] = {}
    for i, (m, k) in enumerate(marks):
        if k is None:
            continue
        end = marks[i + 1][0].start() if i + 1 < len(marks) else len(full)
        mark = full.rfind("@@PAGE ", 0, m.start())
        page = int(full[mark + 7 : full.index("\n", mark)])
        out.setdefault(k, []).append((page, _PAGE_MARKS.sub("\n", full[m.start() : end]).strip()))
    return out


def entries_json(entries: dict[str, list[tuple[int, str]]]) -> dict[str, dict[str, Any]]:
    """`book_keys` as `delve qa keys` prints it: each key's longest entry, `{key: {"page", "text"}}`."""
    out = {}
    for k, found in entries.items():
        page, text = max(found, key=lambda e: len(e[1]))
        out[k] = {"page": page, "text": text}
    return out


@dataclass(frozen=True)
class Part:
    id: str
    pages: tuple[int, int]
    key_pattern: str | None


def read_parts(path: Path) -> list[Part]:
    """The parts of `parts.json`: a list of parts, or an object with the list under `"parts"`."""
    data = json.loads(path.read_text())
    items = data["parts"] if isinstance(data, dict) else data
    parts = []
    for item in items:
        first, last = item.get("pages") or (None, None)
        parts.append(Part(str(item["id"]), (int(first), int(last)), item.get("key_pattern")))
    return parts


@dataclass
class TextReport:
    name: str
    keys: int = 0
    missing: list[str] = field(default_factory=list)
    scores: list[str] = field(default_factory=list)
    bad_headings: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.missing or self.scores or self.bad_headings)

    def lines(self) -> list[str]:
        out = [f"== {self.name}: {self.keys} keys"]
        if self.missing:
            out.append("  in the book, not here: " + " ".join(self.missing))
        out += [f"  {line}" for line in self.scores]
        out += [f"  heading form: {h}" for h in self.bad_headings]
        return out


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _heading(first: str, patterns: list[re.Pattern[str]]) -> tuple[str | None, bool]:
    """A heading line's key, when it is in the form, and whether it looks keyed (its first word is a key)."""
    for pattern in patterns:
        bare = pattern.pattern
        form = re.compile(
            rf"^## (?P<k>{bare})(?:[-–](?P<k2>{bare}))?\.(?: (?P<title>.*?))? \{{#(?P<anchor>[a-z0-9-]+)\}}$"
        )
        m = form.match(first)
        if m and pattern.fullmatch(m["k"]):
            anchor = (m["k"] + (f"-{m['k2']}" if m["k2"] else "")).lower()
            return (m["k"], True) if m["anchor"] == anchor else (None, True)
    token = _KEY_TOKEN.match(first[3:])
    looks_keyed = token is not None and any(_key(token.group(0), p) for p in patterns)
    return None, looks_keyed


def check_text(name: str, markdown: str, parts: list[Part], pages: Path) -> TextReport:
    """The checks on the text `name` (its file name) against the book's entries in `pages`."""
    stem = Path(name).stem
    keyed = [p for p in parts if p.key_pattern]
    own = [p for p in keyed if p.id == stem]
    patterns_of = {p.id: re.compile(_bare(p.key_pattern or "")) for p in keyed}
    sections = [s for s in re.split(r"(?m)^(?=## )", markdown) if s.startswith("## ")]
    if not own:
        own = [p for p in keyed if any(_heading(s.split("\n", 1)[0], [patterns_of[p.id]])[1] for s in sections)]
    patterns = [patterns_of[p.id] for p in own]
    report = TextReport(name)
    have: dict[str, str] = {}
    for section in sections:
        first = section.split("\n", 1)[0].rstrip()
        k, looks_keyed = _heading(first, patterns)
        if k is None:
            if looks_keyed:
                report.bad_headings.append(first)
            continue
        have[k] = have.get(k, "") + section
    report.keys = len(have)
    book: dict[str, list[tuple[int, str]]] = {}
    for part in own:
        stops = [p.key_pattern or "" for p in keyed if p.key_pattern != part.key_pattern]
        entries = book_keys(pages, part.key_pattern or "", first=part.pages[0], last=part.pages[1], stops=stops)
        for k, found in entries.items():
            book.setdefault(k, []).extend(found)
    report.missing = [k for k in book if k not in have]
    for k, section in have.items():
        if k not in book:
            report.scores.append(f"{k}: not found in the text layer (check the page)")
            continue
        mine = _words(section)
        mine_set = set(mine)
        page, entry = max(book[k], key=lambda e: sum(1 for w in _words(e[1]) if w in mine_set))
        theirs = _words(entry)
        theirs_set = set(theirs)
        coverage = sum(1 for w in theirs if w in mine_set) / max(1, len(theirs))
        foreign = sum(1 for w in mine if w not in theirs_set) / max(1, len(mine))
        if coverage < MIN_COVERAGE or (foreign > MAX_FOREIGN and len(mine) > FOREIGN_MIN_WORDS):
            report.scores.append(
                f"{k} (page {page}): covers {coverage:.0%} of the book's {len(theirs)} words; "
                f"{foreign:.0%} of its {len(mine)} words not in the book entry"
            )
    return report
