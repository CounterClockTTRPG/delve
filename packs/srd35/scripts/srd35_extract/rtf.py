"""What the SRD's original RTF release adds to the conversion (DEL-388): the weapons table, which the conversion broke,
and the stat blocks of monsters it lost. The RTFs are untrusted input: they are only read as text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from check_rtf import rtf_text, words

from srd35_extract.common import by_id, slug
from srd35_extract.kinds import SIZES, scrubbed

CHARACTERS = {"endash": "–", "emdash": "—", "lquote": "‘", "rquote": "’", "ldblquote": "“", "rdblquote": "”"}
"""The control words the RTFs write characters with, which `check_rtf.rtf_text` drops: "18\\endash 20" is "18–20"."""


def text(raw: str) -> str:
    """`check_rtf.rtf_text`, with the dashes and quotes the RTFs write as control words kept as their characters."""
    named = "|".join(CHARACTERS)
    return rtf_text(re.sub(rf"(?<!\\)\\({named})(?![a-z]) ?", lambda m: f"\\u{ord(CHARACTERS[m.group(1)])}?", raw))


def lines(raw: str) -> list[str]:
    """The text's non-blank lines, cells split by tabs, each cell's whitespace collapsed (as `check_rtf.lines`)."""
    found = ("\t".join(" ".join(c.split()) for c in line.split("\t")).strip("\t") for line in text(raw).splitlines())
    return [line for line in found if line.strip()]


def _read(path: Path) -> str:
    return path.read_text(encoding="latin-1")


# Weapons

CATEGORIES = {"Simple Weapons": "simple", "Martial Weapons": "martial", "Exotic Weapons": "exotic"}
KINDS = {"Unarmed Attacks": "unarmed", "Light Melee Weapons": "light", "One-Handed Melee Weapons": "one-handed",
         "Two-Handed Melee Weapons": "two-handed", "Ranged Weapons": "ranged"}  # fmt: skip
_CRITICAL = re.compile(r"(?:(\d+)[–-]20/)?x(\d)")


def _superscripts(raw: str, mark: str) -> str:
    """The RTF with each superscript written as `mark` makes it: "" drops the weapons table's footnote marks
    ("Longspear⁴", "1d3³"), " ({})" writes a bonus feat's "Track^B" as the conversion does, "Track (B)"."""
    return re.sub(r"\{[^{}]*\\super ([^{}\\]+)\}", lambda m: mark.format(m.group(1).strip()), raw)


def _none(cell: str) -> str:
    return "" if cell == "—" else cell


def weapons(rtf_dir: Path) -> list[dict[str, Any]]:
    """Equipment.rtf's Table: Weapons, a row per weapon (ammunition, with no damage, left out). The category and the
    kind come from the table's headings; "19–20/x2" is threat 19 and multiplier 2, "x3" threat 20 (a double weapon's
    "x3/x4" gives its first head's)."""
    rows = []
    category = kind = ""
    wrapped = ""
    for line in lines(_superscripts(_read(rtf_dir / "Equipment.rtf"), "")):
        cells = line.split("\t")
        if cells[0] in CATEGORIES and len(cells) > 1 and cells[1] == "Cost":
            category = CATEGORIES[cells[0]]
            continue
        if not category:
            continue
        if re.match(r"\d+ ", line):
            break  # the table's footnotes: it has ended
        if line in KINDS:
            kind = KINDS[line]
            continue
        if len(cells) == 1:
            wrapped += line + " "  # a name broken over two lines ("Hammer, / gnome hooked")
            continue
        name, wrapped = " ".join((wrapped + cells[0]).split()), ""
        if len(cells) < 8 or not re.fullmatch(r"\d+(d\d+)?(/\d+d\d+)?", cells[3]):
            continue  # ammunition, or the net, whose row has no damage
        critical = _CRITICAL.match(cells[4])
        if not critical:
            raise ValueError(f"weapon {name!r}: no critical in {cells[4]!r}")
        rows.append(
            {
                "id": slug(name),
                "name": name,
                "category": category,
                "kind": kind,
                "cost": _none(cells[1]),
                "damage_s": _none(cells[2]),
                "damage_m": cells[3],
                "threat": int(critical.group(1) or 20),
                "mult": int(critical.group(2)),
                "range": _none(cells[5]),
                "weight": _none(cells[6]),
                "type": _none(cells[7]),
            }
        )
    return by_id(rows)


# Monsters

LEFT_OUT = ("Psionic", "Epic", "Divine")
MOST_CR = 5
_HEADING = re.compile(r"[A-Z0-9][A-Z0-9 ,'’()\-–]*")
_LAST_FIELD = "Level Adjustment"
_FIELD = re.compile(r"([A-Z][A-Za-z/ ]+):\t(.*)")


def _continued(values: list[str], more: list[str]) -> list[str]:
    """A field's values with a line it wraps onto ("+2 heavy / shield), touch 11"): a cell per column, or all of it
    to a single column; any other wrap leaves the field without values, so no column takes another's."""
    if len(more) == len(values):
        return [f"{a} {b}" for a, b in zip(values, more, strict=True)]
    return [" ".join([*values, *more])] if len(values) == 1 else []


def _cr(value: str) -> float | None:
    """A challenge rating's number ("1/2", "½", "4 (normal)"), or None when it has none."""
    m = re.match(r"(\d+)/(\d+)|½|(\d+)", value)
    if not m:
        return None
    if m.group(0) == "½":
        return 0.5
    return int(m.group(1)) / int(m.group(2)) if m.group(1) else float(m.group(3))


def _signed(value: str) -> int:
    m = re.match(r"([+–-]?)(\d+)", value)
    return (-1 if m.group(1) in ("–", "-") else 1) * int(m.group(2)) if m else 0


def _parts(value: str) -> list[str]:
    """A field's comma-separated parts, but not the commas inside parentheses."""
    parts, depth, current = [], 0, ""
    for c in value:
        depth += {"(": 1, ")": -1}.get(c, 0)
        if c == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += c
    return [p for p in [*parts, current.strip()] if p and p != "—"]


def _keyed(value: str) -> dict[str, str]:
    """A field like "Str 17, Con —" or "Fort +3, Will –2" as `{"str": "17", "con": "—"}`: the first word is the key."""
    pairs = (part.split(" ", 1) for part in _parts(value))
    return {p[0].lower(): (p[1] if len(p) > 1 else "") for p in pairs}


def _skills(value: str) -> dict[str, str]:
    """The skills, "Listen +1, Knowledge (arcana) +5*", as `{"listen": "+1", "knowledge (arcana)": "+5*"}`."""
    out = {}
    for part in _parts(value):
        m = re.match(r"(.+?)\s+([+–-]\d+.*)$", part)
        out[(m.group(1) if m else part).lower()] = m.group(2) if m else ""
    return out


def _name(column: str, alone: bool) -> str:
    """A block's column title as the conversion names its monsters: "BEAR, BLACK" is "Black Bear", and a race's
    block of one 1st-level warrior ("Orc, 1st-Level Warrior") is the race."""
    warrior = re.fullmatch(r"(.+), 1st-Level Warrior", column)
    if warrior and alone:
        return warrior.group(1)
    if column.isupper():
        column = column.title()
    head, comma, tail = column.partition(", ")
    return f"{tail} {head}" if comma else column


def _blocks(rows: list[str]) -> list[tuple[int, int, list[str], list[str], dict[str, list[str]]]]:
    """Each stat block: where it starts (its headings), where its fields end, its column titles, its size and type
    per column, and its fields by label, a value per column."""
    found = []
    for n, line in enumerate(rows):
        if not line.startswith("Hit Dice:") or n < 2:
            continue
        kinds = [c for c in rows[n - 1].split("\t") if c.strip()]
        names = [c for c in rows[n - 2].split("\t") if c.strip()]
        if not kinds or len(kinds) != len(names) or any(k.split(" ")[0] not in SIZES for k in kinds):
            continue  # a template's text, or a block laid out otherwise
        fields: dict[str, list[str]] = {}
        label, end = "", n
        while end < len(rows):
            field = _FIELD.match(rows[end])
            if field:
                label = field.group(1)
                fields[label] = [c for c in field.group(2).split("\t") if c.strip()]
            elif label and any(_FIELD.match(after) for after in rows[end + 1 : end + 4]):
                fields[label] = _continued(fields[label], [c for c in rows[end].split("\t") if c.strip()])
            else:
                break  # the block ended without its last field
            end += 1
            if label == _LAST_FIELD:
                break
        start = n - 2
        while start > 0 and _HEADING.fullmatch(rows[start - 1]):
            start -= 1
        found.append((start, end, names, kinds, fields))
    return found


def _monster(name: str, kind: str, fields: dict[str, str], description: str) -> dict[str, Any] | None:
    size, _, rest = kind.partition(" ")
    kind_name, _, subtypes = rest.partition(" (")
    hit_dice = fields.get("Hit Dice", "")
    hp = re.search(r"\((\d+) hp\)", hit_dice)
    ac = re.match(r"(.*?),?\s*touch\s+([+–-]?\d+),\s*flat-? ?footed\s+(.+)$", fields.get("Armor Class", ""))
    if not ac:
        return None
    row = {
        "id": slug(name),
        "name": name,
        "size": size,
        "type": kind_name.strip(),
        "subtypes": [s.strip() for s in subtypes.rstrip(")").split(",") if s.strip()],
        "hit_dice": hit_dice.split(" (")[0].strip(),
        "hp": int(hp.group(1)) if hp else None,
        "initiative": _signed(fields.get("Initiative", "")),
        "speed": fields.get("Speed", ""),
        "armor_class": ac.group(1).strip(),
        "touch": _signed(ac.group(2)),
        "flat_footed": ac.group(3).strip(),
        "base_attack_grapple": fields.get("Base Attack/Grapple", ""),
        "attack": fields.get("Attack", ""),
        "full_attack": fields.get("Full Attack", ""),
        "space_reach": fields.get("Space/Reach", ""),
        "special_attacks": fields.get("Special Attacks", ""),
        "special_qualities": fields.get("Special Qualities", ""),
        "saves": _keyed(fields.get("Saves", "")),
        "abilities": _keyed(fields.get("Abilities", "")),
        "skills": _skills(fields.get("Skills", "")),
        "feats": fields.get("Feats", ""),
        "environment": fields.get("Environment", ""),
        "organization": fields.get("Organization", ""),
        "cr": fields.get("Challenge Rating", "").replace("½", "1/2"),
        "treasure": fields.get("Treasure", ""),
        "alignment": fields.get("Alignment", ""),
        "advancement": fields.get("Advancement", ""),
        "level_adjustment": fields.get("Level Adjustment", ""),
        "languages": "",
        "senses": [],
        "text": description,
    }
    for key, value in row.items():
        if isinstance(value, str):
            row[key] = scrubbed(value)
        elif isinstance(value, dict):
            row[key] = {k: scrubbed(v) for k, v in sorted(value.items())}
    return row


def missing_monsters(rtf_dir: Path, have: set[str]) -> list[dict[str, Any]]:
    """The monsters of CR 5 or less in the Monsters*.rtf stat blocks (psionic, epic and divine files left out) that
    the conversion lacks. `have` is the pack's monster names, normalized (`check_rtf.normal`); a monster is had when
    its name, or its column's title, has the same words ("BEAR, BLACK" is "Black Bear"). A block's columns share
    the text after it, and blocks with none share the next one's."""
    had = {words(name) for name in have}
    rows = []
    for path in sorted(rtf_dir.glob("Monsters*.rtf")):
        if path.name.startswith(LEFT_OUT):
            continue
        text_rows = lines(_superscripts(_read(path), " ({})"))
        blocks = _blocks(text_rows)
        descriptions = [""] * len(blocks)
        for number in reversed(range(len(blocks))):  # blocks one after another share the text after the last
            until = blocks[number + 1][0] if number + 1 < len(blocks) else len(text_rows)
            own = "\n\n".join(" ".join(line.split("\t")) for line in text_rows[blocks[number][1] : until])
            descriptions[number] = own or (descriptions[number + 1] if number + 1 < len(blocks) else "")
        for number, (_start, _end, names, kinds, fields) in enumerate(blocks):
            description = descriptions[number]
            for column, (title, kind) in enumerate(zip(names, kinds, strict=True)):
                name = _name(title, alone=len(names) == 1)
                if words(name) in had or words(title) in had:
                    continue
                own = {label: values[column] for label, values in fields.items() if len(values) == len(names)}
                cr = _cr(own.get("Challenge Rating", ""))
                if cr is None or cr > MOST_CR:
                    continue
                row = _monster(name, kind, own, description)
                if row is not None:
                    rows.append(row)
                    had.add(words(name))
    return by_id(rows)
