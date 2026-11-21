"""Spontaneous casting (DEL-389 part 2): a sorcerer or bard casts any spell it knows (`set_build(known=…)`), so many of
each level a day (`derived["casting"]`'s `per_day`: the class table's spells per day and Charisma's bonus spells),
counted in `CharacterState.d20["cast"]` until a rest of a day; a sorcerer/cleric casts its sorcerer spells so beside
its cleric's prepared ones (core's `casts_unprepared` hook). A cleric converts a prepared spell into a cure or inflict
spell, a druid into summon nature's ally (`convert_spell`). Each worked example is checked by hand against the SRD's
tables in its comment."""

from __future__ import annotations

from delve_srd35.engine import Srd35Engine
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.characters import CharacterState, Sheet

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
CANTRIPS = ["Light", "Detect Magic", "Ray of Frost", "Mage Hand"]


def dice(*faces: int) -> Dice:
    return Dice(ScriptedRng(faces), MemoryRollLog(), "c", "beat")


def filled(levels: dict[str, int], abilities: dict[str, int], **d20) -> Sheet:
    cls = "/".join(c.title() for c in levels)
    return ENGINE.fill_derived(
        Sheet(label="Sela", cls=cls, race="Human", levels=levels, ability_scores={**TEN, **abilities}, d20=d20), REF
    )


def _make(srd35_call, name, levels, abilities, **sheet):
    cls = "/".join(c.title() for c in levels)
    made = {"cls": cls, "levels": levels, "race": "Human", "hp_max": 12, "ability_scores": {**TEN, **abilities}}
    out = srd35_call("create_character", name=name, sheet={**made, **sheet})
    assert "error" not in out, out
    return out


def _sela(srd35_call, *first):
    """A 1st-level sorcerer with Cha 16 who knows 4 cantrips and Magic Missile and Shield (or `first`)."""
    _make(srd35_call, "Sela", {"sorcerer": 1}, {"cha": 16})
    known = {"sorcerer": [*CANTRIPS, *(first or ("Magic Missile", "Shield"))]}
    built = srd35_call("set_build", character="Sela", known=known)
    assert "error" not in built, built
    return built


def test_sorcerer_1_cha_16_pool():
    # Table: The Sorcerer, 1st: 5 / 3 a day; Cha 16 (+3) gives a bonus 1st-level spell: 5 / 4. Table: Sorcerer Spells
    # Known, 1st: 4 / 2. DC 10 + level + 3. A sorcerer has no slots: its first class's `slots` and `dc` stay empty.
    sheet = filled({"sorcerer": 1}, {"cha": 16})
    derived = sheet.d20["derived"]
    assert derived["casting"] == {"sorcerer": {"ability": "cha", "caster_level": 1, "prepared": False,
                                               "per_day": {"0": 5, "1": 4}, "known": {"0": 4, "1": 2},
                                               "dc": {"0": 13, "1": 14}}}  # fmt: skip
    assert (derived["slots"], derived["dc"], sheet.spell_slots) == ({}, {}, {})
    assert "warnings" not in derived  # the part 1 "can't cast yet" warning is gone
    # Table: The Bard, 2nd: 3 / 0 a day, a 1st-level spell only with Charisma's bonus; Spells Known 5 / 2¹ ("provided
    # the bard has a high enough Charisma score to have a bonus spell of this level"). Cha 12 (+1) gives it; Cha 10
    # (no bonus, and under 11) knows no 1st-level spells.
    bard = filled({"bard": 2}, {"cha": 12}).d20["derived"]["casting"]["bard"]
    assert (bard["per_day"], bard["known"], bard["dc"]) == ({"0": 3, "1": 1}, {"0": 5, "1": 2}, {"0": 11, "1": 12})
    plain = filled({"bard": 2}, TEN).d20["derived"]["casting"]["bard"]
    assert (plain["per_day"], plain["known"]) == ({"0": 3}, {"0": 5})
    # The DM's sheet numbers carry the pool, and the spells known by name.
    numbers = ENGINE.sheet_numbers(filled({"sorcerer": 1}, {"cha": 16}, known={"sorcerer": ["Magic Missile"]}))
    assert numbers["casting"] == derived["casting"] and numbers["known"] == {"sorcerer": ["Magic Missile"]}
    # Sorcerer 6: Table: The Sorcerer 6 / 6 / 5 / 3 a day; Cha 13 (+1, the least that casts 3rd-level spells) adds a
    # bonus 1st: 6 / 7 / 5 / 3. Spells Known 7 / 4 / 2 / 1. DC 10 + level + 1.
    six = filled({"sorcerer": 6}, {"cha": 13}).d20["derived"]["casting"]["sorcerer"]
    pinned = ({"0": 6, "1": 7, "2": 5, "3": 3}, {"0": 7, "1": 4, "2": 2, "3": 1}, {"0": 11, "1": 12, "2": 13, "3": 14})
    assert (six["per_day"], six["known"], six["dc"]) == pinned
    # A single prepared caster's sheet numbers are as before: its slots and DCs alone.
    assert "casting" not in ENGINE.sheet_numbers(filled({"wizard": 1}, {"int": 16}))


def test_sorcerer_casts_a_known_spell_and_spends(srd35_call):
    built = _sela(srd35_call)
    assert built["build"]["known"] == {"sorcerer": [*CANTRIPS, "Magic Missile", "Shield"]}
    assert "warnings" not in built
    out = srd35_call("cast_spell", character="Sela", spell_name="magic missile")
    assert "error" not in out, out
    assert (out["spell"], out["level"], out["dc"], out["school"], out["left_today"]) == (
        "Magic Missile", 1, 14, "Evocation", 3
    )  # fmt: skip
    light = srd35_call("cast_spell", character="Sela", spell_name="Light")
    assert (light["level"], light["dc"], light["left_today"]) == (0, 13, 4)
    state = srd35_call("get_character", ref="Sela")["state"]
    assert state["d20"]["cast"] == {"sorcerer": {"1": 1, "0": 1}}
    # A sorcerer memorizes nothing.
    refused = srd35_call("memorize_spells", character="Sela", spells=["Magic Missile"])
    assert refused["error"].startswith("A sorcerer memorizes nothing: it casts any spell it knows"), refused


def test_sorcerer_refuses_past_the_day_and_unknown(srd35_call):
    _sela(srd35_call)
    for left in (3, 2, 1, 0):
        assert srd35_call("cast_spell", character="Sela", spell_name="Shield")["left_today"] == left
    past = srd35_call("cast_spell", character="Sela", spell_name="Magic Missile")
    assert past["error"] == ("Sela has cast all 4 of the sorcerer's level-1 spells today: they come back with a rest "
                             "of a day.")  # fmt: skip
    unknown = srd35_call("cast_spell", character="Sela", spell_name="Sleep")
    assert unknown["error"] == ("Sela doesn't know Sleep: the sorcerer's spells known are Light, Detect Magic, Ray of "
                                "Frost, Mage Hand, Magic Missile, Shield.")  # fmt: skip
    # set_build's known: no more of a level than the table, each on the class list; a refusal names the count.
    over = srd35_call("set_build", character="Sela", known={"sorcerer": ["Magic Missile", "Shield", "Sleep"]})
    assert "A 1st-level sorcerer knows 2 level-1 spells, not 3." in over["error"], over
    cantrips = srd35_call("set_build", character="Sela", known={"sorcerer": [*CANTRIPS, "Daze"]})
    assert "A 1st-level sorcerer knows 4 level-0 spells, not 5." in cantrips["error"], cantrips
    off = srd35_call("set_build", character="Sela", known={"sorcerer": ["Cure Light Wounds"]})
    assert "Cure Light Wounds is not on the sorcerer list." in off["error"], off
    wrong = srd35_call("set_build", character="Sela", known={"wizard": ["Magic Missile"]})
    assert "Only a sorcerer or bard knows spells" in wrong["error"], wrong
    # A list replaces the one before: Sleep in place of Shield.
    swapped = srd35_call("set_build", character="Sela", known={"sorcerer": ["Magic Missile", "Sleep"]})
    assert swapped["build"]["known"] == {"sorcerer": ["Magic Missile", "Sleep"]}


def test_rest_restores_the_pool(srd35_call):
    _sela(srd35_call)
    srd35_call("cast_spell", character="Sela", spell_name="Magic Missile")
    srd35_call("rest", character="Sela", days=0)  # a rest of no days gives nothing back
    assert srd35_call("get_character", ref="Sela")["state"]["d20"]["cast"] == {"sorcerer": {"1": 1}}
    assert "error" not in (rested := srd35_call("rest", character="Sela", days=1)), rested
    assert "cast" not in srd35_call("get_character", ref="Sela")["state"]["d20"]
    assert srd35_call("cast_spell", character="Sela", spell_name="Magic Missile")["left_today"] == 3


def test_sorcerer_3_cleric_3_casts_both(srd35_call):
    # Sorcerer 3: 6 / 5 a day, Cha 16 a bonus 1st: 6 / 6, DC 10 + level + 3; known 5 / 3. Cleric 3 with Wis 14 and the
    # domain slots: 4 / 4 / 3, DC 10 + level + 2. The sorcerer comes first: `slots` is {} and the sheet's slots are the
    # cleric's pool.
    sheet = filled({"sorcerer": 3, "cleric": 3}, {"cha": 16, "wis": 14}, domains=["war", "good"])
    casting = sheet.d20["derived"]["casting"]
    assert casting["sorcerer"] | {} == {"ability": "cha", "caster_level": 3, "prepared": False,
                                        "per_day": {"0": 6, "1": 6}, "known": {"0": 5, "1": 3},
                                        "dc": {"0": 13, "1": 14}}  # fmt: skip
    assert casting["cleric"]["slots"] == {"0": 4, "1": 4, "2": 3} and sheet.spell_slots == {0: 4, 1: 4, 2: 3}
    numbers = ENGINE.sheet_numbers(sheet)
    assert numbers["slots"] == {} and numbers["casting"]["cleric"]["slots"] == {"0": 4, "1": 4, "2": 3}

    _make(srd35_call, "Sela", {"sorcerer": 3, "cleric": 3}, {"cha": 16, "wis": 14})
    known = {"sorcerer": ["Magic Missile", "Protection from Evil"]}
    assert "error" not in (b := srd35_call("set_build", character="Sela", domains=["war", "good"], known=known)), b
    memorized = srd35_call("memorize_spells", character="Sela", spells=["Bless", "Protection from Evil"])
    assert "error" not in memorized, memorized
    bless = srd35_call("cast_spell", character="Sela", spell_name="Bless")
    assert (bless["class"], bless["dc"]) == ("cleric", 13), bless
    # The core hook: a sorcerer spell with no memorized copy goes to the sorcerer's pool, slots or not.
    missile = srd35_call("cast_spell", character="Sela", spell_name="Magic Missile")
    assert (missile["class"], missile["dc"], missile["caster_level"], missile["left_today"]) == ("sorcerer", 14, 3, 5)
    # Protection from Evil, prepared by the cleric and known by the sorcerer: the memorized copy first, then the pool.
    first = srd35_call("cast_spell", character="Sela", spell_name="Protection from Evil")
    second = srd35_call("cast_spell", character="Sela", spell_name="Protection from Evil")
    assert (first["class"], first["dc"], "left_today" in first) == ("cleric", 13, False), first
    assert (second["class"], second["dc"], second["left_today"]) == ("sorcerer", 14, 4), second
    state = srd35_call("get_character", ref="Sela")["state"]
    assert state["d20"]["cast"] == {"sorcerer": {"1": 2}}
    # A cleric spell not known by the sorcerer is core's "already cast"; a sorcerer spell isn't memorized.
    assert "already been cast" in srd35_call("cast_spell", character="Sela", spell_name="Bless")["error"]
    refused = srd35_call("memorize_spells", character="Sela", spells=["Magic Missile"])
    assert refused["error"].startswith("Magic Missile is a sorcerer spell. A sorcerer memorizes nothing"), refused


def test_bard_in_light_armour_has_no_failure(srd35_call):
    # The bard "can cast bard spells while wearing light armor without incurring the normal arcane spell failure
    # chance"; a shield's it doesn't ignore, nor medium or heavy armour's. A sorcerer has it in any armour: a chain
    # shirt is 20%.
    _make(srd35_call, "Lyra", {"bard": 1}, {"cha": 12})
    srd35_call("set_build", character="Lyra", armor="chain shirt", known={"bard": ["Daze", "Lullaby", "Flare"]})
    daze = srd35_call("cast_spell", character="Lyra", spell_name="Daze")
    assert "error" not in daze and "spell_failure" not in daze, daze
    srd35_call("set_build", character="Lyra", shield="buckler")
    lullaby = srd35_call("cast_spell", character="Lyra", spell_name="Lullaby")
    assert lullaby["spell_failure"]["chance"] == 5, lullaby  # the buckler's 5% alone: the chain shirt's is ignored
    srd35_call("rest", character="Lyra", days=1)  # her 2 cantrips a day are spent
    srd35_call("set_build", character="Lyra", armor="scale mail")
    heavier = srd35_call("cast_spell", character="Lyra", spell_name="Daze")
    assert heavier["spell_failure"]["chance"] == 30, heavier  # medium armour: scale mail's 25% and the buckler's 5%
    _sela(srd35_call)
    srd35_call("set_build", character="Sela", armor="chain shirt")
    missile = srd35_call("cast_spell", character="Sela", spell_name="Magic Missile")
    assert missile.get("spell_failure", {}).get("chance") == 20 or missile.get("lost"), missile
    # A spell lost to the failure is one of the day's: it says lost, and the day's count keeps it.
    sorcerer = filled({"sorcerer": 1}, {"cha": 16}, armor="chain shirt", known={"sorcerer": ["Magic Missile"]})
    state, said = ENGINE.cast(sorcerer, CharacterState(hp=4), "Magic Missile", 1, dice(20), actor="chr_1")
    assert said == {"lost": True, "level": 1, "left_today": 3,
                    "spell_failure": {"chance": 20, "roll": 20, "failed": True}}  # fmt: skip
    assert state.d20["cast"] == {"sorcerer": {"1": 1}}
    # Flare has no somatic part: no roll at all.
    bard = filled({"bard": 1}, {"cha": 12}, armor="scale mail", known={"bard": ["Flare"]})
    assert "spell_failure" not in ENGINE.cast(bard, CharacterState(hp=4), "Flare", 0, None)[1]


def test_cleric_converts_a_prepared_spell_to_cure(srd35_call):
    # A 1st-level cleric, Wis 14: 3 / 1 + 1 + 1 (the domain slot); DC 10 + 1 + 2 = 13. "A good cleric … can 'lose' any
    # prepared spell that is not a domain spell in order to cast any cure spell" of its level: cure light wounds at
    # 1st. An evil cleric inflicts; a neutral one by the energy it channels.
    for name, alignment in (("Hesk", "Neutral Good"), ("Vor", "Lawful Evil"), ("Ise", "True Neutral")):
        _make(srd35_call, name, {"cleric": 1}, {"wis": 14}, alignment=alignment)
        srd35_call("set_build", character=name, domains=["travel", "war"])
        out = srd35_call("memorize_spells", character=name, spells=["Light", "Bless", "Bless", "Longstrider"])
        assert "error" not in out, out
    cure = srd35_call("convert_spell", character="Hesk", prepared="bless")
    assert "error" not in cure, cure
    assert (cure["spell"], cure["level"], cure["converted"], cure["converted_level"], cure["dc"], cure["school"]) == (
        "Cure Light Wounds", 1, "Bless", 1, 13, "Conjuration"
    )  # fmt: skip
    assert cure["remaining"] == {"1": 2}  # the other Bless and Longstrider
    memorized = srd35_call("get_character", ref="Hesk")["state"]["memorized"]
    assert [(s["name"], s["cast"]) for s in memorized][1:3] == [("Bless", True), ("Bless", False)]
    assert srd35_call("convert_spell", character="Vor", prepared="Bless")["spell"] == "Inflict Light Wounds"
    neutral = srd35_call("convert_spell", character="Ise", prepared="Bless")
    assert neutral["error"].startswith("A neutral cleric converts into cure or inflict spells by the energy"), neutral
    assert "error" not in srd35_call("set_build", character="Ise", choices={"energy": "negative"})
    assert srd35_call("convert_spell", character="Ise", prepared="Bless", into="inflict light wounds")["spell"] == (
        "Inflict Light Wounds"
    )
    # Not a domain spell, not a 0-level one, nothing but the spell of its level, and only an uncast copy.
    domain = srd35_call("convert_spell", character="Hesk", prepared="Longstrider")
    assert domain["error"] == "Longstrider is the domain slot's spell: a domain spell doesn't convert."
    assert srd35_call("convert_spell", character="Hesk", prepared="Light")["error"] == (
        "Only a prepared spell of 1st level or higher converts."
    )
    wrong = srd35_call("convert_spell", character="Hesk", prepared="Bless", into="Cure Moderate Wounds")
    assert wrong["error"] == ("A level-1 Bless of the cleric converts into a spell of level 1 or lower of these: Cure "
                              "Light Wounds; not Cure Moderate Wounds.")  # fmt: skip
    srd35_call("convert_spell", character="Hesk", prepared="Bless")
    assert srd35_call("convert_spell", character="Hesk", prepared="Bless")["error"] == (
        "Hesk has no uncast copy of Bless memorized."
    )
    # A wizard's prepared spell doesn't convert.
    _make(srd35_call, "Odo", {"wizard": 1}, {"int": 14})
    srd35_call("memorize_spells", character="Odo", spells=["Sleep"])
    assert srd35_call("convert_spell", character="Odo", prepared="Sleep")["error"].startswith(
        "A wizard's prepared spell doesn't convert"
    )


def test_druid_converts_to_summon_natures_ally(srd35_call):
    # Table: The Druid, 3rd: 4 / 2 / 1; Wis 14 a bonus 1st and 2nd: 4 / 3 / 2, DC 10 + level + 2. "She can 'lose' a
    # prepared spell in order to cast any summon nature's ally spell" of its level: Barkskin (2nd) into SNA II.
    _make(srd35_call, "Fen", {"druid": 3}, {"wis": 14})
    assert "error" not in srd35_call("memorize_spells", character="Fen", spells=["Entangle", "Barkskin"])
    two = srd35_call("convert_spell", character="Fen", prepared="Barkskin")
    assert (two["spell"], two["level"], two["dc"], two["school"]) == ("Summon Nature’s Ally II", 2, 14, "Conjuration")
    one = srd35_call("convert_spell", character="Fen", prepared="Entangle", into="summon nature's ally i")
    assert (one["spell"], one["dc"], one["remaining"]) == ("Summon Nature’s Ally I", 13, {"1": 0}), one


def test_a_cleric_converts_into_a_lower_level_spell(srd35_call):
    # SRD: "any cure spell of the same spell level or lower". Cleric 3, Wis 14: a 2nd-level Hold Person converts into
    # Cure Light Wounds (DC 10 + 1 + 2 = 13) or, by default, the highest, Cure Moderate Wounds (DC 14).
    _make(srd35_call, "Hesk", {"cleric": 3}, {"wis": 14}, alignment="Neutral Good")
    srd35_call("set_build", character="Hesk", domains=["travel", "war"])
    assert "error" not in srd35_call("memorize_spells", character="Hesk", spells=["Hold Person", "Hold Person"])
    light = srd35_call("convert_spell", character="Hesk", prepared="Hold Person", into="cure light wounds")
    assert (light["spell"], light["level"], light["converted_level"], light["dc"]) == ("Cure Light Wounds", 1, 2, 13)
    assert light["remaining"] == {"2": 1}  # the copy was spent from the 2nd level: the other Hold Person is left
    high = srd35_call("convert_spell", character="Hesk", prepared="Hold Person")
    assert (high["spell"], high["level"], high["dc"], high["remaining"]) == ("Cure Moderate Wounds", 2, 14, {"2": 0})
    # A 9th-level copy: no cure spell is 9th, so the highest is Mass Cure Critical Wounds, 8th. Cleric 17, Wis 20:
    # DC 10 + 8 + 5 = 23.
    _make(srd35_call, "Ama", {"cleric": 17}, {"wis": 20}, alignment="Lawful Good")
    srd35_call("set_build", character="Ama", domains=["travel", "war"])
    assert "error" not in srd35_call("memorize_spells", character="Ama", spells=["Implosion"])
    mass = srd35_call("convert_spell", character="Ama", prepared="Implosion")
    assert (mass["spell"], mass["level"], mass["converted_level"], mass["dc"]) == (
        "Cure Critical Wounds, Mass", 8, 9, 23
    )  # fmt: skip
    # A druid 5 (Wis 14): a 3rd-level Call Lightning into Summon Nature's Ally I, DC 10 + 1 + 2.
    _make(srd35_call, "Fen", {"druid": 5}, {"wis": 14})
    assert "error" not in srd35_call("memorize_spells", character="Fen", spells=["Call Lightning"])
    one = srd35_call("convert_spell", character="Fen", prepared="Call Lightning", into="Summon Nature's Ally I")
    assert (one["spell"], one["level"], one["converted_level"], one["dc"]) == ("Summon Nature’s Ally I", 1, 3, 13)


def test_a_domain_slots_spell_on_the_cleric_list_doesnt_convert(srd35_call):
    # Cleric 1, Wis 14: 1 + 1 ordinary 1st-level slots and the domain slot. Bless, Bless and Magic Weapon (war 1, also
    # cleric 1): the two Bless fill the ordinary slots, so Magic Weapon holds the domain slot and can't convert. With
    # two Magic Weapons, either can sit in an ordinary slot: one converts.
    loadouts = {"Hesk": ["Bless", "Bless", "Magic Weapon"], "Ora": ["Bless", "Magic Weapon", "Magic Weapon"]}
    for name, spells in loadouts.items():
        _make(srd35_call, name, {"cleric": 1}, {"wis": 14}, alignment="Neutral Good")
        srd35_call("set_build", character=name, domains=["war", "travel"])
        assert "error" not in srd35_call("memorize_spells", character=name, spells=spells)
    bound = srd35_call("convert_spell", character="Hesk", prepared="Magic Weapon")
    assert bound["error"] == ("Magic Weapon holds the level-1 domain slot (the other level-1 spells fill the rest): a "
                              "domain spell doesn't convert.")  # fmt: skip
    assert srd35_call("convert_spell", character="Hesk", prepared="Bless")["spell"] == "Cure Light Wounds"
    assert srd35_call("convert_spell", character="Ora", prepared="Magic Weapon")["spell"] == "Cure Light Wounds"


def test_only_a_neutral_cleric_chooses_its_energy(srd35_call):
    _make(srd35_call, "Hesk", {"cleric": 1}, {"wis": 14}, alignment="Neutral Good")
    refused = srd35_call("set_build", character="Hesk", choices={"energy": "negative"})
    assert "A good cleric channels positive energy: only a neutral cleric chooses." in refused["error"], refused
    _make(srd35_call, "Vor", {"cleric": 1}, {"wis": 14}, alignment="Chaotic Evil")
    refused = srd35_call("set_build", character="Vor", choices={"energy": "positive"})
    assert "An evil cleric channels negative energy: only a neutral cleric chooses." in refused["error"], refused
    _make(srd35_call, "Ise", {"cleric": 1}, {"wis": 14}, alignment="True Neutral")
    assert "error" not in srd35_call("set_build", character="Ise", choices={"energy": "positive"})


def _mixed(srd35_call, name, known):
    _make(srd35_call, name, {"sorcerer": 3, "cleric": 3}, {"cha": 16, "wis": 14})
    built = srd35_call("set_build", character=name, domains=["war", "good"], known={"sorcerer": known})
    assert "error" not in built, built


def test_core_says_which_cast_is_from_the_pool(srd35_call):
    # The two cases the engine once had to guess (core now passes `unprepared`). Re-memorizing the same list mid-day:
    # the new copy is the cleric's, then the pool. Sorcerer 3, Cha 16: 6 1st-level spells a day.
    _mixed(srd35_call, "Sela", ["Protection from Evil"])
    srd35_call("memorize_spells", character="Sela", spells=["Protection from Evil"])
    assert srd35_call("cast_spell", character="Sela", spell_name="Protection from Evil")["class"] == "cleric"
    srd35_call("memorize_spells", character="Sela", spells=["Protection from Evil"])
    again = srd35_call("cast_spell", character="Sela", spell_name="Protection from Evil")
    assert (again["class"], "left_today" in again) == ("cleric", False), again
    assert "cast" not in (srd35_call("get_character", ref="Sela")["state"].get("d20") or {})
    pool = srd35_call("cast_spell", character="Sela", spell_name="Protection from Evil")
    assert (pool["class"], pool["left_today"]) == ("sorcerer", 5), pool
    # Learning the spell after a copy of it was cast the same day: the next cast is the pool's, not a free one.
    _mixed(srd35_call, "Tam", ["Magic Missile"])
    srd35_call("memorize_spells", character="Tam", spells=["Protection from Evil"])
    assert srd35_call("cast_spell", character="Tam", spell_name="Protection from Evil")["class"] == "cleric"
    srd35_call("set_build", character="Tam", known={"sorcerer": ["Magic Missile", "Protection from Evil"]})
    learnt = srd35_call("cast_spell", character="Tam", spell_name="Protection from Evil")
    assert (learnt["class"], learnt["left_today"]) == ("sorcerer", 5), learnt
    assert srd35_call("get_character", ref="Tam")["state"]["d20"]["cast"] == {"sorcerer": {"1": 1}}


def test_a_sorcerer_clerics_pool_spell_in_a_round(srd35_call):
    # A round spends a sorcerer/cleric's sorcerer spell from the pool, as it spends the cleric's memorized copy: the
    # prompt tells the DM not to call cast_spell for a spell declared in the round (DEL-389 part 5, F2).
    _mixed(srd35_call, "Sela", ["Magic Missile"])
    srd35_call("memorize_spells", character="Sela", spells=["Bless"])
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False)
    # Bless: the cleric's copy (DC 10 + 1 + Wis 2); Magic Missile: one of the sorcerer's 6 1st-level spells a day.
    blessed = srd35_call("combat_round", beat="beat-1", actions=[{"caster": "Sela", "spell": "Bless"}])
    (memorized,) = blessed["spells_spent"]
    assert (memorized["spell"], memorized["class"], memorized["dc"]) == ("Bless", "cleric", 13), memorized
    assert "cast" not in (srd35_call("get_character", ref="Sela")["state"].get("d20") or {})
    action = [{"caster": "Sela", "spell": "Magic Missile", "target": "Goblin"}]
    out = srd35_call("combat_round", beat="beat-2", actions=action)
    assert "error" not in out, out
    (pooled,) = out["spells_spent"]
    assert pooled == {"caster": "Sela", "spell": "Magic Missile", "level": 1, "dc": 14, "school": "Evocation",
                      "save": "None", "left_today": 5, "class": "sorcerer", "caster_level": 3}, pooled  # fmt: skip
    assert list(out)[-1] == "status", list(out)
    assert srd35_call("get_character", ref="Sela")["state"]["d20"]["cast"] == {"sorcerer": {"1": 1}}
    assert srd35_call("cast_spell", beat="beat-3", character="Sela", spell_name="Magic Missile")["left_today"] == 4


def test_a_sorcerers_round_spends_its_pool_and_refuses_past_it(srd35_call):
    # Sorcerer 1, Cha 16: 3 + 1 bonus = 4 1st-level spells a day, DC 10 + 1 + 3 = 14. Each round's declared Magic
    # Missile is one of them; the 5th is refused before the round is resolved, as cast_spell refuses it.
    _sela(srd35_call)
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False)
    missile = [{"caster": "Sela", "spell": "Magic Missile", "target": "Goblin"}]
    for n, left in enumerate([3, 2, 1, 0]):
        out = srd35_call("combat_round", beat=f"beat-{n}", actions=missile)
        assert "error" not in out, out
        (spent,) = out["spells_spent"]
        assert (spent["dc"], spent["save"], spent["left_today"]) == (14, "None", left), spent
    before = srd35_call("combat_status")["round"]
    past = srd35_call("combat_round", beat="beat-9", actions=missile)
    assert past["error"] == ("Sela has cast all 4 of the sorcerer's level-1 spells today: they come back with a rest "
                             "of a day.")  # fmt: skip
    assert srd35_call("combat_status")["round"] == before  # nothing of the round was resolved
    assert srd35_call("get_character", ref="Sela")["state"]["d20"]["cast"] == {"sorcerer": {"1": 4}}
    # A cantrip comes from its own level's pool; a spell it doesn't know is refused as cast_spell refuses it.
    light = srd35_call("combat_round", beat="beat-10", actions=[{"caster": "Sela", "spell": "Light"}])
    assert light["spells_spent"][0]["level"] == 0, light
    unknown = srd35_call("combat_round", beat="beat-11", actions=[{"caster": "Sela", "spell": "Sleep"}])
    assert unknown["error"].startswith("Sela doesn't know Sleep"), unknown


def test_a_hit_before_the_sorcerers_turn_leaves_her_spell(srd35_call):
    # 3.5 casts a spell of one action on the caster's own turn (DEL-433): a goblin acting earlier in the round and
    # hitting Sela doesn't spoil her Magic Missile, which is cast and spent on her turn.
    _make(srd35_call, "Sela", {"sorcerer": 1}, {"cha": 16, "dex": 3})
    srd35_call("set_build", character="Sela", known={"sorcerer": [*CANTRIPS, "Magic Missile", "Shield"]})
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False)
    srd35_call("update_combatant", id="Goblin", attack_bonus=40)
    actions = [
        {"caster": "Sela", "spell": "Magic Missile", "target": "Goblin"},
        {"attacker": "Goblin", "target": "Sela"},
    ]
    out = srd35_call("combat_round", beat="beat-2", actions=actions)
    assert "error" not in out, out
    order = [a.get("caster") or a.get("attacker") for a in out["actions"]]
    assert order == ["Goblin", "Sela"], out["actions"]  # Dex 3's −4: the goblin acts first
    swing, cast = out["actions"]
    assert swing["hit"] and not swing["spell_disrupted"] and "spell disrupted" not in " ".join(swing["notes"]), swing
    assert cast["cast"] is True and out["outcomes"]["interrupted"] == [], out
    assert out["spells_spent"][0]["left_today"] == 3


def test_a_spell_declared_in_setup_combat_is_round_ones_cast(srd35_call):
    # setup_combat's spells are round 1's actions: setup spends nothing, round 1 spends the cast once, whether it is
    # declared again (the DM's declaration replaces setup's) or left to setup's. A cast the pool can't pay for refuses
    # the setup, leaving no fight (live run 2: one cast was spent twice).
    _sela(srd35_call)
    missile = [{"caster": "Sela", "spell": "Magic Missile", "target": "Goblin"}]
    out = srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False, spells=missile)
    assert "error" not in out and "spells_spent" not in out, out
    assert "cast" not in (srd35_call("get_character", ref="Sela")["state"].get("d20") or {})
    again = srd35_call("combat_round", beat="beat-2", actions=missile)
    (spent,) = again["spells_spent"]
    assert (spent["spell"], spent["dc"], spent["left_today"]) == ("Magic Missile", 14, 3), spent
    assert srd35_call("get_character", ref="Sela")["state"]["d20"]["cast"] == {"sorcerer": {"1": 1}}
    assert "spells_spent" not in srd35_call("combat_round", beat="beat-3", actions=[])  # nothing left marked
    srd35_call("end_combat")
    # Left to setup's declaration, round 1 casts it and spends it once.
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False, spells=missile)
    (spent,) = srd35_call("combat_round", beat="beat-4", actions=[])["spells_spent"]
    assert spent["left_today"] == 2, spent
    srd35_call("end_combat")
    for _ in range(2):
        srd35_call("cast_spell", character="Sela", spell_name="Shield")
    refused = srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1}], surprise=False, spells=missile)
    assert "has cast all 4" in refused["error"], refused
    assert "error" in srd35_call("combat_status")


def test_a_prepared_and_known_caster_pays_once_for_a_long_spell(srd35_call):
    # DEL-458: a sorcerer/cleric who has Summon Monster I (a round long) both memorized and known declares it at setup
    # and again in round 1. It goes on into round 2 and is spent once, from one source: the cleric's copy or the
    # pool's day, never both.
    _mixed(srd35_call, "Sela", ["Summon Monster I"])
    srd35_call("memorize_spells", character="Sela", spells=["Summon Monster I"])
    summon = [{"caster": "Sela", "spell": "Summon Monster I"}]
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False, spells=summon)
    spent = []
    for beat in ("beat-1", "beat-2"):
        out = srd35_call("combat_round", beat=beat, actions=summon if beat == "beat-1" else [])
        assert "error" not in out, out
        spent += out.get("spells_spent", [])
    assert len(spent) == 1, spent
    cast = srd35_call("get_character", ref="Sela")["state"]
    pooled = (cast["d20"] or {}).get("cast")
    copies = [m["cast"] for m in cast["memorized"] if m["name"] == "Summon Monster I"]
    assert (pooled is None) != all(copies), (pooled, copies)  # the pool or the copy was spent, not both


def _sela_and_goblin(srd35_call, *known):
    """Sela (Dex 3, so the goblin acts first), and a goblin that always hits."""
    _make(srd35_call, "Sela", {"sorcerer": 1}, {"cha": 16, "dex": 3})
    srd35_call("set_build", character="Sela", known={"sorcerer": [*CANTRIPS, *(known or ("Magic Missile", "Shield"))]})
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False)
    srd35_call("update_combatant", id="Goblin", attack_bonus=40)


def test_a_caster_downed_before_its_turn_keeps_its_spell(srd35_call):
    # She never gets to cast: the spell is not spent (live run 2: spent though "down — cannot act"). The goblin's
    # damage is 10, so its hit drops her below 0 (at exactly 0 she would be disabled, and cast: DEL-434).
    _sela_and_goblin(srd35_call)
    srd35_call("update_combatant", id="Sela", stats={"hp": 1})
    srd35_call("update_combatant", id="Goblin", damage="10")
    actions = [
        {"caster": "Sela", "spell": "Magic Missile", "target": "Goblin"},
        {"attacker": "Goblin", "target": "Sela"},
    ]
    out = srd35_call("combat_round", beat="beat-2", actions=actions)
    assert "error" not in out, out
    (cast,) = [a for a in out["actions"] if a.get("caster") == "Sela"]
    assert "skipped" in cast and "spells_spent" not in out, out
    assert "cast" not in (srd35_call("get_character", ref="Sela")["state"].get("d20") or {})


def test_a_spoilt_cast_is_spent(srd35_call):
    # A spell of a round (Summon Monster I) is under way through the round: the goblin's hit spoils it, and a spell
    # lost so is one of the day's (the SRD: a disrupted spell is lost).
    _sela_and_goblin(srd35_call, "Magic Missile", "Summon Monster I")
    actions = [{"caster": "Sela", "spell": "Summon Monster I"}, {"attacker": "Goblin", "target": "Sela"}]
    out = srd35_call("combat_round", beat="beat-2", actions=actions)
    (cast,) = [a for a in out["actions"] if a.get("caster") == "Sela"]
    assert cast["cast"] is False, cast
    (spent,) = out["spells_spent"]
    assert (spent["spell"], spent["left_today"]) == ("Summon Monster I", 3), spent


def _marked(srd35_call, name="Sela"):
    (c,) = [c for c in srd35_call("combat_status")["combatants"] if c["name"] == name]
    return (c.get("d20") or {}).get("pool_spell")


def test_a_cast_spent_leaves_no_mark_for_the_next_round(srd35_call):
    # Her last 1st-level cast, declared in setup, is spent in round 1; round 2 without her is not refused for it.
    _sela(srd35_call)
    for _ in range(3):
        srd35_call("cast_spell", character="Sela", spell_name="Shield")
    missile = [{"caster": "Sela", "spell": "Magic Missile", "target": "Goblin"}]
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False, spells=missile)
    assert _marked(srd35_call) == "Magic Missile"
    (spent,) = srd35_call("combat_round", beat="beat-2", actions=missile)["spells_spent"]
    assert spent["left_today"] == 0 and _marked(srd35_call) is None
    second = srd35_call("combat_round", beat="beat-3", actions=[{"attacker": "Goblin", "target": "Sela"}])
    assert "error" not in second and "spells_spent" not in second, second


def test_a_continuing_spell_keeps_its_mark_until_it_is_done(monkeypatch):
    # A spell of more than a round carries over: its mark stays while the round says it `continues`, and is cleared
    # when a later round casts (and spends) it. No sorcerer spell of the SRD takes so long in a fight, so the round's
    # answers are core's shapes, given.
    from types import SimpleNamespace

    from delve_srd35.engine import tools as srd35_tools

    marks: dict = {}
    spent: list = []
    monkeypatch.setattr(srd35_tools, "_mark", lambda ctx, changes: marks.update(changes))
    monkeypatch.setattr(srd35_tools, "_pool_cast", lambda ctx, who, spell: spent.append(spell) or {"spell": spell})
    pool = ("c", (SimpleNamespace(id="chr"), "X"))
    monkeypatch.setattr(srd35_tools, "_round_pool", lambda ctx, actions: (dict([pool]), set()))
    ctx = SimpleNamespace(campaign_id="cmp", storage=SimpleNamespace(combats=SimpleNamespace(live=lambda _: None)))
    for entry in ({"caster_id": "c", "spell": "X", "continues": True}, {"caster_id": "c", "spell": "X", "cast": True}):
        core = SimpleNamespace(fn=lambda ctx, args, entry=entry: {"actions": [entry], "status": {}})
        srd35_tools._combat_round(core)(ctx, {"actions": []})
        if "continues" in entry:
            assert (marks, spent) == ({"c": "X"}, []), (marks, spent)
    assert (marks, spent) == ({"c": None}, ["X"]), (marks, spent)


def test_a_remade_combatant_keeps_its_declared_pool_spell(srd35_call):
    # A change to the sheet between setup and round 1 makes her combatant again (set_build's weapon): the mark stays,
    # and round 1 still spends the cast.
    _sela(srd35_call)
    missile = [{"caster": "Sela", "spell": "Magic Missile", "target": "Goblin"}]
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False, spells=missile)
    assert "error" not in srd35_call("set_build", character="Sela", weapon="quarterstaff")
    assert _marked(srd35_call) == "Magic Missile"
    (spent,) = srd35_call("combat_round", beat="beat-2", actions=[])["spells_spent"]
    assert spent["left_today"] == 3, spent


def test_a_round_giving_the_caster_another_action_clears_setups_spell(srd35_call):
    # Final review M1: setup declares her Magic Missile, but round 1 has her stab instead: the declaration is replaced,
    # its mark gone. Her last cast spent later through cast_spell, a round leaving her out is not refused for it.
    _sela(srd35_call)
    for _ in range(3):
        srd35_call("cast_spell", character="Sela", spell_name="Shield")
    missile = [{"caster": "Sela", "spell": "Magic Missile", "target": "Goblin"}]
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False, spells=missile)
    first = srd35_call("combat_round", beat="beat-2", actions=[{"attacker": "Sela", "target": "Goblin"}])
    assert "error" not in first and "spells_spent" not in first, first
    assert _marked(srd35_call) is None
    assert "error" not in srd35_call("cast_spell", character="Sela", spell_name="Magic Missile")
    second = srd35_call("combat_round", beat="beat-3", actions=[{"attacker": "Goblin", "target": "Sela"}])
    assert "error" not in second and "spells_spent" not in second, second


def test_a_round_declared_pool_spell_rolls_arcane_spell_failure(srd35_call):
    # Final review (optional): a bard in scale mail (medium, 25%) casts Daze declared in the round; its spells_spent
    # entry carries the failure roll, and a spell lost to it is still one of the day's.
    _make(srd35_call, "Lyra", {"bard": 1}, {"cha": 12})
    srd35_call("set_build", character="Lyra", armor="scale mail", known={"bard": ["Daze", "Lullaby", "Flare"]})
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False)
    out = srd35_call("combat_round", beat="beat-2", actions=[{"caster": "Lyra", "spell": "Daze", "target": "Goblin"}])
    assert "error" not in out, out
    (spent,) = out["spells_spent"]
    assert spent["spell_failure"]["chance"] == 25, spent
    assert spent.get("lost", False) is spent["spell_failure"]["failed"], spent
    assert srd35_call("get_character", ref="Lyra")["state"]["d20"]["cast"] == {"bard": {"0": 1}}


def test_a_pool_cast_in_the_round_carries_its_dc(srd35_call):
    # A sorcerer's Magic Missile from its pool: DC 10 + 1 + Cha 3 = 14, and the round's cast entry says so (the DM
    # read a DC off the sheet when it had none, DEL-429).
    _sela(srd35_call)
    srd35_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False)
    action = [{"caster": "Sela", "spell": "Magic Missile", "target": "Goblin"}]
    out = srd35_call("combat_round", beat="beat-2", actions=action)
    (cast,) = out["actions"]
    assert (cast["dc"], cast["school"].lower(), cast["save"]) == (14, "evocation", "None"), cast
