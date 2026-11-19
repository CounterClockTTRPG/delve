"""A monster's attack line as attack forms (DEL-388): "Morningstar +2 melee (1d6) or javelin +3 ranged (1d4)" is two
forms, "2 claws +3 melee (1d4)" one form "claw" with `count` 2, "Falchion +4 melee (2d4+4/18–20)" one that threatens on
18. Each form is a `Combatant.d20["attacks"]` entry: `name`, `bonus` (the first attack of "+16/+11", "+ 22" too;
None only for a swarm's "Swarm (1d6)", which hits without a roll), `damage` (the
dice, "0" when the line has none or its dice aren't hit points, as "1d4 Wisdom drain"), `threat` (the lowest face
that threatens), `mult`, `count`, `touch`, `hands` (2 for a two-handed weapon of the SRD's table), `ranged`, and
`plus` when the damage has more to it ("1d4 acid", "disease") for the DM.

The alternatives ("or", ";") and the forms of one full attack ("and", ",") are all forms: the DM picks the one that
swings. The lines come with typographic signs and dashes ("+3", "–2", "18–20", "×3") or plain ones ("3", "-1",
"18-20", "x3"); both read."""

from __future__ import annotations

import re
from functools import cache
from typing import Any

from delve_srd35 import data
from delve_srd35.engine import numbers

_PLAIN = str.maketrans({"–": "-", "−": "-", "—": "-", "×": "x"})
_SEPARATOR = re.compile(r";|,(?!\s*\()|\bor\b|\band\b")
_FORM = re.compile(
    r"^(?:(?P<count>\d+)\s+)?(?P<name>.*?\S)\s*(?:(?P<bonus>[+-]\s?\d+)(?:/[+-]\s?\d+)*)?\s*(?P<kind>melee|ranged)?"
    r"(?:\s+(?P<touch>touch))?\s*,?\s*(?:\((?P<inner>[^()]*)\))?\s*$",
    re.IGNORECASE,
)
_DICE = re.compile(r"\d+d\d+(?:[+-]\d+)?|\d+")
_THREAT = re.compile(r"(\d+)-20")
_MULT = re.compile(r"x(\d+)", re.IGNORECASE)


def _pieces(text: str) -> list[str]:
    """The line split at its separators outside parentheses."""
    pieces, depth, start = [], 0, 0
    for found in re.finditer(r"[()]|" + _SEPARATOR.pattern, text):
        token = found.group()
        if token in "()":
            depth += 1 if token == "(" else -1
        elif depth == 0:
            pieces.append(text[start : found.start()])
            start = found.end()
    pieces.append(text[start:])
    return [p.strip() for p in pieces if p.strip()]


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


def _inner(text: str) -> tuple[str, int, int, str]:
    """The damage, threat, multiplier and the rest ("plus") of "2d4+4/18-20/x3 plus 1d6 cold"."""
    main, _, plus = text.partition(" plus ")
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
    forms, warnings = [], []
    for piece in _pieces(str(text or "").translate(_PLAIN).replace("*", "")):
        found = _FORM.match(piece)
        swarm = found is not None and found["name"].strip().lower() == "swarm" and found["inner"] is not None
        if found is None or found["bonus"] is None and not swarm:
            if re.search(r"[\d()]", piece):
                warnings.append(f"Unreadable attack '{piece}': left out; the DM rolls it.")
            continue
        count = int(found["count"] or 1)
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
        if plus:
            form["plus"] = plus
        forms.append(form)
    return forms, warnings
