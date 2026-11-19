"""Saves, skill checks and ability checks under 3.5 (DEL-388): a d20 plus the total plus the modifier, against a DC.

A save's total is the sheet's derived save, or a combatant's `d20["saves"]`; a natural 1 always fails it and a natural
20 always succeeds. A skill's total is its derived total, or untrained its key ability's modifier with the armour check
penalty and the race's and size's bonuses (`numbers` works it out with no ranks); a trained-only skill without ranks is
refused with a note and no roll, and a natural 1 or 20 is just a number. Each negative level takes 1 off all three (the
SRD's energy drain); `derived` doesn't take them, so it is done here. Without a DC the answer is the total, no success.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from delve.dice import Roll
from delve.domain.characters import Sheet
from delve.rules.classic.checks import CheckError
from delve.rules.classic.combat import Combatant
from delve.rules.d20 import CheckResult, SaveResult
from delve_srd35.engine import numbers

if TYPE_CHECKING:
    from delve.dice import Dice

SAVES = {"fort": "Fortitude", "ref": "Reflex", "will": "Will"}
ABILITIES = {"str": "strength", "dex": "dexterity", "con": "constitution", "int": "intelligence", "wis": "wisdom",
             "cha": "charisma"}  # fmt: skip


@dataclass(frozen=True)
class Save(SaveResult):
    """A 3.5 save: `base` is the save total, `modifier` the modifier given less the negative levels."""

    needed: int | None  # type: ignore[assignment]
    """The d20 face needed; None without a DC."""
    total: int
    """The d20 plus `base` plus `modifier`."""
    dc: int | None


@dataclass(frozen=True)
class Check(CheckResult):
    """A 3.5 skill or ability check: `bonus` is the skill total or ability modifier, `modifier` the modifier given less
    the negative levels. A refused check has a `note` and no roll."""

    needed: int | None  # type: ignore[assignment]
    """The d20 face needed; None without a DC or when refused."""
    roll: Roll | None  # type: ignore[assignment]
    bonus: int
    modifier: int
    total: int | None
    dc: int | None
    note: str = ""

    @property
    def all_rolls(self) -> tuple[Roll, ...]:
        return () if self.roll is None else (self.roll,)


def _negative(sheet: Sheet) -> int:
    return int((sheet.d20 or {}).get("negative_levels", 0))


def _occasion(purpose: str, occasion: str) -> str:
    return f"{purpose}#{occasion}" if occasion else purpose


def save_type(text: str) -> str:
    """The save, "fort", "ref" or "will", for any of their names ("Fortitude", "reflex", "Will")."""
    wanted = text.strip().lower()
    found = next((kind for kind, name in SAVES.items() if wanted in (kind, name.lower())), None)
    if found is None:
        raise CheckError(f"Unknown save '{text}'.", hint="Use fort, ref or will.", candidates=SAVES)
    return found


def save(
    subject: Sheet | Combatant,
    kind: str,
    dc: int | None,
    modifier: int,
    dice: Dice,
    reference: Any,
    *,
    actor: str,
    combat_round: int | None = None,
) -> Save:
    kind = save_type(kind)
    if isinstance(subject, Sheet):
        base = int(((subject.d20 or {}).get("derived") or numbers.derived(subject, reference))[kind])
        modifier -= _negative(subject)
        basis = f"sheet: {SAVES[kind]} {base:+d}"
    else:
        saves = (subject.d20 or {}).get("saves")
        if not saves or kind not in saves:
            raise CheckError(f"{subject.name} has no saves.", hint="Add it to the fight from a monster or a sheet.")
        base = int(saves[kind])
        basis = f"combatant: {SAVES[kind]} {base:+d}"
    roll = dice.d(20, purpose=f"save:{kind}", actor=actor, combat_round=combat_round)
    total = roll.total + base + modifier
    success = dc is not None and roll.total != 1 and (roll.total == 20 or total >= dc)
    needed = None if dc is None else dc - base - modifier
    return Save(success, needed, roll, kind, SAVES[kind], base, modifier, basis, total, dc)


def _check(
    dice: Dice, purpose: str, name: str, bonus: int, dc: int | None, modifier: int, actor: str, occasion: str
) -> Check:
    roll = dice.d(20, purpose=_occasion(purpose, occasion), actor=actor)
    total = roll.total + bonus + modifier
    needed = None if dc is None else dc - bonus - modifier
    return Check(dc is not None and total >= dc, needed, roll, name, bonus, modifier, total, dc)


def skill_check(
    sheet: Sheet, skill: str, dc: int | None, modifier: int, dice: Dice, reference: Any, *, actor: str, occasion: str
) -> Check:
    build = sheet.d20 or {}
    ranked = [name for name, ranks in build.get("skills", {}).items() if ranks]
    wanted = numbers.skill_named(reference, skill, ranked)
    row = numbers.skill_row(reference, wanted)
    assert row is not None  # skill_named names only skills that have a row
    modifier -= _negative(sheet)
    if build.get("skills", {}).get(wanted, 0) > 0:
        known = (build.get("derived") or {}).get("skills", {})
        bonus = known[wanted] if wanted in known else numbers.derived(sheet, reference)["skills"][wanted]
    elif row["trained_only"]:
        note = f"{row['name']} can't be used untrained: {sheet.label or 'the character'} has no ranks in it."
        return Check(False, None, None, row["name"], 0, modifier, None, dc, note)
    else:
        untrained = replace(sheet, d20={**build, "skills": {wanted: 0}})
        bonus = numbers.derived(untrained, reference)["skills"][wanted]
    return _check(dice, f"skill:{wanted}", row["name"], int(bonus), dc, modifier, actor, occasion)


def ability_check(
    sheet: Sheet, ability: str, dc: int | None, modifier: int, dice: Dice, *, actor: str, occasion: str
) -> Check:
    wanted = ability.strip().lower()
    short = next((key for key, name in ABILITIES.items() if wanted in (key, name)), None)
    if short is None:
        raise CheckError(
            f"Unknown ability '{ability}'.", hint="Use str, dex, con, int, wis or cha.", candidates=ABILITIES
        )
    bonus = numbers.modifier(numbers.ability_score(sheet, short))
    return _check(dice, f"ability:{short}", short, bonus, dc, modifier - _negative(sheet), actor, occasion)
