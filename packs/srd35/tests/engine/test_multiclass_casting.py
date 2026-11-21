"""A casting pool per class for multiclass casters (DEL-389 part 2): each prepared class has its own slots and DCs
(`derived["casting"]`), the sheet's `spell_slots` is their sum, and a memorized copy is cast as the class it is
assigned to, computed from the memorized list (never stored). Each worked example is checked by hand against the SRD's
tables in its comment."""

from __future__ import annotations

from dataclasses import replace

from delve_srd35.engine import Srd35Engine, numbers
from delve_srd35.reference import Srd35Reference

from delve.domain.characters import CharacterState, MemorizedSpell, Sheet

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
SCORES = {**TEN, "wis": 14, "int": 16}


def filled(levels: dict[str, int], abilities: dict[str, int], **d20) -> Sheet:
    cls = "/".join(c.title() for c in levels)
    return ENGINE.fill_derived(
        Sheet(label="Ansel", cls=cls, race="Human", levels=levels, ability_scores={**TEN, **abilities}, d20=d20), REF
    )


def mystic(**d20) -> Sheet:
    return filled({"cleric": 3, "wizard": 3}, SCORES, domains=["war", "good"], **d20)


def _ansel(srd35_call, **build):
    sheet = {"cls": "Cleric/Wizard", "levels": {"cleric": 3, "wizard": 3}, "race": "Human", "hp_max": 24,
             "ability_scores": SCORES}  # fmt: skip
    assert "error" not in (made := srd35_call("create_character", name="Ansel", sheet=sheet)), made
    assert "error" not in (built := srd35_call("set_build", character="Ansel", domains=["war", "good"], **build)), built


def test_cleric_3_wizard_3_pools():
    # Table: The Cleric, 3rd: 4 / 2+1 / 1+1. Wis 14 (+2) gives a bonus spell of 1st and 2nd: 4 / 4 / 3, DCs 10 + level
    # + 2. Table: The Wizard, 3rd: 4 / 2 / 1. Int 16 (+3) gives a bonus spell of 1st to 3rd: 4 / 3 / 2, DCs + 3.
    sheet = mystic()
    derived = sheet.d20["derived"]
    assert derived["casting"] == {
        "cleric": {"ability": "wis", "caster_level": 3, "prepared": True,
                   "slots": {"0": 4, "1": 4, "2": 3}, "dc": {"0": 12, "1": 13, "2": 14}},
        "wizard": {"ability": "int", "caster_level": 3, "prepared": True,
                   "slots": {"0": 4, "1": 3, "2": 2}, "dc": {"0": 13, "1": 14, "2": 15}},
    }  # fmt: skip
    # The first casting class's slots and DCs stay where Phase 2 reads them; the sheet's slots are the sum.
    assert derived["slots"] == {"0": 4, "1": 4, "2": 3} and derived["dc"] == {"0": 12, "1": 13, "2": 14}
    assert sheet.spell_slots == {0: 8, 1: 7, 2: 5}
    # Four cleric and three wizard 1st-level spells fill both pools; an eighth is one too many.
    full = ["Bless", "Bless", "Bless", "Magic Weapon", "Magic Missile", "Shield", "Sleep"]
    assert ENGINE.can_memorize(sheet, [1] * 7, full) is None
    assert ENGINE.can_memorize(sheet, [1] * 8, [*full, "Bless"]) is not None
    # Hold Person is cleric 2 and wizard 3: at 2nd the cleric's; at 3rd no class here casts it.
    assert ENGINE.spell_level(sheet, "Hold Person") == 2
    assert ENGINE.can_memorize(sheet, [2], ["Hold Person"]) is None
    assert ENGINE.can_memorize(sheet, [3], ["Hold Person"]) == "Ansel can cast up to 2nd-level spells."
    # Each copy is cast with its class's DC.
    state = CharacterState(hp=24, memorized=(MemorizedSpell("Bless", 1, cast=True), MemorizedSpell("Sleep", 1, True)))
    assert ENGINE.cast(sheet, state, "Bless", 1)[1]["dc"] == 13
    assert ENGINE.cast(sheet, state, "Sleep", 1)[1]["dc"] == 14


def test_a_spell_on_both_lists_fills_either(srd35_call):
    # Protection from Evil is cleric 1, good 1 and wizard 1. Three Bless fill the cleric's non-domain slots; the first
    # Protection from Evil takes the cleric's last (the domain slot, a good spell), the second goes to the wizard.
    _ansel(srd35_call)
    spells = ["Bless", "Bless", "Bless", "Protection from Evil", "Protection from Evil", "Magic Missile", "Shield"]
    out = srd35_call("memorize_spells", character="Ansel", spells=spells)
    assert out["by_level"] == {"1": [s.replace("from", "From") for s in spells]}, out  # the reference's spelling
    first = srd35_call("cast_spell", character="Ansel", spell_name="Protection from Evil")
    second = srd35_call("cast_spell", character="Ansel", spell_name="Protection from Evil")
    assert (first["dc"], first["class"]) == (13, "cleric"), first
    assert (second["dc"], second["class"]) == (14, "wizard"), second


def test_a_full_class_refuses_its_own_spell(srd35_call):
    # Magic Missile, Shield and Sleep are on no cleric list: four of them overfill the wizard's 3 level-1 slots while
    # the cleric's stand empty.
    _ansel(srd35_call)
    out = srd35_call("memorize_spells", character="Ansel", spells=["Magic Missile", "Shield", "Sleep", "Magic Missile"])
    assert out["error"] == "The wizard's 3 level-1 slots are full: Magic Missile is one too many.", out
    sheet = mystic()
    # Bless four times leaves no cleric slot for a domain spell: the domain slot holds only one.
    domain = ENGINE.can_memorize(sheet, [1] * 4, ["Bless"] * 4)
    assert domain and "domain slot" in domain and "Magic Weapon" in domain
    # A spell on both lists at that level with both pools full names both.
    both = ENGINE.can_memorize(sheet, [0] * 9, ["Light"] * 9)
    assert both == "The cleric's 4 and the wizard's 4 level-0 slots are full: Light is one too many."
    assert ENGINE.can_memorize(sheet, [1], ["Entangle"]) == "Entangle is no level-1 spell of the cleric or wizard list."


def test_arcane_failure_only_on_the_wizard_copy(srd35_call):
    # A chain shirt is 20% arcane spell failure: the wizard's copy rolls it, the cleric's (a divine spell) never does,
    # also for a spell both lists have.
    _ansel(srd35_call, armor="chain shirt")
    spells = ["Bless", "Bless", "Bless", "Protection from Evil", "Protection from Evil", "Magic Missile"]
    assert "error" not in (out := srd35_call("memorize_spells", character="Ansel", spells=spells)), out
    bless = srd35_call("cast_spell", character="Ansel", spell_name="Bless")
    assert "spell_failure" not in bless and bless["class"] == "cleric", bless
    first = srd35_call("cast_spell", character="Ansel", spell_name="Protection from Evil")
    assert "spell_failure" not in first and first["class"] == "cleric", first
    second = srd35_call("cast_spell", character="Ansel", spell_name="Protection from Evil")
    assert second["spell_failure"]["chance"] == 20, second
    missile = srd35_call("cast_spell", character="Ansel", spell_name="Magic Missile")
    assert missile["spell_failure"]["chance"] == 20, missile


def test_a_phase_2_single_class_caster_unchanged():
    # A 1st-level wizard with Int 16: 3 / 1 + 1, DC 14 at 1st; its numbers and its cast are as Phase 2 had them.
    sheet = filled({"wizard": 1}, {"int": 16})
    derived = sheet.d20["derived"]
    assert derived["slots"] == {"0": 3, "1": 2} and derived["dc"] == {"0": 13, "1": 14}
    assert derived["casting"] == {"wizard": {"ability": "int", "caster_level": 1, "prepared": True,
                                             "slots": {"0": 3, "1": 2}, "dc": {"0": 13, "1": 14}}}  # fmt: skip
    assert sheet.spell_slots == {0: 3, 1: 2}
    state = CharacterState(hp=4, memorized=(MemorizedSpell("Sleep", 1, cast=True),))
    assert ENGINE.cast(sheet, state, "Sleep", 1)[1] == {"dc": 14, "school": "Enchantment", "save": "Will negates"}
    # A sheet stored by Phase 2 has no `casting` in its derived numbers: it memorizes and casts the same.
    stored = replace(sheet, d20={**sheet.d20, "derived": {k: v for k, v in derived.items() if k != "casting"}})
    assert ENGINE.can_memorize(stored, [1, 1], ["Sleep", "Shield"]) is None
    assert ENGINE.can_memorize(stored, [1, 1, 1], ["Sleep"] * 3).startswith("Too many level-1 spells")
    assert ENGINE.cast(stored, state, "Sleep", 1)[1]["dc"] == 14


def test_a_feats_caster_level_is_each_classs_own():
    # Brew Potion needs caster level 3. A paladin 4/wizard 2 casts at 2 (half of 4) and 2: the highest is 2, short. A
    # paladin 6/wizard 2 casts at 3 as a paladin: enough.
    short = Sheet(label="Ansel", cls="Paladin/Wizard", race="Human", levels={"paladin": 4, "wizard": 2},
                  ability_scores={**TEN, "wis": 14, "int": 14}, d20={"feats": ["brew-potion"]})  # fmt: skip
    assert numbers.feat_problems(short, REF, 5) == ["Brew Potion needs caster level 3."]
    enough = replace(short, levels={"paladin": 6, "wizard": 2})
    assert numbers.feat_problems(enough, REF, 7) == []
    assert numbers.feat_problems(replace(short, levels={"wizard": 3}), REF, 1) == []


def test_a_sorcerer_clerics_cleric_pool_prepares():
    # A sorcerer 2/cleric 3: the cleric's pool (Wis 14: 4 / 4 / 3) prepares; the sorcerer's (Table: The Sorcerer, 2nd:
    # 6 / 4, Cha 14 a bonus 1st: 6 / 5; known 5 / 2) casts its spells known, unmemorized.
    sheet = filled({"sorcerer": 2, "cleric": 3}, {**SCORES, "cha": 14}, domains=["war", "good"])
    casting = sheet.d20["derived"]["casting"]
    assert casting["sorcerer"] == {"ability": "cha", "caster_level": 2, "prepared": False, "per_day": {"0": 6, "1": 5},
                                   "known": {"0": 5, "1": 2}, "dc": {"0": 12, "1": 13}}  # fmt: skip
    assert casting["cleric"]["slots"] == {"0": 4, "1": 4, "2": 3}
    assert sheet.spell_slots == {0: 4, 1: 4, 2: 3}
    assert ENGINE.can_memorize(sheet, [1, 1], ["Bless", "Magic Weapon"]) is None
    assert ENGINE.can_memorize(sheet, [1], ["Magic Missile"]) == (
        "Magic Missile is a sorcerer spell. A sorcerer memorizes nothing: it casts any spell it knows (set_build's "
        "known), so many a day, with cast_spell."
    )
    state = CharacterState(hp=20, memorized=(MemorizedSpell("Bless", 1, cast=True),))
    assert ENGINE.cast(sheet, state, "Bless", 1)[1]["dc"] == 13
