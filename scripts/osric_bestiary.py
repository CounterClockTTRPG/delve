"""Read OSRIC 3.0's bestiary out of the Gamemaster Guide PDF into `packs/osric/src/delve_osric/data/monsters.json` (DEL-301).

    uv run python scripts/osric_bestiary.py ~/osric.tar.gz        # the archive with osric/reference/*.pdf
    uv run python scripts/osric_bestiary.py OSRIC_3.0_Gamemaster_Guide.pdf

The OSRIC 3.0 Third-Party License lets a product print monsters verbatim, so each monster keeps its stat block and its
text as the guide prints them. Needs `pdftotext` (poppler-utils).

The guide sets its monsters in two columns, a stat block a table of labelled rows (FREQUENCY … EXPERIENCE), some
tables with a column per variant (BADGER: ORDINARY, GIANT) and some as wide as the page. The text layer is read by
word positions (`pdftotext -bbox`), not as running text: a row is the band around its label, midway to the next, so a
value set on two lines around its label stays whole; a variant's column starts where its heading does. The prose is the
columns' words outside the stat blocks, in reading order, each block's from its table to the next block.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "packs" / "osric" / "src" / "delve_osric" / "data" / "monsters.json"
PAGES = (89, 322)
"""The Gamemaster Guide's PART TWO: MONSTERS, by the PDF's page numbers."""
MIDDLE = 306.0
"""Where the left column ends on the guide's letter pages."""
PRINTED = 1
"""The guide's printed page numbers run one behind the PDF's (the cover): page 108 is the PDF's 109."""
TOP, BOTTOM = 36.0, 755.0
"""The running header and the page footer lie outside."""

LABELS = (
    ("frequency", ("FREQUENCY",)),
    ("no_encountered", ("NO.", "ENCOUNTERED")),
    ("size", ("SIZE",)),
    ("alignment", ("ALIGNMENT",)),
    ("move", ("MOVE",)),
    ("armour_class", ("ARMOUR", "CLASS")),
    ("hit_dice", ("HIT", "DICE")),
    ("attacks", ("MELEE", "ATTACKS")),
    ("senses", ("SENSES",)),
    ("magic_resistance", ("MAGIC", "RESISTANCE")),
    ("lair_chance", ("LAIR", "CHANCE")),
    ("intelligence", ("INTELLIGENCE",)),
    ("morale", ("MORALE",)),
    ("loot", ("LOOT",)),
    ("experience", ("EXPERIENCE",)),
)
LABEL_WORDS = {word for _, words in LABELS for word in words} | {"ATTACKS"}
NUMBER = re.compile(r"[\d][\d\-–+]*")
FREQUENCY_WORD = re.compile(r"(Common|Uncommon|Rare|Very|Unique|Varies|Variable)\b")
FIRST_WORD = {words[0]: key for key, words in LABELS} | {"ATTACKS": "attacks"}

RUNNING = re.compile(r"(\d+ \| )?(OSRIC 3\.0 - PART TWO: MONSTERS|CHAPTER [A-Z]+: [A-Z ()]+)( \| \d+)?")
"""The pages' running headers and footers."""

SECTIONS = (
    "Surprise and Initiative",
    "Special Features",
    "Special Attacks",
    "Special Defences",
    "Special Defenses",
    "Immunities and Resistances",
    "Vulnerabilities",
    "Spellcasting",
    "Spell-Like Abilities",
    "Language",
    "Languages",
    "Ecology",
    "Combat",
    "Lair",
    "Variants",
)
"""The headings the guide's monster text is set under."""


@dataclass(frozen=True)
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def y(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def is_title(self) -> bool:
        """A monster's name is set larger than anything else in a column (14.5 pt against the text's 12)."""
        return self.height > 14

    @property
    def is_heading(self) -> bool:
        """A word of a variant's heading over its column of a stat block: in capitals, smaller than a title."""
        letters = [c for c in self.text if c.isalpha()]
        return len(letters) > 1 and all(c.isupper() for c in letters) and not self.is_title


@dataclass
class Block:
    page: int
    column: int
    left: float
    right: float
    top: float
    bottom: float
    name: str
    variants: list[str]
    rows: dict[str, list[str]] = field(default_factory=dict)
    text: list[str] = field(default_factory=list)
    base: str = ""
    description: str = ""
    sections: dict[str, str] = field(default_factory=dict)


def pages(pdf: Path) -> list[list[Word]]:
    """The words of each page of PART TWO, by `pdftotext -bbox`."""
    out = subprocess.run(
        ["pdftotext", "-bbox", "-f", str(PAGES[0]), "-l", str(PAGES[1]), str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    found = []
    for page in re.findall(r"<page [^>]*>(.*?)</page>", out, re.DOTALL):
        words = [
            Word(float(a), float(b), float(c), float(d), html.unescape(t).replace("\ufeff", ""))
            for a, b, c, d, t in re.findall(
                r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', page
            )
        ]
        found.append([w for w in words if TOP < w.y < BOTTOM])
    return found


def lines(words: list[Word], gap: float = 3.0) -> list[list[Word]]:
    """Words in lines, top to bottom, each line left to right."""
    out: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.y, w.x0)):
        if out and abs(out[-1][0].y - word.y) < gap:
            out[-1].append(word)
        else:
            out.append([word])
    return [sorted(line, key=lambda w: w.x0) for line in out]


def runs(words: list[Word], gap: float = 7.0) -> list[list[Word]]:
    """A line's words in runs: words closer than `gap` belong together ("Very rare", "7 [13]")."""
    out: list[list[Word]] = []
    for word in sorted(words, key=lambda w: w.x0):
        if out and word.x0 - out[-1][-1].x1 < gap:
            out[-1].append(word)
        else:
            out.append([word])
    return out


def blocks_of(number: int, words: list[Word]) -> list[Block]:
    """The stat blocks of a page: each FREQUENCY label, its label column below it, and the values beside."""
    found = []
    for freq in sorted((w for w in words if w.text == "FREQUENCY"), key=lambda w: (w.x0, w.y)):
        column = 0 if freq.x0 < MIDDLE else 1
        others = [w for w in words if w.text == "FREQUENCY" and w is not freq and abs(w.y - freq.y) < 200]
        right = min((w.x0 - 6 for w in others if w.x0 > freq.x0 + 100), default=None)
        # A table as wide as the page: a value of its FREQUENCY row lies past the middle.
        frequency_row = [w for w in words if abs(w.y - freq.y) < 3 and w.x0 > freq.x1]
        wide = column == 0 and any(
            run[0].x0 > MIDDLE and FREQUENCY_WORD.match(run[0].text) for run in runs(frequency_row)
        )
        if right is None:
            right = 612.0 if (wide or column == 1) else MIDDLE - 4
        # The label column: label words at the FREQUENCY's left edge, down to EXPERIENCE.
        labels: list[tuple[str, Word]] = []
        for w in sorted((w for w in words if abs(w.x0 - freq.x0) < 4 and w.y >= freq.y - 1), key=lambda w: w.y):
            text = w.text.rstrip(":")
            if text in FIRST_WORD:
                labels.append((FIRST_WORD[text], w))
                if text == "EXPERIENCE":
                    break
            elif text not in LABEL_WORDS:
                break
        if not labels or labels[-1][0] != "experience":
            print(f"  page {number}: a FREQUENCY without its rows, at y {freq.y:.0f}", file=sys.stderr)
            continue
        label_right = max(w.x1 for w in words if abs(w.x0 - freq.x0) < 4 and freq.y - 1 <= w.y <= labels[-1][1].y + 1)
        value_left = label_right + 2
        centres = [w.y for _, w in labels]
        step = (centres[-1] - centres[0]) / max(1, len(centres) - 1)
        bands = []
        for i, c in enumerate(centres):
            top = (centres[i - 1] + c) / 2 if i else c - step / 2
            bottom = (c + centres[i + 1]) / 2 if i + 1 < len(centres) else c + step / 2
            bands.append((top, bottom))
        inside = [w for w in words if freq.x0 - 2 <= w.x0 < right]
        # The variants' columns start where the FREQUENCY row's values do. Their headings lie over them, up to three
        # lines above, in lines of capitals (and numbers: "5-6 HEADED", "3 HD"), "CHARONO-" over "SAURUS".
        starts = [run[0].x0 for run in runs([w for w in inside if abs(w.y - freq.y) < 3 and w.x0 >= value_left - 4])]
        zone = [w for w in inside if bands[0][0] - 44 < w.y < bands[0][0] and w.x0 >= value_left - 4 and not w.is_title]
        heading = [
            w
            for line in lines(zone)
            if all(h.is_heading or NUMBER.fullmatch(h.text) for h in line) and any(h.is_heading for h in line)
            for w in line
        ]
        variants: list[str] = []
        if heading and len(starts) > 1:
            names: list[list[Word]] = [[] for _ in starts]
            for w in heading:
                names[min(range(len(starts)), key=lambda i: abs(starts[i] - w.x0))].append(w)
            variants = [
                re.sub(r"- (?=[A-Z])", "", " ".join(w.text for w in sorted(n, key=lambda w: (round(w.y), w.x0))))
                for n in names
            ]
        elif heading:
            variants = [" ".join(w.text for w in heading)]
        if len(variants) < 2:
            starts, variants = [value_left], []
        # The name: the title-sized lines just above the table, one or two of them.
        above = sorted((w for w in inside if w.is_title and bands[0][0] - 60 < w.y < bands[0][0]), key=lambda w: w.y)
        title_lines = lines(above)
        while len(title_lines) > 1 and title_lines[1][0].y - title_lines[0][-1].y > 22:
            title_lines = title_lines[1:]
        name = " ".join(w.text for line in title_lines for w in line)
        if not name:
            # A table under its monster's text: the nearest title above it in its column.
            higher = lines([w for w in inside if w.is_title and w.y < bands[0][0]])
            name = " ".join(w.text for w in higher[-1]) if higher else ""
        top = min(
            (w.y0 for line in title_lines for w in line), default=min((w.y0 for w in heading), default=bands[0][0])
        )
        block = Block(number, column, freq.x0 - 2, right, top - 2, bands[-1][1], name, variants)
        for (key, _), (top_y, bottom_y) in zip(labels, bands, strict=True):
            cells: list[list[str]] = [[] for _ in starts]
            for line in lines([w for w in inside if top_y <= w.y < bottom_y and w.x0 >= value_left - 4]):
                for run in runs(line):
                    i = max((i for i, start in enumerate(starts) if start <= run[0].x0 + 6), default=0)
                    cells[i].append(" ".join(w.text for w in run))
            block.rows[key] = [" ".join(cell) for cell in cells]
        found.append(block)
    return found


def stream(all_pages: list[list[Word]], blocks: list[Block]) -> list[tuple[tuple, str | Block]]:
    """The text outside the stat blocks, line by line in reading order, with each block in its place."""
    items: list[tuple[tuple, str | Block]] = []
    for number, words in enumerate(all_pages, start=PAGES[0]):
        mine = [b for b in blocks if b.page == number]

        def in_block(w: Word) -> bool:
            return any(b.left <= w.x0 < b.right and b.top <= w.y <= b.bottom for b in mine)  # noqa: B023

        for column in (0, 1):
            col = [w for w in words if (w.x0 < MIDDLE) == (column == 0) and not in_block(w)]
            for line in lines(col):
                items.append(((number, column, line[0].y), " ".join(w.text for w in line)))
        for b in mine:
            items.append(((number, b.column, b.top), b))
    return sorted(items, key=lambda item: item[0])


def prose(raw: list[str]) -> tuple[str, dict[str, str]]:
    """A block's text: the description, then its sections by heading, the lines joined and the hyphens mended."""
    parts: list[tuple[str, list[str]]] = [("", [])]
    for line in raw:
        text = line.strip()
        if not text or RUNNING.fullmatch(text) or re.fullmatch(r"MONSTERS|[A-Z]\.?", text):
            continue
        if text in SECTIONS:
            parts.append((text, []))
        else:
            parts[-1][1].append(text)

    def join(chunk: list[str]) -> str:
        out = ""
        for piece in chunk:
            if out.endswith("-") and piece[:1].islower():
                out = out[:-1] + piece
            else:
                out = f"{out} {piece}" if out else piece
        return re.sub(r"\s+", " ", out).strip()

    sections: dict[str, str] = {}
    for heading, chunk in parts[1:]:
        sections[heading] = (sections.get(heading, "") + " " + join(chunk)).strip()
    return join(parts[0][1]), sections


def family(name: str) -> str:
    """A name without a numbered part: 'Other dinosaurs ii' is 'Other dinosaurs'."""
    return re.sub(r"\s+[ivx]+$", "", name)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def title(name: str) -> str:
    """'DRAGON, RED' → 'Dragon, red'; 'ZOMBIE, JUJU' → 'Zombie, juju'."""
    words = name.strip().lower().split(", ")
    return ", ".join([words[0].capitalize(), *words[1:]])


def monsters(pdf: Path) -> list[dict]:
    all_pages = pages(pdf)
    blocks = [b for number, words in enumerate(all_pages, start=PAGES[0]) for b in blocks_of(number, words)]
    # The monster chapter's pages carry its running header. Past it (a monster in a magic item's text: the Deck of
    # Many Things' dread wraith) a block's text is the rest of its own column only.
    chapter = {
        number
        for number, words in enumerate(all_pages, start=PAGES[0])
        if any(
            re.search(r"PART TWO: MONSTERS|MONSTER STATISTICS", " ".join(w.text for w in line)) for line in lines(words)
        )
    }
    current: Block | None = None
    for (page, column, _), item in stream(all_pages, blocks):
        if isinstance(item, Block):
            current = item
        elif re.search(r"\.{8,}", item):
            current = None  # the index after the last monster
        elif current is not None and (page in chapter or (page, column) == (current.page, current.column)):
            current.text.append(item)
    last, told = "", ""
    for b in blocks:
        description, sections = prose(b.text)
        if b.name and family(title(b.name)) != family(last):
            told = ""
        # A table that continues its family's (BEETLES, GIANT on), with no text of its own between: the family's.
        description = description or told
        told = description
        b.description, b.sections = description, sections
        b.base = last = title(b.name) if b.name else last  # a table continued from the page before
    # A family's first table with all its text after a later one (SAHUAGIN): the later one's.
    for here, after in zip(reversed(blocks[:-1]), reversed(blocks[1:]), strict=True):
        if not here.description and family(here.base) == family(after.base):
            here.description = after.description
    out = []
    for b in blocks:
        names, base = b.variants or [""], b.base
        for i, variant in enumerate(names):
            kind = variant.lower()
            name = f"{base}, {kind}" if variant and kind not in base.lower() else base
            out.append(
                {
                    "slug": slug(name),
                    "name": name,
                    "family": base if len(names) > 1 else None,
                    **{key: cells[i] if i < len(cells) else "" for key, cells in b.rows.items()},
                    "description": b.description,
                    "sections": b.sections,
                    "page": b.page - PRINTED,
                }
            )
    return out


def pdf_of(path: Path, tmp: Path) -> Path:
    if path.suffix == ".pdf":
        return path
    with tarfile.open(path) as tar:
        member = tar.getmember("osric/reference/OSRIC_3.0_Gamemaster_Guide.pdf")
        tar.extract(member, tmp, filter="data")
    return tmp / member.name


def main(source: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        found = monsters(pdf_of(Path(source).expanduser(), Path(tmp)))
    table = {
        "_source": "OSRIC 3.0 Gamemaster Guide, Part Two: Monsters (PDF pages 89-322), read by scripts/osric_bestiary.py;"
        " `page` is the guide's printed page."
        " Each monster's stat block and text as the guide prints them (the OSRIC 3.0 Third-Party License allows"
        " monsters verbatim).",
        "monsters": found,
    }
    OUT.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(found)} monsters into {OUT}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "~/osric.tar.gz")
