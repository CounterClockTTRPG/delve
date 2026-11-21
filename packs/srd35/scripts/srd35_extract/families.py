"""The family monsters (DEL-389 part 3): the true dragons by age, a full stat block per colour and age from the SRD's
tables, and each family's parent row naming its variants (`variants`). The RTFs
give each colour as two tables of a row per age ("Red Dragons by Age", "Red Dragon Abilities by Age"), its block's
lines ("Challenge Ratings: Wyrmling 4; very young 5; …") and its text (the breath weapon's shape, which abilities are
spell-like); the general entry ("DRAGON, TRUE") gives the attacks and their damage by size. The RTFs are untrusted
input: they are only read as text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from srd35_extract.common import slug
from srd35_extract.kinds import scrubbed
from srd35_extract.rtf import _read, _superscripts, defences, lines

FILE = "MonstersDr-Dw.rtf"
COLOURS = ("Black", "Blue", "Green", "Red", "White", "Brass", "Bronze", "Copper", "Gold", "Silver")
AGES = ("Wyrmling", "Very young", "Young", "Juvenile", "Young adult", "Adult", "Mature adult", "Old", "Very old",
        "Ancient", "Wyrm", "Great wyrm")  # fmt: skip
"""The age categories as the tables write them, youngest first."""
SIZE_LETTERS = {"F": "Fine", "D": "Diminutive", "T": "Tiny", "S": "Small", "M": "Medium", "L": "Large", "H": "Huge",
                "G": "Gargantuan", "C": "Colossal"}  # fmt: skip
SECONDARY = 5
"""The penalty of a secondary attack (the claws, wings and tail slap: "requiring a –5 penalty on the attack roll")."""
_BY_AGE = 16
_ABILITIES_BY_AGE = 7
_CAPITALS = re.compile(r"[A-Z][A-Z ,'’-]+")
"""An entry's heading ("SILVER DRAGON", "DRAGON TURTLE"): where a colour's text ends."""
_CASTER = re.compile(r"^(.*?)\s*(\d+(?:st|nd|rd|th)|—)$")


def name(age: str, colour: str) -> str:
    """A variant's name, as the SRD's tables head it, in title case: "Very Young Red Dragon"."""
    return f"{age.title()} {colour} Dragon"


def _rows(raw: list[str], title: str, header: str, cells: int) -> list[list[str]]:
    """The 12 rows (one per age) of the table headed `title`, after its header lines (the first starting `header`)."""
    at = raw.index(title) + 1
    while not raw[at].startswith(header):
        at += 1
    while raw[at].split("\t")[0] in ("Age", "Grapple"):
        at += 1
    rows = [line.split("\t") for line in raw[at : at + len(AGES)]]
    for age, row in zip(AGES, rows, strict=True):
        if row[0] != age:
            raise ValueError(f"{title}: {row[0]!r} where {age!r} was expected")
        if len(row) == cells - 1 and cells == _ABILITIES_BY_AGE:
            # The Special Abilities cell is missing ("…\t1st\t—") or run into the caster level ("Sunburst 15th").
            ability = _CASTER.match(row[4])
            row[4:5] = [ability.group(1), ability.group(2)] if ability else ["", row[4]]
        if cells == _ABILITIES_BY_AGE and row[3].endswith(" DR"):  # "flat-footed 35 DR\t15/magic": the very old brass
            row[3], row[4] = row[3].removesuffix(" DR"), f"DR {row[4]}"
        if len(row) != cells:
            raise ValueError(f"{title}, {age}: {len(row)} cells, not {cells}")
    return rows


def _attacks_by_size(raw: list[str]) -> dict[str, dict[str, str]]:
    """Table: Dragon Space/Reach, Attacks, and Damage, by size: the space/reach and each attack's dice ("" for "—")."""
    at = raw.index("Dragon Space/Reach, Attacks, and Damage") + 2
    found = {}
    for line in raw[at : at + 7]:
        size, reach, *dice = line.split("\t")
        keys = ("bite", "claw", "wing", "tail slap", "crush", "tail sweep")
        found[size] = {"space_reach": reach, **{k: ("" if d == "—" else d) for k, d in zip(keys, dice, strict=True)}}
    return found


def _breath_lengths(raw: list[str]) -> dict[str, dict[str, str]]:
    """Table: Dragon Breath Weapons: the line's and the cone's length by size ("80 ft.")."""
    at = raw.index("Dragon Breath Weapons") + 2
    return {size: {"line": line, "cone": cone} for size, line, cone in (r.split("\t") for r in raw[at : at + 7])}


def _block(raw: list[str], colour: str) -> tuple[dict[str, str], str, list[str]]:
    """The colour's block lines by label, its type line ("Dragon (Fire)") and its text lines after the tables."""
    start = raw.index(f"{colour.upper()} DRAGON")
    end = next((n for n in range(start + 1, len(raw)) if _CAPITALS.fullmatch(raw[n])), len(raw))  # the next entry
    tables = raw.index(f"{colour} Dragons by Age", start)
    fields: dict[str, str] = {}
    for line in raw[start + 2 : tables]:
        label, colon, value = line.partition(": ")
        if colon and label in ("Environment", "Organization", "Challenge Rating", "Challenge Ratings", "Treasure",
                               "Alignment", "Advancement", "Level Adjustment"):  # fmt: skip
            fields.setdefault(label.removesuffix("s") if label == "Challenge Ratings" else label, value)
    after = raw.index(f"{colour} Dragon Abilities by Age", start) + 2 + len(AGES)
    return fields, raw[start + 1], raw[after:end]


def _by_age(value: str, age: str) -> str:
    """An age's part of a by-age line ("Wyrmling 4; very young 5; …; others —"): "5" for very young."""
    found = {}
    keys = sorted((*(a.lower() for a in AGES), "others"), key=len, reverse=True)
    for part in (p.strip() for p in value.split(";")):
        key = next((k for k in keys if part.lower().startswith(k + " ")), None)
        if key is not None:
            found[key] = part[len(key) :].strip()
    return found.get(age.lower(), found.get("others", ""))


def _signed(number: int) -> str:
    return f"+{number}" if number >= 0 else f"–{-number}"


def _dice(dice: str, bonus: int) -> str:
    return dice if bonus == 0 else f"{dice}{'+' if bonus > 0 else '–'}{abs(bonus)}"


def _breaths(text: list[str]) -> list[tuple[str, str]]:
    """The colour's breath weapons from its "Breath Weapon (Su):" line, as (shape, what): ("cone", "fire")."""
    line = next(t for t in text if t.startswith("Breath Weapon (Su):"))
    sentence = line.split(".")[0]
    return re.findall(r"\ba (line|cone) of ([a-z ()]+?)(?= and a |,|$)", sentence)


def _spell_like(text: list[str]) -> str:
    """The colour's text that names its spell-like abilities: its "… (Sp):" headings and "Spell-Like Abilities:"
    lines, lower case."""
    found = [t.split(":")[0] for t in text if re.match(r"[A-Z][\w/ ]+ \(Sp\):", t)]
    found += [t for t in text if re.match(r"(?:Other )?Spell-Like Abilities:", t)]
    return " ".join(found).lower()


def dragons(rtf_dir: Path) -> list[dict[str, Any]]:
    """The 120 true dragons by colour and age, each a full stat block (`name`'s names, ids their slugs): the age
    tables' numbers; the bite at the table's Attack and the claws, wings and tail slap (as the dragon's size has them)
    as secondary attacks 5 lower, with the general entry's damage by size plus the Strength bonus (all of it for the
    bite, half for claws and wings, one and a half for the tail slap, rounded down); a Huge or larger dragon's crush
    and a Gargantuan or larger dragon's tail sweep as special attacks; the breath weapon (its shape from the colour's
    text, its length by size), frightful presence and spells; and the qualities: blindsense, keen senses, the
    immunities (the colour's, and every dragon's to sleep and paralysis), the special abilities gained up to that age
    (the spell-like ones as special attacks), the damage reduction of that age and its spell resistance. The block's
    by-age lines give the CR, advancement and level adjustment; skills, feats and languages are not in the tables.
    Only the colours the file has (a fixture cut from it has one); none without the file (the fixtures cut from the
    other RTFs)."""
    if not (rtf_dir / FILE).is_file():
        return []
    raw = lines(_superscripts(_read(rtf_dir / FILE), " ({})"))
    by_size = _attacks_by_size(raw)
    lengths = _breath_lengths(raw)
    out = []
    for colour in (c for c in COLOURS if f"{c.upper()} DRAGON" in raw):
        fields, kind, text = _block(raw, colour)
        numbers = _rows(raw, f"{colour} Dragons by Age", "Age\tSize", _BY_AGE)
        abilities = _rows(raw, f"{colour} Dragon Abilities by Age", "Age\tSpeed", _ABILITIES_BY_AGE)
        breaths = _breaths(text)
        spell_like = _spell_like(text)
        subtypes = re.findall(r"\(([^)]*)\)", kind)
        gained: list[str] = []
        immune: list[str] = []
        dr = ""
        for age, row, more in zip(AGES, numbers, abilities, strict=True):
            _, letter, hit_dice, *scores = row[:9]
            bab, attack, fort, ref, will, breath, presence = row[9:]
            size = SIZE_LETTERS[letter]
            speed, initiative, armour, special, caster, sr = more[1:]
            strength = (int(scores[0]) - 10) // 2
            for part in (p.strip() for p in special.split(",") if p.strip()):
                if part.lower().startswith("immunity to "):
                    immune += [e for e in re.split(r"\s+and\s+", part[len("immunity to ") :]) if e not in immune]
                elif part.startswith("DR "):
                    dr = part
                elif part.lower() not in (g.lower() for g in gained):
                    gained.append(part[0].lower() + part[1:] if not part.isupper() else part)
            bite = int(attack.replace("–", "-"))
            weapons = by_size[size]
            forms = [f"Bite {_signed(bite)} melee ({_dice(weapons['bite'], strength)})"]
            heavy = strength * 3 // 2
            for label, key, bonus in (("2 claws", "claw", strength // 2), ("2 wings", "wing", strength // 2),
                                      ("tail slap", "tail slap", heavy)):  # fmt: skip
                if weapons[key]:
                    forms.append(f"{label} {_signed(bite - SECONDARY)} melee ({_dice(weapons[key], bonus)})")
            damage, dc = re.fullmatch(r"(\S+) \((\d+)\)", breath).groups()
            shapes = [f"{lengths[size][shape].replace(' ft.', '-ft.')} {shape} of {what}" for shape, what in breaths]
            attacks = [f"breath weapon ({shapes[0]}, {damage}, DC {dc}"
                       + "".join(f"; or {shape}, DC {dc}" for shape in shapes[1:]) + ")"]  # fmt: skip
            if weapons["crush"]:
                attacks.append(f"crush ({_dice(weapons['crush'], heavy)}, DC {dc})")
            if weapons["tail sweep"]:
                attacks.append(f"tail sweep ({_dice(weapons['tail sweep'], heavy)}, DC {dc})")
            if presence != "—":
                attacks.append(f"frightful presence (DC {presence})")
            sla = [g for g in gained if g.lower() in spell_like]
            if sla:
                attacks.append(f"spell-like abilities ({', '.join(sla)})")
            if caster != "—":
                attacks.append(f"spells (caster level {caster})")
            immunities = [*immune, "sleep", "paralysis"]
            qualities = ["blindsense 60 ft.", "darkvision 120 ft.", "keen senses", "low-light vision",
                         f"immunity to {', '.join(immunities[:-1])}, and {immunities[-1]}",
                         *(g for g in gained if g not in sla)]  # fmt: skip
            if dr:
                qualities.append(dr)
            if sr != "—":
                qualities.append(f"spell resistance {sr}")
            special_qualities = scrubbed(", ".join(qualities))
            special_qualities = special_qualities[0].upper() + special_qualities[1:]
            ac = re.fullmatch(r"(.*?),\s*touch\s+(\d+),\s*flat-footed\s+(\d+)", armour)
            hp = re.search(r"\((\d+)\)", hit_dice)
            variant = name(age, colour)
            row_out: dict[str, Any] = {
                "abilities": dict(zip(("str", "dex", "con", "int", "wis", "cha"), scores, strict=True)),
                "advancement": _by_age(fields.get("Advancement", ""), age),
                "alignment": fields.get("Alignment", ""),
                "armor_class": ac.group(1).strip(),
                "attack": forms[0],
                "base_attack_grapple": bab,
                "cr": _by_age(fields.get("Challenge Rating", ""), age),
                "environment": fields.get("Environment", ""),
                "feats": "",
                "flat_footed": ac.group(3),
                "full_attack": " and ".join(forms),
                "hit_dice": hit_dice.split(" (")[0],
                "hp": int(hp.group(1)) if hp else None,
                "id": slug(variant),
                "initiative": int(initiative.replace("–", "-")),
                "languages": "",
                "level_adjustment": _by_age(fields.get("Level Adjustment", ""), age),
                "name": variant,
                "organization": fields.get("Organization", ""),
                "saves": {"fort": fort, "ref": ref, "will": will},
                "senses": [],
                "size": size,
                "skills": {},
                "space_reach": weapons["space_reach"],
                "special_attacks": scrubbed(", ".join(attacks)),
                "special_qualities": special_qualities,
                "speed": speed,
                "subtypes": [s.strip() for s in ",".join(subtypes).split(",") if s.strip()],
                "text": "",
                "touch": int(ac.group(2)),
                "treasure": fields.get("Treasure", ""),
                "type": "Dragon",
            }
            row_out.update(defences(special_qualities))
            out.append(row_out)
    return out


FAMILIES = (*(f"{colour} Dragon" for colour in COLOURS), "True Dragon", "Air Elemental", "Earth Elemental",
            "Fire Elemental", "Water Elemental", "Animated Object", "Hydra", "Arrowhawk", "Salamander", "Tojanida",
            "Xorn")  # fmt: skip
"""The SRD's entries whose stat block is a column per variant (by age, size, heads or grade): their parent rows stay
the reference entry, and each variant is a row of its own. The true dragon's variants are the ten colours."""
LEAST_VARIANTS = 3


def variants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows with each family's parent naming its variants, smallest first (by hit points): the rows with a full
    attack named "<variant> <family>" ("Young Red Dragon", "Five-headed Hydra", "Elder Xorn"); the true dragon's are
    the ten colours' parents. Only the families whose parent is among the rows; raises ValueError for one with fewer
    than `LEAST_VARIANTS`."""
    by_name = {row["name"]: row for row in rows}
    found: dict[str, list[str]] = {}
    for family in FAMILIES:
        if family == "True Dragon" or family not in by_name:
            continue
        ending = " " + family.lower()
        kin = [r for r in rows if r["name"].lower().endswith(ending) and str(r.get("full_attack") or "").strip()]
        found[family] = [r["name"] for r in sorted(kin, key=lambda r: (r.get("hp") or 0, r["name"]))]
    if "True Dragon" in by_name:
        found["True Dragon"] = [f"{colour} Dragon" for colour in COLOURS if f"{colour} Dragon" in found]
    out = []
    for row in rows:
        row = {key: value for key, value in row.items() if key != "variants"}
        if row["name"] in found:
            if len(found[row["name"]]) < LEAST_VARIANTS:
                raise ValueError(f"family {row['name']!r}: variants {found[row['name']]!r}")
            row["variants"] = found[row["name"]]
        out.append(row)
    return out
