"""The 3.5 engine's prepared spells and turning undead (DEL-388): slots, domain slots and class lists, arcane spell
failure, and turning by the SRD's table. Each worked example is checked by hand in its comment."""

from __future__ import annotations

from dataclasses import replace

import pytest
from delve_srd35.engine import Srd35Engine, magic
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.characters import CharacterState, MemorizedSpell, Sheet

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def dice(*faces: int) -> tuple[Dice, ScriptedRng]:
    rng = ScriptedRng(faces)
    return Dice(rng, MemoryRollLog(), "c", "beat"), rng


def filled(cls: str, levels: dict[str, int], abilities: dict[str, int], **d20) -> Sheet:
    return ENGINE.fill_derived(
        Sheet(label=cls, cls=cls, race="Human", levels=levels, ability_scores={**TEN, **abilities}, d20=d20), REF
    )


def cleric(level: int = 1, **abilities) -> Sheet:
    return filled("Cleric", {"cleric": level}, {"wis": 15, **abilities}, domains=["war", "good"])


def wizard(**d20) -> Sheet:
    # Int 16: slots 0: 3, 1: 1 + 1 bonus = 2; DC at level 1 is 10 + 1 + 3 = 14.
    return filled("Wizard", {"wizard": 1}, {"int": 16}, **d20)


def spent(*names: str) -> CharacterState:
    return CharacterState(hp=6, memorized=tuple(MemorizedSpell(name, 1, cast=True) for name in names))


def test_cleric_domain_slot_takes_only_a_domain_spell():
    # A 1st-level cleric with Wis 15 has 1 + 1 bonus + 1 domain = 3 level-1 slots, one of them for a domain spell
    # (war's is magic weapon, good's protection from evil).
    sheet = cleric()
    assert sheet.d20["derived"]["slots"]["1"] == 3
    assert ENGINE.can_memorize(sheet, [1, 1, 1], ["Bless", "Bless", "Magic Weapon"]) is None
    assert ENGINE.can_memorize(sheet, [1, 1, 1], ["Bless", "Shield of Faith", "Protection from Evil"]) is None
    refusal = ENGINE.can_memorize(sheet, [1, 1, 1], ["Bless", "Bless", "Shield of Faith"])
    assert refusal and "domain" in refusal and "Magic Weapon" in refusal
    # A domain spell on no cleric list fills the domain slot; level 0 has no domain slot.
    assert ENGINE.can_memorize(sheet, [0, 0, 0], ["Light", "Guidance", "Resistance"]) is None
    # More spells than slots is refused, whatever they are.
    assert "slots" in ENGINE.can_memorize(sheet, [1, 1, 1, 1], ["Magic Weapon"] * 4)


def test_only_the_domain_slot_holds_a_spell_off_the_cleric_list():
    # Fire's 1st-level spell is burning hands and animal's calm animals, both off the cleric list: the one domain slot
    # holds one of them, the other two slots (Wis 15) take cleric spells.
    fire = filled("Cleric", {"cleric": 1}, {"wis": 15}, domains=["fire", "animal"])
    assert fire.d20["derived"]["slots"]["1"] == 3
    twice = ENGINE.can_memorize(fire, [1, 1, 1], ["Burning Hands", "Burning Hands", "Bless"])
    assert twice and "domain slot" in twice and "Burning Hands" in twice
    both = ENGINE.can_memorize(fire, [1, 1], ["Burning Hands", "Calm Animals"])
    assert both and "domain slot" in both and "Calm Animals" in both
    assert ENGINE.can_memorize(fire, [1, 1, 1], ["Burning Hands", "Bless", "Shield of Faith"]) is None
    assert ENGINE.can_memorize(fire, [1, 1], ["Calm Animals", "Bless"]) is None


def test_wizard_cannot_prepare_a_cleric_spell():
    sheet = wizard()
    assert ENGINE.can_memorize(sheet, [1, 1], ["Sleep", "magic missile"]) is None
    refusal = ENGINE.can_memorize(sheet, [1], ["Bless"])
    assert refusal and "Bless" in refusal and "wizard" in refusal
    # A wizard spell at the wrong level, and a name that is no spell.
    assert "level-1 wizard spell" in ENGINE.can_memorize(sheet, [0], ["Sleep"])
    assert "no spell" in ENGINE.can_memorize(sheet, [1], ["Fireballz"])
    # A wizard has no domain slot: its slots go by count alone, and level 2 it has none of (DEL-389: its highest).
    assert "slots" in ENGINE.can_memorize(sheet, [1, 1, 1])
    assert ENGINE.can_memorize(sheet, [2], ["Blur"]) == "Wizard can cast up to 1st-level spells."
    fighter = filled("Fighter", {"fighter": 1}, {})
    assert ENGINE.can_memorize(fighter, [], []) is None
    assert "casts no spells" in ENGINE.can_memorize(fighter, [1], ["Sleep"])
    with pytest.raises(ValueError, match="names"):
        ENGINE.can_memorize(sheet, [1, 1], ["Sleep"])


def test_a_level_above_the_casters_highest_is_refused():
    # A 7th-level cleric with Wis 15 has 4th-level slots (1 + 1 domain) and none of 5th (DEL-389: to 9th by the table).
    sheet = cleric(7)
    assert sheet.d20["derived"]["slots"]["4"] == 2
    assert ENGINE.can_memorize(sheet, [4], ["Divine Power"]) is None
    assert ENGINE.can_memorize(sheet, [5], ["Flame Strike"]) == "Cleric can cast up to 4th-level spells."
    assert ENGINE.can_memorize(sheet, [3, 3], ["Magic Vestment", "Prayer"]) is None


def test_spell_failure_rolls_in_armour():
    # A chain shirt is 20% arcane spell failure; sleep is V, S, M. The SRD's 20% chance is rolls 1-20 of a d100: a
    # 20 fails and the spell is lost, a 21 casts.
    sheet = wizard(armor="chain shirt")
    assert sheet.d20["derived"]["spell_failure"] == 20
    state = spent("Sleep")
    roll, rng = dice(20)
    after, said = ENGINE.cast(sheet, state, "Sleep", 1, dice=roll)
    assert after is state
    assert said == {"cast": False, "lost": True, "spell_failure": {"chance": 20, "roll": 20, "failed": True}}
    assert rng.calls == [(1, 100)]
    roll, _ = dice(21)
    after, said = ENGINE.cast(sheet, state, "sleep", 1, dice=roll)
    assert after is state
    assert said == {"dc": 14, "school": "Enchantment", "save": "Will negates",
                    "spell_failure": {"chance": 20, "roll": 21, "failed": False}}  # fmt: skip
    # Each spent copy rolls its own d100, also within one beat.
    roll, rng = dice(50, 5)
    twice = spent("Sleep", "Sleep")
    assert ENGINE.cast(sheet, spent("Sleep"), "Sleep", 1, dice=roll)[1].get("cast") is not False
    assert ENGINE.cast(sheet, twice, "Sleep", 1, dice=roll)[1]["lost"] is True
    with pytest.raises(ValueError, match="dice"):
        ENGINE.cast(sheet, state, "Sleep", 1)


def test_two_wizards_roll_their_own_failure_in_one_beat():
    # The roll log gives a key it has seen its stored roll: two casters of one spell in one beat need two keys.
    log = MemoryRollLog()
    rng = ScriptedRng([5, 90])
    shared = Dice(rng, log, "c", "beat")
    first = replace(wizard(armor="chain shirt"), label="Ilsa")
    second = replace(wizard(armor="chain shirt"), label="Oswin")
    assert ENGINE.cast(first, spent("Sleep"), "Sleep", 1, dice=shared)[1]["lost"] is True
    assert ENGINE.cast(second, spent("Sleep"), "Sleep", 1, dice=shared)[1]["spell_failure"]["roll"] == 90
    rng.assert_done()
    # The same caster's same copy asked again is the stored roll: nothing new is rolled.
    assert ENGINE.cast(first, spent("Sleep"), "Sleep", 1, dice=shared)[1]["spell_failure"]["roll"] == 5


def test_two_casters_of_one_name_roll_their_own_failure():
    # DEL-395: core hands `cast` the character's id: two characters both called Ilsa are two casters, with two rolls.
    log = MemoryRollLog()
    rng = ScriptedRng([5, 90])
    shared = Dice(rng, log, "c", "beat")
    ilsa = replace(wizard(armor="chain shirt"), label="Ilsa")
    assert ENGINE.cast(ilsa, spent("Sleep"), "Sleep", 1, dice=shared, actor="pc_1")[1]["lost"] is True
    other = ENGINE.cast(ilsa, spent("Sleep"), "Sleep", 1, dice=shared, actor="pc_2")[1]
    assert other["spell_failure"]["roll"] == 90
    rng.assert_done()
    assert [roll.key.actor for _, roll in log.rolls] == ["pc_1", "pc_2"]


def test_verbal_only_spell_has_no_failure_roll():
    # Feather fall is V only: the SRD casts a spell without a somatic component in armour with no failure chance.
    sheet = wizard(armor="chain shirt")
    roll, rng = dice()
    state = spent("Feather Fall")
    after, said = ENGINE.cast(sheet, state, "Feather Fall", 1, dice=roll)
    assert after is state and rng.calls == []
    assert said == {"dc": 14, "school": "Transmutation", "save": "Will negates (harmless) or Will negates (object)"}
    # Without armour a wizard rolls nothing, and a cleric's divine spells never roll.
    assert ENGINE.cast(wizard(), spent("Sleep"), "Sleep", 1)[1]["dc"] == 14
    priest = filled("Cleric", {"cleric": 1}, {"wis": 15}, armor="full plate", domains=["war", "good"])
    assert ENGINE.cast(priest, spent("Bless"), "Bless", 1)[1] == {"dc": 13, "school": "Enchantment", "save": "None"}


def test_turning_table_and_damage():
    # A 3rd-level cleric with Cha 12 (+1) turns 3 + 1 = 4 times a day. The check 13 + 1 = 14 reads "13-15: level + 1",
    # 4 HD; the damage 2d6 (4 + 5) + 3 + 1 = 13 HD in total; 3 // 2 = 1 HD or less is destroyed. A ghoul has 2 HD.
    sheet = cleric(3, cha=12)
    assert sheet.d20["derived"]["turning_per_day"] == 4
    state = CharacterState(hp=15)
    roll, rng = dice(13, 4, 5)
    said = ENGINE.turn_undead(sheet, 3, "ghoul", 0, roll, actor="pc_1", state=state)
    rng.assert_done()
    assert {k: said[k] for k in ("max_hd", "total_hd", "destroy_up_to_hd", "attempts_left")} == {
        "max_hd": 4, "total_hd": 13, "destroy_up_to_hd": 1, "attempts_left": 3}  # fmt: skip
    assert (said["check"], said["hd"], said["turned"], said["destroyed"]) == (14, 2, True, False)
    assert said["state"].d20 == {"turning_used": 1} and said["state"].hp == 15
    # The table's ends: 0 or lower is level - 4 (a 1 - 1 at Cha 8 is 0), 22 or higher level + 4 (a 20 + 2 at Cha 14);
    # a 20 + 1 at Cha 12 is 21, level + 3.
    low = ENGINE.turn_undead(cleric(3, cha=8), 3, "", 1, dice(1)[0], actor="pc_1", state=state)
    assert (low["check"], low["max_hd"], low["turned"], low["total_hd"]) == (0, -1, False, 0)
    high = ENGINE.turn_undead(sheet, 3, "", 1, dice(20, 1, 1)[0], actor="pc_1", state=state)
    assert (high["check"], high["max_hd"]) == (21, 6)
    higher = ENGINE.turn_undead(cleric(3, cha=14), 3, "", 1, dice(20, 1, 1)[0], actor="pc_1", state=state)
    assert (higher["check"], higher["max_hd"]) == (22, 7)
    # An undead stronger than the check affects is not turned and rolls no damage; a 1 HD one is destroyed.
    roll, rng = dice(1)
    wight = ENGINE.turn_undead(sheet, 3, "wight", 0, roll, actor="pc_1", state=state)
    assert (wight["max_hd"], wight["hd"], wight["turned"], wight["total_hd"]) == (0, 4, False, 0)
    rng.assert_done()
    skeleton = ENGINE.turn_undead(sheet, 3, "human warrior skeleton", 0, dice(10, 1, 1)[0], actor="pc_1", state=state)
    assert (skeleton["hd"], skeleton["turned"], skeleton["destroyed"]) == (1, True, True)
    # Only undead are turned: an orc is refused without a roll or a spent attempt.
    roll, rng = dice()
    orc = ENGINE.turn_undead(sheet, 3, "orc", 0, roll, actor="pc_1", state=state)
    assert "undead" in orc["note"] and "state" not in orc and rng.calls == []


def test_turning_runs_out():
    sheet = cleric(3, cha=12)
    state = CharacterState(hp=15, d20={"turning_used": 3})
    said = ENGINE.turn_undead(sheet, 3, "ghoul", 0, dice(12, 1, 1)[0], actor="pc_1", state=state)
    assert said["attempts_left"] == 0 and said["state"].d20 == {"turning_used": 4}
    roll, rng = dice()
    said = ENGINE.turn_undead(sheet, 3, "ghoul", 0, roll, actor="pc_1", state=said["state"])
    assert "4 times a day" in said["note"] and said["attempts_left"] == 0 and "state" not in said
    assert rng.calls == []
    # After a rest the attempts are back.
    rested, _ = ENGINE.rest(sheet, CharacterState(hp=15, d20={"turning_used": 4}), 1)
    assert ENGINE.turn_undead(sheet, 3, "ghoul", 0, dice(12, 1, 1)[0], actor="pc_1", state=rested)["attempts_left"] == 3
    # A character that can't turn is refused, and without a sheet the DM's numbers are used (Cha +0, no count).
    fighter = filled("Fighter", {"fighter": 3}, {})
    assert "can't turn" in ENGINE.turn_undead(fighter, 3, "ghoul", 0, dice()[0], actor="pc_2", state=state)["note"]
    bare = ENGINE.turn_undead(None, 3, "ghoul", 0, dice(12, 1, 1)[0], actor=None)
    assert (bare["max_hd"], bare["total_hd"], bare["attempts_left"], bare.get("state")) == (3, 5, None, None)


def test_uncounted_turnings_in_one_beat_roll_their_own_check():
    # DEL-395: a turning without a sheet counts no attempts, so each is keyed by what is turned and at which level: two
    # in one beat roll two checks. The very same turning asked again is the stored roll: a beat never rolls it twice.
    log = MemoryRollLog()
    rng = ScriptedRng([12, 1, 1, 3])
    shared = Dice(rng, log, "c", "beat")
    ghoul = ENGINE.turn_undead(None, 3, "ghoul", 0, shared, actor=None)
    wight = ENGINE.turn_undead(None, 3, "wight", 0, shared, actor=None)
    assert (ghoul["check"], wight["check"]) == (12, 3)
    rng.assert_done()
    assert ENGINE.turn_undead(None, 3, "ghoul", 0, shared, actor=None)["check"] == 12
    assert ENGINE.turn_undead(None, 5, "", 2, Dice(ScriptedRng([7, 1, 1]), log, "c", "beat"), actor=None)["check"] == 7


def test_unknown_components_count_as_somatic():
    # The SRD exempts only a spell that lacks a somatic component; data without components doesn't show that.
    from delve_srd35.engine import magic

    assert magic._somatic({"components": ""}) and magic._somatic({"components": "V, S, M"})
    assert not magic._somatic({"components": "V (Brd only), M"}) and not magic._somatic({"components": "V, F"})


def test_spell_level_is_the_casters_own():  # R16
    # Sleep is wizard 1 (sorcerer/wizard 1, bard 1); Bless is on no wizard list.
    assert ENGINE.spell_level(wizard(), "Sleep") == 1
    assert ENGINE.spell_level(wizard(), "sleep") == 1
    assert ENGINE.spell_level(wizard(), "Bless") is None
    # A war/good cleric: Magic Weapon is cleric 1 and war 1, Protection from Evil cleric 1 and good 1; Sleep is on none.
    assert ENGINE.spell_level(cleric(), "Magic Weapon") == 1
    assert ENGINE.spell_level(cleric(), "Protection from Evil") == 1
    assert ENGINE.spell_level(cleric(), "Sleep") is None
    # Burning Hands is on no cleric list; the fire domain's 1st-level spell, so a fire cleric's 1.
    fire = filled("Cleric", {"cleric": 1}, {"wis": 15}, domains=["fire", "animal"])
    assert ENGINE.spell_level(fire, "Burning Hands") == 1
    assert ENGINE.spell_level(cleric(), "Burning Hands") is None
    # A fighter casts nothing, and an unknown name is no spell.
    fighter = filled("Fighter", {"fighter": 1}, {})
    assert ENGINE.spell_level(fighter, "Sleep") is None
    assert ENGINE.spell_level(wizard(), "Sleepy Time") is None


def test_memorize_spells_resolves_through_the_engine(srd35_call):  # R16, through core's memorize_spells
    sheet = {"cls": "Wizard", "level": 1, "race": "Elf", "hp_max": 4, "ability_scores": {**TEN, "int": 16}}
    srd35_call("create_character", name="Elowen", sheet=sheet)
    out = srd35_call("memorize_spells", character="Elowen", spells=["sleep", "magic missile"])
    assert out["by_level"] == {"1": ["Sleep", "Magic Missile"]}, out
    refused = srd35_call("memorize_spells", character="Elowen", spells=["Bless"])
    assert refused["error"] == "Bless is on none of Elowen's spell lists."
    sheet = {"cls": "Cleric", "level": 1, "race": "Dwarf", "hp_max": 10, "ability_scores": {**TEN, "wis": 15}}
    srd35_call("create_character", name="Dorna", sheet=sheet)
    srd35_call("set_build", character="Dorna", domains=["war", "good"])
    out = srd35_call("memorize_spells", character="Dorna", spells=["Bless", "Cure Light Wounds", "Magic Weapon"])
    assert out["by_level"] == {"1": ["Bless", "Cure Light Wounds", "Magic Weapon"]}, out


def test_a_spell_is_memorized_whatever_its_apostrophe(srd35_call):  # DEL-401: the data's is curly
    sheet = {"cls": "Wizard", "level": 3, "race": "Elf", "hp_max": 10, "ability_scores": {**TEN, "int": 16}}
    srd35_call("create_character", name="Elowen", sheet=sheet)
    for typed in ("bull's strength", "Bull`s Strength"):
        out = srd35_call("memorize_spells", character="Elowen", spells=[typed])
        assert out["by_level"] == {"2": ["Bull’s Strength"]}, out


def test_a_fighter_casting_is_refused_by_the_engine(srd35_call):  # I3: the per-day cast asks the engine for the level
    sheet = {"cls": "Fighter", "level": 1, "race": "Human", "hp_max": 12, "ability_scores": TEN}
    srd35_call("create_character", name="Bram", sheet=sheet)
    out = srd35_call("cast_spell", character="Bram", spell_name="Sleep")
    assert out["error"] == "Sleep is on none of Bram's spell lists.", out
    assert srd35_call("cast_spell", character="Bram", spell_name="Sleepy Time")["error"] == "No spell 'Sleepy Time'."


def test_turning_takes_the_clerics_level_from_its_sheet():
    # A 3rd-level cleric with Cha 12 passed level 1: the sheet's 3 counts. 13 + 1 = 14 is "13-15: level + 1", 4 HD;
    # the damage 2d6 (4 + 5) + 3 + 1 = 13.
    said = ENGINE.turn_undead(cleric(3, cha=12), 1, "ghoul", 0, dice(13, 4, 5)[0], actor="pc_1",
                              state=CharacterState(hp=15))  # fmt: skip
    assert (said["max_hd"], said["total_hd"], said["destroy_up_to_hd"]) == (4, 13, 1)


def test_knowledge_religion_5_ranks_add_2_to_the_turning_check():  # DEL-389
    # Turn Undead: "+2 bonus on turning checks against undead if you have 5 or more ranks in Knowledge (religion)". A
    # 3rd-level cleric with Cha 12: 13 + 1 = 14 with 4 ranks ("13-15: level + 1", 4 HD); 13 + 1 + 2 = 16 with 5
    # ("16-18: level + 2", 5 HD). The damage takes no bonus: 2d6 (4 + 5) + 3 + 1 = 13 either way.
    def turning(ranks):
        sheet = filled("Cleric", {"cleric": 3}, {"wis": 15, "cha": 12}, domains=["war", "good"],
                       skills={"knowledge-religion": ranks})  # fmt: skip
        return ENGINE.turn_undead(sheet, 3, "ghoul", 0, dice(13, 4, 5)[0], actor="pc_1", state=CharacterState(hp=15))

    four, five = turning(4), turning(5)
    assert (four["check"], four["max_hd"], four["total_hd"], "synergy" in four) == (14, 4, 13, False)
    assert (five["check"], five["max_hd"], five["total_hd"]) == (16, 5, 13)
    assert five["synergy"] == "+2 (Knowledge (religion) 5+ ranks)"


def test_turning_needs_the_damage_to_reach_the_undead():
    # A 3rd-level cleric with Cha 8: 20 - 1 = 19 is "19-21: level + 3", 6 HD; the damage 2d6 (1 + 1) + 3 - 1 = 4 HD of
    # turning damage, too few for one 6-HD undead: it is not turned.
    said = ENGINE.turn_undead(cleric(3, cha=8), 3, "", 6, dice(20, 1, 1)[0], actor="pc_1", state=CharacterState(hp=15))
    assert (said["max_hd"], said["total_hd"], said["turned"], said["destroyed"]) == (6, 4, False, False)


def test_a_druid_prepares_from_the_druid_list():
    # A 1st-level druid with Wis 15: 3 orisons and 1 + 1 bonus = 2 level-1 slots; DC at level 1 is 10 + 1 + 2 = 13.
    sheet = filled("Druid", {"druid": 1}, {"wis": 15})
    assert sheet.d20["derived"]["slots"] == {"0": 3, "1": 2} and sheet.d20["derived"]["dc"]["1"] == 13
    assert ENGINE.can_memorize(sheet, [1, 1], ["Entangle", "Cure Light Wounds"]) is None
    assert ENGINE.can_memorize(sheet, [1], ["Bless"]) == "Bless is not on the druid list."
    assert ENGINE.spell_level(sheet, "Entangle") == 1


def test_a_paladin_prepares_from_4th_level_with_half_its_caster_level():
    # Table: The Paladin gives a 4th-level paladin 0 spells of 1st level, with bonus spells by Wis: Wis 14 gives 1.
    # It has no 0-level spells. A 3rd-level paladin casts none. Its caster level is half its paladin level (SRD).
    assert "casts no spells" in ENGINE.can_memorize(filled("Paladin", {"paladin": 3}, {"wis": 14}), [1], ["Bless"])
    sheet = filled("Paladin", {"paladin": 4}, {"wis": 14})
    assert sheet.d20["derived"]["slots"] == {"1": 1}
    assert ENGINE.can_memorize(sheet, [1], ["Bless"]) is None
    assert ENGINE.can_memorize(sheet, [0], ["Light"]) == "Too many level-0 spells: 1 given, 0 slots available."
    _, said = ENGINE.cast(sheet, CharacterState(hp=30), "Bless", 1, dice()[0])
    assert said["caster_level"] == 2 and said["school"] == "Enchantment"
    # A paladin with Wis 10 has 0 + no bonus: no slots at all.
    assert filled("Paladin", {"paladin": 4}, {"wis": 10}).d20["derived"]["slots"] == {}


def test_a_ranger_prepares_from_4th_level():
    sheet = filled("Ranger", {"ranger": 4}, {"wis": 12})
    assert sheet.d20["derived"]["slots"] == {"1": 1}
    assert ENGINE.can_memorize(sheet, [1], ["Entangle"]) is None
    assert ENGINE.can_memorize(sheet, [1], ["Sleep"]) == "Sleep is not on the ranger list."


def test_an_adept_prepares_from_its_own_list():
    # The adept's list is in its class text, extracted into the spells' levels: bless 1st, cure minor wounds 0.
    sheet = filled("Adept", {"adept": 1}, {"wis": 13})
    assert sheet.d20["derived"]["slots"] == {"0": 3, "1": 2}
    assert ENGINE.spell_level(sheet, "Bless") == 1 and ENGINE.spell_level(sheet, "Cure Minor Wounds") == 0
    assert ENGINE.can_memorize(sheet, [0, 1, 1], ["Cure Minor Wounds", "Bless", "Burning Hands"]) is None
    assert ENGINE.can_memorize(sheet, [1], ["Magic Missile"]) == "Magic Missile is not on the adept list."


def unprepared(cls: str) -> str:
    return (
        f"A {cls} memorizes nothing: it casts any spell it knows (set_build's known), so many a day, with cast_spell."
    )


@pytest.mark.parametrize(("cls", "spell"), [("sorcerer", "Magic Missile"), ("bard", "Cure Light Wounds")])
def test_a_spontaneous_caster_memorizes_nothing(cls, spell):
    # DEL-389 part 2: a sorcerer or bard casts from its spells known (`test_spontaneous`); it memorizes nothing.
    sheet = filled(cls.title(), {cls: 2}, {"cha": 16})
    assert ENGINE.can_memorize(sheet, [1], [spell]) == unprepared(cls)
    assert ENGINE.can_memorize(sheet, [0], []) == unprepared(cls)
    _, said = ENGINE.cast(sheet, CharacterState(hp=8), spell, 1, dice()[0])
    assert said == {"cast": False, "refusal": f"{cls.title()} doesn't know {spell}: the {cls}'s spells known are none "
                                              "yet: set them with set_build's known."}  # fmt: skip
    # No slots: core's per-day cast asks the engine; its class features still play, and no warning stands.
    assert sheet.spell_slots == {}
    assert any(f["id"] == "casting" for f in sheet.d20["derived"]["features"])
    assert "warnings" not in sheet.d20["derived"]


def test_a_sorcerer_and_a_bard_cast_only_what_they_know_in_play(srd35_call):
    for name, cls, spell in (("Sela", "Sorcerer", "magic missile"), ("Bryn", "Bard", "cure light wounds")):
        sheet = {"cls": cls, "level": 2, "race": "Human", "hp_max": 8, "ability_scores": {**TEN, "cha": 16}}
        srd35_call("create_character", name=name, sheet=sheet)
        assert srd35_call("cast_spell", character=name, spell_name=spell)["error"].startswith(f"{name} doesn't know")
        assert srd35_call("memorize_spells", character=name, spells=[spell])["error"] == unprepared(cls.lower())


def test_set_build_no_longer_warns_a_sorcerer_or_bard(srd35_call):
    # Part 1's "can't cast yet" warning is gone with part 2: a sorcerer's, bard's or fighter/sorcerer's build has none.
    for name, cls in (("Sela", "Sorcerer"), ("Bryn", "Bard"), ("Tor", "Fighter")):
        sheet = {"cls": cls, "level": 1, "race": "Human", "hp_max": 8, "ability_scores": {**TEN, "cha": 16}}
        made = srd35_call("create_character", name=name, sheet=sheet)
        built = srd35_call("set_build", character=name, weapon="dagger")
        assert "error" not in built, built
        assert "warnings" not in built and "warnings" not in made["sheet"]["d20"]["derived"]
    multi = {"cls": "Fighter/Sorcerer", "levels": {"fighter": 1, "sorcerer": 1}, "race": "Human", "hp_max": 12,
             "ability_scores": TEN}  # fmt: skip
    srd35_call("create_character", name="Mix", sheet=multi)
    assert "warnings" not in srd35_call("set_build", character="Mix", weapon="dagger")


def test_spell_focus_raises_its_schools_dcs():
    # SRD: Spell Focus "Add +1 to the Difficulty Class for all saving throws against spells from the school of magic
    # you select"; Greater Spell Focus +1 more, stacking. A wizard 5, Int 16: 3rd-level DC 10 + 3 + 3 = 16, 2nd 15.
    # With Spell Focus (evocation), Fireball is DC 17 and Web (conjuration) stays 15; with Greater Spell Focus too, 18.
    focus = {"id": "spell-focus", "choice": "evocation"}
    sheet = filled("Wizard", {"wizard": 5}, {"int": 16}, feats=[focus])
    assert ENGINE.cast(sheet, spent("Fireball"), "Fireball", 3, None)[1]["dc"] == 17
    assert ENGINE.cast(sheet, spent("Web"), "Web", 2, None)[1]["dc"] == 15
    greater = filled("Wizard", {"wizard": 5}, {"int": 16}, feats=[focus, {"id": "greater-spell-focus",
                                                                           "choice": "evocation"}])  # fmt: skip
    assert ENGINE.cast(greater, spent("Fireball"), "Fireball", 3, None)[1]["dc"] == 18
    # The sheet's DCs by level stay the class's own: the school is the spell's.
    assert sheet.d20["derived"]["dc"]["3"] == 16
    # A sorcerer 1, Cha 16, with Spell Focus (enchantment): Sleep from its pool at 10 + 1 + 3 + 1 = 15.
    sorcerer = filled("Sorcerer", {"sorcerer": 1}, {"cha": 16}, known={"sorcerer": ["Sleep"]},
                      feats=[{"id": "spell-focus", "choice": "enchantment"}])  # fmt: skip
    assert ENGINE.cast(sorcerer, CharacterState(hp=4), "Sleep", 1, None)[1]["dc"] == 15
    # A good cleric 1, Wis 15, with Spell Focus (conjuration): Bless converted into Cure Light Wounds (conjuration) at
    # 10 + 1 + 2 + 1 = 14.
    good = replace(filled("Cleric", {"cleric": 1}, {"wis": 15}, domains=["war", "good"],
                          feats=[{"id": "spell-focus", "choice": "conjuration"}]), alignment="Lawful Good")  # fmt: skip
    state = CharacterState(hp=6, memorized=(MemorizedSpell("Bless", 1),))
    assert magic.convert(good, state, "Bless", "", REF)[1]["dc"] == 14


def _einara(srd35_call):
    """A wizard 6, Int 18 with Spell Focus (evocation): Fireball is 10 + 3 + 4 + 1 = DC 18. Fireball is memorized."""
    made = {"cls": "Wizard", "levels": {"wizard": 6}, "race": "Human", "hp_max": 20,
            "ability_scores": {**TEN, "int": 18},
            "d20": {"feats": [{"id": "spell-focus", "choice": "evocation"}]}}  # fmt: skip
    assert "error" not in srd35_call("create_character", name="Einara", sheet=made)
    assert "error" not in srd35_call("memorize_spells", character="Einara", spells=["Fireball", "Fireball"])


def test_a_cast_in_the_round_carries_its_dc(srd35_call):
    # The round's cast entry takes the DC, school and save of its `spells_spent` entry (Spell Focus's +1 in it).
    _einara(srd35_call)
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False)
    out = srd35_call("combat_round", beat="beat-2", actions=[{"caster": "Einara", "spell": "Fireball"}])
    (cast,) = out["actions"]
    (spent,) = out["spells_spent"]
    assert spent["dc"] == 18 and (cast["dc"], cast["school"].lower()) == (18, "evocation"), cast
    assert cast["save"] == magic.spell_row("Fireball")["saving_throw"] == spent["save"]


def test_a_spell_declared_in_setup_combat_has_its_dc_in_round_one(srd35_call):
    # Setup spent the memorized copy, so round 1 has no `spells_spent` entry: the DC is the engine's read.
    _einara(srd35_call)
    declared = [{"caster": "Einara", "spell": "Fireball"}]
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False, spells=declared)
    out = srd35_call("combat_round", beat="beat-2", actions=[])
    (cast,) = out["actions"]
    assert "spells_spent" not in out, out
    assert (cast["dc"], cast["school"].lower()) == (18, "evocation") and cast["save"], cast


def test_spell_numbers_reads_a_cast_and_spends_nothing():
    sheet = filled("Wizard", {"wizard": 5}, {"int": 16}, feats=[{"id": "spell-focus", "choice": "evocation"}])
    state = CharacterState(hp=20)
    assert magic.spell_numbers(sheet, state, "Fireball", REF)["dc"] == 17
    assert magic.spell_numbers(sheet, state, "Web", REF)["dc"] == 15
    assert magic.spell_numbers(sheet, state, "Nonesuch", REF) == {}
