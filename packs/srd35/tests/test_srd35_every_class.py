"""Every one of the pack's 31 classes to its top through the DM's tools (DEL-389 part 5), with seeded dice and the
tripwire on: each base and NPC class from 1st to 20th by `update_character(patch={"level": n})`, its 21st refused; each
prestige class from a build that qualifies, entered and raised one level at a time by `update_character(patch={"levels":
…})` to its table's last, the next refused; and an ogre barbarian, whose racial Hit Dice and level adjustment count
toward 20th.

Asserted at every level: no call has an error, the sheet's derived numbers warn of no missing table row, and its
features are every feature row of its classes up to their levels (`features.granted`'s rows, the requirement rows
aside); at the end, the ECL is the class levels plus the race's Hit Dice and level adjustment, the sheet warns of
nothing, and a caster prestige class has advanced the casting classes named for it.

The base classes are humans with Int 14 and their casting score 14 (the rest 12); the prestige builds are part 4's
(`engine/test_prestige_requirements.py`, `test_scripted_session_prestige.py`) where they exist, else the least the
class's requirements ask, with the DM's confirmation (`set_build(choices={"requirements": …})`) of a special one the
engine can't check and the casting class each caster advances (`advances`). A new class's first level is core's
level-up, as any other level is (DEL-457); the hit points don't matter here."""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from delve_srd35 import data
from delve_srd35.engine import features

CLASSES = {c["id"]: c for c in data.load("classes")}
BASE_AND_NPC = sorted(cid for cid, c in CLASSES.items() if c["type"] in ("base", "npc"))
PRESTIGE = sorted(cid for cid, c in CLASSES.items() if c["type"] == "prestige")

RACE_LEVELS = {"Human": 0, "Elf": 0, "Dwarf": 0, "Ogre": 4 + 2}
"""Each race's Hit Dice plus level adjustment: the ogre's 4 HD and LA +2 (`monsters.json`); a core race has none."""

TWELVE = {"str": 12, "dex": 12, "con": 12, "int": 14, "wis": 12, "cha": 12}

ALIGNMENT = {"paladin": "Lawful Good", "monk": "Lawful Neutral", "barbarian": "Chaotic Neutral", "druid": "Neutral"}
"""The base classes with an alignment the class asks for; the rest are Neutral Good."""


def casting_score(cls: str) -> str | None:
    """The ability a class casts with, from its casting feature row: None for a class that casts nothing."""
    return next((row["ability"] for row in features.rows(cls) if row["kind"] == "casting" and "ability" in row), None)


CONFIRM = "the DM confirms it"


def build(cls: str) -> dict[str, Any]:
    """A build that qualifies for the prestige class `cls`: the character's race, alignment, scores and base levels,
    and the `set_build` arguments (skills, feats, domains, the special requirements confirmed)."""
    special = [row["requires"]["special"] for row in features.rows(cls) if "special" in row.get("requires", {})]
    builds: dict[str, dict[str, Any]] = {
        # Ilsa's, a fighter for the ranger: "Ability to cast 1st-level arcane spells" (the wizard's).
        "arcane-archer": {"race": "Elf", "levels": {"fighter": 6, "wizard": 1}, "alignment": "Chaotic Good",
                          "scores": {"dex": 16}, "feats": ["point blank shot", "precise shot",
                                                           {"id": "weapon focus", "choice": "longbow"}]},
        # The requirements test's: a rogue 3 (+2d6) / wizard 5 casts mage hand and 3rd-level spells.
        "arcane-trickster": {"levels": {"rogue": 3, "wizard": 5}, "alignment": "Chaotic Neutral",
                             "skills": {"decipher script": 7, "disable device": 7, "escape artist": 7,
                                        "knowledge arcana": 4}, "advances": ["wizard"]},
        # A wizard 13 with Int 18 casts 7th-level spells ("10 + the spell level" = 17).
        "archmage": {"levels": {"wizard": 13}, "scores": {"int": 18},
                     "skills": {"knowledge arcana": 15, "spellcraft": 15},
                     "feats": [{"id": "skill focus", "choice": "spellcraft"}, {"id": "spell focus", "choice": "evocation"},
                               {"id": "spell focus", "choice": "conjuration"}], "advances": ["wizard"]},
        # Vex.
        "assassin": {"levels": {"rogue": 5}, "alignment": "Neutral Evil", "scores": {"dex": 16},
                     "skills": {"disguise": 4, "hide": 8, "move silently": 8}},
        # Mord, his Str 13 his own.
        "blackguard": {"levels": {"fighter": 7}, "alignment": "Lawful Evil", "scores": {"str": 13},
                       "skills": {"hide": 5, "knowledge religion": 2},
                       "feats": ["power attack", "cleave", "combat expertise", "improved sunder"]},
        # A sorcerer casts arcane spells without preparation; 8 ranks are a 5th-level character's most.
        "dragon-disciple": {"levels": {"sorcerer": 5}, "skills": {"knowledge arcana": 8}},
        # Tumble 5 ranks cross-class: a 7th-level character's most ((7 + 3) / 2).
        "duelist": {"levels": {"fighter": 7}, "scores": {"dex": 14},
                    "skills": {"perform dance": 3, "tumble": 5}, "feats": ["dodge", "mobility", "weapon finesse"]},
        # Thrain, with Dodge's Dex 13.
        "dwarven-defender": {"race": "Dwarf", "levels": {"fighter": 7}, "alignment": "Lawful Neutral",
                             "scores": {"dex": 13}, "feats": ["dodge", "endurance", "toughness"]},
        # Ansel, with Int 16.
        "eldritch-knight": {"levels": {"wizard": 5, "fighter": 1}, "scores": {"int": 16}, "advances": ["wizard"]},
        # A cleric 13 with Wis 18 casts 7th-level spells.
        "hierophant": {"levels": {"cleric": 13}, "scores": {"wis": 18}, "domains": ["war", "good"],
                       "skills": {"knowledge religion": 15}, "feats": ["empower spell"], "advances": ["cleric"]},
        # A ranger has Endurance as a bonus feat from 3rd: it meets the requirement.
        "horizon-walker": {"levels": {"ranger": 5}, "skills": {"knowledge geography": 8}},
        # The requirements test's sage; the wizard's own Scribe Scroll is the third item creation feat.
        "loremaster": {"levels": {"wizard": 7}, "scores": {"int": 16},
                       "skills": {"knowledge history": 10, "knowledge local": 10},
                       "feats": ["empower spell", "craft wand",
                                 {"id": "skill focus", "choice": "knowledge history"}], "advances": ["wizard"]},
        # Mira.
        "mystic-theurge": {"levels": {"cleric": 3, "wizard": 3}, "scores": {"wis": 14}, "domains": ["war", "good"],
                           "skills": {"knowledge arcana": 6, "knowledge religion": 6},
                           "advances": ["wizard", "cleric"]},
        # A rogue 7 has 10 ranks at most.
        "shadowdancer": {"levels": {"rogue": 7}, "scores": {"dex": 14},
                         "skills": {"hide": 10, "move silently": 8, "perform dance": 5},
                         "feats": ["combat reflexes", "dodge", "mobility"]},
        # The requirements test's: a cleric 7 (Wis 14) casts lesser planar ally.
        "thaumaturgist": {"levels": {"cleric": 7}, "scores": {"wis": 14}, "domains": ["war", "good"],
                          "feats": [{"id": "spell focus", "choice": "conjuration"}], "advances": ["cleric"]},
    }  # fmt: skip
    made = builds[cls]
    return {"race": "Human", "alignment": "Neutral Good", **made, "scores": {**TWELVE, **made.get("scores", {})},
            "special": special}  # fmt: skip


@pytest.fixture
def play(srd35_tripwire, srd35_storage, srd35_campaign):
    """`play(tool, **args)` on the srd35 campaign, each call in a beat of its own with the next seed; an answer with
    an error fails the test."""
    from delve.dice import SeededRng
    from delve.dm.tools import ToolHost
    from tests.fixtures.rulesets import srd35_catalogs

    seeds = itertools.count(1)
    host = ToolHost(srd35_storage, lambda: SeededRng(next(seeds)), catalogs=srd35_catalogs())
    beats = itertools.count(1)

    def run(tool, /, refused=False, **args):
        out = host.call(srd35_campaign.id, f"beat-{next(beats)}", tool, args)
        assert ("error" in out) is refused, (tool, args, out)
        return out

    return run


def sheet_of(play, name: str) -> dict[str, Any]:
    return play("get_character", ref=name)["sheet"]


def checked(sheet: dict[str, Any]) -> None:
    """No warning of a missing table row; every feature row of each class up to its level is on the sheet."""
    derived = sheet["d20"]["derived"]
    assert not [w for w in derived.get("warnings", ()) if "has no level" in w], derived["warnings"]
    have = {(f["class"], f["id"]) for f in derived["features"]}
    for cls, level in sheet["levels"].items():
        rows = {
            (cls, row["id"]) for row in features.rows(cls) if row["level"] <= level and row["kind"] != "requirement"
        }
        assert rows <= have, (cls, level, sorted(rows - have))


def at_the_end(sheet: dict[str, Any]) -> None:
    """The ECL is the class levels plus the race's Hit Dice and level adjustment, and the sheet warns of nothing."""
    derived = sheet["d20"]["derived"]
    assert derived["ecl"] == sum(sheet["levels"].values()) + RACE_LEVELS[sheet["race"]]
    assert not derived.get("warnings"), derived["warnings"]


def spaced(levels: dict[str, int]) -> dict[str, Any]:
    """A `levels` patch by the classes' names, as the DM gives it: "eldritch knight", with `cls` to match."""
    return {
        "cls": "/".join(CLASSES[c]["name"] for c in levels),
        "levels": {CLASSES[c]["name"].lower(): n for c, n in levels.items()},
    }


def test_every_class_is_swept():
    assert len(BASE_AND_NPC) == 16 and len(PRESTIGE) == 15
    assert sorted(BASE_AND_NPC + PRESTIGE) == sorted(CLASSES) and len(CLASSES) == 31


@pytest.mark.parametrize("cls", BASE_AND_NPC)
def test_a_base_class_levels_1_to_20(play, cls):
    scores = {**TWELVE, **({casting_score(cls): 14} if casting_score(cls) else {})}
    name = CLASSES[cls]["name"]
    play("create_character", name="Hero", sheet={"cls": name, "level": 1, "race": "Human", "hp_max": 12,
                                                  "alignment": ALIGNMENT.get(cls, "Neutral Good"),
                                                  "ability_scores": scores})  # fmt: skip
    checked(sheet_of(play, "Hero"))
    for level in range(2, 21):
        play("update_character", ref="Hero", patch={"level": level}, reason=f"{name} {level}")
        sheet = sheet_of(play, "Hero")
        assert sheet["levels"] == {cls: level}
        checked(sheet)
    at_the_end(sheet)
    assert sheet["d20"]["derived"]["ecl"] == 20
    refused = play("update_character", refused=True, ref="Hero", patch={"level": 21}, reason="21st")
    assert "20th level, the top" in refused["error"], refused


def enter(play, cls: str) -> tuple[dict[str, int], dict[str, Any]]:
    """A character made at the build's base levels, its build set, and its first level in `cls` through the tools:
    the levels it has then, and the build."""
    made = build(cls)
    base = made["levels"]
    play("create_character", name="Hero", sheet={**spaced(base), "race": made["race"], "hp_max": 60,
                                                  "alignment": made["alignment"],
                                                  "ability_scores": made["scores"]})  # fmt: skip
    args = {key: made[key] for key in ("skills", "feats", "domains") if key in made}
    if made["special"]:
        args["choices"] = {"requirements": {cls: made["special"]}}
    if args:
        play("set_build", character="Hero", **args)
    levels = {**base, cls: 1}
    play("update_character", ref="Hero", patch=spaced(levels), reason=f"enters the {cls}")
    if "advances" in made:
        play("set_build", character="Hero", advances={cls: made["advances"]})
    sheet = sheet_of(play, "Hero")
    assert sheet["levels"] == levels
    checked(sheet)
    return levels, made


def raise_to_last(play, cls: str, levels: dict[str, int]) -> dict[str, Any]:
    """The prestige class raised one level at a time to its table's last; the sheet then."""
    last = len(CLASSES[cls]["levels"])
    for level in range(2, last + 1):
        levels = {**levels, cls: level}
        play("update_character", ref="Hero", patch=spaced(levels), reason=f"{cls} {level}")
        sheet = sheet_of(play, "Hero")
        assert sheet["levels"] == levels
        checked(sheet)
    at_the_end(sheet)
    return sheet


@pytest.mark.parametrize("cls", PRESTIGE)
def test_a_prestige_class_levels_to_its_last(play, cls):
    levels, made = enter(play, cls)
    sheet = raise_to_last(play, cls, levels)
    last = len(CLASSES[cls]["levels"])
    assert sheet["levels"][cls] == last
    # A caster's levels advance the casting classes the DM named: each one's caster level is its own levels and the
    # prestige class's casting levels (the eldritch knight's from 2nd: 9).
    casting = next((row for row in features.rows(cls) if row["kind"] == "casting" and "advances" in row), None)
    for target in made.get("advances", ()):
        gained = sum(1 for at in casting["by_level"] if int(at) <= last)
        assert sheet["d20"]["derived"]["casting"][target]["caster_level"] == made["levels"][target] + gained
    refused = play("update_character", refused=True, ref="Hero", patch=spaced({**sheet["levels"], cls: last + 1}),
                   reason="one more")  # fmt: skip
    assert f"table has no level {last + 1}" in refused["error"], refused


@pytest.mark.parametrize("cls", ["archmage", "hierophant", "thaumaturgist"])
def test_five_level_prestige_classes_stop_at_5th(play, cls):
    assert len(CLASSES[cls]["levels"]) == 5
    levels, _ = enter(play, cls)
    sheet = raise_to_last(play, cls, levels)
    assert sheet["d20"]["derived"]["ecl"] < 20  # refused by the class's table, not the top
    refused = play("update_character", refused=True, ref="Hero", patch=spaced({**sheet["levels"], cls: 6}),
                   reason="a 6th")  # fmt: skip
    assert "table has no level 6" in refused["error"] and "20th level" not in refused["error"], refused
    assert sheet_of(play, "Hero")["levels"][cls] == 5


def test_ogre_barbarian_14_is_the_top(play):
    # An ogre (4 HD, LA +2; favoured class barbarian) is ECL 7 as a barbarian 1: barbarian 14 is ECL 20, and the
    # 15th barbarian level, which the barbarian's table has, is refused at the top.
    play("create_character", name="Grug", sheet={"cls": "Barbarian", "level": 1, "race": "Ogre", "hp_max": 40,
                                                  "alignment": "Chaotic Evil",
                                                  "ability_scores": {**TWELVE, "str": 21}})  # fmt: skip
    assert sheet_of(play, "Grug")["d20"]["derived"]["ecl"] == 7
    for level in range(2, 15):
        play("update_character", ref="Grug", patch={"level": level}, reason=f"barbarian {level}")
        sheet = sheet_of(play, "Grug")
        checked(sheet)
    assert sheet["levels"] == {"barbarian": 14}
    at_the_end(sheet)
    assert sheet["d20"]["derived"]["ecl"] == 4 + 2 + 14 == 20
    assert len(CLASSES["barbarian"]["levels"]) >= 15
    refused = play("update_character", refused=True, ref="Grug", patch={"level": 15}, reason="15th")
    assert "Grug is 20th level, the top: there is no level after it." in refused["error"], refused
    assert sheet_of(play, "Grug")["levels"] == {"barbarian": 14}
