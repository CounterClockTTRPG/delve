"""A monster's attack line as attack forms (DEL-388): "Morningstar +2 melee (1d6) or javelin +3 ranged (1d4)" is two
forms, "2 claws +3 melee (1d4)" one form "claw" with `count` 2, "Falchion +4 melee (2d4+4/18–20)" one that threatens on
18. Each form is a `Combatant.d20["attacks"]` entry: `name`, `bonus` (the first attack of "+16/+11", "+ 22" too;
None only for a swarm's "Swarm (1d6)", which hits without a roll), `damage` (the
dice, "0" when the line has none or its dice aren't hit points, as "1d4 Wisdom drain"), `threat` (the lowest face
that threatens), `mult`, `count`, `touch`, `hands` (2 for a two-handed weapon of the SRD's table), `ranged`, and
`plus` when the damage has more to it ("1d4 acid", "disease") for the DM. Iterative attacks ("+16/+11", each 5 below
the one before) are the form's `count`, marked `iterative`, as a character's weapon form is.

The alternatives ("or", ";") and the forms of one full attack ("and", ",") are all forms: the DM picks the one that
swings. The lines come with typographic signs and dashes ("+3", "–2", "18–20", "×3") or plain ones ("3", "-1",
"18-20", "x3"); both read."""

from __future__ import annotations

import re
from functools import cache
from itertools import pairwise
from typing import Any

from delve_srd35 import data
from delve_srd35.engine import numbers

_PLAIN = str.maketrans({"–": "-", "−": "-", "—": "-", "×": "x"})
_SEPARATOR = re.compile(r";|,(?!\s*\()|\bor\b|\band\b")
_FORM = re.compile(
    r"^(?:(?P<count>\d+)\s+)?(?P<name>.*?\S)\s*(?:(?P<bonus>[+-]\s?\d+)(?P<more>(?:/[+-]\s?\d+)*))?\s*"
    r"(?P<kind>melee|ranged)?"
    r"(?:\s+(?P<touch>touch))?\s*,?\s*(?:\((?P<inner>[^()]*)\))?\s*$",
    re.IGNORECASE,
)
_DICE = re.compile(r"\d+d\d+(?:[+-]\d+)?|\d+")
_THREAT = re.compile(r"(\d+)-20")
_MULT = re.compile(r"x(\d+)", re.IGNORECASE)


def _pieces(text: str) -> list[tuple[str, int]]:
    """The line split at its separators outside parentheses, each piece with the number of its alternative (the
    pieces between one "or" or ";" and the next are one full attack)."""
    pieces, depth, start, alternative = [], 0, 0, 0
    for found in re.finditer(r"[()]|" + _SEPARATOR.pattern, text):
        token = found.group()
        if token in "()":
            depth += 1 if token == "(" else -1
        elif depth == 0:
            pieces.append((text[start : found.start()].strip(), alternative))
            start = found.end()
            alternative += token.strip().lower() in (";", "or")
    pieces.append((text[start:].strip(), alternative))
    return [(p, at) for p, at in pieces if p]


def singular(name: str) -> str:
    """The singular of a natural weapon's plural: "claws" → "claw", "hooves" → "hoof", "tentacles" → "tentacle"."""
    if name.endswith("ves"):
        return name[:-3] + "f"
    if name.endswith("ies"):
        return name[:-3] + "y"
    if re.search(r"(?:s|x|ch|sh)es$", name):
        return name[:-2]
    return name[:-1] if name.endswith("s") and not name.endswith("ss") else name


@cache
def _weapons() -> dict[str, dict[str, Any]]:
    """The SRD's weapons by slug of their id and of their name as said ("Crossbow, light" is "light-crossbow")."""
    table = {}
    for row in data.load("weapons"):
        said = " ".join(reversed([part.strip() for part in row["name"].split(",")]))
        for key in (row["id"], numbers.slug(row["name"]), numbers.slug(said)):
            table.setdefault(key, row)
    return table


def weapon(name: str) -> dict[str, Any] | None:
    """The weapon row for a name ("warhammer", "light crossbow", "Sword, short"), or for a form whose name ends in
    one ("+1 greatclub", "huge frost greataxe"); None for a natural weapon or an unknown name."""
    key = numbers.slug(name)
    table = _weapons()
    if key in table:
        return table[key]
    found = [k for k in table if key.endswith("-" + k)]
    return table[max(found, key=len)] if found else None


SIZES = ("fine", "diminutive", "tiny", "small", "medium", "large", "huge", "gargantuan", "colossal")
TINY = {"1d3": "1", "1d4": "1d2", "1d6": "1d3", "1d8": "1d4", "1d10": "1d6", "1d12": "1d8", "2d4": "1d4", "2d6": "1d8",
        "2d8": "1d10", "2d10": "2d6"}  # fmt: skip
LARGE = {"1d2": "1d3", "1d3": "1d4", "1d4": "1d6", "1d6": "1d8", "1d8": "2d6", "1d10": "2d8", "1d12": "3d6",
         "2d4": "2d6", "2d6": "3d6", "2d8": "3d8", "2d10": "4d8"}  # fmt: skip
"""The SRD's Table: Tiny and Large Weapon Damage (Equipment, "Damage"): a Medium weapon's damage as a Tiny and as a
Large weapon's (the Small one is the weapons table's own column; a Tiny 1d2 is "—", none)."""
STEP_UP = {"1d2": "1d3", "1d3": "1d4", "1d4": "1d6", "1d6": "1d8", "1d8": "2d6", "1d10": "2d8", "2d6": "3d6",
           "2d8": "3d8"}  # fmt: skip
"""The SRD's Table: Increased Damage By Size (Improving Monsters), repeated for each size category beyond Large."""
PROGRESSIONS = (("1d2", "1d3", "1d4", "1d6", "1d8", "2d6", "3d6", "4d6", "6d6", "8d6", "12d6"),
                ("1d10", "2d8", "3d8", "4d8", "6d8", "8d8", "12d8"))  # fmt: skip
"""The SRD's Improved Natural Attack (Monster Feats): damage "increases by one step, as if the creature's size had
increased by one category", along these two progressions; they go on where Table: Increased Damage By Size stops."""
STEP = {**{a: b for chain in PROGRESSIONS for a, b in pairwise(chain)}, **STEP_UP}
"""One size step up of a damage: Table: Increased Damage By Size, then the progressions beyond it."""
STEP_DOWN = {after: before for before, after in STEP.items()}
"""The same steps backwards: a natural weapon's damage without Improved Natural Attack."""


def size_of(name: str) -> str | None:
    """The size word a weapon's name gives ("large longsword", "+1 Huge greataxe"); None without one."""
    return next((word for word in numbers.slug(name).split("-") if word in SIZES), None)


def sized(row: dict[str, Any], size: str) -> tuple[str, str | None]:
    """The weapon's damage (its first head's) as a weapon of `size`, and a note where the SRD's tables don't go that
    far: Small and Medium from the weapons table, Tiny and Large from Table: Tiny and Large Weapon Damage, Huge and up
    the Large damage stepped once a size (`STEP`: Table: Increased Damage By Size, then Improved Natural Attack's
    progressions); Diminutive and Fine as Tiny, said."""
    medium = str(row["damage_m"]).split("/")[0]
    if size == "small":
        return str(row["damage_s"]).split("/")[0], None
    if size in ("medium", ""):
        return medium, None
    if size in ("tiny", "diminutive", "fine"):
        die = TINY.get(medium)
        if die is None:
            return "1", f"A Tiny {row['name'].lower()} has no damage in the SRD's table: 1."
        said = None if size == "tiny" else f"The SRD gives no damage below Tiny: a {size} weapon as a Tiny one, {die}."
        return die, said
    die = LARGE.get(medium, medium)
    for _ in range(SIZES.index(size) - SIZES.index("large")):
        if die not in STEP:
            return die, f"The SRD's tables stop at {die}: a {size} {row['name'].lower()} deals {die}, unless ruled."
        die = STEP[die]
    return die, None


_TWO = re.compile(r"^(\d+d\d+(?:[+-]\d+)?(?:/[^,]*)?)\s*(,|\band\b)\s*(.+)$", re.IGNORECASE)
"""A die and more beside it: an energy joined by "and" ("1d3 and 1d4 fire", the fire mephit's claw), or the next
attacks' values after a comma ("1d4+2, 1d4+1", the xill's claws): the first die is the form's."""


def _inner(text: str) -> tuple[str, int, int, str]:
    """The damage, threat, multiplier and the rest ("plus") of "2d4+4/18-20/x3 plus 1d6 cold"; "1d3 and 1d4 fire" is
    1d3 plus 1d4 fire, and of "1d4+2, 1d4+1" the first is the form's (`_TWO`)."""
    main, _, plus = text.partition(" plus ")
    if both := _TWO.match(main.strip()):
        main = both.group(1)
        if both.group(2).lower() == "and":
            plus = f"{both.group(3)} plus {plus}" if plus else both.group(3)
    tokens = [t.strip() for t in main.split("/")]
    damage, threat, mult = "0", 20, 2
    if _DICE.fullmatch(tokens[0].replace(" ", "")):
        damage = tokens[0].replace(" ", "")
    elif tokens[0]:
        plus = f"{tokens[0]} plus {plus}" if plus else tokens[0]
    for token in tokens[1:]:
        if found := _THREAT.fullmatch(token):
            threat = int(found.group(1))
        elif found := _MULT.fullmatch(token):
            mult = int(found.group(1))
    return damage, threat, mult, plus.strip()


def parse(text: str) -> list[dict[str, Any]]:
    """The attack forms of a line (`read`'s forms)."""
    return read(text)[0]


def read(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """The attack forms of a line, and a warning for each piece with numbers in it that reads as no form (no bonus
    outside a swarm's "Swarm (1d6)"): such a piece is left out, never swung. A piece without numbers ("—",
    "Breath weapon") is no attack and says nothing."""
    read_out, warnings = _read(text)
    return [form for form, _ in read_out], warnings


def alternatives(text: str) -> list[int]:
    """Each form's full attack, in `read`'s order: the number of its alternative (the forms between one "or" or ";"
    and the next are one full attack: "2 claws … and bite …" is [0, 0], "greatclub … or javelin …" [0, 1])."""
    return [alternative for _, alternative in _read(text)[0]]


def roles(text: str) -> list[str]:
    """Each form's part in its full attack, in `read`'s order (the SRD's natural attacks): "sole" for a creature's only
    natural attack in its full attack, one blow ("Bite +3 melee (1d6+1)": 1½ × Str); "secondary" for a natural attack
    beside a manufactured weapon, or below the best natural attack beside it ("2 claws +11 … and bite +6": the bite,
    −5 and ½ × Str); "weapon" for a manufactured weapon; "primary" for the rest."""
    read_out, _ = _read(text)
    groups: dict[int, list[dict[str, Any]]] = {}
    for form, alternative in read_out:
        groups.setdefault(alternative, []).append(form)
    out = []
    for form, alternative in read_out:
        group = groups[alternative]
        naturals = [f for f in group if natural(f)]
        if not natural(form):
            out.append("weapon")
        elif len(group) == 1:
            out.append("sole" if int(form["count"]) == 1 and not form.get("iterative") else "primary")
        elif len(naturals) < len(group):
            out.append("secondary")
        else:
            best = max(int(f["bonus"]) for f in naturals if f.get("bonus") is not None)
            out.append("secondary" if form.get("bonus") is not None and int(form["bonus"]) < best else "primary")
    return out


def natural(form: dict[str, Any]) -> bool:
    """A natural weapon's melee form: not a weapon of the SRD's table, a touch or a ranged attack."""
    return weapon(str(form["name"])) is None and not form["touch"] and not form["ranged"] and form["bonus"] is not None


_AFTER = re.compile(r"\)\s*(/[^()]*)$")
"""A critical printed after the parentheses: the pixie's "longbow +5 ranged (1d6–2)/x3"."""


def _read(text: str) -> tuple[list[tuple[dict[str, Any], int]], list[str]]:
    """The forms of a line, each with the number of its alternative (`_pieces`), and the warnings."""
    forms, warnings = [], []
    for raw, alternative in _pieces(str(text or "").translate(_PLAIN).replace("*", "")):
        piece = _AFTER.sub(r"\1)", raw)
        found = _FORM.match(piece)
        swarm = found is not None and found["name"].strip().lower() == "swarm" and found["inner"] is not None
        if found is None or found["bonus"] is None and not swarm:
            if re.search(r"[\d()]", piece):
                warnings.append(f"Unreadable attack '{raw}': left out; the DM rolls it.")
            continue
        count = int(found["count"] or 1)
        # "+16/+11": iterative attacks, one for each bonus, each 5 below the one before ("2 claws +17/+17" are the 2).
        bonuses = [found["bonus"], *found["more"].split("/")[1:]] if found["bonus"] is not None else []
        steps = [int(a.replace(" ", "")) - int(b.replace(" ", "")) for a, b in pairwise(bonuses)]
        iterative = bool(steps) and all(step == 5 for step in steps)
        if iterative:
            count = len(bonuses)
        name = found["name"].strip().lower()
        if count > 1:
            name = singular(name)
        damage, threat, mult, plus = _inner(found["inner"] or "")
        row = weapon(name)
        form = {
            "name": name,
            "bonus": None if found["bonus"] is None else int(found["bonus"].replace(" ", "")),
            "damage": damage,
            "threat": threat,
            "mult": mult,
            "count": count,
            "touch": bool(found["touch"]) or name.endswith("touch"),
            "hands": 2 if row is not None and row["kind"] == "two-handed" else 1,
            "ranged": (found["kind"] or "").lower() == "ranged",
        }
        if iterative:
            form["iterative"] = True
        if plus:
            form["plus"] = plus
        forms.append((form, alternative))
    return forms, warnings
