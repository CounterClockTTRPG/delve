"""OSRIC's ways where the trial of 2026-11-11 found the engine playing another's (DEL-368 to DEL-377): spells' casting
times, natural rolls, the dying, turning counts, fleeing foes, healing, initiative by side, the prime-requisite XP
bonus, and what a sheet leaves out (attack rates, Strength damage, spell slots). Through the DM's tools, with dice
forced where a check needs a face."""

import random

import pytest

from delve.dm.tools import ToolHost
from delve.rules.classic import combat as rules
from delve.web.routes.campaigns import initiative_of_ruleset
from tests.play.conftest import crypt_campaign

SWORD = {"name": "long sword", "damage_sm": "1d8", "damage_l": "1d12", "speed": 5}


class LoadedRng:
    """Seeded dice, with faces forced per die size: `force(20, 1)` makes the next d20 a 1."""

    def __init__(self, seed: int = 11) -> None:
        self.r = random.Random(seed)
        self.forced: dict[int, list[int]] = {}

    def force(self, size: int, *faces: int) -> None:
        self.forced.setdefault(size, []).extend(faces)

    def randint(self, a: int, b: int) -> int:
        queue = self.forced.get(b)
        return queue.pop(0) if queue else self.r.randint(a, b)


@pytest.fixture
def play(storage, osric_catalogs):
    rng = LoadedRng()
    host = ToolHost(storage, lambda: rng, catalogs=osric_catalogs)
    campaign = crypt_campaign(storage, ruleset="osric", setting=None)
    beat = [0]

    def call(tool, **args):
        beat[0] += 1
        out = host.call(campaign.id, f"beat-{beat[0]}", tool, args)
        assert "error" not in out, out
        return out

    call.rng, call.storage, call.campaign = rng, storage, campaign
    return call


def pc(cls, level, **sheet):
    return {"race": "Human", "cls": cls, "levels": {cls.lower(): level}, "hp_max": 10 * level, "ac": 5, **sheet}


def fight(play):
    return rules.from_json(play.storage.combats.live(play.campaign.id)[1])


def foe(play):
    return next(c for c in fight(play).combatants.values() if c.side == "enemy")


# --- DEL-369, DEL-370: natural rolls -------------------------------------------------------------------------------


def test_a_natural_20_counts_25_and_a_natural_1_is_no_certain_miss(play):
    play("create_character", name="Halvaine", sheet=pc("Magic-User", 1))
    play("create_character", name="Lord", sheet=pc("Fighter", 13, attacks=[SWORD]))
    play("setup_combat", enemies=[{"name": "orc", "count": 1, "ac": -5}], surprise=False)
    orc = foe(play).id
    play.rng.force(20, 20)
    assert play("resolve_attack", attacker="Halvaine", target=orc)["hit"]  # THAC0 20 needs 25 against AC -5
    play("update_combatant", id=orc, stats={"ac": -6})
    play.rng.force(20, 20)
    missed = play("resolve_attack", attacker="Halvaine", target=orc)
    assert not missed["hit"] and "A natural 20 counts as 25 (the table's repeated 20s)." in missed["notes"]
    play("update_combatant", id=orc, stats={"ac": 10})
    play.rng.force(20, 1)
    assert play("resolve_attack", attacker="Lord", target=orc)["hit"]  # THAC0 8 hits AC 10 on anything


def test_a_natural_1_always_fails_a_save(play):
    play("create_character", name="Anselm", sheet=pc("Cleric", 1))
    play.rng.force(20, 1, 2)
    assert not play("saving_throw", character="Anselm", save_type="para", modifier=10)["success"]
    assert play("saving_throw", character="Anselm", save_type="poly", modifier=11)["success"]  # a 2 is no natural 1


# --- DEL-371: the dying --------------------------------------------------------------------------------------------


def test_the_unconscious_bleed_from_0_and_die_of_any_more_damage(play):
    made = play("create_character", name="Garrek", sheet=pc("Fighter", 1))
    play("setup_combat", enemies=[{"name": "orc", "count": 1}], surprise=False)
    play("apply_damage", character="Garrek", amount=10)
    play("combat_round", actions=[])
    assert fight(play).combatants[made["id"]].hp == -1  # at 0, bleeding
    hit = play("apply_damage", character="Garrek", amount=1)
    assert hit["dead"] and hit["hp_after"] == -10 and hit["slain_while_unconscious"]
    play("end_combat")
    play("create_character", name="Pippa", sheet=pc("Thief", 1))
    play("update_character", ref="Pippa", patch={"hp": 0})
    assert play("apply_damage", character="Pippa", amount=1)["dead"]  # outside a fight too


# --- DEL-372: the XP bonus -----------------------------------------------------------------------------------------


def test_a_high_prime_requisite_earns_10_percent_more_xp(play):
    play("create_character", name="Garrek", sheet=pc("Fighter", 1, ability_scores={"str": "18/50"}))
    out = play("award_xp", character="Garrek", amount=1910)
    assert (out["xp_awarded"], out["xp_bonus"], out["xp_total"]) == (1910, 191, 2101)
    assert out["xp_bonus_basis"] == ["+10% for Fighter (Strength 18/50)"]
    assert out["per_class"][0]["ready"]
    play("create_character", name="Plain", sheet=pc("Fighter", 1, ability_scores={"str": 15}))
    assert "xp_bonus" not in play("award_xp", character="Plain", amount=100)
    # A paladin needs both Strength and Wisdom; a fighter/magic-user's share takes only its fighter's.
    play("create_character", name="Hal", sheet=pc("Paladin", 1, ability_scores={"str": 17, "wis": 15}))
    assert "xp_bonus" not in play("award_xp", character="Hal", amount=100)
    elf = {"race": "Elf", "cls": "Fighter/Magic-User", "levels": {"fighter": 1, "magic-user": 1}, "hp_max": 6, "ac": 6}
    play("create_character", name="Aerin", sheet={**elf, "ability_scores": {"str": 16, "int": 12}})
    assert play("award_xp", character="Aerin", amount=1000)["xp_bonus"] == 50


# --- DEL-373: turning ----------------------------------------------------------------------------------------------


def test_a_turning_d_star_affects_1d6_plus_6_and_fiends_one_or_two(play):
    out = play("turning_undead", level=8, undead="skeleton")
    assert out["destroyed"] and out["count_roll"]["notation"] == "1d6+6" and 7 <= out["count"] <= 12
    assert out["extra_turned"] == 0 and out["extra_roll"] is None
    play.rng.force(20, 20)
    fiend = play("turning_undead", level=8, undead="fiend")
    assert fiend["count_roll"]["notation"] == "1d2"
    assert play("turning_undead", level=5, undead="wight")["meaning"].endswith(
        "2d6 of these undead are turned and flee."
    )


# --- DEL-374: fleeing ----------------------------------------------------------------------------------------------


def test_a_foe_fleeing_is_attacked_at_plus_4_on_top_of_the_attackers_own(play):
    play("create_character", name="Garrek", sheet=pc("Fighter", 1, attacks=[SWORD]))
    play("setup_combat", enemies=[{"name": "orc", "count": 1, "ac": 10, "hp": 30}], surprise=False)
    orc = foe(play).id
    play("resolve_attack", attacker="Garrek", target=orc)
    play.rng.force(20, 6)  # THAC0 20 needs 10 against AC 10: +4 makes a 6 hit
    fled = play("resolve_attack", attacker="Garrek", target=orc, condition="fleeing")
    assert fled["hit"] and "+4 to hit (target fleeing from melee)." in fled["notes"]
    assert "extra_attack" not in fled


# --- DEL-375: healing ----------------------------------------------------------------------------------------------


def test_osric_heals_1_hp_a_day_without_bed_rest_and_fully_in_four_weeks(play):
    play("create_character", name="Garrek", sheet=pc("Fighter", 4, ability_scores={"con": 16}))
    play("create_character", name="Frail", sheet=pc("Thief", 4, ability_scores={"con": 5}))
    play("update_character", ref="Garrek", patch={"hp": 1})
    play("update_character", ref="Frail", patch={"hp": 1})
    out = play("rest", days=3, bed_rest=True)
    assert out["rate_per_day"] == 1 and out["basis"] == "1 hp/day x 3 day(s) (rest)"
    assert out["healing"]["Garrek"]["hp_after"] == 4
    assert out["healing"]["Frail"]["hp_after"] == 3  # Constitution 5's -1 delays it a day
    two_weeks = play("rest", character="Garrek", days=14)
    assert two_weeks["healing"]["Garrek"]["con_weekly_bonus"] == 2  # Constitution 16's +2, over the second week
    assert play("rest", character="Frail", days=28)["healing"]["Frail"]["hp_after"] == 40


# --- DEL-376: initiative by side -----------------------------------------------------------------------------------


def test_a_new_osric_campaign_rolls_initiative_by_side(storage, osric_catalogs):
    campaign = crypt_campaign(storage, ruleset="osric", setting=None)
    assert campaign.initiative == "combatant"
    assert initiative_of_ruleset(storage, campaign, osric_catalogs).initiative == "side"
    missing = crypt_campaign(storage, ruleset="adnd2e", setting=None)
    assert initiative_of_ruleset(storage, missing, osric_catalogs).initiative == "combatant"  # not installed


# --- DEL-377: what a sheet leaves out ------------------------------------------------------------------------------


def test_a_fighter_fights_at_its_class_rate_and_strength_adds_to_damage(play):
    play("create_character", name="Garrek", sheet=pc("Fighter", 1, ability_scores={"str": "18/50"}, attacks=[SWORD]))
    bow = {**SWORD, "name": "long bow", "damage_sm": "1d6"}
    play("create_character", name="Veteran", sheet=pc("Fighter", 7, attacks=[SWORD, bow]))
    play("create_character", name="Lord", sheet=pc("Fighter", 13, attacks=[{**SWORD, "damage_sm": "1d8+1"}]))
    play("create_character", name="Blade", sheet=pc("Fighter", 1, weapon_profs=["long sword (specialised)"],
                                                    attacks=[SWORD]))  # fmt: skip
    play("create_character", name="Ward", sheet=pc("Ranger", 7, attacks=[SWORD]))
    setup = play("setup_combat", enemies=[{"name": "orc", "count": 1}], surprise=False)["party_attacks"]
    assert (setup["Garrek"]["damage_sm"], setup["Garrek"]["damage_l"], setup["Garrek"]["thac0"]) == ("1d8+3", "1d12+3",
                                                                                                     19)  # fmt: skip
    assert setup["Veteran"]["per_round"] == 1.5
    bow = next(b for b in next(c for c in fight(play).combatants.values() if c.name == "Veteran").attacks
               if b.name == "long bow")  # fmt: skip
    assert bow.rate == 1.0  # a missile keeps the sheet's rate
    assert (setup["Lord"]["per_round"], setup["Lord"]["damage_sm"]) == (2.0, "1d8+1")  # a modifier of its own stays
    assert (setup["Blade"]["per_round"], setup["Ward"]["per_round"]) == (1.5, 1.0)  # specialised; a ranger at 8th


def test_a_casters_spell_slots_come_from_its_table_with_wisdoms_bonus(play):
    mage = play("create_character", name="Halvaine", sheet=pc("Magic-User", 1))
    assert play.storage.characters.get(mage["id"]).sheet.spell_slots == {1: 1}
    play("memorize_spells", character="Halvaine", spells=["Magic Missile"])
    priest = play("create_character", name="Anselm", sheet=pc("Cleric", 1, ability_scores={"wis": 15}))
    assert play.storage.characters.get(priest["id"]).sheet.spell_slots == {1: 3}  # 1, and Wisdom 15's 2 (no 2nd yet)
    play("update_character", ref="Anselm", patch={"level": 3})
    assert play.storage.characters.get(priest["id"]).sheet.spell_slots == {1: 4, 2: 2}  # 2/1, and Wisdom's 2/1
    given = play("create_character", name="Odd", sheet=pc("Magic-User", 1, spell_slots={"1": 2}))
    assert play.storage.characters.get(given["id"]).sheet.spell_slots == {1: 2}  # the sheet's own stay
