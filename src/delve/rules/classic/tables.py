"""The numbers a ruleset gives the classic engine (DEL-302): its saving throws, Constitution survival, reaction and
surprise dice, encounter checks and turning columns. The engine holds no ruleset's numbers; each ruleset fills a
`RuleTables` and the checks read the campaign's own."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from delve.rules.classic.encumbrance import EncumbranceTables
from delve.rules.classic.overland import TravelRates

SaveBands = tuple[tuple[int, tuple[int, ...]], ...]
"""Saving throws by level: (highest level of the band, the saves in `save_types` order). A level above the last band
uses the last band."""


@dataclass(frozen=True)
class LevelDrain:
    """How an energy drain takes a level (`play.characters.drain_level`)."""

    xp: str = "midpoint"
    """Where the XP drops: "midpoint", halfway between the new level's minimum and the next one's; "floor", the new
    level's minimum."""
    tie: str = "xp"
    """Which of a multi-class character's equal highest levels goes: "xp", the class needing more XP for it; or
    "random"."""
    zero_level: bool = True
    """Whether a character drained from 1st level lives on at 0-level, slain by the next drain, rather than dying at
    once."""


@dataclass(frozen=True)
class FightRules:
    """The ruleset's ways a fight keeps with it (`Combat.rules`), set when it starts: the defaults are the engine's
    own, which its first ruleset played."""

    automatic_naturals: bool = True
    """Whether a natural 20 always hits and a natural 1 always misses. Without them (OSRIC), a natural 20 counts as
    `natural_twenty`."""
    natural_twenty: int = 20
    """What a natural 20 counts as without automatic naturals: OSRIC's 25, the to-hit table's repeated 20s."""
    fleeing_bonus: int = 2
    """The to-hit bonus against a foe fleeing from melee."""
    fleeing_attack_free: bool = False
    """Whether the attack on a foe fleeing comes on top of the attacker's own (OSRIC: "even if they have already
    attacked")."""
    bleed_from_zero: bool = False
    """Whether a character at exactly 0 hp bleeds too (OSRIC), not only one below 0."""
    unconscious_slain_by_damage: bool = False
    """Whether any damage to an unconscious character kills it at once (OSRIC 1.6.6)."""


@dataclass(frozen=True)
class Healing:
    """Natural healing (`play.characters.rest`): the defaults are the engine's own."""

    per_day: int = 1
    bed_rest_per_day: int | None = 3
    """Hit points a day of complete bed rest; None for a ruleset without it (OSRIC: every rest is 1 a day)."""
    con_bonus: str = "bed_rest_weekly"
    """When the Constitution hit-point bonus is added: "bed_rest_weekly", each full week of bed rest; "second_week",
    once, over the second week of rest (OSRIC)."""
    con_penalty_delays: bool = False
    """Whether a Constitution hit-point penalty delays healing by that many days (OSRIC)."""
    full_after_days: int | None = None
    """Days of rest that heal anyone fully (OSRIC's four weeks); None for none."""


@dataclass(frozen=True)
class RuleTables:
    save_types: tuple[str, ...]
    """The saving throws in the ruleset's order. Sheets key their saves by these."""
    save_names: Mapping[str, str]
    """Each save type's name as the table reads it."""
    save_aliases: Mapping[str, str]
    """What a DM may call each save ("para", "bw"); every save type is its own alias."""
    save_short: tuple[str, ...]
    """The short names a refusal suggests, one per save type, in `save_types` order."""
    saves_by_group: Mapping[str, SaveBands]
    """The saves of each class group by level."""
    class_groups: Mapping[str, str]
    """Class names (lowercase, with kits and synonyms) onto their group of `saves_by_group`."""
    saves_source: str
    """Where the class saves come from, as a check cites it ("OSRIC class table")."""
    monster_save_group: str
    """The group a monster saves as, by its hit dice, when the ruleset has no table of monster saves of its own."""
    monster_saves: Mapping[str, SaveBands] | None
    """The monsters' own saves by Hit Dice, `intelligent` and `non_intelligent`; None to save as `monster_save_group`."""
    shock: Mapping[int, int]
    """System shock survival (%) by Constitution."""
    shock_default: int
    resurrect: Mapping[int, int]
    """Resurrection survival (%) by Constitution."""
    resurrect_default: int
    morale_roll: str
    """The dice of a morale check ("2d10", "1d100"): it holds at or under the rating."""
    initiative_die: int
    """The die each combatant or side rolls for initiative, lowest first."""
    weapon_speed_in_initiative: bool
    """Whether a weapon's speed adds to its wielder's initiative (a spell's casting time and an item's always do)."""
    reaction_roll: str
    """The dice of a reaction roll ("2d10"), read against `reaction_bands`."""
    reaction_bands: tuple[tuple[int, str, str], ...]
    """A reaction roll's bands: the highest total of each, then the band and what it means."""
    reaction_top: tuple[str, str]
    """The band above the last of `reaction_bands`."""
    disposition_step: int
    """How many points of disposition (-100…100) make one point of reaction modifier."""
    reputation_step: int
    """How many points of faction reputation (-100…100) make one point of reaction modifier."""
    surprise_die: int
    surprise_on: int
    """Each side rolls a d`surprise_die` and is surprised on 1…`surprise_on`."""
    encounter_checks: Mapping[str, Mapping[str, int]]
    """How often an encounter is checked, by kind of place: `die`, `threshold`, `interval_minutes`."""
    encounter_check_default: Mapping[str, int]
    turning_level_columns: tuple[str, ...]
    """The turning table's level columns: a level ("1"), a range ("10-11") or the last open one ("14+")."""
    class_aliases: Mapping[str, str]
    """Kits and synonyms (lowercase) onto the class whose XP table they use ("berserker": "Fighter")."""
    travel: TravelRates
    """The speeds of the modes of travel."""
    caster_classes: Mapping[str, tuple[str, ...]]
    """Each spell list ("priest", "wizard") with the class words that cast from it, for a spell on several lists."""
    encumbrance: EncumbranceTables
    """Item weights and the Strength bands of a load."""
    nonproficient: Mapping[str, int]
    """The THAC0 penalty of each class group for a weapon the character isn't proficient with."""
    mounts: Mapping[str, tuple[int, int, int, int, list[str], int]]
    """Mount species with their `(hp_max, ac, mv, thac0, attacks, morale)`."""
    mount_fly: Mapping[str, int]
    """The flying movement of the mounts that fly."""
    extra: Mapping[str, Any] = field(default_factory=dict)
    """Anything else a ruleset's own code reads."""
    level_drain: LevelDrain = LevelDrain()
    fight: FightRules = FightRules()
    healing: Healing = Healing()
    save_natural_one_fails: bool = False
    """Whether a natural 1 on a saving throw always fails (OSRIC)."""
    turning_counts: Mapping[str, tuple[str, str | None]] = field(
        default_factory=lambda: {"number": ("2d6", None), "T": ("2d6", None), "D": ("2d6", None), "D*": ("2d6", "2d4")}
    )
    """The dice of how many undead a turning affects, by the table's entry ("number" for one rolled for), and of
    how many more are turned (a D*'s 2d4)."""
    turning_few: Mapping[str, str] = field(default_factory=dict)
    """Turning types (lowercase, as the table names them: "fiend") that a success affects fewer of: their dice."""
    initiative_mode: str = "combatant"
    """A new campaign's initiative: per "combatant", or per "side" (OSRIC's d6 a side)."""
    melee_rates: Mapping[str, tuple[tuple[int, float], ...]] = field(default_factory=dict)
    """Each class group's melee attacks per round by level, (lowest level, rate) from the first: the rate of a melee
    attack whose sheet says fewer (OSRIC's Melee Attack Combination)."""
    specialised_melee_rates: tuple[tuple[int, float], ...] = ()
    """The melee attacks per round with a specialised weapon by level, (lowest level, rate), for the class groups of
    `melee_rates`."""
    strength_damage: bool = False
    """Whether Strength's damage adjustment is added to a melee attack whose damage dice carry no modifier of their
    own (OSRIC); else the sheet's dice have it folded in."""
    bonus_spells: Mapping[int, Mapping[int, int]] = field(default_factory=dict)
    """The extra spell slots of high Wisdom, by score and then spell level, for `bonus_spell_classes`."""
    bonus_spell_classes: tuple[str, ...] = ()
    """The class groups that get `bonus_spells` (OSRIC's clerics and druids)."""
    xp_bonus: bool = False
    """Whether `award_xp` adds each class's prime-requisite bonus from the sheet's scores (the class lookup's
    `xp_bonus_requisites`)."""

    def melee_rate(self, cls: str, level: int, *, specialised: bool = False) -> float | None:
        """The melee attacks per round of `cls` at `level` from `melee_rates` (`specialised_melee_rates` with a
        specialised weapon); None for a class without them."""
        bands = self.melee_rates.get(self.class_group(cls) or "")
        if not bands:
            return None
        if specialised and self.specialised_melee_rates:
            bands = self.specialised_melee_rates
        rate = None
        for low, value in bands:
            if level >= low:
                rate = value
        return rate

    def group_saves(self, group: str, level: int) -> dict[str, int]:
        """The saves of `group` at `level`, by save type."""
        for top, values in self.saves_by_group[group]:
            if level <= top:
                return dict(zip(self.save_types, values, strict=True))
        raise AssertionError("the last band covers every level")

    def monster_save(self, level: int, *, intelligent: bool = True) -> dict[str, int] | None:
        """The saves of a monster saving at `level` (its Hit Dice, one more with extra hit points) from the ruleset's
        table of monster saves; None without one."""
        if self.monster_saves is None:
            return None
        for top, values in self.monster_saves["intelligent" if intelligent else "non_intelligent"]:
            if level <= top:
                return dict(zip(self.save_types, values, strict=True))
        raise AssertionError("the last band covers every level")

    def class_group(self, cls: str) -> str | None:
        """The group of a class name ("Fighter", "specialist mage", "Necromancer"), or None."""
        return self.class_groups.get(cls.strip().lower())

    def turning_column(self, level: int) -> int | None:
        """The column of the turning table for an effective turning level, or None below the first."""
        for index, label in enumerate(self.turning_level_columns):
            low, high = _band(label)
            if low <= level <= high:
                return index
        return None


def _band(label: str) -> tuple[int, float]:
    """A turning column's levels: "4" is 4…4, "10-11" is 10…11, "14+" is 14 and up."""
    if label.endswith("+"):
        return int(label[:-1]), float("inf")
    low, _, high = label.partition("-")
    if not re.fullmatch(r"\d+", low) or (high and not re.fullmatch(r"\d+", high)):
        raise ValueError(f"not a turning column: {label!r}")
    return int(low), int(high or low)
