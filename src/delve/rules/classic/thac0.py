"""THAC0 per attack (plateau 7): the sheet's THAC0 worked out for one of its attacks, part by part.

The sheet and the fight use the same number: the sheet shows `attack_thac0(...).value`, and `combat.start` gives it to
a PC's attack block, so the to-hit roll needs what the sheet shows. An attack's own stored `thac0` is the DM's
override and wins.

The parts, in order (each a THAC0 change; lower is better):
- `base`: the sheet's THAC0;
- `nonproficient`: the ruleset's penalty by class group when the sheet lists weapon proficiencies and none names
  the weapon, the smallest for a multi-class character;
- `specialised`: −1 when the matching proficiency says it is specialised;
- `strength`: minus Strength's hit probability (the reference's Strength table), for a melee attack;
- `dexterity`: instead, for a missile attack, minus Dexterity's missile attack adjustment. An attack is a
  missile attack when it has a `range`, or its name names a bow, crossbow, sling, dart or javelin, or says "thrown";
- `magic`: minus the weapon's own `+N`: not one in parentheses or after "vs", which counts only against some foes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from delve.domain.characters import Attack, Sheet
from delve.domain.reference import RulesetReference
from delve.rules.classic.encumbrance import parse_strength
from delve.rules.classic.tables import RuleTables

# The non-proficiency penalty to hit, as a THAC0 change.

_MAGIC = re.compile(r"\+\s*(\d+)")
_AGAINST = re.compile(r"(?:\+\s*\d+\s*)?\b(?:vs\b\.?|versus\b|against\b).*", re.IGNORECASE)
"""A bonus against some foes ("+3 vs undead") and all after it: not the weapon's own `+N`."""
_SIGNED = re.compile(r"^[+-]?\d+$")
_MISSILE = re.compile(r"\b(?:\w*bows?|crossbows?|slings?|darts?|javelins?|thrown|throwing)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Thac0:
    """An attack's THAC0 and the parts it adds up from, as (name, change); the first is `base` or `stored`."""

    value: int
    parts: list[tuple[str, int]] = field(default_factory=list)


def _weapon(name: str) -> str:
    """A weapon's name to compare: no `+N` or what it is against, no parentheses, nothing but letters and digits,
    lower case, and singular ("darts" is a dart)."""
    bare = _MAGIC.sub("", _AGAINST.sub("", re.sub(r"\(.*?\)", "", name)))
    plain = re.sub(r"[^\w]|_", "", bare).casefold()
    return plain.removesuffix("s")


def _proficiency(sheet: Sheet, attack: Attack) -> str | None:
    """The `weapon_profs` entry naming the attack's weapon, or None. The names must be the same weapon: a part of a
    name isn't, as a bow is not a crossbow, nor a sword a two-handed sword."""
    wanted = _weapon(attack.name)
    for entry in sheet.weapon_profs:
        if wanted and _weapon(entry) == wanted:
            return entry
    return None


def _magic(name: str) -> int:
    """The weapon's own `+N`: the first outside parentheses and not part of a "vs" clause; 0 when it has none."""
    found = _MAGIC.search(_AGAINST.sub("", re.sub(r"\(.*?\)", "", name)))
    return int(found.group(1)) if found else 0


def _penalty(sheet: Sheet, rules: RuleTables) -> int:
    """The smallest non-proficiency penalty of the sheet's classes; 0 when none of them is known."""
    classes = [re.sub(r"\d+", "", c) for c in sheet.cls.split("/")] + list(sheet.levels)
    penalties = [rules.nonproficient[g] for c in classes if (g := rules.class_group(c)) in rules.nonproficient]
    return min(penalties, default=0)


def is_missile(attack: Attack) -> bool:
    """Whether `attack` is a missile attack: it has a range, or its name names a missile weapon."""
    return bool(attack.range) or _MISSILE.search(attack.name) is not None


def _signed(found: dict, column: str) -> int:
    value = str((found.get("values") or {}).get(column, "")).strip()
    return int(value) if _SIGNED.match(value) else 0


def _dexterity_missile(sheet: Sheet, reference: RulesetReference) -> int:
    """Dexterity's missile attack adjustment from the reference; 0 without a score or a row for it."""
    raw = sheet.ability_scores.get("dex")
    return 0 if raw is None else _signed(reference.ability("dex", str(raw).strip()), "missile_adj")


def _strength_hit(sheet: Sheet, reference: RulesetReference) -> int:
    """Strength's hit probability from the reference; 0 without a score or a row for it."""
    raw = sheet.ability_scores.get("str")
    if raw is None:
        return 0
    score, pct = parse_strength(raw, sheet.ability_scores.get("str_pct"))
    return _signed(reference.ability("str", f"18/{pct % 100:02d}" if pct else str(score)), "hit_prob")


def attack_thac0(sheet: Sheet, attack: Attack, reference: RulesetReference, *, rules: RuleTables) -> Thac0:
    """The THAC0 `attack` hits with, worked out from the sheet; the attack's stored `thac0` when it has one."""
    if attack.thac0 is not None:
        return Thac0(int(attack.thac0), [("stored", int(attack.thac0))])
    parts: list[tuple[str, int]] = [("base", sheet.thac0)]
    proficiency = _proficiency(sheet, attack)
    if sheet.weapon_profs and proficiency is None and (penalty := _penalty(sheet, rules)):
        parts.append(("nonproficient", penalty))
    if proficiency is not None and "special" in proficiency.casefold():
        parts.append(("specialised", -1))
    if is_missile(attack):
        if dexterity := _dexterity_missile(sheet, reference):
            parts.append(("dexterity", -dexterity))
    elif strength := _strength_hit(sheet, reference):
        parts.append(("strength", -strength))
    if magic := _magic(attack.name):
        parts.append(("magic", -magic))
    return Thac0(sum(change for _, change in parts), parts)
