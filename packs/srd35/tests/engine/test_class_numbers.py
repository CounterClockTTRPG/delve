"""The base and NPC classes' numbers on the sheet and in a fight (DEL-389): the class features' bonuses to AC, speed,
saves, skills and initiative in `derived`, damage reduction, a ranger's favoured enemies, and the monk's unarmed
strike. Each number is worked by hand in its comment."""

from __future__ import annotations

import dataclasses

import pytest
from delve_srd35 import data
from delve_srd35.engine import Srd35Engine, features, numbers
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.campaigns import Character
from delve.domain.characters import Sheet
from delve.rules.classic import combat as rules
from delve.rules.classic.combat import AttackBlock, Combatant
from delve.rules.classic.tables import FightRules

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def sheet(cls: str, levels: dict[str, int], race: str = "Human", d20: dict | None = None, armor: str = "",
          **abilities) -> Sheet:  # fmt: skip
    build = {**(d20 or {}), **({"armor": armor} if armor else {})}
    return Sheet(label=cls, cls=cls, race=race, levels=levels, ability_scores={**TEN, **abilities}, d20=build)


def combatant(built: Sheet) -> Combatant:
    filled = ENGINE.fill_derived(built, REF)
    character = Character("pc_1", "c", built.label, sheet=filled)
    return ENGINE.combatant_from_sheet(character, Combatant("pc_1", built.label, "party", character_id="pc_1", hp=30))


def weapon(wid: str) -> dict:
    return next(row for row in data.load("weapons") if row["id"] == wid)


def dice(*faces: int) -> tuple[Dice, ScriptedRng]:
    rng = ScriptedRng(faces)
    return Dice(rng, MemoryRollLog(), "c", "beat"), rng


def test_monk_1_ac_and_unarmed():
    d = numbers.derived(sheet("Monk", {"monk": 1}, wis=14, dex=14), REF)
    assert d["ac"] == 10 + 2 + 2 and d["touch"] == 14  # Dex 2 + Wis 2, unarmoured
    assert d["flat_footed"] == 10 + 2  # the monk's bonus stays flat-footed; Dex goes
    form = combatant(sheet("Monk", {"monk": 1}, str=12)).d20["attacks"][0]
    assert form["name"] == "unarmed strike" and form["damage"] == "1d6+1"
    assert form["bonus"] == 0 + 1 and form["armed"] is True  # BAB 0 + Str 1, no -4: the monk strikes armed


def test_monk_bonus_goes_in_armour_and_grows_with_level():
    # Monk 5, Wis 14: +2 Wis and +1 at 5th; scale mail (+4) takes the monk's bonus away.
    assert numbers.derived(sheet("Monk", {"monk": 5}, wis=14), REF)["ac"] == 10 + 2 + 1
    assert numbers.derived(sheet("Monk", {"monk": 5}, wis=14, armor="scale mail"), REF)["ac"] == 10 + 4
    # Wis 8 takes nothing off: "her Wisdom bonus (if any)".
    assert numbers.derived(sheet("Monk", {"monk": 1}, wis=8), REF)["ac"] == 10


def test_monk_fast_movement_and_small_unarmed_die():
    assert numbers.derived(sheet("Monk", {"monk": 3}), REF)["speed"] == 30 + 10
    form = combatant(sheet("Monk", {"monk": 4}, race="Halfling")).d20["attacks"][0]
    assert form["damage"] == "1d6"  # a Small monk's 4th-level die


def test_barbarian_fast_movement_and_dr():
    d = numbers.derived(sheet("Barbarian", {"barbarian": 5}, race="Human"), REF)
    assert d["speed"] == 40
    assert numbers.derived(sheet("Barbarian", {"barbarian": 5}, armor="full plate"), REF)["speed"] == 20  # heavy armour
    assert "dr" not in d  # DR 1/— comes at 7th
    # In medium armour fast movement counts, before the armour slows: 40 ft. in scale mail is 30 ft.
    assert numbers.derived(sheet("Barbarian", {"barbarian": 5}, armor="scale mail"), REF)["speed"] == 30


def test_barbarian_7_has_dr_1_and_it_soaks_a_hit():
    barbarian = combatant(sheet("Barbarian", {"barbarian": 7}))
    assert barbarian.d20["dr"] == [{"value": 1, "bypass": ["—"]}]  # a monster row's shape (part 3)
    assert numbers.derived(sheet("Barbarian", {"barbarian": 7}), REF)["dr"] == "1/—"
    form = {"name": "club", "bonus": 10, "damage": "1d6", "threat": 20, "mult": 2, "count": 1, "touch": False,
            "hands": 1, "ranged": False}  # fmt: skip
    attacker = Combatant("a", "Orc", "enemy", attacks=(AttackBlock("club", "1d6", "1d6"),), init=12,
                         d20={"bab": 10, "attacks": [form], "stance": {}})  # fmt: skip
    rolled, rng = dice(15, 4)  # 15 + 10 hits; 4 damage less DR 1 is 3
    out = ENGINE.swing(attacker, barbarian, "", rolled, 2, FightRules())
    rng.assert_done()
    assert out.hit and out.damage == 3 and "DR 1/— (-1)" in out.notes
    rolled, _ = dice(15, 1)  # 1 damage less DR 1: 0, not the usual least 1
    assert ENGINE.swing(attacker, barbarian, "", rolled, 2, FightRules()).damage == 0


def test_paladin_2_divine_grace():
    d = numbers.derived(sheet("Paladin", {"paladin": 2}, cha=14, con=10, dex=10, wis=10), REF)
    assert (d["fort"], d["ref"], d["will"]) == (3 + 2, 0 + 2, 0 + 2)
    assert numbers.derived(sheet("Paladin", {"paladin": 1}, cha=14), REF)["fort"] == 2  # from 2nd
    # Cha 8: "her Charisma bonus (if any)", so no penalty.
    low = numbers.derived(sheet("Paladin", {"paladin": 2}, cha=8), REF)
    assert (low["fort"], low["ref"], low["will"]) == (3, 0, 0)


def test_druid_nature_sense_on_its_skills():
    d = numbers.derived(sheet("Druid", {"druid": 1}, d20={"skills": {"survival": 4}}), REF)
    assert d["skills"]["survival"] == 4 + 0 + 2


def test_favoured_enemies_by_the_choices():
    one = sheet("Ranger", {"ranger": 1}, d20={"choices": {"favoured_enemy": ["orc"]}})
    assert numbers.derived(one, REF)["favoured_enemy"] == {"orc": 2}
    # 5th: a second enemy and one +2 raise, the first's unless the list names one again.
    five = sheet("Ranger", {"ranger": 5}, d20={"choices": {"favoured_enemy": ["orc", "undead"]}})
    assert numbers.derived(five, REF)["favoured_enemy"] == {"orc": 4, "undead": 2}
    raised = sheet("Ranger", {"ranger": 5}, d20={"choices": {"favoured_enemy": ["orc", "undead", "undead"]}})
    assert numbers.derived(raised, REF)["favoured_enemy"] == {"orc": 2, "undead": 4}
    assert "favoured_enemy" not in numbers.derived(sheet("Ranger", {"ranger": 1}), REF)


def test_favoured_enemy_raises_are_capped_by_level():
    # A stored list past the level (an older build): ranger 5 has one raise, so +4 at most; ranger 10 two, +6.
    five = sheet("Ranger", {"ranger": 5}, d20={"choices": {"favoured_enemy": ["orc", "orc", "orc"]}})
    assert numbers.derived(five, REF)["favoured_enemy"] == {"orc": 4}
    ten = sheet("Ranger", {"ranger": 10}, d20={"choices": {"favoured_enemy": ["orc"] * 5}})
    assert numbers.derived(ten, REF)["favoured_enemy"] == {"orc": 6}
    one = sheet("Ranger", {"ranger": 1}, d20={"choices": {"favoured_enemy": ["orc", "undead", "orc"]}})
    assert numbers.derived(one, REF)["favoured_enemy"] == {"orc": 2}


def test_warrior_and_commoner_proficiency():
    assert features.proficient(sheet("Warrior", {"warrior": 1}), weapon("longsword"), "humans")
    assert not features.proficient(sheet("Commoner", {"commoner": 1}), weapon("longsword"), "humans")


# --- in a fight, through the tools -------------------------------------------------------------------------------


class Fight:
    """A fight on the srd35 campaign: characters made and built with the tools, enemies set up with setup_combat,
    and a swing by the engine with the faces given."""

    def __init__(self, call, storage, campaign):
        self.call, self.storage, self.campaign = call, storage, campaign

    def character(self, name: str, cls: str, level: int, **build) -> dict:
        scores = {"str": 14, "dex": 12, "con": 12, "int": 10, "wis": 12, "cha": 10}
        sheet = {"cls": cls, "level": level, "race": "Human", "hp_max": 10 * level, "ability_scores": scores}
        out = self.call("create_character", name=name, sheet=sheet)
        assert "error" not in out, out
        if build:
            out = self.call("set_build", character=name, **build)
            assert "error" not in out, out
        return out

    def enemies(self, *names: str) -> None:
        enemies = [{"name": name, "count": 1, "hp": 30} for name in names]
        out = self.call("setup_combat", enemies=enemies, surprise=False)
        assert "error" not in out, out

    def combatant(self, name: str) -> Combatant:
        fight = rules.from_json(self.storage.combats.live(self.campaign.id)[1])
        return next(c for c in fight.combatants.values() if c.name == name)

    def swing(self, attacker: str, target: str, *faces: int):
        rolled, rng = dice(*faces)
        defender = dataclasses.replace(self.combatant(target), init=0)  # it has acted: not flat-footed
        out = ENGINE.swing(
            dataclasses.replace(self.combatant(attacker), init=30), defender, "", rolled, 2, FightRules()
        )
        rng.assert_done()
        return out


@pytest.fixture
def fight(srd35_call, srd35_storage, srd35_campaign):
    return Fight(srd35_call, srd35_storage, srd35_campaign)


def test_ranger_favoured_enemy_in_a_fight(fight):
    fight.character("Ranger", "Ranger", 1, weapon="longsword", choices={"favoured_enemy": ["humanoid (orc)"]})
    fight.enemies("orc", "wolf")
    assert fight.combatant("Ranger").d20["favoured_enemy"] == {"orc": 2}
    hit = fight.swing("Ranger", "Orc", 15, 4)  # 15 + 3 hits; 1d8 4 + Str 2 + 2
    assert "+2 favoured enemy" in " ".join(hit.notes) and hit.damage == 4 + 2 + 2
    wolf = fight.swing("Ranger", "Wolf", 15, 4)  # an animal: no bonus
    assert not any("favoured" in note for note in wolf.notes) and wolf.damage == 4 + 2


def test_set_build_checks_favoured_enemies_and_class(fight):
    fight.character("Ranger", "Ranger", 1)
    out = fight.call("set_build", character="Ranger", choices={"favoured_enemy": ["orc", "undead"]})
    assert "A 1st-level ranger has 1 favoured enemy, not 2." in out["error"]
    out = fight.call("set_build", character="Ranger", choices={"favoured_enemy": ["orc", "orc"]})
    assert "A 1st-level ranger has 0 raises of a favoured enemy, not 1." in out["error"]
    out = fight.call("set_build", character="Ranger", choices={"favoured_enemy": ["humanoid"]})
    assert "Unknown favoured enemy 'humanoid'" in out["error"]
    out = fight.call("set_build", character="Ranger", favoured_class="jester")
    assert "Unknown favoured class 'jester'" in out["error"]
    built = fight.call("set_build", character="Ranger", favoured_class="Ranger",
                       choices={"favoured_enemy": ["Magical Beast"]})  # fmt: skip
    assert built["build"]["favoured_class"] == "ranger"
    assert built["build"]["choices"] == {"favoured_enemy": ["magical beast"]}
    assert built["derived"]["favoured_enemy"] == {"magical beast": 2}
    fight.character("Bors", "Fighter", 1)
    out = fight.call("set_build", character="Bors", choices={"favoured_enemy": ["orc"]})
    assert "Only a ranger has favoured enemies." in out["error"]


def test_set_build_refuses_raises_past_the_level(fight):
    fight.character("Ranger", "Ranger", 5)
    out = fight.call("set_build", character="Ranger", choices={"favoured_enemy": ["orc", "orc", "orc"]})
    assert "A 5th-level ranger has 1 raise of a favoured enemy, not 2." in out["error"]
    built = fight.call("set_build", character="Ranger", choices={"favoured_enemy": ["orc", "orc"]})
    assert built["derived"]["favoured_enemy"] == {"orc": 4}
