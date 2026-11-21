"""What the SRD's original RTF release adds to the conversion (DEL-388): the weapons table, which the conversion broke,
and the stat blocks of monsters it lost. The RTFs are untrusted input: they are only read as text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from check_rtf import rtf_text, words

from srd35_extract.common import by_id, clean, slug
from srd35_extract.kinds import SIZES, scrubbed

CHARACTERS = {"endash": "–", "emdash": "—", "lquote": "‘", "rquote": "’", "ldblquote": "“", "rdblquote": "”"}
"""The control words the RTFs write characters with, which `check_rtf.rtf_text` drops: "18\\endash 20" is "18–20"."""


SYMBOL = {0xF020: " ", 0xF0D7: "×"}
"""The Symbol-font characters the RTFs write as `\\u-4064\\'3f` (a code in the private area, then its one-character
fallback "?" as a hex escape, which `check_rtf.rtf_text` keeps): "9 x\\u-4064\\'3f(2 + Int" is "9 x (2 + Int",
"1d8/\\u-3881\\'3f3" "1d8/×3"."""


def _unicode(m: re.Match[str]) -> str:
    code = int(m.group(1)) % 65536
    return f"\\u{ord(SYMBOL.get(code, chr(code)))}?"


def text(raw: str) -> str:
    """`check_rtf.rtf_text`, with the dashes and quotes the RTFs write as control words kept as their characters, and
    a `\\uN` whose fallback is a hex escape read as its one character (`SYMBOL`'s for the Symbol font's)."""
    named = "|".join(CHARACTERS)
    raw = re.sub(r"(?<!\\)\\u(-?\d+) ?\\'[0-9a-fA-F]{2}", _unicode, raw)
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


def _entries(rtf_dir: Path) -> list[tuple[str, str, str, dict[str, str], str, list[str]]]:
    """Each column of the Monsters*.rtf stat blocks (psionic, epic and divine files left out), in file order: its
    name as the conversion names monsters, its column title, its size and type, its own fields, the text after its
    block and the block's column titles. A block's columns share the text after it, and blocks with none share the
    next one's."""
    found = []
    for path in sorted(rtf_dir.glob("Monsters*.rtf")):
        if path.name.startswith(LEFT_OUT):
            continue
        text_rows = lines(_superscripts(_read(path), " ({})"))
        # a label spaced from its colon ("Hit Dice :", the lantern archon's block) read as the others are
        text_rows = [re.sub(r"^([A-Z][A-Za-z/ ]+?) :\t", r"\1:\t", row) for row in text_rows]
        blocks = _blocks(text_rows)
        descriptions = [""] * len(blocks)
        for number in reversed(range(len(blocks))):  # blocks one after another share the text after the last
            until = blocks[number + 1][0] if number + 1 < len(blocks) else len(text_rows)
            own = "\n\n".join(" ".join(line.split("\t")) for line in text_rows[blocks[number][1] : until])
            descriptions[number] = own or (descriptions[number + 1] if number + 1 < len(blocks) else "")
        for number, (_start, _end, names, kinds, fields) in enumerate(blocks):
            for column, (title, kind) in enumerate(zip(names, kinds, strict=True)):
                own = {label: values[column] for label, values in fields.items() if len(values) == len(names)}
                name = _name(title, alone=len(names) == 1)
                found.append((name, title, kind, own, descriptions[number], names))
    return found


def missing_monsters(rtf_dir: Path, have: set[str]) -> list[dict[str, Any]]:
    """The monsters of CR 5 or less in the Monsters*.rtf stat blocks (psionic, epic and divine files left out) that
    the conversion lacks. `have` is the pack's monster names, normalized (`check_rtf.normal`); a monster is had when
    its name, or its column's title, has the same words ("BEAR, BLACK" is "Black Bear"). A block's columns share
    the text after it, and blocks with none share the next one's."""
    had = {words(name) for name in have}
    rows = []
    for name, title, kind, own, description, _names in _entries(rtf_dir):
        if words(name) in had or words(title) in had:
            continue
        cr = _cr(own.get("Challenge Rating", ""))
        if cr is None or cr > MOST_CR:
            continue
        row = _monster(name, kind, own, description)
        if row is not None:
            rows.append(row)
            had.add(words(name))
    return by_id(rows)


# Monsters' qualities and race data (DEL-389 part 3)

BYPASS = ("cold iron", "adamantine", "bludgeoning", "piercing", "slashing", "chaotic", "lawful", "silver", "magic",
          "good", "evil", "epic", "—")  # fmt: skip
"""The words a damage reduction names (the SRD's), longest first so "cold iron" is read before any shorter word."""
ENERGY = ("acid", "cold", "electricity", "fire", "sonic")
_DR = re.compile(r"(?i)\b(?:damage reduction|DR)\s+(\d+)/")
_DR_MORE = re.compile(r"\s+and\s+(\d+)/")  # "DR 10/— and 5/good": a second entry
_SR = re.compile(r"(?i)\b(?:spell resistance|SR)\s+(?:equal to\s+)?(\d+)(\s*\+\s*class levels)?")
_SR_TRAIT = re.compile(r"(?im)^—?\s*Spell resistance equal to (\d+)( \+ class levels)?")
_SR_BY_LEVELS = re.compile(r"(?i)spell resistance equal to (\d+) \+ class levels")
"""A race section's "spell resistance equal to 13 + class levels" (the azer's), anywhere in a trait line: it marks
the stat block's SR 13 as growing with class levels, when the numbers agree."""
_REGENERATION = re.compile(r"(?i)\bregeneration\s+(\d+)")
_FAST_HEALING = re.compile(r"(?i)\bfast healing\s+(\d+)")
_ENERGY = "|".join(ENERGY)
_RESIST = re.compile(rf"(?i)\bresistance to ((?:(?:{_ENERGY}) \d+(?:,? and |, )?)+)")
_RESIST_PAIR = re.compile(rf"(?i)({_ENERGY}) (\d+)")
_IMMUNE = re.compile(r"(?i)\bimmun(?:ity|e) to ((?:[a-z \-]+, )+and [a-z \-]+?|[a-z \-]+?)(?=,|;|\.|\)|$|\s+(?:"
                     r"resistance|spell resistance|damage reduction|vulnerability|DR|SR|blindsense|blindsight|"
                     r"darkvision|low-light|\w+ traits|hive mind)\b)")  # fmt: skip
"""An immunity's list: "immunity to fire and poison", or the SRD's "immunity to poison, charm, and compulsion" (its
items before the qualities' next comma only with the list's closing "and")."""
_REGENERATION_TEXT = re.compile(r"Regeneration(?: \((?:Ex|Su)\))?: (?:(.+?) deals? normal damage|[^.]*? takes? "
                                r"(?:normal )?damage from ([^.]+))")  # fmt: skip
_REGENERATION_WORDS = (
    (r"good-aligned silvered weapons", "good and silver"),
    (r"epic evil-aligned weapons", "epic and evil"),
    (r"silvered weapons", "silver"),
    (r"(\w+)-aligned weapons", r"\1"),
    (r"spells (?:or|and) effects with the (\w+) descriptor", r"\1 and spell"),
    (r"(\w+) weapons", r"\1"),
)
"""How the text that stops a regeneration is read: "Fire and acid deal normal damage" is fire or acid; a devil's
"silvered weapons, good-aligned weapons, and spells or effects with the good descriptor" is silver or good; a weapon
that must be both ("good-aligned silvered weapons") is one alternative needing both, "good and silver". A spell's
alternative ("spells or effects with the good descriptor") has the word "spell" besides its descriptor, `["good",
"spell"]`: no weapon has it, so a holy sword alone doesn't stop a pit fiend's regeneration."""


def _bypass(after: str) -> tuple[dict[str, list[str]], int]:
    """What a damage reduction's "/…" names, and how much of `after` that took: "magic" is `{"bypass": ["magic"]}`,
    "cold iron and good" both needed, "magic or silver" either (`bypass_any`), "—" (or the RTFs' "–") nothing."""
    found, joins, at, low = [], set(), 0, after.lower()
    while True:
        rest = "—" + low[at + 1 :] if low[at : at + 1] in ("–", "-") else low[at:]
        word = next((w for w in BYPASS if rest.startswith(w) and not rest[len(w) : len(w) + 1].isalpha()), None)
        if word is None:
            break
        found.append(word)
        at += len(word)
        join = re.match(r"\s+(and|or)\s+(?=[a-z—–-])", low[at:])
        if not join:
            break
        joins.add(join.group(1))
        at += join.end()
    return ({"bypass_any" if joins == {"or"} else "bypass": found} if found else {}), at


def _regeneration_bypass(text: str, name: str = "") -> list[list[str]] | None:
    """What deals a regenerating creature normal damage, from its "Regeneration (Ex):" text (of several, the one that
    names it: the angels' share a text), as alternatives, each a list of what it needs all of: the troll's
    `[["fire"], ["acid"]]`, the pit fiend's `[["good", "silver"], ["good", "spell"]]`; None without one."""
    found_all = list(_REGENERATION_TEXT.finditer(text))
    named = [m for m in found_all if any(w in m.group(0).lower() for w in name.lower().split() if len(w) > 3)]
    m = (named or found_all or [None])[0]
    if not m:
        return None
    if re.search(r"No form of attack deals lethal damage", text):
        return []
    phrase = (m.group(1) or m.group(2)).strip()
    found: list[str] = []
    for part in re.split(r",\s*(?:and\s+)?|\s+and\s+(?!effects)", phrase):
        part = part.strip().lower().removeprefix("from ")
        for pattern, word in _REGENERATION_WORDS:
            part = re.sub(rf"^{pattern}$", word, part)
        if part and part.split(" and ") not in found:
            found.append(part.split(" and "))
    return found


def defences(qualities: str, text: str = "", name: str = "", traits: str = "") -> dict[str, Any]:
    """The keys a monster's Special Qualities give (only those it has): `dr` (a list, each `{"value", "bypass"}` or
    `{"value", "bypass_any"}`), `sr` (and `sr_plus_class_levels` for "11 + class levels"), `regeneration` (`{"value",
    "bypass"}`, what deals it normal damage, read from `text`'s "Regeneration (Ex):" that names `name`),
    `fast_healing`, `resist` (`{"fire": 10}`) and `immune` (`["fire", "sleep"]`). Without a spell resistance in the
    qualities, a race's trait in `traits` gives it ("Spell resistance equal to 11 + class levels", the drow's); a
    trait that gives the same number "+ class levels" sets `sr_plus_class_levels`."""
    out: dict[str, Any] = {}
    dr = []
    for m in _DR.finditer(qualities):
        value, rest = int(m.group(1)), qualities[m.end() :]
        while True:  # "DR 10/— and 5/good": an entry, then any more
            bypass, used = _bypass(rest)
            dr.append({"value": value, **bypass})
            if not (more := _DR_MORE.match(rest[used:])):
                break
            value, rest = int(more.group(1)), rest[used + more.end() :]
    if dr:
        out["dr"] = dr
    if sr := _SR.search(qualities) or _SR_TRAIT.search(traits):
        out["sr"] = int(sr.group(1))
        by_levels = (int(n) for n in _SR_BY_LEVELS.findall(traits))
        if sr.group(2) or out["sr"] in by_levels:
            out["sr_plus_class_levels"] = True
    if regeneration := _REGENERATION.search(qualities):
        stops = _regeneration_bypass(text, name)
        out["regeneration"] = {"value": int(regeneration.group(1)), "bypass": stops or []}
    if healing := _FAST_HEALING.search(qualities):
        out["fast_healing"] = int(healing.group(1))
    resist = {}
    for m in _RESIST.finditer(qualities):
        resist.update({e.lower(): int(n) for e, n in _RESIST_PAIR.findall(m.group(1))})
    if resist:
        out["resist"] = resist
    immune: list[str] = []
    for m in _IMMUNE.finditer(qualities):
        for part in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1)):
            part = part.strip().lower().removesuffix(" effects").strip()
            if part and part not in immune:
                immune.append(part)
    if immune:
        out["immune"] = immune
    return out


DEFENCES = ("dr", "sr", "sr_plus_class_levels", "regeneration", "fast_healing", "resist", "immune")
_SECTION = re.compile(r"(?i)^(.+?) (?:as )?characters$")
_LA_TRAIT = re.compile(r"(?im)^—?\s*Level adjustment ([+–-]?\d+[^.\n]*)\.?\s*$")


def _flat(value: str) -> str:
    return " ".join(re.sub(r"[–—-]", "-", value).lower().split())


def _completes(given: str, had: str) -> bool:
    """Whether the RTF's `given` says all the conversion's `had` says, and more: each of `had`'s words is one of
    `given`'s, or two of them run together ("abilitiesscent"). The conversion dropped its link text ("Damage
    reduction 10/magic, darkvision 60 ft., freeze" is its " freeze")."""
    mine = set(re.findall(r"[a-z0-9]+", given.lower()))
    joined = {a + b for a in mine for b in mine}
    return _flat(given) != _flat(had) and all(w in mine or w in joined for w in re.findall(r"[a-z0-9]+", had.lower()))


def garbled(line: str) -> bool:
    """Whether an RTF Special Qualities line is broken: it ends in "resistance to" or "immunity to", a clause starts
    with an energy's number and no "resistance to" ("…, electricity 10 and fire 10"), or a run of four or more words
    comes twice (the elder tojanida's resistances, the ettin skeleton's "darkvision 60 ft.")."""
    if re.search(r"(?i)(?:resistance|immunity) to\s*$", line):
        return True
    if any(re.match(rf"(?i)({_ENERGY}) \d+", part) for part in _parts(_RESIST.sub("", line))):
        return True
    tokens = re.findall(r"[a-z0-9]+", line.lower())
    runs = [" ".join(tokens[i : i + 4]) for i in range(len(tokens) - 3)]
    return len(runs) != len(set(runs))


def markdown_qualities(srd: Path) -> dict[str, str]:
    """The Special Qualities line of each stat block in the SRD Markdown copy's monster pages (`3.5 Compendium/
    Monsters/*.md`, pipe tables with a column per monster), by the words of the monster's name: "Adult Tojanida
    Medium Outsider (…)" is the adult tojanida. Only read to stand in for an RTF line that is `garbled`."""
    found: dict[str, str] = {}
    size = re.compile(rf"\s+(?:{'|'.join(SIZES)})\s")
    for path in sorted((srd / "3.5 Compendium" / "Monsters").glob("*.md")):
        text = path.read_text(encoding="utf-8").splitlines()
        names: list[str] = []
        for line, after in zip(text, [*text[1:], ""], strict=True):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if after.startswith("|---"):  # a table's header: its monsters' names, each before its size
                names = [size.split(c, maxsplit=1)[0] for c in cells if c]
            elif line.startswith("|**Special Qualities:**") and names:
                values = [c for c in cells[1:] if c]
                if len(values) == len(names):
                    for name, value in zip(names, values, strict=True):
                        found.setdefault(words(name), clean(value))
    return found


def _sections(description: str) -> dict[str, str]:
    """A block's "… AS CHARACTERS" sections ("OGRES AS CHARACTERS", "Jann as Characters", "TROGLODYTE CHARACTERS")
    by the words of the creature they name: the heading, then its paragraphs up to the last trait line ("—…")
    before the next heading."""
    found = {}
    paragraphs = description.split("\n\n")
    for n, heading in enumerate(paragraphs):
        name = _SECTION.match(heading)
        if not name or not any("racial traits" in after for after in paragraphs[n + 1 : n + 4]):
            continue
        end = n + 1
        for m in range(n + 1, len(paragraphs)):
            if _SECTION.match(paragraphs[m]) or _HEADING.fullmatch(paragraphs[m]):
                break
            if paragraphs[m].startswith("—"):
                end = m
        found[words(name.group(1))] = "\n\n".join(paragraphs[n : end + 1])
    return found


def _singular(word: str) -> str:
    """A heading's word as the monster's name has it: "giants" is "giant", "jann" "janni" (the SRD's plural)."""
    return {"jann": "janni"}.get(word) or (word[:-1] if word.endswith("s") and not word.endswith("ss") else word)


def _section_for(sections: dict[str, str], name: str) -> str | None:
    """The section that names `name`, singular or plural ("OGRES" is the ogre, "HILL GIANTS" the hill giant)."""
    key = words(name)
    for heading, section in sections.items():
        if key in (heading, " ".join(sorted(_singular(w) for w in heading.split()))):
            return section
    return None


def qualities(rtf_dir: Path, rows: list[dict[str, Any]], srd: Path | None = None) -> list[dict[str, Any]]:
    """The rows completed from the Monsters*.rtf stat blocks they are had by (the same words as `missing_monsters`
    reads them): the Special Qualities where the RTF's say all the conversion's do and more (`_completes`; where they
    disagree the conversion's stay), the Special Attacks and Space/Reach where blank, the level adjustment where blank
    (the block's, or the "Level adjustment +N" trait), the "… AS CHARACTERS" section where the text has none, and the
    keys `defences` reads from the qualities. A row no block has keeps its fields; every row gains the `defences` its
    qualities give. A `garbled` RTF line is not taken: the SRD Markdown copy's line (`markdown_qualities` of `srd`)
    is, when given. Rows are copies, in the same order."""
    entries: dict[str, tuple[dict[str, str], str]] = {}
    for name, title, _kind, own, description, _names in _entries(rtf_dir):
        for key in (words(name), words(title)):
            entries.setdefault(key, (own, description))
    copy = markdown_qualities(srd) if srd else {}
    out = []
    for row in rows:
        row = {key: value for key, value in row.items() if key not in DEFENCES}  # read afresh on every run
        own, description = entries.get(words(row["name"]), ({}, ""))
        given = scrubbed(own.get("Special Qualities", ""))
        if given and garbled(given):
            given = scrubbed(copy.get(words(row["name"]), ""))
        if given and _completes(given, row.get("special_qualities", "")):
            row["special_qualities"] = given
        for field, label in (("special_attacks", "Special Attacks"), ("space_reach", "Space/Reach")):
            if not str(row.get(field, "")).strip() and own.get(label):
                row[field] = scrubbed(own[label])
        text = str(row.get("text", ""))
        section = _section_for(_sections(description), row["name"]) if description else None
        if section and section.split("\n\n", 1)[0].lower() not in text.lower():
            row["text"] = scrubbed(f"{text}\n\n{section}" if text.strip() else section)
        if not str(row.get("level_adjustment", "")).strip():
            la = scrubbed(own.get("Level Adjustment", ""))
            if not la and (trait := _LA_TRAIT.search(row.get("text", ""))):
                la = trait.group(1).strip()
            if la:
                row["level_adjustment"] = la
        text = str(row.get("text", ""))
        row.update(defences(row.get("special_qualities", ""), f"{description}\n\n{text}", row["name"], traits=text))
        out.append(row)
    return out


# Class tables (DEL-389 part 4)

CLASS_FILE = "PrestigeClasses.rtf"
"""The RTF with the prestige classes' tables, the one the conversion lost a table of (the mystic theurge's)."""
_ORDINAL = re.compile(r"(\d+)(?:st|nd|rd|th)$")
_COLUMNS = {"Base Attack Bonus": "bab", "Fort Save": "fort", "Ref Save": "ref", "Will Save": "will",
            "Special": "special"}  # fmt: skip
"""A class table's columns by the level row's key; the others ("Spells per Day") are left to the class text."""


def class_levels(rtf_dir: Path, name: str) -> list[dict[str, Any]]:
    """The level rows of "Table: The <name>" in `CLASS_FILE`, keyed as `classes.json`'s (`bab`, the saves, `special`,
    and `spells_per_day` empty: a "+1 level of existing class" column is read from the class text). The heading's
    words run over several lines ("Level\\tBase", "Attack", "Bonus\\tFort"), and a cell over two ("…class/", "+1
    level…"), so the lines are joined again: a line that starts no level row goes on the one before. Empty when the
    table isn't there."""
    rows = lines(_read(rtf_dir / CLASS_FILE))
    title = f"Table: The {name}"
    if title not in rows:
        return []
    heading: list[str] = []
    table: list[list[str]] = []
    for line in rows[rows.index(title) + 1 :]:
        cells = line.split("\t")
        if _ORDINAL.match(cells[0]):
            table.append(cells)
        elif table:
            if line == "Class Features" or line.isupper():
                break
            table[-1][-1] = f"{table[-1][-1]}{line}"
        else:
            heading = [*heading[:-1], f"{heading[-1]} {cells[0]}", *cells[1:]] if heading else cells
    out = []
    for cells in table:
        found = dict(zip(heading, cells, strict=True))
        level = _ORDINAL.match(cells[0]).group(1)  # type: ignore[union-attr]
        row: dict[str, Any] = {"level": int(level), "special": "", "spells_per_day": {}}
        row |= {key: found[column] for column, key in _COLUMNS.items() if column in found}
        out.append(dict(sorted(row.items())))
    return out
