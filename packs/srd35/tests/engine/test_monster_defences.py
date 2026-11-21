"""Monsters' defences in a fight (DEL-389 part 3): damage reduction and what overcomes it, spell resistance, regeneration
and fast healing, and energy resistance and immunity. Each number is the SRD's, worked by hand in its comment."""

from __future__ import annotations

import dataclasses

import pytest
from delve_srd35 import data
from delve_srd35.engine import Srd35Engine, defences
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


def dice(*faces: int) -> tuple[Dice, ScriptedRng]:
    rng = ScriptedRng(faces)
    return Dice(rng, MemoryRollLog(), "c", "beat"), rng


def row(id: str) -> dict:
    return next(r for r in data.load("monsters") if r["id"] == id)


class Fight:
    """Combatants made by the engine (monsters from their rows, attackers with one form) and a swing with the faces
    given, in round 2 at a target that has acted (not flat-footed)."""

    def monster(self, id: str) -> Combatant:
        core = Combatant(f"mon_{id}", id, "enemy", hp=60, hp_max=60, attacks=(AttackBlock("", "1d6", "1d6"),))
        return ENGINE.combatant_from_monster(row(id), core, {})

    def wielding(self, name: str, damage: str, bonus: int = 10, **extra) -> Combatant:
        form = {"name": name, "bonus": bonus, "damage": damage, "threat": 20, "mult": 2, "count": 1, "touch": False,
                "hands": 1, "ranged": False, **extra}  # fmt: skip
        return Combatant("a", "Attacker", "party", attacks=(AttackBlock(name, damage, damage),), init=12,
                         d20={"bab": bonus, "attacks": [form], "stance": {}})  # fmt: skip

    def hero(self, cls: str, levels: dict[str, int], **d20) -> Combatant:
        sheet = ENGINE.fill_derived(Sheet(label="Hero", cls=cls, race="Human", levels=levels,
                                          ability_scores={**TEN, "str": 14}, d20=d20), REF)  # fmt: skip
        character = Character("pc_1", "c", "Hero", sheet=sheet)
        return ENGINE.combatant_from_sheet(character, Combatant("pc_1", "Hero", "party", character_id="pc_1", hp=10))

    def swing(self, attacker: Combatant, target: Combatant, *faces: int):
        rolled, rng = dice(*faces)
        out = ENGINE.swing(dataclasses.replace(attacker, init=30), dataclasses.replace(target, init=0), "", rolled, 2,
                           FightRules())  # fmt: skip
        rng.assert_done()
        return out


@pytest.fixture
def fight():
    return Fight()


def test_a_monster_combatant_carries_its_defences(fight):
    # Succubus: DR 10/cold iron or good, SR 18, resistance to acid 10, cold 10 and fire 10, immunity to electricity
    # and poison (the SRD's entry).
    succubus = fight.monster("succubus").d20
    assert succubus["dr"] == [{"value": 10, "bypass_any": ["cold iron", "good"]}]
    assert (succubus["sr"], succubus["resist"], succubus["immune"]) == (
        18, {"acid": 10, "cold": 10, "fire": 10}, ["electricity", "poison"])  # fmt: skip
    troll = fight.monster("troll").d20
    assert troll["regeneration"] == {"value": 5, "bypass": [["fire"], ["acid"]]} and "dr" not in troll
    assert fight.monster("vampire-spawn").d20["fast_healing"] == 2
    assert not {"dr", "sr", "regeneration", "fast_healing", "resist", "immune"} & set(fight.monster("orc").d20)


def test_dr_10_magic_against_a_plain_and_a_plus_1_longsword(fight):
    # Gargoyle, AC 16, DR 10/magic. 12 + 10 hits; a plain longsword's 1d8 6 + 3 = 9 is all soaked by DR 10: 0.
    gargoyle = fight.monster("gargoyle")
    plain = fight.swing(fight.wielding("longsword", "1d8+3"), gargoyle, 12, 6)
    assert (plain.hit, plain.damage) == (True, 0) and "DR 10/magic (-9)" in plain.notes
    # A +1 longsword (enhancement +1, a magic weapon) overcomes it: 6 + 3 = 9, nothing off.
    magic = fight.swing(fight.wielding("longsword", "1d8+3", enhancement=1), gargoyle, 12, 6)
    assert magic.damage == 9 and "DR 10/magic overcome (magic)" in magic.notes
    # A monster's "+2 bastard sword" is a magic weapon by its name.
    named = fight.swing(fight.wielding("+2 bastard sword", "1d10+5"), gargoyle, 12, 6)
    assert named.damage == 11 and "DR 10/magic overcome (magic)" in named.notes


def test_dr_5_silver_against_a_plus_1_longsword(fight):
    # Vampire spawn, DR 5/silver: "not made of the correct material have their damage reduced, even if the weapon
    # has an enhancement bonus". 6 + 3 = 9 - 5 = 4. An alchemical silver one overcomes it: 9.
    spawn = fight.monster("vampire-spawn")
    out = fight.swing(fight.wielding("longsword", "1d8+3", enhancement=1), spawn, 12, 6)
    assert out.damage == 4 and "DR 5/silver (-5)" in out.notes
    silver = fight.swing(fight.wielding("longsword", "1d8+3", materials=["silver"]), spawn, 12, 6)
    assert silver.damage == 9 and "DR 5/silver overcome (silver)" in silver.notes


def test_dr_by_alternatives_all_needed_and_damage_type(fight):
    # Succubus DR 10/cold iron or good: a good-aligned sword is enough. Pit fiend DR 15/good and silver: a good
    # sword isn't (6 + 3 = 9, all soaked), a good silver one is.
    succubus, fiend = fight.monster("succubus"), fight.monster("pit-fiend")
    good = fight.wielding("longsword", "1d8+3", bonus=30, aligned=["good"])
    assert "DR 10/cold iron or good overcome (good)" in fight.swing(good, succubus, 15, 6).notes
    assert fight.swing(good, fiend, 19, 6).damage == 0
    both = fight.wielding("longsword", "1d8+3", bonus=30, aligned=["good"], materials=["silver"])
    assert "DR 15/good and silver overcome (good and silver)" in fight.swing(both, fiend, 19, 6).notes
    # A skeleton's DR 5/bludgeoning: a mace (bludgeoning, weapons.json) overcomes it, a longsword (slashing) doesn't.
    skeleton = next(r["id"] for r in data.load("monsters") if r.get("dr") == [{"value": 5, "bypass": ["bludgeoning"]}])
    bones = fight.monster(skeleton)
    assert fight.swing(fight.wielding("heavy mace", "1d8+3", bonus=30), bones, 15, 6).damage == 9
    assert fight.swing(fight.wielding("longsword", "1d8+3", bonus=30), bones, 15, 6).damage == 4


def test_natural_weapons_by_the_creatures_dr_and_subtypes(fight):
    # "Such creatures' natural weapons ... are treated as magic weapons": a gargoyle's claw (DR 10/magic) overcomes
    # another's DR 10/magic. 15 + 6 hits; 1d4 3 + 2 = 5.
    gargoyle = fight.monster("gargoyle")
    out = fight.swing(gargoyle, gargoyle, 15, 3)
    assert out.damage == 5 and "DR 10/magic overcome (magic)" in out.notes
    # A succubus (Chaotic, Evil subtypes) overcomes a hound archon's DR 10/evil with her claws: 1d6 4 + 1 = 5. A
    # troll's claw (no subtype, no DR) doesn't: 1d6 4 + 6 = 10 - 10 = 0.
    archon = fight.monster("hound-archon")
    assert fight.swing(fight.monster("succubus"), archon, 19, 4).damage == 5
    assert fight.swing(fight.monster("troll"), archon, 19, 4).damage == 0


def test_monk_ki_strike_bypasses_magic(fight):
    # Monk 4: ki strike (magic). Her unarmed strike, 1d8 + Str 2, overcomes the gargoyle's DR 10/magic; a monk of
    # 3rd hasn't ki strike: 1d6 5 + 2 = 7, all soaked.
    monk = fight.hero("Monk", {"monk": 4})
    assert monk.d20["attacks"][0]["bypasses"] == ["magic"]
    gargoyle = fight.monster("gargoyle")
    out = fight.swing(monk, gargoyle, 19, 5)
    assert out.damage == 7 and "DR 10/magic overcome (magic)" in out.notes
    assert fight.swing(fight.hero("Monk", {"monk": 3}), gargoyle, 19, 5).damage == 0


def test_a_stored_combatant_without_dr_keeps_fighting(fight):
    # A barbarian's DR is the list shape now: Barbarian 7, DR 1/—.
    barbarian = fight.hero("Barbarian", {"barbarian": 7})
    assert barbarian.d20["dr"] == [{"value": 1, "bypass": ["—"]}]
    # One stored before, with the int: it reads as 2/—. 15 + 10 hits; 1d6 4 - 2 = 2.
    old = dataclasses.replace(barbarian, d20={**barbarian.d20, "dr": 2})
    out = fight.swing(fight.wielding("club", "1d6"), old, 15, 4)
    assert out.damage == 2 and "DR 2/— (-2)" in out.notes
    # One stored without any defence keys: no DR, and it keeps fighting.
    bare = dataclasses.replace(barbarian, d20={k: v for k, v in barbarian.d20.items() if k != "dr"})
    assert fight.swing(fight.wielding("club", "1d6"), bare, 15, 4).damage == 4
    # A monster stored before its row had DR (its d20 without the key) reads it from its row: 9 - 10 → 0.
    gargoyle = fight.monster("gargoyle")
    stored = dataclasses.replace(gargoyle, d20={k: v for k, v in gargoyle.d20.items() if k != "dr"})
    assert fight.swing(fight.wielding("longsword", "1d8+3"), stored, 12, 6).damage == 0


def test_energy_damage_with_resistance_and_immunity(fight):
    # A Large fire elemental's slam: 2d6+2 plus 2d6 fire. DR doesn't negate "energy damage dealt along with an
    # attack". At a succubus (fire resistance 10, DR 10/cold iron or good): slam 4 + 5 + 2 = 11 - 10 = 1, fire 5 + 6
    # = 11 - 10 = 1: 2.
    elemental = fight.monster("large-fire-elemental")
    out = fight.swing(elemental, fight.monster("succubus"), 15, 4, 5, 5, 6)
    assert out.damage == 2
    assert "plus 2d6 fire: 11, resistance to fire 10 (-10), in the damage" in out.notes
    # At a bearded devil (immune to fire, DR 5/silver or good): 11 - 5 = 6, and no fire.
    devil = fight.swing(elemental, fight.monster("bearded-devil-barbazu"), 15, 4, 5, 5, 6)
    assert devil.damage == 6 and "plus 2d6 fire: immune to fire" in devil.notes
    # At a troll: 11 + 11 fire = 22, of which the slam's 11 is nonlethal (its regeneration, DEL-421) and the fire's
    # 11 lethal.
    troll = fight.swing(elemental, fight.monster("troll"), 15, 4, 5, 5, 6)
    assert (troll.damage, troll.nonlethal) == (11, 11) and "plus 2d6 fire: 11, in the damage" in troll.notes


def test_one_energy_of_an_or_and_a_die_beside_an_energy(fight):
    # The marut's slam: 2d6+12 plus 3d6 sonic or 3d6 electricity, one of them, not both: 3 + 4 + 12 = 19 and sonic
    # 1 + 2 + 3 = 6, 25, the electricity named for the DM. The scripted faces end there (no second 3d6).
    marut = fight.swing(fight.monster("marut"), fight.monster("orc"), 10, 3, 4, 1, 2, 3)
    assert marut.damage == 25 and "plus 3d6 sonic: 6, in the damage" in marut.notes
    assert "plus 3d6 sonic or 3d6 electricity: the DM's choice, 3d6 sonic rolled" in marut.notes
    # The fire mephit's claw, "1d3 and 1d4 fire": 1d3 [2] (Str 10, +0) and fire 1d4 [3], 5; its die, not 0.
    claw = fight.monster("fire-mephit").d20["attacks"][0]
    assert (claw["damage"], claw["plus"]) == ("1d3", "1d4 fire")
    mephit = fight.swing(fight.monster("fire-mephit"), fight.monster("orc"), 15, 2, 3)
    assert mephit.damage == 5 and "plus 1d4 fire: 3, in the damage" in mephit.notes
    # The xill's four claws, "(1d4+2, 1d4+1)": the first value is the form's; its short swords' "1d6+2/19–20, ..."
    # keep their 19–20.
    forms = {f["name"]: f for f in fight.monster("xill").d20["attacks"]}
    assert any(f["damage"] == "1d4+2" for f in fight.monster("xill").d20["attacks"] if f["name"] == "claw")
    assert (forms["short sword"]["damage"], forms["short sword"]["threat"]) == ("1d6+2", 19)


def test_troll_regenerates_and_fire_stops_it(fight):
    # Troll, regeneration 5 (fire and acid deal it lethal damage). A longsword's hit, [6] + 3 = 9, is nonlethal, none
    # of it in `damage` (DEL-421); the elemental's slam, [4, 5] + 2 = 11, is nonlethal, its fire, [5, 6] = 11, lethal.
    troll = fight.monster("troll")
    sword = fight.swing(fight.wielding("longsword", "1d8+3"), troll, 15, 6)
    assert "regeneration 5: nonlethal damage (fire or acid deals lethal)" in sword.notes
    assert (sword.damage, sword.nonlethal) == (0, 9)
    fire = fight.swing(fight.monster("large-fire-elemental"), troll, 15, 4, 5, 5, 6)
    assert "regeneration 5: the fire damage (11) is lethal, the rest nonlethal" in fire.notes
    assert (fire.damage, fire.nonlethal) == (11, 11)
    # Pit fiend, regeneration 5 (good and silver weapons, or good spells): a good silver sword's hit is lethal, 6 + 3.
    both = fight.wielding("longsword", "1d8+3", bonus=30, aligned=["good"], materials=["silver"])
    silver = fight.swing(both, fight.monster("pit-fiend"), 19, 6)
    assert "regeneration 5: lethal (good and silver)" in silver.notes
    assert (silver.damage, silver.nonlethal) == (9, 0)


# --- through the tools -----------------------------------------------------------------------------------------


SCORES = {"str": 10, "dex": 12, "con": 12, "int": 16, "wis": 10, "cha": 10}


def _live(storage, campaign):
    return rules.from_json(storage.combats.live(campaign.id)[1])


def test_spell_resistance_check(srd35_call, srd35_storage, srd35_campaign):
    # Wizard 7 casts magic missile (SR: Yes) at a succubus, SR 18: d20 + 7 against 18.
    srd35_call("create_character", name="Mira", sheet={"cls": "Wizard", "level": 7, "race": "Human", "hp_max": 20,
                                                       "ability_scores": SCORES})  # fmt: skip
    out = srd35_call("setup_combat", enemies=[{"name": "succubus", "count": 1, "hp": 30}], surprise=False)
    assert "error" not in out, out
    target = next(c for c in _live(srd35_storage, srd35_campaign).combatants.values() if c.side == "enemy")
    said = srd35_call("spell_resistance", caster="Mira", target=target.id, spell="magic missile")
    assert "error" not in said, said
    assert (said["caster_level"], said["sr"]) == (7, 18)
    assert said["total"] == said["roll"] + 7 and said["overcome"] is (said["total"] >= 18)
    # The DM's caster level for a caster without one on its sheet (a monster); a spell that allows none rolls none.
    by_dm = srd35_call("spell_resistance", caster=target.id, target="Mira", spell="magic missile", caster_level=9)
    assert by_dm["overcome"] is True and "has no spell resistance" in by_dm["note"] and "roll" not in by_dm
    none = srd35_call("spell_resistance", caster="Mira", target=target.id, spell="acid splash")
    assert none["overcome"] is True and "roll" not in none and "allows no spell resistance" in none["note"]
    # Not on the caster's lists and no caster level given: refused.
    refused = srd35_call("spell_resistance", caster="Mira", target=target.id, spell="cure light wounds")
    assert "caster_level" in refused["error"]
    given = srd35_call("spell_resistance", caster="Mira", target=target.id, spell="cure light wounds", caster_level=3)
    assert given["caster_level"] == 3 and given["total"] == given["roll"] + 3


def test_spell_resistance_plus_class_levels(srd35_call):
    # An azer's SR is "equal to 13 + class levels" (Azers as Characters): an azer fighter 3 has SR 16.
    srd35_call("create_character", name="Vel", sheet={"cls": "Fighter", "level": 3, "race": "Azer", "hp_max": 20,
                                                      "ability_scores": SCORES})  # fmt: skip
    srd35_call("create_character", name="Mira", sheet={"cls": "Wizard", "level": 5, "race": "Human", "hp_max": 20,
                                                       "ability_scores": SCORES})  # fmt: skip
    said = srd35_call("spell_resistance", caster="Mira", target="Vel", spell="magic missile")
    assert "error" not in said, said
    assert (said["sr"], said["caster_level"]) == (16, 5)


def test_regeneration_and_fast_healing_each_round(srd35_call, srd35_storage, srd35_campaign):
    out = srd35_call("setup_combat", enemies=[{"name": "troll", "count": 1, "hp": 63},
                                              {"name": "vampire spawn", "count": 1, "hp": 29}], surprise=False)  # fmt: skip
    assert "error" not in out, out
    # The engine heals them at the round's end (DEL-421): the troll's 10 nonlethal by its regeneration 5, to 5; the
    # vampire spawn's 10 lethal by its fast healing 2, 19 → 21.
    srd35_call("apply_damage", character="Troll", amount=10, nonlethal=True)
    srd35_call("apply_damage", character="Vampire Spawn", amount=10)
    said = srd35_call("combat_round", actions=[])
    assert "error" not in said, said
    assert said["defences"] == ["Troll: regeneration 5 (fire or acid deals lethal damage): nonlethal 10 → 5.",
                                "Vampire Spawn: fast healing 2: hp 19 → 21."]  # fmt: skip
    fight = {c.name: c for c in _live(srd35_storage, srd35_campaign).combatants.values()}
    assert (fight["Troll"].hp, fight["Troll"].d20["nonlethal"], fight["Vampire Spawn"].hp) == (63, 5, 21)
    status = {e["name"]: e for e in said["status"]["combatants"]}
    assert (status["Troll"]["nonlethal"], status["Vampire Spawn"]["hp"]) == (5, 21)


# --- fix round 1 -----------------------------------------------------------------------------------------------


def test_a_good_sword_alone_doesnt_stop_a_pit_fiends_regeneration(fight):
    # The pit fiend "takes normal damage from good-aligned silvered weapons, and from spells or effects with the good
    # descriptor": the lone good alternative is a spell's (`["good", "spell"]`), so a holy longsword that isn't silver
    # deals nonlethal damage; a good silver one lethal.
    fiend = fight.monster("pit-fiend")
    assert fiend.d20["regeneration"]["bypass"] == [["good", "silver"], ["good", "spell"]]
    holy = fight.wielding("longsword", "1d8+3", bonus=30, aligned=["good"], enhancement=1)
    note = "regeneration 5: nonlethal damage (good and silver or good spells deals lethal)"
    assert note in fight.swing(holy, fiend, 19, 6).notes
    both = fight.wielding("longsword", "1d8+3", bonus=30, aligned=["good"], materials=["silver"])
    assert "regeneration 5: lethal (good and silver)" in fight.swing(both, fiend, 19, 6).notes


def test_rakshasa_dr_good_and_piercing(fight):
    # Rakshasa, DR 15/good and piercing (AC 21): a good-aligned longsword (slashing) doesn't overcome it, 6 + 3 = 9
    # all soaked; a good-aligned rapier (piercing) does: 1d6 5 + 3 = 8.
    rakshasa = fight.monster("rakshasa")
    assert rakshasa.d20["dr"] == [{"value": 15, "bypass": ["good", "piercing"]}]
    slashing = fight.swing(fight.wielding("longsword", "1d8+3", bonus=30, aligned=["good"]), rakshasa, 15, 6)
    assert slashing.damage == 0 and "DR 15/good and piercing (-9)" in slashing.notes
    piercing = fight.swing(fight.wielding("rapier", "1d6+3", bonus=30, aligned=["good"]), rakshasa, 15, 5)
    assert piercing.damage == 8 and "DR 15/good and piercing overcome (good and piercing)" in piercing.notes


def test_energy_joined_by_and():
    from delve_srd35.engine import defences

    assert defences.energy({"plus": "1d6 fire and 1d6 cold"}) == ([("1d6", "fire"), ("1d6", "cold")], "")
    assert defences.energy({"plus": "1d6 fire plus poison"}) == ([("1d6", "fire")], "poison")
    assert defences.energy({"plus": "poison and 2d6 acid"}) == ([("2d6", "acid")], "poison")
    assert defences.energy({"plus": "poison"}) == ([], "poison")


def test_a_stored_monster_shows_its_rows_defences(srd35_call, srd35_storage, srd35_campaign):
    # A gargoyle stored before its d20 had defences: the update answer shows its row's DR 10/magic.
    out = srd35_call("setup_combat", enemies=[{"name": "gargoyle", "count": 1, "hp": 37}], surprise=False)
    assert "error" not in out, out
    id, raw = srd35_storage.combats.live(srd35_campaign.id)
    fight = rules.from_json(raw)
    gargoyle = next(c for c in fight.combatants.values() if c.side == "enemy")
    bare = dataclasses.replace(gargoyle, d20={k: v for k, v in gargoyle.d20.items() if k != "dr"})
    fight = dataclasses.replace(fight, combatants={**fight.combatants, bare.id: bare})
    srd35_storage.combats.save(id, fight.phase, rules.to_json(fight))
    said = srd35_call("update_combatant", id=gargoyle.id, stats={"hp": 30})
    assert said["numbers"]["defences"] == {"dr": "10/magic"}, said
    troll = srd35_call("add_combatant", name="troll", count=1)
    assert "error" not in troll, troll


def test_spell_resistance_by_the_casting_class(srd35_call, srd35_storage, srd35_campaign):
    # Wizard 5/cleric 3 casts hold person (cleric 2, wizard 3; SR yes) at a succubus (SR 18): without cls, the first
    # class's (the wizard's) caster level 5, named in the note; as a cleric, 3; caster_level overrides both.
    sheet = {"cls": "Wizard/Cleric", "levels": {"wizard": 5, "cleric": 3}, "race": "Human", "hp_max": 30,
             "ability_scores": {**SCORES, "wis": 14}}  # fmt: skip
    assert "error" not in (made := srd35_call("create_character", name="Ansel", sheet=sheet)), made
    srd35_call("setup_combat", enemies=[{"name": "succubus", "count": 1, "hp": 30}], surprise=False)
    target = next(c for c in _live(srd35_storage, srd35_campaign).combatants.values() if c.side == "enemy")
    first = srd35_call("spell_resistance", caster="Ansel", target=target.id, spell="hold person")
    assert first["caster_level"] == 5 and first["total"] == first["roll"] + 5
    assert "on the wizard and cleric lists: the wizard's caster level 5 is used" in first["note"]
    cleric = srd35_call("spell_resistance", caster="Ansel", target=target.id, spell="hold person", cls="cleric")
    assert cleric["caster_level"] == 3 and "note" not in cleric
    over = srd35_call("spell_resistance", caster="Ansel", target=target.id, spell="hold person", cls="cleric",
                      caster_level=9)  # fmt: skip
    assert over["caster_level"] == 9
    refused = srd35_call("spell_resistance", caster="Ansel", target=target.id, spell="hold person", cls="druid")
    assert "isn't one of its casting classes" in refused["error"]


def test_spell_penetration_adds_to_the_check(srd35_call, srd35_storage, srd35_campaign):  # DEL-389
    # Spell Penetration: "+2 bonus on caster level checks (1d20 + caster level) made to overcome a creature's spell
    # resistance"; Greater Spell Penetration's +2 "stacks with the one from Spell Penetration".
    srd35_call("create_character", name="Mira", sheet={"cls": "Wizard", "level": 7, "race": "Human", "hp_max": 20,
                                                       "ability_scores": SCORES})  # fmt: skip
    srd35_call("setup_combat", enemies=[{"name": "succubus", "count": 1, "hp": 30}], surprise=False)
    target = next(c for c in _live(srd35_storage, srd35_campaign).combatants.values() if c.side == "enemy")
    plain = srd35_call("spell_resistance", caster="Mira", target=target.id, spell="magic missile")
    assert plain["total"] == plain["roll"] + 7 and "spell_penetration" not in plain
    srd35_call("set_build", character="Mira", feats=["spell penetration"])
    one = srd35_call("spell_resistance", beat="beat-2", caster="Mira", target=target.id, spell="magic missile")
    assert (one["total"], one["spell_penetration"]) == (one["roll"] + 7 + 2, 2)
    srd35_call("set_build", character="Mira", feats=["spell penetration", "greater spell penetration"])
    both = srd35_call("spell_resistance", beat="beat-3", caster="Mira", target=target.id, spell="magic missile")
    assert (both["total"], both["spell_penetration"]) == (both["roll"] + 7 + 4, 4)


def test_a_riders_damage_is_said_to_be_in_the_total(srd35_storage, srd35_campaign):
    # A hell hound's bite, 1d8+1 [6] + 1 plus 1d6 fire [2]: 9, the fire in the hit's `damage`. The entry says so: the
    # note ends ", in the damage" and `of_which` names the energy's part, so the DM doesn't add the fire again.
    from delve.dice import SeededRng
    from delve.dm.tools import ToolHost
    from tests.fixtures.rulesets import srd35_catalogs

    scripts: list[list[int]] = []
    host = ToolHost(srd35_storage, lambda: ScriptedRng(scripts.pop(0)) if scripts else SeededRng(1),
                    catalogs=srd35_catalogs())  # fmt: skip

    def call(tool, **args):
        return host.call(srd35_campaign.id, "beat-1", tool, args)

    made = {"cls": "Fighter", "levels": {"fighter": 1}, "race": "Human", "hp_max": 200, "ability_scores": TEN}
    assert "error" not in call("create_character", name="Bram", sheet=made)
    call("setup_combat", enemies=[{"name": "hellhound", "count": 1}], surprise=False)
    call("update_combatant", id="Hellhound", attack_bonus=40)
    scripts.append([15, 6, 2])  # the attack's d20, the bite's d8, the fire's d6
    out = call("combat_round", actions=[{"attacker": "Hellhound", "target": "Bram"}])
    (hit,) = out["actions"]
    assert hit["hit"] and hit["damage"] == 9 and hit["of_which"] == {"fire": 2}, hit
    assert "plus 1d6 fire: 2, in the damage" in hit["notes"] and hit["notes"][-1].endswith(", in the damage")
    assert hit["hp_after"] == 200 - 9


def test_a_riders_note_says_what_resistance_took_off_and_nothing_when_it_took_all(fight):
    elemental = fight.monster("large-fire-elemental")
    out = fight.swing(elemental, fight.monster("succubus"), 15, 4, 5, 5, 6)
    assert "plus 2d6 fire: 11, resistance to fire 10 (-10), in the damage" in out.notes
    assert defences.of_which(out.notes) == {"fire": 1}
    devil = fight.swing(elemental, fight.monster("bearded-devil-barbazu"), 15, 4, 5, 5, 6)
    assert "plus 2d6 fire: immune to fire" in devil.notes and defences.of_which(devil.notes) == {}
