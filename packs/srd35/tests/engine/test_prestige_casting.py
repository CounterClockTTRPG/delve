"""Prestige classes that advance an existing class's spellcasting (DEL-389 part 4): "+1 level of existing … class". The
class named in `Sheet.d20["advances"]` (set by `set_build(advances=…)`) casts as if it had those levels more: its
spells a day or slots, spells known and caster level are its table's at that level; its other class features don't
advance. The hierophant's levels raise only the caster level ("do not advance spell progression … still stack with
the character's base spellcasting levels to determine caster level"). Without `advances`, nothing is advanced and a
warning says to set it; set later, the earlier prestige levels count too (worked out from the levels)."""

from __future__ import annotations

from delve_srd35.engine import Srd35Engine, features, numbers
from delve_srd35.reference import Srd35Reference

from delve.domain.characters import Sheet
from delve.rules.classic import combat as rules

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
SCORES = {**TEN, "int": 16, "wis": 14, "cha": 14, "str": 13}


def sheet(levels: dict[str, int], **d20) -> Sheet:
    cls = "/".join(c.title() for c in levels)
    made = Sheet(label="Ansel", cls=cls, race="Human", alignment="", levels=levels, hp_max=30, ability_scores=SCORES,
                 d20=d20)  # fmt: skip
    return ENGINE.fill_derived(made, REF)


def casting(made: Sheet) -> dict:
    return made.d20["derived"]["casting"]


def warnings(made: Sheet) -> list[str]:
    return made.d20["derived"].get("warnings", [])


def test_wizard_5_eldritch_knight_3_casts_as_wizard_7():
    # Eldritch knight 1st: no advance; 2nd and 3rd: +1 level of existing arcane spellcasting class each. A wizard 7
    # (Int 16) has 4/5/4/3/1 (Table: The Wizard 4/4/3/2/1, and 1st-3rd bonus spells of Int 16), caster level 7.
    knight = sheet({"wizard": 5, "fighter": 1, "eldritch-knight": 3}, advances={"eldritch-knight": ["wizard"]})
    wizard = casting(knight)["wizard"]
    assert wizard["caster_level"] == 7
    assert wizard["slots"] == {"0": 4, "1": 5, "2": 4, "3": 3, "4": 1}
    assert wizard["slots"] == casting(sheet({"wizard": 7}))["wizard"]["slots"]
    assert numbers.caster_level(knight, "wizard") == 7
    assert "eldritch-knight" not in casting(knight)
    # Eldritch knight 1: nothing to advance yet, no warning.
    first = sheet({"wizard": 5, "fighter": 1, "eldritch-knight": 1})
    assert casting(first)["wizard"]["caster_level"] == 5
    assert not [w for w in warnings(first) if "advances" in w]
    # Its other class features don't advance: the wizard's are a wizard 5's.
    def own(made: Sheet) -> list:
        return [f for f in made.d20["derived"]["features"] if f["class"] == "wizard"]

    assert own(knight) == own(sheet({"wizard": 5}))


def test_cleric_3_wizard_3_mystic_theurge_2():
    # The mystic theurge: +1 level of existing arcane and +1 level of existing divine spellcasting class each level.
    theurge = sheet({"cleric": 3, "wizard": 3, "mystic-theurge": 2}, advances={"mystic-theurge": ["wizard", "cleric"]})
    found = casting(theurge)
    assert (found["cleric"]["caster_level"], found["wizard"]["caster_level"]) == (5, 5)
    # Cleric 5 (Wis 14): 5/3+1+1/2+1+1/1+1 with the domain slot; wizard 5 (Int 16): 4/3+1/2+1/1+1.
    assert found["cleric"]["slots"] == {"0": 5, "1": 5, "2": 4, "3": 2}
    assert found["wizard"]["slots"] == {"0": 4, "1": 4, "2": 3, "3": 2}
    # The first prepared class's slots, where Phase 2 reads them, follow too.
    assert theurge.d20["derived"]["slots"] == found["cleric"]["slots"]


def test_sorcerer_5_arcane_trickster_2():
    # Arcane trickster: +1 level of existing class from 1st. A sorcerer 7 (Cha 14): 6/7/7/4 a day (Table: The
    # Sorcerer 6/6/6/4 and Cha 14's bonus spells), knows 7/5/3/2.
    trickster = sheet({"sorcerer": 5, "rogue": 3, "arcane-trickster": 2}, advances={"arcane-trickster": ["sorcerer"]})
    entry = casting(trickster)["sorcerer"]
    assert entry["caster_level"] == 7
    assert entry["per_day"] == {"0": 6, "1": 7, "2": 7, "3": 4}
    assert entry["known"] == {"0": 7, "1": 5, "2": 3, "3": 2}


def test_no_advances_set_warns_and_doesnt_advance():
    # Review Focus 2: the level is taken, nothing is advanced, a warning says to set it.
    knight = sheet({"wizard": 5, "fighter": 1, "eldritch-knight": 3})
    assert casting(knight)["wizard"]["caster_level"] == 5
    assert casting(knight)["wizard"]["slots"] == casting(sheet({"wizard": 5}))["wizard"]["slots"]
    assert ("the eldritch knight's 2 caster levels advance no class: name it with set_build's advances (an arcane "
            "casting class: wizard).") in warnings(knight)  # fmt: skip
    # Set later, both earlier levels count: the advance is worked out from the levels, not a history.
    later = sheet({"wizard": 5, "fighter": 1, "eldritch-knight": 3}, advances={"eldritch-knight": ["wizard"]})
    assert casting(later)["wizard"]["caster_level"] == 7
    assert not [w for w in warnings(later) if "advance" in w]
    # A stored choice that no longer holds (the class isn't one the sheet casts of that kind) advances nothing, warned.
    wrong = sheet({"wizard": 5, "cleric": 1, "eldritch-knight": 3}, advances={"eldritch-knight": ["cleric"]})
    assert casting(wrong)["cleric"]["caster_level"] == 1
    assert any("eldritch knight" in w and "advance" in w for w in warnings(wrong))


def test_assassin_casts_its_own_list():
    # The assassin's own spellcasting (Table: The Assassin, its own list) is a casting class of its own, no advance.
    assassin = sheet({"rogue": 5, "assassin": 3})
    entry = casting(assassin)["assassin"]
    assert (entry["caster_level"], entry["prepared"]) == (3, False)
    assert entry["per_day"] == {"1": 3, "2": 1}
    assert features.casters(assassin) == {"assassin": "int"}
    assert not [w for w in warnings(assassin) if "advance" in w]
    blackguard = sheet({"fighter": 6, "blackguard": 2})
    assert casting(blackguard)["blackguard"]["slots"] == {"1": 2}


def test_hierophant_raises_the_caster_level_only():
    # Cleric 13 / hierophant 2: caster level 15, but a cleric 13's slots.
    hierophant = sheet({"cleric": 13, "hierophant": 2}, advances={"hierophant": ["cleric"]})
    entry = casting(hierophant)["cleric"]
    assert entry["caster_level"] == 15
    assert entry["slots"] == casting(sheet({"cleric": 13}))["cleric"]["slots"]
    row = next(r for r in features.rows("hierophant") if r["kind"] == "casting")
    assert (row["advances"], row["caster_level_only"]) == ("divine", True)
    assert list(row["by_level"]) == ["1", "2", "3", "4", "5"]
    assert features.casting("hierophant") is None


def test_the_effective_level_stops_at_the_tables_20th():
    # A wizard 18 / archmage 5: caster level 23, a wizard 20's slots.
    archmage = sheet({"wizard": 18, "archmage": 5}, advances={"archmage": ["wizard"]})
    entry = casting(archmage)["wizard"]
    assert entry["caster_level"] == 23
    assert entry["slots"] == casting(sheet({"wizard": 20}))["wizard"]["slots"]


def test_sheet_numbers_name_the_prestige_classes_and_what_they_advance():
    # The web sheet marks a prestige class and heads a casting class's pool with the levels prestige classes add
    # ("Wizard: caster level 7 … +2 from eldritch knight"): a single prepared caster advanced has its pool too.
    knight = sheet({"wizard": 5, "fighter": 1, "eldritch-knight": 3}, advances={"eldritch-knight": ["wizard"]})
    found = ENGINE.sheet_numbers(knight)
    assert found["prestige"] == ["eldritch-knight"]
    assert found["advanced"] == {"wizard": {"eldritch-knight": 2}}
    assert found["casting"]["wizard"]["caster_level"] == 7
    theurge = ENGINE.sheet_numbers(sheet({"cleric": 3, "wizard": 3, "mystic-theurge": 2},
                                         advances={"mystic-theurge": ["wizard", "cleric"]}))  # fmt: skip
    assert theurge["advanced"] == {"wizard": {"mystic-theurge": 2}, "cleric": {"mystic-theurge": 2}}
    hierophant = ENGINE.sheet_numbers(sheet({"cleric": 13, "hierophant": 2}, advances={"hierophant": ["cleric"]}))
    assert hierophant["advanced"] == {"cleric": {"hierophant": 2}}
    # Advancing nothing yet (no advances set), the prestige class is still marked; nothing is advanced.
    unset = ENGINE.sheet_numbers(sheet({"wizard": 5, "fighter": 1, "eldritch-knight": 3}))
    assert unset["prestige"] == ["eldritch-knight"] and "advanced" not in unset
    # A sheet without a prestige class has neither key.
    plain = ENGINE.sheet_numbers(sheet({"wizard": 5}))
    assert "prestige" not in plain and "advanced" not in plain and "casting" not in plain


# --- through the tools -----------------------------------------------------------------------------------------


def _make(srd35_call, name: str, levels: dict[str, int]):
    cls = "/".join(c.title() for c in levels)
    made = srd35_call("create_character", name=name, sheet={"cls": cls, "levels": levels, "race": "Human",
                                                            "hp_max": 30, "ability_scores": SCORES})  # fmt: skip
    assert "error" not in made, made
    return made


def test_set_build_advances_checked(srd35_call):
    _make(srd35_call, "Ansel", {"wizard": 5, "cleric": 1, "fighter": 1, "eldritch-knight": 3})
    # A divine class for an arcane advance; a class it hasn't; a class that advances nothing; two for one.
    refused = srd35_call("set_build", character="Ansel", advances={"eldritch-knight": ["cleric"]})
    assert "The eldritch knight advances an arcane casting class (wizard), not cleric." in refused["error"]
    refused = srd35_call("set_build", character="Ansel", advances={"eldritch knight": ["sorcerer"]})
    assert "The eldritch knight advances an arcane casting class (wizard), not sorcerer." in refused["error"]
    refused = srd35_call("set_build", character="Ansel", advances={"fighter": ["wizard"]})
    assert "The fighter advances no class's spellcasting." in refused["error"]
    refused = srd35_call("set_build", character="Ansel", advances={"loremaster": ["wizard"]})
    assert "Ansel has no loremaster levels." in refused["error"]
    refused = srd35_call("set_build", character="Ansel", advances={"eldritch-knight": ["wizard", "wizard"]})
    assert "The eldritch knight advances 1 class, not 2." in refused["error"]
    # By its spaced names, a string for one: stored by id.
    built = srd35_call("set_build", character="Ansel", advances={"Eldritch Knight": "Wizard"})
    assert "error" not in built, built
    assert built["build"]["advances"] == {"eldritch-knight": ["wizard"]}
    assert built["derived"]["casting"]["wizard"]["caster_level"] == 7


def test_set_build_mystic_theurge_one_of_each(srd35_call):
    _make(srd35_call, "Mira", {"cleric": 3, "wizard": 3, "sorcerer": 1, "mystic-theurge": 2})
    refused = srd35_call("set_build", character="Mira", advances={"mystic-theurge": ["wizard", "sorcerer"]})
    assert "The mystic theurge advances one arcane and one divine casting class (arcane: wizard, sorcerer; divine: " \
           "cleric), not wizard and sorcerer." in refused["error"]  # fmt: skip
    built = srd35_call("set_build", character="Mira", advances={"mystic theurge": ["cleric", "sorcerer"]})
    assert "error" not in built, built
    found = built["derived"]["casting"]
    assert (found["cleric"]["caster_level"], found["sorcerer"]["caster_level"], found["wizard"]["caster_level"]) == (
        5, 3, 3)  # fmt: skip


def test_spell_resistance_caster_level_follows(srd35_call, srd35_storage, srd35_campaign):
    # Part 3's SR check reads casting[cls]["caster_level"]: a wizard 5 / eldritch knight 3 rolls d20 + 7 against a
    # succubus's SR 18.
    _make(srd35_call, "Ansel", {"wizard": 5, "fighter": 1, "eldritch-knight": 3})
    assert "error" not in srd35_call("set_build", character="Ansel", advances={"eldritch-knight": ["wizard"]})
    out = srd35_call("setup_combat", enemies=[{"name": "succubus", "count": 1, "hp": 30}], surprise=False)
    assert "error" not in out, out
    live = rules.from_json(srd35_storage.combats.live(srd35_campaign.id)[1])
    target = next(c for c in live.combatants.values() if c.side == "enemy")
    said = srd35_call("spell_resistance", caster="Ansel", target=target.id, spell="magic missile")
    assert "error" not in said, said
    assert (said["caster_level"], said["sr"]) == (7, 18)
    assert said["total"] == said["roll"] + 7
