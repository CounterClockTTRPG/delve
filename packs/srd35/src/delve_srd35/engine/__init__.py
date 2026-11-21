"""The 3.5 rules engine (DEL-388): SRD 3.5's `delve.rules.d20.D20Engine`, delegating to one module per job. The
character's numbers are in `numbers`, its levels, XP, drain and rest in `progress`, its saves and checks in `checks`,
its fights in `combat`, its spells and turning in `magic`, animal companions, mounts and wild shape's forms in
`companions`, and the DM's 3.5 tools in `tools`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from fractions import Fraction
from typing import TYPE_CHECKING, Any

from delve.domain.characters import CharacterState, Sheet
from delve.domain.reference import RulesetReference
from delve.rules.classic.combat import Combatant
from delve.rules.classic.tables import FightRules
from delve.rules.d20 import CheckResult, HitDie, Initiative, Progress, SaveResult, Swing
from delve_srd35.data import load
from delve_srd35.engine import checks, combat, magic, numbers, progress
from delve_srd35.reference import Srd35Reference
from delve_srd35.tables import slowed

if TYPE_CHECKING:
    from delve.dice import Dice
    from delve.domain.campaigns import Character

PROMPT_TERMS = {"attack_number": "attack bonus against AC", "saves_list": "Fortitude, Reflex and Will against a DC"}
CLASSIC_RATE = Sheet.__dataclass_fields__["movement_rate"].default
"""Core's default movement rate, a classic one (12): no 3.5 speed, so a sheet that has it hasn't been given one."""
SHEET_NUMBERS = ("bab", "fort", "ref", "will", "ac", "touch", "flat_footed", "init", "skills")
FEATURE_KEYS = ("id", "class", "name", "kind", "per_day", "per", "value", "spends", "elemental_per_day")
"""A granted feature's keys the sheet shows (`numbers.derived`'s `features` has its condition, target … too); `per`
only on a feature counted a week ("week"), `spends` on one that spends another's uses (each bardic music performance),
`elemental_per_day` on a druid's wild shape from 16th."""


def spell_slots(found: Mapping[str, Any]) -> dict[int, int]:
    """`Sheet.spell_slots` from derived numbers: by spell level, the sum of the prepared classes' slots (a cleric's
    domain slots in them); derived numbers without `casting` (a companion's) give their own `slots`."""
    pools = [entry["slots"] for entry in found.get("casting", {}).values() if entry.get("prepared")]
    if "casting" not in found:
        pools = [found["slots"]]
    out: dict[int, int] = {}
    for pool in pools:
        for level, count in pool.items():
            out[int(level)] = out.get(int(level), 0) + count
    return dict(sorted(out.items()))


class Srd35Engine:
    def __init__(self, reference: Srd35Reference) -> None:
        self.reference = reference

    def fill_derived(self, sheet: Sheet, reference: Any) -> Sheet:
        """The sheet with its derived numbers in `d20["derived"]` and its slots in `spell_slots` (the sum of its
        prepared classes' pools, `derived["casting"]`, DEL-389); the build (skills, feats, domains, weapon, armour,
        shield) is kept. Its `movement_rate` is the race's speed in feet in the armour worn while it is core's classic
        default or the speed the race and armour gave before (so a new race's or armour's follows); one the DM set
        stays (DEL-404, DEL-407). A companion's are its animal's (`combat.companion_derived`, DEL-389)."""
        found = combat.companion_derived(sheet, reference) or numbers.derived(sheet, reference)
        slots = spell_slots(found)
        before = ((sheet.d20 or {}).get("derived") or {}).get("speed")
        speed = sheet.movement_rate
        if found.get("speed") and speed in (CLASSIC_RATE, before):
            speed = found["speed"]
        return replace(sheet, d20={**(sheet.d20 or {}), "derived": found}, spell_slots=slots, movement_rate=speed)

    def sheet_numbers(self, sheet: Sheet) -> dict[str, Any]:
        build = sheet.d20 or {}
        found = numbers.stored(sheet, self.reference)
        out = {
            **{key: found[key] for key in SHEET_NUMBERS},
            "feats": list(build.get("feats", [])),
            "domains": list(build.get("domains", [])),
            "slots": found["slots"],
            "dc": found["dc"],
            # The granted class features with their uses a day (DEL-389); the uses spent are the state's `d20["used"]`,
            # which `character_json` sends with the state: this has the sheet alone.
            "features": [{key: f[key] for key in FEATURE_KEYS if key in f} for f in found.get("features", ())],
        }
        if found.get("items"):  # the magic items with their bonuses (DEL-389 part 3), only a sheet that has some
            out["items"] = found["items"]
        if found.get("abilities"):  # the scores with the items' enhancement, those it changes
            out["abilities"] = found["abilities"]
        # The prestige classes (DEL-389 part 4), which the sheet marks, and the caster levels they add to each casting
        # class; a single prepared caster advanced has its pool then, headed by where its caster level comes from.
        if prestige := [numbers.slug(c) for c, n in sheet.levels.items() if n and self._prestige(c)]:
            out["prestige"] = prestige
        if advanced := numbers.advanced_by(sheet):
            out["advanced"] = advanced
        casting = found.get("casting") or {}
        if len(casting) > 1 or advanced or any(not entry.get("prepared") for entry in casting.values()):
            # Every pool (DEL-389): a multiclass caster's, whose `slots` are its first class's alone, and a sorcerer's
            # or bard's spells a day and known; the spells it knows by name, and cast today (the state's `d20["cast"]`).
            out["casting"] = casting
            if build.get("known"):
                out["known"] = build["known"]
        if build.get("companion_of"):  # its master's (DEL-389): the digest and primer show it so, not as a classless PC
            out.update(companion_of=build["companion_of"], animal=build.get("animal", ""), hit_dice=found.get("hit_dice"))
        return out

    def _prestige(self, cls: str) -> bool:
        return (self.reference.char_class(numbers.slug(cls)) or {}).get("type") == "prestige"

    def prompt_terms(self) -> Mapping[str, str]:
        return PROMPT_TERMS

    def loaded_speed(self, sheet: Sheet, band: str, speed: int) -> int | None:
        """The speed itself under a medium or heavy load (core's "moderate" and "heavy") for a race whose trait says it
        moves at its speed with one, the dwarf's. In armour that slows (the sheet at its derived speed, with the
        unarmoured `base_speed` beside it), the worse of the armour's speed and the load's from the unarmoured one:
        "use the worse figure (from armor or from load) ... Do not stack the penalties" (Encumbrance by Armor,
        DEL-407). None, the pack's reduced speeds (`tables.slowed`) from `speed`, otherwise (a speed the DM set)."""
        if band in ("moderate", "heavy") and numbers.unslowed(numbers.race_named(self.reference, sheet.race)):
            return speed
        found = numbers.stored(sheet, self.reference)
        if (base := found.get("base_speed")) and speed == found.get("speed"):
            return min(speed, slowed(band, base))
        return None

    def load_multiplier(self, sheet: Sheet) -> float:
        """Bigger and Smaller Creatures' multiplier for the race's size, as a biped (Small ×3/4); 1 for a Medium race
        and for one the SRD doesn't have (DEL-399)."""
        race = numbers.race_named(self.reference, sheet.race) or {}
        return float(Fraction(load("carrying")["sizes"].get(race.get("size", ""), "1")))

    # Levels, XP, drain and rest (`progress`).
    def level_up(self, sheet: Sheet, cls: str, reference: RulesetReference, dice: Dice) -> Sheet:
        """One more level in `cls`, with the numbers filled again for the new level and the sheet's scores as they are
        now: core's update calls only this on a patch that raises a level, also when it changes the scores. Each
        prepared casting class has its own pool of slots and DCs (`numbers`, `derived["casting"]`)."""
        return self.fill_derived(progress.level_up(sheet, cls, reference, dice), reference)

    def award_xp(self, sheet: Sheet, state: CharacterState, amount: int) -> CharacterState:
        return progress.award_xp(sheet, state, amount, self.reference)

    def progress(self, sheet: Sheet, state: CharacterState, reference: RulesetReference) -> Progress:
        return progress.progress(sheet, state, reference)

    def drain(
        self, sheet: Sheet, state: CharacterState, levels: int, reference: RulesetReference, dice: Dice
    ) -> tuple[Sheet, CharacterState, dict[str, Any]]:
        after, state, said = progress.drain(sheet, state, levels)
        return self.fill_derived(after, reference), state, said

    def rest(
        self, sheet: Sheet, state: CharacterState, days: int, *, bed_rest: bool = False
    ) -> tuple[CharacterState, dict[str, Any]]:
        return progress.rest(sheet, state, days, bed_rest=bed_rest)

    def xp_for_defeated(self, combatant: Combatant, party_levels: Sequence[int]) -> int | None:
        """The award by the combatant's CR, the same whatever the party's levels (Unearthed Arcana's)."""
        return progress.xp_for_defeated(combatant)

    # Saves and checks (`checks`).
    def save(
        self,
        subject: Sheet | Combatant,
        save_type: str,
        dc: int | None,
        modifier: int,
        dice: Dice,
        *,
        actor: str,
        combat_round: int | None = None,
    ) -> SaveResult:
        return checks.save(
            subject, save_type, dc, modifier, dice, self.reference, actor=actor, combat_round=combat_round
        )

    def skill_check(
        self, sheet: Sheet, skill: str, dc: int | None, modifier: int, dice: Dice, *, actor: str, occasion: str
    ) -> CheckResult:
        return checks.skill_check(sheet, skill, dc, modifier, dice, self.reference, actor=actor, occasion=occasion)

    def ability_check(
        self, sheet: Sheet, ability: str, dc: int | None, modifier: int, dice: Dice, *, actor: str, occasion: str
    ) -> CheckResult:
        return checks.ability_check(sheet, ability, dc, modifier, dice, actor=actor, occasion=occasion)

    # Combat (`combat`).
    def combatant_from_sheet(self, character: Character, combatant: Combatant) -> Combatant:
        return combat.combatant_from_sheet(character, combatant, self.reference)

    def combatant_from_monster(
        self, row: Mapping[str, Any], combatant: Combatant, overrides: Mapping[str, Any]
    ) -> Combatant:
        return combat.combatant_from_monster(row, combatant, overrides)

    def read_hit_dice(self, line: str) -> tuple[HitDie, ...] | None:
        return combat.read_hit_dice(line)

    def swing(
        self, attacker: Combatant, target: Combatant, condition: str, dice: Dice, combat_round: int, fight: FightRules
    ) -> Swing:
        """The attack by 3.5's rules; the fight's classic rules (`fight`) play no part."""
        return combat.swing(attacker, target, condition, dice, combat_round)

    def nonlethal_state(self, c: Combatant) -> str | None:
        """The SRD's Nonlethal Damage: "when your nonlethal damage equals your current hit points, you're staggered,
        and when it exceeds your current hit points, you fall unconscious" (DEL-421)."""
        return combat.nonlethal_state(c)

    def initiative(self, combatant: Combatant, dice: Dice, combat_round: int) -> Initiative:
        return combat.initiative(combatant, dice, combat_round)

    # Spells and turning (`magic`).
    def cast(
        self,
        sheet: Sheet,
        state: CharacterState,
        spell: str,
        level: int,
        dice: Dice | None = None,
        *,
        actor: str | None = None,
        unprepared: bool = False,
    ) -> tuple[CharacterState, dict[str, Any]]:
        """A prepared spell's cast, after core has spent the copy, or a sorcerer's or bard's from its spells a day:
        arcane spell failure in armour, else the DC."""
        return magic.cast(sheet, state, spell, level, dice, self.reference, actor=actor, unprepared=unprepared)

    def can_memorize(self, sheet: Sheet, levels: Iterable[int], spells: Sequence[str] = ()) -> str | None:
        return magic.can_memorize(sheet, levels, spells, self.reference)

    def casts_unprepared(self, sheet: Sheet, spell: str) -> bool:
        """True for a spell a sorcerer or bard of the sheet knows: core casts it from that class's spells a day when no
        uncast copy is memorized (DEL-389)."""
        return magic.casts_unprepared(sheet, spell, self.reference)

    def spell_level(self, sheet: Sheet, name: str) -> int | None:
        return magic.spell_level(sheet, name, self.reference)

    def turn_undead(
        self,
        sheet: Sheet | None,
        level: int,
        undead: str,
        hd: int,
        dice: Dice,
        *,
        actor: str | None,
        state: CharacterState | None = None,
    ) -> dict[str, Any]:
        return magic.turn_undead(sheet, level, undead, hd, dice, self.reference, actor=actor, state=state)

    # The DM's tools (`tools`), imported only when a campaign first asks: they reach into core's DM tools and play.
    def tools(self) -> list[Any]:
        from delve_srd35.engine import tools

        return tools.specs()
