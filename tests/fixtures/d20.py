"""A fake d20 ruleset for the d20 hooks' tests (DEL-387): simple d20 maths that never equal the classic numbers for the
same input, over OSRIC's lookups, and a tripwire in place of its tables that fails on any read of the classic maths, so
a test sees a hook missed. The engine records the name of every method it runs in `called`."""

from __future__ import annotations

import functools
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from delve.dice import Dice
from delve.domain.campaigns import Character
from delve.domain.characters import CharacterState, Sheet
from delve.domain.reference import RulesetReference
from delve.packs.catalogs import Catalogs
from delve.rules.catalog import RulesetEntry
from delve.rules.classic.checks import CheckResult, SaveResult
from delve.rules.classic.combat import Combatant
from delve.rules.classic.tables import FightRules
from delve.rules.d20 import HitDie, Initiative, Progress, Swing
from tests.fixtures.rulesets import osric, osric_catalogs

FAKE_D20 = "faked20"
"""The fake d20 ruleset's id."""

CLASSIC_MATHS = (
    "saves_by_group",
    "class_groups",
    "saves_source",
    "monster_save_group",
    "monster_saves",
    "save_aliases",
    "save_natural_one_fails",
    "initiative_die",
    "weapon_speed_in_initiative",
    "initiative_mode",
    "melee_rates",
    "nonproficient",
    "caster_classes",
    "class_aliases",
    "level_drain",
    "turning_level_columns",
    "turning_counts",
    "turning_few",
)
"""The classic tables a d20 ruleset replaces: reading one is a hook the code missed."""

DEFAULT_DC = 15


class Tripwire:
    """OSRIC's tables, but for the classic maths: reading one of `CLASSIC_MATHS` raises."""

    def __init__(self) -> None:
        self._tables = osric().tables

    @property
    def fight(self) -> FightRules:
        return replace(self._tables.fight, initiative_once=True, highest_first=True)

    def __getattr__(self, name: str) -> Any:
        if name in CLASSIC_MATHS:
            raise AssertionError(f"classic table read: {name}")
        return getattr(self._tables, name)


def scoped_tools() -> list[Any]:
    """The fake ruleset's own tools: a `saving_throw` that takes a `dc` (every core param kept), and `fake_flourish`."""
    from delve.dm.tools.host import all_specs
    from delve.dm.tools.schema import ToolSpec, integer, params, plain, tool
    from delve.play import characters, combat
    from delve.rules.classic import checks

    core = next(spec for spec in all_specs() if spec.name == "saving_throw")
    schema = {
        **core.params,
        "properties": {**core.params["properties"], "dc": integer("The difficulty class to beat.")},
    }

    def saving_throw(ctx, args: dict[str, Any]) -> dict[str, Any]:
        modifier = args.get("modifier", 0)
        fighting = combat.combatant(ctx, args["character"])
        if fighting is not None:
            return combat.saving_throw(ctx, fighting.id, args["save_type"], modifier)
        who = characters.get(ctx, args["character"])
        modifier += checks.effects_save(who.state.effects)
        result = ctx.d20.save(who.sheet, args["save_type"], args.get("dc"), modifier, ctx.dice, actor=who.id)
        return {"character_id": who.id, "character": who.name, **plain(result)}

    scoped = ToolSpec(
        "saving_throw",
        core.description,
        schema,
        saving_throw,
        core.mutates,
        core.player_visible,
        core.dm_only_keys,
        core.areas,
        (FAKE_D20,),
    )
    extra: list[ToolSpec] = []

    @tool(extra, "fake_flourish", params(), mutates=False)
    def fake_flourish(ctx) -> dict[str, Any]:
        """A flourish only the fake d20 ruleset has."""
        return {"flourish": True}

    return [scoped, *(replace(spec, rulesets=(FAKE_D20,)) for spec in extra)]


def _level(sheet: Sheet) -> int:
    return sum(sheet.levels.values()) or 1


def _hd(text: str) -> int:
    """The first integer of a hit dice text; 1 when there is none."""
    found = re.search(r"\d+", text or "")
    return int(found.group()) if found else 1


def _modifier(score: int | str) -> int:
    return (int(score) - 10) // 2 if str(score).lstrip("-").isdigit() else 0


class Called(set):
    """The names of the methods run, as a set; `calls` keeps every call in order, so a test sees what one tool call ran."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def add(self, name: str) -> None:
        self.calls.append(name)
        super().add(name)

    def clear(self) -> None:
        self.calls.clear()
        super().clear()


class FakeD20Engine:
    """The fake rules, one method per `D20Engine` hook, each recording its name in `called` before it works."""

    def __init__(self) -> None:
        self.called = Called()
        self.cast_dice: Dice | None = None
        self.cast_actor: str | None = None
        self.cast_unprepared: bool | None = None
        self.memorize_spells: list[str] = []
        self.turn_state: CharacterState | None = None

    def fill_derived(self, sheet: Sheet, reference: RulesetReference) -> Sheet:
        self.called.add("fill_derived")
        level = _level(sheet)
        numbers = {"attack": level, "defence": 10 + level, "save": 2 + level // 2, "pool": level}
        return replace(sheet, d20={**(sheet.d20 or {}), **numbers}, skills={**sheet.skills, "climb": level})

    def level_up(self, sheet: Sheet, cls: str, reference: RulesetReference, dice: Dice) -> Sheet:
        self.called.add("level_up")
        raised = replace(sheet, levels={**sheet.levels, cls: sheet.levels.get(cls, 0) + 1})
        return self.fill_derived(raised, reference)

    def award_xp(self, sheet: Sheet, state: CharacterState, amount: int) -> CharacterState:
        self.called.add("award_xp")
        return replace(state, xp=state.xp + amount)

    def progress(self, sheet: Sheet, state: CharacterState, reference: RulesetReference) -> Progress:
        self.called.add("progress")
        level = 1 + state.xp // 1000
        ready = tuple(sheet.levels) if _level(sheet) < level else ()
        return Progress(level, state.xp, level * 1000, ready)

    def drain(
        self, sheet: Sheet, state: CharacterState, levels: int, reference: RulesetReference, dice: Dice
    ) -> tuple[Sheet, CharacterState, dict[str, Any]]:
        self.called.add("drain")
        if not sheet.levels:
            return sheet, replace(state, hp=0), {"slain": True, "levels": levels}
        top = max(sheet.levels, key=lambda name: sheet.levels[name])
        left = sheet.levels[top] - levels
        if left < 1:
            return sheet, replace(state, hp=0), {"slain": True, "levels": levels}
        drained = self.fill_derived(replace(sheet, levels={**sheet.levels, top: left}), reference)
        return drained, state, {"slain": False, "levels": levels, "class": top}

    def rest(
        self, sheet: Sheet, state: CharacterState, days: int, *, bed_rest: bool = False
    ) -> tuple[CharacterState, dict[str, Any]]:
        self.called.add("rest")
        rate = 2 if bed_rest else 1
        hp = min(state.hp + rate * days, sheet.hp_max) if sheet.hp_max else state.hp + rate * days
        report = {"healed": hp - state.hp, "basis": f"fake rest, {rate} hp a day"}
        return replace(state, hp=hp, d20={**(state.d20 or {}), "used": 0}), report

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
        self.called.add("cast")
        self.cast_dice = dice
        self.cast_actor = actor
        self.cast_unprepared = unprepared
        used = (state.d20 or {}).get("used", 0)
        if used >= (sheet.d20 or {}).get("pool", 0):
            return state, {"cast": False, "refusal": "No spells left to cast."}
        return replace(state, d20={**(state.d20 or {}), "used": used + 1}), {"cast": True, "spell": spell}

    def can_memorize(self, sheet: Sheet, levels: Iterable[int], spells: Sequence[str] = ()) -> str | None:
        self.called.add("can_memorize")
        self.memorize_spells = list(spells)
        return None

    def casts_unprepared(self, sheet: Sheet, spell: str) -> bool:
        self.called.add("casts_unprepared")
        return False

    def spell_level(self, sheet: Sheet, name: str) -> int | None:
        self.called.add("spell_level")
        return 1

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
        self.called.add("save")
        base = (subject.d20 or {})["save"]
        needed = (dc or DEFAULT_DC) - base - modifier
        roll = dice.d(20, purpose=f"save:{save_type}", actor=actor, combat_round=combat_round)
        return SaveResult(roll.total >= needed, needed, roll, save_type, actor, base, modifier, "faked20")

    def skill_check(
        self, sheet: Sheet, skill: str, dc: int | None, modifier: int, dice: Dice, *, actor: str, occasion: str
    ) -> CheckResult:
        self.called.add("skill_check")
        return self._check(dice, f"skill:{skill}", skill, sheet.skills.get(skill, 0), dc, modifier, actor, occasion)

    def ability_check(
        self, sheet: Sheet, ability: str, dc: int | None, modifier: int, dice: Dice, *, actor: str, occasion: str
    ) -> CheckResult:
        self.called.add("ability_check")
        bonus = _modifier(sheet.ability_scores.get(ability, 10))
        return self._check(dice, f"ability:{ability}", ability, bonus, dc, modifier, actor, occasion)

    @staticmethod
    def _check(
        dice: Dice, purpose: str, name: str, bonus: int, dc: int | None, modifier: int, actor: str, occasion: str
    ) -> CheckResult:
        needed = (dc or DEFAULT_DC) - bonus - modifier
        roll = dice.d(20, purpose=f"{purpose}#{occasion}" if occasion else purpose, actor=actor)
        return CheckResult(roll.total >= needed, needed, roll, name)

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
        self.called.add("turn_undead")
        self.turn_state = state
        roll = dice.d(20, purpose="turn_undead", actor=actor)
        return {"turned": roll.total + level >= 10 + hd, "roll": roll.total, "undead": undead}

    def combatant_from_sheet(self, character: Character, combatant: Combatant) -> Combatant:
        self.called.add("combatant_from_sheet")
        return replace(combatant, d20=dict(character.sheet.d20 or {}))

    def combatant_from_monster(
        self, row: Mapping[str, Any], combatant: Combatant, overrides: Mapping[str, Any]
    ) -> Combatant:
        self.called.add("combatant_from_monster")
        hd = _hd(str(row.get("hit_dice", "")))
        return replace(combatant, d20={"attack": hd, "defence": 10 + hd, "save": hd // 2})

    def read_hit_dice(self, line: str) -> tuple[HitDie, ...] | None:
        """None: the fake leaves every line to core's reading."""
        self.called.add("read_hit_dice")
        return None

    def load_multiplier(self, sheet: Sheet) -> float:
        """A halfling carries half."""
        self.called.add("load_multiplier")
        return 0.5 if sheet.race.lower() == "halfling" else 1.0

    def loaded_speed(self, sheet: Sheet, band: str, speed: int) -> int | None:
        """A dwarf isn't slowed by a load it can still carry; anyone else as the ruleset has it."""
        self.called.add("loaded_speed")
        return speed if sheet.race.lower() == "dwarf" and band != "overloaded" else None

    def swing(
        self, attacker: Combatant, target: Combatant, condition: str, dice: Dice, combat_round: int, fight: FightRules
    ) -> Swing:
        self.called.add("swing")
        roll = dice.d(20, purpose="attack", actor=attacker.id, target=target.id, combat_round=combat_round)
        hit = roll.total + (attacker.d20 or {})["attack"] >= (target.d20 or {})["defence"]
        rolls = (roll,)
        damage = 0
        die = None
        if hit:
            held = 0 <= attacker.weapon < len(attacker.attacks)
            die = (attacker.attacks[attacker.weapon].damage_sm if held else "") or "1d3"
            rolled = dice.roll(die, purpose="damage", actor=attacker.id, target=target.id, combat_round=combat_round)
            damage = max(rolled.total, 0)
            rolls = (roll, rolled)
        spent = replace(attacker, attacks_used=attacker.attacks_used + 1)
        if (attacker.d20 or {}).get("subdual"):  # a sap: every hit nonlethal
            return Swing(hit, 0, roll.total, (), rolls, spent, die, nonlethal=damage)
        return Swing(hit, damage, roll.total, (), rolls, spent, die)

    def nonlethal_state(self, c: Combatant) -> str | None:
        """The SRD's: staggered at nonlethal damage equal to the hit points, unconscious above them."""
        self.called.add("nonlethal_state")
        nonlethal = int((c.d20 or {}).get("nonlethal") or 0)
        if not nonlethal:
            return None
        return "staggered" if nonlethal == c.hp else "unconscious" if nonlethal > c.hp else None

    def initiative(self, combatant: Combatant, dice: Dice, combat_round: int) -> Initiative:
        self.called.add("initiative")
        roll = dice.d(20, purpose="initiative", actor=combatant.id, combat_round=combat_round)
        return Initiative(roll.total, roll.total, (roll,))

    def xp_for_defeated(self, combatant: Combatant, party_levels: Sequence[int]) -> int | None:
        self.called.add("xp_for_defeated")
        return 100 * _hd(combatant.hit_dice)

    def sheet_numbers(self, sheet: Sheet) -> dict[str, Any]:
        self.called.add("sheet_numbers")
        numbers = sheet.d20 or {}
        return {"defence": numbers["defence"], "attack": numbers["attack"], "save": numbers["save"]}

    def prompt_terms(self) -> Mapping[str, str]:
        self.called.add("prompt_terms")
        return {"attack_number": "attack bonus", "saves_list": "one save, `save`"}

    def tools(self) -> list[Any]:
        self.called.add("tools")
        return scoped_tools()


class FakeD20Ruleset:
    """The ruleset `faked20`: OSRIC's lookups and book, the tripwire for its tables, and the fake engine."""

    id = FAKE_D20
    title = "Fake d20"
    notice = ""
    prompt = "Fake d20 rules."
    encounters = None
    treasure = None

    def __init__(self) -> None:
        self._osric = osric()
        self.reference = self._osric.reference
        self.tables = Tripwire()
        self.d20 = FakeD20Engine()

    @property
    def rulebook(self) -> Any:
        return self._osric.rulebook

    def kinds(self) -> tuple[str, ...]:
        return self._osric.kinds()

    def lookup(self, kind: str, query: str, limit: int = 5) -> list[Any]:
        return self._osric.lookup(kind, query, limit)

    def merchant_catalogue(self) -> tuple[Any, ...]:
        return self._osric.merchant_catalogue()


@functools.cache
def fake_ruleset() -> FakeD20Ruleset:
    """The one fake ruleset every `d20_catalogs()` hands out, so a test reaches its engine's `called`."""
    return FakeD20Ruleset()


def fake_engine() -> FakeD20Engine:
    return fake_ruleset().d20


def d20_catalogs() -> Catalogs:
    """OSRIC's catalogs with the fake d20 ruleset beside it."""
    catalogs = osric_catalogs()
    entry = RulesetEntry(FAKE_D20, "Fake d20", "tests", fake_ruleset)
    return Catalogs((*catalogs.rulesets, entry), catalogs.settings, catalogs.packs)
