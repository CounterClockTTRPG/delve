"""The class features a character uses (DEL-389): `use_feature`'s rage, smite evil, inspire courage and lay on hands,
the monk's flurry of blows as a stance, and the paladin's turning. Each number is worked by hand in its comment."""

from __future__ import annotations

import dataclasses

import pytest
from delve_srd35.engine import Srd35Engine
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.characters import CharacterState, Effect, Sheet
from delve.rules.classic import combat as rules
from delve.rules.classic.combat import Combatant
from delve.rules.classic.tables import FightRules

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
SCORES = {"str": 14, "dex": 12, "con": 12, "int": 10, "wis": 12, "cha": 10}


def dice(*faces: int) -> tuple[Dice, ScriptedRng]:
    rng = ScriptedRng(faces)
    return Dice(rng, MemoryRollLog(), "c", "beat"), rng


class Fight:
    """Characters made and built with the tools on the srd35 campaign, enemies set up with setup_combat, and a swing
    by the engine with the faces given."""

    def __init__(self, call, storage, campaign):
        self.call, self.storage, self.campaign = call, storage, campaign

    def character(self, name: str, cls: str, level: int, scores: dict | None = None, **build) -> dict:
        sheet = {"cls": cls, "level": level, "race": "Human", "hp_max": 10 * level,
                 "ability_scores": {**SCORES, **(scores or {})}}  # fmt: skip
        out = self.call("create_character", name=name, sheet=sheet)
        assert "error" not in out, out
        if build:
            out = self.call("set_build", character=name, **build)
            assert "error" not in out, out
        return out

    def enemies(self, *names: str) -> None:
        out = self.call("setup_combat", enemies=[{"name": n, "count": 1, "hp": 30} for n in names], surprise=False)
        assert "error" not in out, out

    def combatant(self, name: str) -> Combatant:
        fight = rules.from_json(self.storage.combats.live(self.campaign.id)[1])
        return next(c for c in fight.combatants.values() if c.name == name)

    def stance(self, name: str, **stance) -> dict:
        return self.call("set_stance", combatant=self.combatant(name).id, **stance)

    def swing(self, attacker: str, target: str, *faces: int):
        rolled, rng = dice(*faces)
        defender = dataclasses.replace(self.combatant(target), init=0)  # it has acted: not flat-footed
        out = ENGINE.swing(dataclasses.replace(self.combatant(attacker), init=30), defender, "", rolled, 2,
                           FightRules())  # fmt: skip
        rng.assert_done()
        return out

    def state(self, name: str):
        return next(c for c in self.storage.characters.list(self.campaign.id) if c.name == name)


@pytest.fixture
def fight(srd35_call, srd35_storage, srd35_campaign):
    return Fight(srd35_call, srd35_storage, srd35_campaign)


# --- rage --------------------------------------------------------------------------------------------------------


def test_rage_once_a_day_then_rest(srd35_call, fight):
    fight.character("Krug", "Barbarian", 1)
    assert srd35_call("use_feature", character="Krug", feature="rage")["effect"]["name"] == "Rage"
    refused = srd35_call("use_feature", character="Krug", feature="rage")
    assert "already raging" in refused["error"]
    srd35_call("use_feature", character="Krug", feature="rage", amount=-1)
    refused = srd35_call("use_feature", character="Krug", feature="rage")
    assert "Rage: 1 a day at this level, used 1." in refused["error"]
    srd35_call("rest", character="Krug", days=1)
    assert "error" not in srd35_call("use_feature", character="Krug", feature="rage")


def test_rage_numbers_and_its_end(fight):
    # Barbarian 2, Con 12 (+1): raging, Con 16 (+3) lasts 3 + 3 = 6 rounds and gives +2 hp per Hit Die, 4. The Effect
    # keeps core's classic AC sign: +2 is 2 easier to hit, the rage's -2 AC.
    fight.character("Krug", "Barbarian", 2)
    fight.enemies("orc")
    before = fight.combatant("Krug")
    out = fight.call("use_feature", character="Krug", feature="rage")
    assert "error" not in out, out
    effect = out["effect"]
    # The Str comes in the swing by the attack (rage_strength), so the effect has only the AC.
    numbers = tuple(effect.get(key, 0) for key in ("to_hit", "dmg", "ac", "save"))
    assert (effect["name"], effect["duration"], numbers) == ("Rage", 6, (0, 0, 2, 0))
    assert effect["source"] == "rage"
    assert "fatigued" in " ".join(out["notes"])
    raging = fight.combatant("Krug")
    assert (raging.hp, raging.hp_max) == (before.hp + 4, before.hp_max + 4)
    assert raging.d20["raging"] is True
    # The orc swings at a raging Krug: its AC is 2 lower (the classic +2 of the effect).
    hit = fight.swing("Orc", "Krug", 10, 1, 1)  # a falchion, 2d4
    assert "+2 AC modifier on Krug (active effects)." in hit.notes
    # +2 on Will (a morale bonus) and on Fort (the +4 Con's +2 modifier) while raging, none on Ref: the effect's
    # save is 0.
    will = fight.call("saving_throw", character="Krug", save_type="will", dc=10)
    fort = fight.call("saving_throw", character="Krug", save_type="fort", dc=10)
    ref = fight.call("saving_throw", character="Krug", save_type="ref", dc=10)
    sheet = fight.state("Krug").sheet.d20["derived"]
    assert (will["base"], will["modifier"]) == (sheet["will"], 2)
    assert (fort["base"], fort["modifier"]) == (sheet["fort"], 2)
    assert (ref["base"], ref["modifier"]) == (sheet["ref"], 0)
    # Ended: the hit points go, the effect goes, and Krug is fatigued.
    ended = fight.call("use_feature", character="Krug", feature="rage", amount=-1)
    assert "error" not in ended, ended
    after = fight.combatant("Krug")
    assert (after.hp, after.hp_max) == (before.hp, before.hp_max)
    assert "fatigued" in after.conditions and not any(e.name == "Rage" for e in after.effects)
    assert "raging" not in after.d20
    assert "rage" not in (fight.state("Krug").state.d20 or {})
    # Fatigued, -2 Str and Dex: Str 14 → 12 (+2 → +1) and Dex 12 → 10 (+1 → +0), the combatant made again at the
    # end: its attack one less to hit, its AC and Ref one lower; a save in the fight reads the tired sheet too.
    assert after.d20["ac"] == before.d20["ac"] - 1
    assert after.d20["saves"]["ref"] == before.d20["saves"]["ref"] - 1
    assert after.d20["attacks"][0]["bonus"] == before.d20["attacks"][0]["bonus"] - 1
    tired_ref = fight.call("saving_throw", character="Krug", save_type="ref", dc=10)
    assert tired_ref["base"] == sheet["ref"] - 1


def test_rage_strength_by_the_attack(fight):
    # Barbarian 1, Str 14 (+2), Dex 12 (+1), BAB +1. Raging, Str 18 (+4) is +2 more on a melee attack roll; on damage
    # +2 in melee and thrown, +3 two-handed, none with a bow.
    fight.character("Krug", "Barbarian", 1, weapon="greataxe")
    fight.enemies("orc")
    fight.call("use_feature", character="Krug", feature="rage")
    axe = fight.swing("Krug", "Orc", 8, 6)  # 8 + 3 + 2 = 13 hits the orc's AC 13 (8 + 3 alone wouldn't); 6 + 3 + 3
    assert axe.hit and axe.damage == 6 + 3 + 3 and "rage: +2 to hit, +3 damage" in axe.notes
    fight.call("set_build", character="Krug", weapon="longbow")
    bow = fight.swing("Krug", "Orc", 10)  # 10 + 2 = 12 misses: no +2 to hit on a bow
    assert not bow.hit and not any(note.startswith("rage") for note in bow.notes)
    bow = fight.swing("Krug", "Orc", 12, 5)  # 12 + 2 hits; 1d8 5, no Str, no rage
    assert bow.damage == 5
    fight.call("set_build", character="Krug", weapon="javelin")
    javelin = fight.swing("Krug", "Orc", 12, 3)  # thrown: 12 + 2 hits; 1d6 3 + Str 2 + rage 2
    assert javelin.damage == 3 + 2 + 2 and "rage: +2 damage" in javelin.notes


def test_rage_strength_on_a_critical(fight):
    # Barbarian 1, Str 14 (+2), BAB +1, greataxe (×3): +1 + 2 = +3, 1d12+3 (1.5 × Str 2). Raging, +2 to hit and +3
    # damage (two-handed). A 20 threatens; the confirmation 10 + 3 + 2 = 15 ≥ the orc's AC 13 confirms, ×3: three
    # damage rolls, each with the full bonus, rage's +3 too: (4 + 3 + 3) + (5 + 3 + 3) + (6 + 3 + 3) = 33.
    fight.character("Krug", "Barbarian", 1, weapon="greataxe")
    fight.character("Brak", "Barbarian", 1, weapon="greataxe")
    fight.enemies("orc")
    fight.call("use_feature", character="Krug", feature="rage")
    crit = fight.swing("Krug", "Orc", 20, 10, 4, 5, 6)
    assert crit.hit and "confirmed ×3" in crit.notes and "rage: +2 to hit, +3 damage" in crit.notes
    assert crit.damage == (4 + 3 + 3) + (5 + 3 + 3) + (6 + 3 + 3)
    # The same barbarian not raging: 10 + 3 = 13 still confirms; each roll lacks the +3: 33 − 3 × 3 = 24.
    calm = fight.swing("Brak", "Orc", 20, 10, 4, 5, 6)
    assert "confirmed ×3" in calm.notes and calm.damage == (4 + 3) + (5 + 3) + (6 + 3)


def test_a_rage_across_two_fights_keeps_hp_right(fight):
    # Krug, barbarian 1 with 10 hp: raging, 12 of 12. Fight A ends with Krug at 12; fight B makes him again from the
    # sheet (12 of 12); a hit of 5 and a heal of 5 are 12 again (the raised maximum); the end leaves 10 of 10.
    fight.character("Krug", "Barbarian", 1)
    fight.enemies("orc")
    fight.call("use_feature", character="Krug", feature="rage")
    assert (fight.combatant("Krug").hp, fight.combatant("Krug").hp_max) == (12, 12)
    fight.call("end_combat")
    assert (fight.state("Krug").state.hp, fight.state("Krug").sheet.hp_max) == (12, 12)
    fight.enemies("orc")
    assert (fight.combatant("Krug").hp, fight.combatant("Krug").hp_max) == (12, 12)
    fight.call("apply_damage", character="Krug", amount=5)
    fight.call("apply_heal", character="Krug", amount=5)
    assert fight.combatant("Krug").hp == 12
    fight.call("use_feature", character="Krug", feature="rage", amount=-1)
    assert (fight.combatant("Krug").hp, fight.combatant("Krug").hp_max) == (10, 10)
    assert fight.state("Krug").sheet.hp_max == 10
    fight.call("end_combat")
    assert fight.state("Krug").state.hp == 10


def test_a_rest_ends_a_rage_left_on(fight):
    fight.character("Krug", "Barbarian", 1)
    fight.call("use_feature", character="Krug", feature="rage")
    out = fight.call("rest", character="Krug", days=1)
    assert "error" not in out, out
    assert out["rage_ended"][0]["ended"] is True and out["rage_ended"][0]["fatigued"] is True
    after = fight.state("Krug")
    assert (after.state.hp, after.sheet.hp_max) == (10, 10)
    assert "rage" not in after.state.d20 and not after.state.effects
    assert "fatigued" not in after.state.conditions  # a night's rest clears the rage's fatigue
    assert out["fatigue_cleared"] == ["Krug"]
    assert "rage_ended" not in fight.call("rest", character="Krug", days=1)  # nothing to end
    assert "error" not in fight.call("use_feature", character="Krug", feature="rage")  # the rest gave the use back


def test_rage_end_stops_at_1_hp(fight):
    fight.character("Krug", "Barbarian", 1)
    fight.enemies("orc")
    fight.call("use_feature", character="Krug", feature="rage")
    fight.call("apply_damage", character="Krug", amount=fight.combatant("Krug").hp - 1)  # 1 hp left of the raised ones
    ended = fight.call("use_feature", character="Krug", feature="rage", amount=-1)
    assert fight.combatant("Krug").hp == 1
    assert any("SRD" in note for note in ended["notes"])


def test_rage_outside_a_fight_raises_max_hp_then_gives_it_back(fight):
    fight.character("Krug", "Barbarian", 1)
    before = fight.state("Krug")
    fight.call("use_feature", character="Krug", feature="rage")
    raging = fight.state("Krug")
    assert (raging.state.hp, raging.sheet.hp_max) == (before.state.hp + 2, before.sheet.hp_max + 2)
    fight.call("use_feature", character="Krug", feature="rage", amount=-1)
    after = fight.state("Krug")
    assert (after.state.hp, after.sheet.hp_max) == (before.state.hp, before.sheet.hp_max)
    assert "fatigued" in after.state.conditions and not after.state.effects


def test_a_rage_before_the_fight_goes_into_it_and_ends_there(fight):
    fight.character("Krug", "Barbarian", 1)
    before = fight.state("Krug")
    fight.call("use_feature", character="Krug", feature="rage")
    fight.enemies("orc")
    krug = fight.combatant("Krug")
    assert krug.d20["raging"] is True and krug.hp_max == before.sheet.hp_max + 2
    assert any(e.name == "Rage" for e in krug.effects)
    fight.call("use_feature", character="Krug", feature="rage", amount=-1)
    krug = fight.combatant("Krug")
    assert krug.hp_max == before.sheet.hp_max and "fatigued" in krug.conditions
    assert fight.state("Krug").sheet.hp_max == before.sheet.hp_max
    fight.call("end_combat")
    after = fight.state("Krug")
    # The rage ended in the fight, so its fatigue ended with the encounter (DEL-412).
    assert after.state.hp == before.state.hp and "fatigued" not in after.state.conditions
    assert after.state.d20["used"] == {"rage": 1}


def test_a_fighter_has_no_rage(fight):
    fight.character("Bors", "Fighter", 1)
    out = fight.call("use_feature", character="Bors", feature="rage")
    assert "Bors hasn't Rage" in out["error"]
    assert "Unknown feature" in fight.call("use_feature", character="Bors", feature="juggling")["error"]


def test_a_raging_monster_saves_fort_and_will_plus_two():
    # +4 Con is +2 Con modifier, so Fort +2; Will +2 morale; Ref nothing. Only while the Rage effect is on.
    saves = {"saves": {"fort": 3, "ref": 0, "will": -1}, "raging": True}
    orc = Combatant("m", "Orc", "enemy", d20=saves, effects=(Effect("Rage", 5, ac=2, source="rage"),))
    will, fort, ref = (ENGINE.save(orc, kind, 10, 0, dice(10)[0], actor="m") for kind in ("will", "fort", "ref"))
    assert (will.total, fort.total, ref.total) == (10 - 1 + 2, 10 + 3 + 2, 10)
    assert "+2 rage" in fort.basis and "rage" not in ref.basis
    # The effect expired (core counts it down): the mark alone adds nothing.
    expired = dataclasses.replace(orc, effects=())
    assert ENGINE.save(expired, "will", 10, 0, dice(10)[0], actor="m").total == 10 - 1
    assert ENGINE.save(expired, "fort", 10, 0, dice(10)[0], actor="m").total == 10 + 3


def test_rage_counts_only_while_its_effect_is_on(fight):
    # Barbarian 1, greataxe +3, 1d12+3. Raging, its Rage effect taken off as core takes it off when it runs out: the
    # swing has no rage +2 / +3 and says to end the rage; the saves have no +2.
    fight.character("Krug", "Barbarian", 1, weapon="greataxe")
    fight.enemies("orc")
    fight.call("use_feature", character="Krug", feature="rage")
    fight.call("remove_effect", target="Krug", name="Rage")  # what core's expiry leaves: the mark, no effect
    assert fight.combatant("Krug").d20["raging"] is True
    out = fight.swing("Krug", "Orc", 10, 6)  # 10 + 3 = 13 hits AC 13; 6 + 3, no rage
    assert out.hit and out.damage == 6 + 3
    assert "Rage has run out: call use_feature(rage, amount=-1)." in out.notes
    assert not any(note.startswith("rage:") for note in out.notes)
    will = fight.call("saving_throw", character="Krug", save_type="will", dc=10)
    fort = fight.call("saving_throw", character="Krug", save_type="fort", dc=10)
    assert (will["modifier"], fort["modifier"]) == (0, 0)
    # Out of the fight too: the character's own effects are read.
    fight.call("end_combat")
    assert fight.call("saving_throw", character="Krug", save_type="will", dc=10)["modifier"] == 0


def test_rage_fatigue_ends_with_the_encounter(srd35_call, fight):  # DEL-412
    # Grak rages in the fight and the rage ends there: fatigued "for the rest of the encounter", so end_combat takes
    # it off. A barbarian the DM made fatigued with update_character (a forced march) keeps it.
    fight.character("Grak", "Barbarian", 2)
    fight.character("Ulf", "Barbarian", 2)
    srd35_call("update_character", ref="Ulf", patch={"conditions": ["fatigued"]}, reason="a forced march")
    fight.enemies("orc")
    assert "error" not in srd35_call("use_feature", character="Grak", feature="rage")
    assert srd35_call("use_feature", character="Grak", feature="rage", amount=-1)["fatigued"] is True
    assert "fatigued" in fight.combatant("Grak").conditions and fight.combatant("Grak").d20["rage_fatigue"] is True
    out = srd35_call("end_combat")
    assert "error" not in out, out
    assert "fatigued" not in fight.state("Grak").state.conditions
    assert "fatigued" not in out["characters"][fight.state("Grak").id]["conditions"]
    assert "fatigued" in fight.state("Ulf").state.conditions


def test_a_fatigued_barbarian_cant_rage(srd35_call, fight):
    # Barbarian 4: rage 2 a day. Raged and ended, fatigued: the second rage is refused while the fatigue lasts.
    fight.character("Krug", "Barbarian", 4)
    srd35_call("use_feature", character="Krug", feature="rage")
    srd35_call("use_feature", character="Krug", feature="rage", amount=-1)
    refused = srd35_call("use_feature", character="Krug", feature="rage")
    assert refused["error"] == "Krug is fatigued: a barbarian can't rage again until it passes."
    # In a fight, fatigued on its combatant: refused the same.
    fight.enemies("orc")
    assert "is fatigued" in srd35_call("use_feature", character="Krug", feature="rage")["error"]


def test_tireless_rage_rages_while_fatigued(srd35_call, fight):
    # A 17th-level barbarian's tireless rage: no fatigue after a rage, and one fatigued otherwise may still rage.
    fight.character("Krug", "Barbarian", 17)
    srd35_call("update_character", ref="Krug", patch={"conditions": ["fatigued"]}, reason="a forced march")
    out = srd35_call("use_feature", character="Krug", feature="rage")
    assert "error" not in out, out


# --- smite evil --------------------------------------------------------------------------------------------------


def test_smite_on_an_evil_and_a_neutral_target(fight):
    # Paladin 1, Str 14 (+2), Cha 14 (+2), longsword: +1 + 2 = +3, 1d8+2. Smiting the orc (often chaotic evil): +2 to
    # hit and +1 damage (paladin 1). The wolf (neutral): no bonus, the note says so; the smite is spent either way.
    fight.character("Aldra", "Paladin", 1, scores={"cha": 14}, weapon="longsword")
    fight.enemies("orc", "wolf")
    out = fight.call("use_feature", character="Aldra", feature="smite evil")
    assert "error" not in out, out
    assert fight.combatant("Aldra").d20["smite"]
    orc = fight.swing("Aldra", "Orc", 10, 4)  # 10 + 3 + 2 = 15 hits the orc's AC 13; 4 + 2 + 1
    assert orc.hit and orc.damage == 4 + 2 + 1
    assert "smite evil: +2 to hit, +1 damage" in orc.notes
    assert "smite" not in orc.attacker.d20
    wolf = fight.swing("Aldra", "Wolf", 15, 4)
    assert wolf.damage == 4 + 2 and "smite" not in wolf.attacker.d20
    assert any("isn't evil" in note for note in wolf.notes)
    refused = fight.call("use_feature", character="Aldra", feature="smite-evil")
    assert "Smite evil: 1 a day at this level, used 1." in refused["error"]


def test_smite_is_spent_by_resolve_attack(fight):
    fight.character("Aldra", "Paladin", 1, scores={"cha": 14}, weapon="longsword")
    fight.enemies("orc")
    fight.call("combat_round")
    fight.call("use_feature", character="Aldra", feature="smite evil")
    out = fight.call("resolve_attack", attacker="Aldra", target="Orc")
    assert "error" not in out, out
    assert any("smite evil" in note for note in out["notes"])
    assert "smite" not in fight.combatant("Aldra").d20


def test_smite_and_favoured_enemy_on_a_labelled_monster(fight):
    # The orcs fight as "Orc raiders" (a label): smite evil and favoured enemy read the row by its id, not the name.
    # Paladin 1, Cha 14: +2 to hit, +1 damage on the (chaotic evil) orc. Ranger 1, favoured enemy orc: +2 damage.
    fight.character("Aldra", "Paladin", 1, scores={"cha": 14}, weapon="longsword")
    fight.character("Rook", "Ranger", 1, weapon="longsword", choices={"favoured_enemy": ["orc"]})
    out = fight.call("setup_combat", enemies=[{"name": "orc", "count": 1, "hp": 30, "label": "Orc raiders"}],
                     surprise=False)  # fmt: skip
    assert "error" not in out, out
    raider = fight.combatant("Orc raiders")
    assert raider.group == "Orc raiders" and raider.d20["monster"] == "orc"
    fight.call("use_feature", character="Aldra", feature="smite evil")
    smitten = fight.swing("Aldra", "Orc raiders", 10, 4)  # 10 + 3 + 2 = 15 hits AC 13; 4 + 2 + 1
    assert smitten.damage == 4 + 2 + 1 and "smite evil: +2 to hit, +1 damage" in smitten.notes
    favoured = fight.swing("Rook", "Orc raiders", 12, 4)  # 12 + 1 + 2 hits; 4 + Str 2 + favoured 2
    assert favoured.damage == 4 + 2 + 2 and "+2 favoured enemy" in favoured.notes
    # Without the id (a combatant made before it), the group lookup still serves.
    plain = dataclasses.replace(raider, group="Orc", d20={k: v for k, v in raider.d20.items() if k != "monster"})
    from delve_srd35.engine import class_features

    assert class_features.evil(plain) and not class_features.evil(dataclasses.replace(plain, group="Orc raiders"))


def test_smite_waits_for_a_melee_attack(fight):
    # "One normal melee attack": a bow shot leaves the smite waiting, with a note, and adds nothing.
    fight.character("Aldra", "Paladin", 1, scores={"cha": 14}, weapon="longbow")
    fight.enemies("orc")
    fight.call("use_feature", character="Aldra", feature="smite evil")
    shot = fight.swing("Aldra", "Orc", 12, 5)  # 12 + 1 (BAB) + 1 (Dex) hits; 1d8 5, no smite
    assert shot.damage == 5 and shot.attacker.d20["smite"]
    assert "smite evil waits for a melee attack: not on this one" in shot.notes


def test_smite_needs_a_fight(fight):
    fight.character("Aldra", "Paladin", 1, scores={"cha": 14})
    assert "fight" in fight.call("use_feature", character="Aldra", feature="smite evil")["error"]


# --- inspire courage ---------------------------------------------------------------------------------------------


def test_inspire_courage_on_the_party(fight):
    fight.character("Lyra", "Bard", 1, skills={"perform": 4})
    fight.character("Bors", "Fighter", 1)
    fight.enemies("orc")
    out = fight.call("use_feature", character="Lyra", feature="inspire courage")
    assert "error" not in out, out
    for name in ("Lyra", "Bors"):
        effect = next(e for e in fight.combatant(name).effects if e.name == "Inspire Courage +1")
        assert (effect.to_hit, effect.dmg, effect.save, effect.duration) == (1, 1, 0, 0)
    assert not fight.combatant("Orc").effects
    said = " ".join(out["notes"])
    assert "charm and fear" in said and "remove_effect" in said
    # A morale bonus: on a save it doesn't stack with rage's +2 on Will, also a morale bonus.
    assert "don't stack with another morale bonus, such as a rage's +2 on Will" in said
    # Bard 1 has 1 bardic music a day.
    refused = fight.call("use_feature", character="Lyra", feature="inspire courage")
    assert "Bardic music: 1 a day at this level, used 1." in refused["error"]


def test_inspire_courage_needs_perform_ranks(fight):
    fight.character("Lyra", "Bard", 1)
    fight.enemies("orc")
    assert "3 ranks in Perform" in fight.call("use_feature", character="Lyra", feature="inspire courage")["error"]


# --- lay on hands ------------------------------------------------------------------------------------------------


def test_lay_on_hands_pool(fight):
    # Paladin 2, Cha 14 (+2): 2 × 2 = 4 hp a day. 3, then 2 is refused with 1 left.
    fight.character("Aldra", "Paladin", 2, scores={"cha": 14})
    fight.character("Bors", "Fighter", 1)
    fight.call("apply_damage", character="Bors", amount=5)
    hp = fight.state("Bors").state.hp
    out = fight.call("use_feature", character="Aldra", feature="lay on hands", target="Bors", amount=3)
    assert "error" not in out, out
    assert fight.state("Bors").state.hp == hp + 3
    refused = fight.call("use_feature", character="Aldra", feature="lay on hands", target="Bors", amount=2)
    assert "Lay on hands: 4 hp a day at this level, used 3: 1 left." in refused["error"]
    assert "error" not in fight.call("use_feature", character="Aldra", feature="lay on hands", amount=1)
    assert "a number of hit points" in fight.call("use_feature", character="Aldra", feature="lay-on-hands")["error"]


# --- flurry of blows ---------------------------------------------------------------------------------------------


def test_flurry_at_monk_1(fight):
    # Monk 1, BAB 0, Str 14 (+2): flurrying, two unarmed strikes at 0 - 2 + 2 each.
    fight.character("Monk", "Monk", 1)
    fight.enemies("orc")
    bab0, str_mod = 0, 2
    c = fight.stance("Monk", flurry=True)
    assert "error" not in c, c
    assert [a["bonus"] for a in c["attacks_this_round"]] == [bab0 - 2 + str_mod, bab0 - 2 + str_mod]
    assert c["stance"]["flurry"] is True
    monk = fight.combatant("Monk")
    assert monk.attacks[monk.weapon].rate == 2
    hit = fight.swing("Monk", "Orc", 15, 3)
    assert "flurry of blows (-2)" in hit.notes
    off = fight.stance("Monk", flurry=False)
    assert "attacks_this_round" not in off
    assert fight.combatant("Monk").d20["attacks"][0]["bonus"] == bab0 + str_mod


def test_flurry_at_monk_5_is_minus_one(fight):
    fight.character("Monk", "Monk", 5)
    fight.enemies("orc")
    c = fight.stance("Monk", flurry=True)
    assert [a["bonus"] for a in c["attacks_this_round"]] == [3 - 1 + 2] * 2  # BAB 3, -1, Str 2


def test_flurry_refused_for_a_fighter_in_armour_or_with_a_longsword(fight):
    fight.character("Bors", "Fighter", 1)
    fight.character("Monk", "Monk", 1, armor="leather")
    fight.character("Kai", "Monk", 1, weapon="longsword")
    fight.enemies("orc")
    assert "only a monk" in fight.stance("Bors", flurry=True)["error"]
    assert "armour" in fight.stance("Monk", flurry=True)["error"]
    assert "unarmed" in fight.stance("Kai", flurry=True)["error"]


def test_flurry_with_a_kama(fight):
    fight.character("Monk", "Monk", 1, weapon="kama")
    fight.enemies("orc")
    assert fight.stance("Monk", flurry=True)["attacks_this_round"][0]["bonus"] == 0 - 2 + 2


# --- paladin turning ---------------------------------------------------------------------------------------------


def _paladin(level: int, cha: int = 14) -> Sheet:
    scores = {**SCORES, "cha": cha}
    built = Sheet(label="Aldra", cls="Paladin", race="Human", levels={"paladin": level}, ability_scores=scores, d20={})
    return ENGINE.fill_derived(built, REF)


def test_paladin_turns_at_4th_level_not_before():
    state = CharacterState(hp=20)
    three = ENGINE.turn_undead(_paladin(3), 3, "ghoul", 0, dice()[0], actor="pc_1", state=state)
    assert "can't turn" in three["note"]
    # Paladin 4, Cha 14 (+2): 3 + 2 = 5 a day, at turning level 4 - 3 = 1. Check 13 + 2 = 15 is level + 1, 2 HD; the
    # damage 2d6 (3 + 4) + 1 + 2 = 10; destroys up to 1 // 2 = 0 HD.
    four = _paladin(4)
    assert four.d20["derived"]["turning_per_day"] == 5
    roll, rng = dice(13, 3, 4)
    said = ENGINE.turn_undead(four, 9, "ghoul", 0, roll, actor="pc_1", state=state)
    rng.assert_done()
    assert (said["max_hd"], said["total_hd"], said["destroy_up_to_hd"], said["attempts_left"]) == (2, 10, 0, 4)
    assert said["turned"] is True


def test_a_days_rest_clears_fatigue(fight):
    fight.character("Krug", "Barbarian", 1)
    fight.call("use_feature", character="Krug", feature="rage")
    fight.call("use_feature", character="Krug", feature="rage", amount=-1)
    assert "fatigued" in fight.state("Krug").state.conditions
    out = fight.call("rest", character="Krug", days=1)
    assert out["fatigue_cleared"] == ["Krug"] and "rage_ended" not in out
    assert "fatigued" not in fight.state("Krug").state.conditions
    # Less than a day (days=0) leaves it.
    rested, said = ENGINE.rest(_paladin(1), CharacterState(hp=5, conditions=("fatigued",)), 0)
    assert "fatigued" in rested.conditions and "fatigue_cleared" not in said


def test_a_rest_of_no_days_keeps_the_days_uses():
    # The uses are a day's: a rest of 0 days gives none back; a day's rest does.
    spent = CharacterState(hp=5, d20={"used": {"lay-on-hands": 4, "smite-evil": 1}})
    rested, _ = ENGINE.rest(_paladin(2), spent, 0)
    assert rested.d20["used"] == {"lay-on-hands": 4, "smite-evil": 1}
    rested, _ = ENGINE.rest(_paladin(2), spent, 1)
    assert rested.d20["used"] == {}


def test_a_fatigued_character_has_less_str_and_dex(fight):
    # Fighter 1, Str 14 (+2), Dex 12 (+1), longsword +1 + 2 = +3. Fatigued (the DM's ruling, outside a fight):
    # Str 12 (+1), Dex 10 (+0). In a fight made then, +2 to hit, AC and Ref one lower; outside it, a Ref save and a
    # Dex-based check one lower. The sheet's stored numbers stay the rested ones.
    fight.character("Tor", "Fighter", 1, weapon="longsword")
    fight.character("Ulf", "Fighter", 1, weapon="longsword")
    rested_ref = fight.call("saving_throw", character="Tor", save_type="ref", dc=10)["base"]
    rested_hide = fight.call("skill_check", character="Tor", skill="hide", dc=10)["bonus"]
    fight.call("update_character", ref="Tor", patch={"conditions": ["fatigued"]}, reason="a forced march")
    assert fight.call("saving_throw", character="Tor", save_type="ref", dc=10)["base"] == rested_ref - 1
    assert fight.call("skill_check", character="Tor", skill="hide", dc=10)["bonus"] == rested_hide - 1
    assert fight.state("Tor").sheet.d20["derived"]["ref"] == rested_ref
    fight.enemies("orc")
    tor, ulf = fight.combatant("Tor"), fight.combatant("Ulf")
    assert tor.d20["attacks"][0]["bonus"] == ulf.d20["attacks"][0]["bonus"] - 1 == 2
    assert (tor.d20["ac"], tor.d20["saves"]["ref"]) == (ulf.d20["ac"] - 1, ulf.d20["saves"]["ref"] - 1)
    assert tor.d20["attacks"][0]["damage"] == "1d8+1"


def test_rest_clears_the_days_uses():
    sheet = _paladin(2)
    rested, _ = ENGINE.rest(sheet, CharacterState(hp=5, d20={"used": {"lay-on-hands": 4}, "turning_used": 1}), 1)
    assert rested.d20 == {"used": {}, "turning_used": 0}
    # A state without uses gains no key (Phase 2's states read unchanged).
    plain, _ = ENGINE.rest(sheet, CharacterState(hp=5), 1)
    assert plain.d20 == {"turning_used": 0}
