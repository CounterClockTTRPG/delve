"""Magic items' numbers on a character (DEL-389 part 3): a weapon's and armour's enhancement, the worn items' bonuses
with the SRD's stacking (the highest of one type counts, different types add), weapon special abilities in a fight,
and `set_build(items=[...])`. Each number is the SRD's, worked by hand in its comment."""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
import sys
from pathlib import Path

from delve_srd35 import data
from delve_srd35.engine import Srd35Engine, numbers
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.campaigns import Character
from delve.domain.characters import Sheet
from delve.rules.classic.combat import AttackBlock, Combatant
from delve.rules.classic.tables import FightRules

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
PACK = Path(__file__).resolve().parents[2]
SCRIPTS = PACK / "scripts"
DATA = PACK / "src" / "delve_srd35" / "data"


def sheet(cls: str, levels: dict[str, int], items: list[dict], race: str = "Human", **build) -> Sheet:
    scores = {**TEN, **build.pop("scores", {})}
    return Sheet(label=cls, cls=cls, race=race, levels=levels, ability_scores=scores, d20={"items": items, **build})


def fighter(items: list[dict], **build) -> Sheet:
    return sheet("Fighter", {"fighter": 1}, items, scores={"str": 14, "dex": 12, **build.pop("scores", {})}, **build)


def combatant(built: Sheet) -> Combatant:
    filled = ENGINE.fill_derived(built, REF)
    character = Character("pc_1", "c", built.label, sheet=filled)
    return ENGINE.combatant_from_sheet(character, Combatant("pc_1", built.label, "party", character_id="pc_1", hp=30))


def form(built: Sheet) -> dict:
    return combatant(built).d20["attacks"][0]


def monster(id: str) -> Combatant:
    row = next(r for r in data.load("monsters") if r["id"] == id)
    core = Combatant(f"mon_{id}", id, "enemy", hp=60, hp_max=60, attacks=(AttackBlock("", "1d6", "1d6"),))
    return ENGINE.combatant_from_monster(row, core, {})


def swing(attacker: Combatant, target: Combatant, *faces: int):
    rng = ScriptedRng(faces)
    rolled = Dice(rng, MemoryRollLog(), "c", "beat")
    out = ENGINE.swing(dataclasses.replace(attacker, init=30), dataclasses.replace(target, init=0), "", rolled, 2,
                       FightRules())  # fmt: skip
    rng.assert_done()
    return out


def test_the_effects_table_is_the_srds():
    effects = data.load("item_effects")
    # "a deflection bonus of +1 to +5 to AC"; bracers "an armor bonus of +1 to +8"; "a +2 enhancement bonus to his
    # Strength score"; the belt "+4 or +6"; the amulet of health "+2, +4, or +6".
    assert effects["protection"] == {"type": "deflection", "target": "ac", "by_bonus": True, "bonuses": [1, 2, 3, 4, 5]}
    assert effects["bracers-of-armor"]["bonuses"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert effects["gauntlets-of-ogre-power"] == {"type": "enhancement", "target": "str", "by_bonus": False,
                                                  "bonuses": [2]}  # fmt: skip
    assert effects["belt-of-giant-strength"]["bonuses"] == [4, 6]
    assert (effects["amulet-of-health"]["target"], effects["amulet-of-health"]["bonuses"]) == ("con", [2, 4, 6])
    assert (effects["amulet-of-natural-armor"]["type"], effects["cloak-of-resistance"]["target"]) == ("natural", "saves")
    # Flaming: "an extra 1d6 points of fire damage"; flaming burst 1d10 more on a critical, 2d10 at x3, 3d10 at x4;
    # holy "makes the weapon good-aligned" and "an extra 2d6 points of damage against all of evil alignment".
    assert effects["flaming"] == {"type": "ability", "on": "weapon", "price": 1, "energy": "1d6 fire"}
    assert effects["flaming-burst"]["burst"] == {"kind": "fire", "2": "1d10", "3": "2d10", "4": "3d10"}
    assert effects["flaming-burst"]["energy"] == "1d6 fire" and effects["icy-burst"]["energy"] == "1d6 cold"
    assert effects["holy"]["aligned"] == ["good"] and effects["holy"]["against"] == {"dice": "2d6", "alignment": "evil"}
    assert effects["axiomatic"]["aligned"] == ["lawful"] and effects["anarchic"]["aligned"] == ["chaotic"]
    assert effects["keen"]["threat"] == "double" and effects["speed"]["price"] == 3
    assert effects["chain-shirt"]["target"] == "armor" and effects["buckler"]["target"] == "shield"
    assert effects["headband-of-intellect"]["skill_points"] is False


def test_the_script_makes_the_same_bytes(tmp_path):
    shutil.copy(DATA / "items.json", tmp_path / "items.json")
    done = subprocess.run([sys.executable, "-I", str(SCRIPTS / "extract_item_effects.py"), str(tmp_path)],
                          capture_output=True, text=True, check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "item_effects.json").read_bytes() == (DATA / "item_effects.json").read_bytes()


def test_plus_1_longsword_and_plus_2_chain_shirt():
    # Human fighter 1, Str 14 (+2), Dex 12 (+1). A +1 longsword: BAB 1 + Str 2 + 1 = +4 to hit, 1d8 + 2 + 1 = 1d8+3;
    # a magic weapon against DR (enhancement 1).
    built = fighter([{"id": "longsword", "kind": "weapon", "bonus": 1}, {"id": "chain-shirt", "kind": "armor", "bonus": 2}],
                    weapon="longsword", armor="chain shirt")  # fmt: skip
    longsword = form(built)
    assert (longsword["bonus"], longsword["damage"], longsword["enhancement"]) == (4, "1d8+3", 1)
    # A +2 chain shirt: armour 4 + 2 = 6. AC 10 + 6 + Dex 1 = 17, touch 11, flat-footed 16. "All magic armor is
    # masterwork armor (with an armor check penalty 1 less than normal)": -2 is -1.
    d = numbers.derived(built, REF)
    assert (d["ac"], d["touch"], d["flat_footed"], d["acp"], d["max_dex"]) == (17, 11, 16, -1, 4)
    # Without the items the same build is the plain one: +3, 1d8+2, AC 15, ACP -2.
    plain = dataclasses.replace(built, d20={**built.d20, "items": []})
    assert (form(plain)["bonus"], form(plain)["damage"], "enhancement" in form(plain)) == (3, "1d8+2", False)
    assert (numbers.derived(plain, REF)["ac"], numbers.derived(plain, REF)["acp"]) == (15, -2)


def test_a_magic_weapon_not_in_hand_adds_nothing():
    # The +1 longsword is carried; the hand holds a dagger: 1 + 2 = +3, 1d4+2.
    built = fighter([{"id": "longsword", "kind": "weapon", "bonus": 1}], weapon="dagger")
    dagger = form(built)
    assert (dagger["bonus"], dagger["damage"], "enhancement" in dagger) == (3, "1d4+2", False)


def test_rings_of_protection_dont_stack():
    # Two rings of protection, +1 and +2: deflection bonuses don't stack, +2 counts. AC 10 + 2 = 12, and deflection
    # counts against touch attacks and flat-footed: 12 and 12.
    rings = [{"id": "protection", "bonus": 1}, {"id": "protection", "bonus": 2}]
    d = numbers.derived(sheet("Fighter", {"fighter": 1}, rings), REF)
    assert (d["ac"], d["touch"], d["flat_footed"]) == (12, 12, 12)
    # An amulet of natural armor +1 is another type: AC 13, touch still 12 (natural armour isn't against touch).
    more = numbers.derived(sheet("Fighter", {"fighter": 1}, [*rings, {"id": "amulet-of-natural-armor", "bonus": 1}]),
                           REF)  # fmt: skip
    assert (more["ac"], more["touch"], more["flat_footed"]) == (13, 12, 13)


def test_bracers_of_armor_and_worn_armour_take_the_higher():
    # Bracers of armor +3 and a chain shirt (+4): both armor bonuses, the higher counts: 4. Bracers +5 over it: 5.
    # AC 10 + 4 = 14 and 10 + 5 = 15; touch 10 either way.
    low = numbers.derived(sheet("Fighter", {"fighter": 1}, [{"id": "bracers-of-armor", "bonus": 3}], armor="chain shirt"), REF)
    high = numbers.derived(sheet("Fighter", {"fighter": 1}, [{"id": "bracers-of-armor", "bonus": 5}], armor="chain shirt"), REF)
    assert (low["ac"], high["ac"], high["touch"]) == (14, 15, 10)


def test_amulet_of_natural_armor_enhances_a_races_natural_armour():
    # An enhancement bonus to natural armour adds to a race's own: a lizardfolk's +5 natural and an amulet +2 is 7
    # (AC 10 + 7 + Dex 0 = 17 without armour; the lizardfolk's Medium size gives nothing).
    plain = numbers.derived(sheet("Fighter", {"fighter": 1}, [], race="Lizardfolk"), REF)
    worn = numbers.derived(sheet("Fighter", {"fighter": 1}, [{"id": "amulet-of-natural-armor", "bonus": 2}],
                                 race="Lizardfolk"), REF)  # fmt: skip
    assert worn["ac"] - plain["ac"] == 2


def test_cloak_of_resistance_and_divine_grace_stack():
    # Paladin 2, Cha 14 (+2), Con 10, Dex 10, Wis 10: base Fort +3, Ref +0, Will +0; divine grace +2 on each. A cloak
    # of resistance +1 is a resistance bonus, another type: Fort 3 + 2 + 1 = 6, Ref 0 + 2 + 1 = 3, Will 3.
    cloak = [{"id": "cloak-of-resistance", "bonus": 1}]
    d = numbers.derived(sheet("Paladin", {"paladin": 2}, cloak, scores={"cha": 14}), REF)
    assert (d["fort"], d["ref"], d["will"]) == (6, 3, 3)
    # Two cloaks, +1 and +3: only +3 counts (Fort 3 + 2 + 3 = 8).
    two = numbers.derived(sheet("Paladin", {"paladin": 2}, [*cloak, {"id": "cloak-of-resistance", "bonus": 3}],
                                scores={"cha": 14}), REF)  # fmt: skip
    assert (two["fort"], two["ref"], two["will"]) == (8, 5, 5)
    # A cloak of Charisma +2 raises Cha to 16 (+3), and divine grace with it: Fort 3 + 3 + 1 = 7.
    graced = numbers.derived(sheet("Paladin", {"paladin": 2}, [*cloak, {"id": "cloak-of-charisma", "bonus": 2}],
                                   scores={"cha": 14}), REF)  # fmt: skip
    assert graced["fort"] == 7


def test_belt_of_giant_strength_4_changes_attack_and_damage():
    # Str 14 + 4 = 18 (+4): a longsword at 1 + 4 = +5 for 1d8+4; Climb 4 ranks + 4 = 8.
    belt = [{"id": "belt-of-giant-strength", "bonus": 4}]
    built = fighter(belt, weapon="longsword", skills={"climb": 4})
    assert (form(built)["bonus"], form(built)["damage"]) == (5, "1d8+4")
    assert numbers.derived(built, REF)["skills"]["climb"] == 8
    # Gauntlets of ogre power (+2) with the belt: enhancement bonuses to Strength don't stack, +4 counts.
    both = fighter([*belt, {"id": "gauntlets-of-ogre-power", "bonus": 2}], weapon="longsword")
    assert (form(both)["bonus"], form(both)["damage"]) == (5, "1d8+4")
    # A greatsword two-handed: 1½ × Str +4 = +6.
    assert form(fighter(belt, weapon="greatsword"))["damage"] == "2d6+6"


def test_a_periapt_of_wisdom_raises_a_clerics_spell_dcs():
    # Cleric 1, Wis 15 (+2): DC of a 1st-level spell 10 + 1 + 2 = 13. A periapt of Wisdom +2: Wis 17 (+3), DC 14.
    plain = numbers.derived(sheet("Cleric", {"cleric": 1}, [], scores={"wis": 15}), REF)
    worn = numbers.derived(sheet("Cleric", {"cleric": 1}, [{"id": "periapt-of-wisdom", "bonus": 2}], scores={"wis": 15}), REF)
    assert (plain["dc"]["1"], worn["dc"]["1"]) == (13, 14)


def test_gloves_of_dexterity_under_armour_s_max_dex():
    # Dex 12 + gloves +4 = 16 (+3); in a chain shirt (max Dex +4) all count: AC 10 + 4 + 3 = 17, init +3. In scale
    # mail (max Dex +3) as well; in full plate (max Dex +1), 10 + 8 + 1 = 19, init still +3.
    gloves = [{"id": "gloves-of-dexterity", "bonus": 4}]
    shirt = numbers.derived(fighter(gloves, armor="chain shirt"), REF)
    plate = numbers.derived(fighter(gloves, armor="full plate"), REF)
    assert (shirt["ac"], shirt["init"], plate["ac"], plate["init"]) == (17, 3, 19, 3)


def test_mithral_armour():
    # A mithral chain shirt: max Dex 4 + 2 = 6, ACP -2 lessened by 3 to 0, spell failure 20% - 10% = 10%. A mithral
    # breastplate (medium) is light for movement: a human's 30 ft.
    shirt = numbers.derived(sheet("Wizard", {"wizard": 1}, [{"id": "chain-shirt", "kind": "armor", "bonus": 0,
                                                              "material": "mithral"}], armor="chain shirt"), REF)  # fmt: skip
    assert (shirt["max_dex"], shirt["acp"], shirt["spell_failure"]) == (6, 0, 10)
    plate = numbers.derived(fighter([{"id": "breastplate", "kind": "armor", "bonus": 1, "material": "mithral"}],
                                    armor="breastplate"), REF)  # fmt: skip
    assert (plate["speed"], plate["max_dex"], plate["acp"]) == (30, 5, -1)  # breastplate: max Dex 3, ACP -4


def test_adamantine_armour_gives_damage_reduction():
    # "Armor made from adamantine grants its wearer damage reduction of 1/— if it's light armor, 2/— if it's medium
    # armor, and 3/— if it's heavy armor"; masterwork: ACP 1 less (full plate -6 is -5).
    plate = numbers.derived(fighter([{"id": "full-plate", "kind": "armor", "bonus": 0, "material": "adamantine"}],
                                    armor="full plate"), REF)  # fmt: skip
    assert (plate["dr"], plate["acp"]) == ("3/—", -5)


def test_weapon_materials_against_dr():
    # A cold iron longsword overcomes a succubus's DR 10/cold iron or good; an alchemical silver one overcomes a
    # vampire spawn's DR 5/silver, at -1 damage: 1d8 + 2 - 1 = 1d8+1. An adamantine weapon is masterwork: +1 to hit.
    cold = form(fighter([{"id": "longsword", "kind": "weapon", "bonus": 0, "material": "cold iron"}], weapon="longsword"))
    assert cold["materials"] == ["cold iron"] and "enhancement" not in cold
    silver = form(fighter([{"id": "longsword", "kind": "weapon", "bonus": 0, "material": "silver"}], weapon="longsword"))
    assert (silver["materials"], silver["damage"]) == (["silver"], "1d8+1")
    adamantine = form(fighter([{"id": "longsword", "kind": "weapon", "bonus": 0, "material": "adamantine"}],
                              weapon="longsword"))  # fmt: skip
    assert (adamantine["materials"], adamantine["bonus"]) == (["adamantine"], 4)
    # The same with the weapon named so in the hand and no item: "cold iron longsword".
    assert form(fighter([], weapon="cold iron longsword"))["materials"] == ["cold iron"]
    spawn = monster("vampire-spawn")
    hit = swing(combatant(fighter([{"id": "longsword", "kind": "weapon", "bonus": 0, "material": "silver"}],
                                  weapon="longsword")), spawn, 15, 6)  # fmt: skip
    assert hit.damage == 7 and "DR 5/silver overcome (silver)" in hit.notes


def test_a_flaming_longsword_against_a_troll():
    # A +1 flaming longsword: 1d8+3 plus 1d6 fire. At a troll (AC 16): 15 + 4 hits; 6 + 3 = 9, fire 4: 13, and the
    # fire is lethal against its regeneration: 4 lethal, the sword's 9 nonlethal (DEL-421).
    built = fighter([{"id": "longsword", "kind": "weapon", "bonus": 1, "abilities": ["flaming"]}], weapon="longsword")
    longsword = form(built)
    assert (longsword["plus"], longsword["enhancement"]) == ("1d6 fire", 1)
    out = swing(combatant(built), monster("troll"), 15, 6, 4)
    assert (out.damage, out.nonlethal) == (4, 9) and "plus 1d6 fire: 4, in the damage" in out.notes
    assert "regeneration 5: the fire damage (4) is lethal, the rest nonlethal" in out.notes


def test_flaming_burst_on_a_critical_hit():
    # A +1 flaming burst battleaxe (×3): on a confirmed critical, 1d8+3 three times, 1d6 fire once and 2d10 fire.
    # At an orc (AC 13): 20 threatens, 15 confirms; 5 + 3, 4 + 3, 6 + 3 = 24, fire 3, burst 7 + 8 = 15: 42.
    built = fighter([{"id": "battleaxe", "kind": "weapon", "bonus": 1, "abilities": ["flaming-burst"]}], weapon="battleaxe")
    assert form(built)["burst"] == "2d10 fire"
    out = swing(combatant(built), monster("orc"), 20, 15, 5, 4, 6, 3, 7, 8)
    assert out.damage == 42 and "plus 2d10 fire (critical): 15, in the damage" in out.notes


def test_a_holy_longsword_against_a_succubus():
    # A +1 holy longsword is good-aligned: a succubus's DR 10/cold iron or good is overcome, and she is chaotic evil:
    # 2d6 more. 18 + 4 hits AC 20; 6 + 3 = 9, holy 3 + 4 = 7: 16.
    built = fighter([{"id": "longsword", "kind": "weapon", "bonus": 1, "abilities": ["holy"]}], weapon="longsword")
    assert form(built)["aligned"] == ["good"]
    out = swing(combatant(built), monster("succubus"), 18, 6, 3, 4)
    assert out.damage == 16 and "DR 10/cold iron or good overcome (good)" in out.notes
    assert "holy: +2d6 against an evil target (7)" in out.notes


def test_ammunition_from_a_magic_launcher_is_magic_and_aligned():
    # "Ammunition fired from a projectile weapon with an enhancement bonus of +1 or higher is treated as a magic
    # weapon for the purpose of overcoming damage reduction. Similarly, ... with an alignment gains the alignment."
    # A +1 longbow at a gargoyle (DR 10/magic): overcome. A +1 axiomatic longbow's arrows are lawful.
    bow = fighter([{"id": "longbow", "kind": "weapon", "bonus": 1}], weapon="longbow")
    out = swing(combatant(bow), monster("gargoyle"), 19, 6)
    assert "DR 10/magic overcome (magic)" in out.notes
    lawful = form(fighter([{"id": "longbow", "kind": "weapon", "bonus": 1, "abilities": ["axiomatic"]}], weapon="longbow"))
    assert (lawful["enhancement"], lawful["aligned"]) == (1, ["lawful"])


def test_a_keen_rapier():
    # A keen rapier: 18–20 doubled to 15–20; with Improved Critical as well, still 15–20 (they don't stack).
    keen = [{"id": "rapier", "kind": "weapon", "bonus": 1, "abilities": ["keen"]}]
    assert form(fighter(keen, weapon="rapier"))["threat"] == 15
    critical = fighter(keen, weapon="rapier", feats=[{"id": "improved-critical", "choice": "rapier"}])
    assert form(critical)["threat"] == 15


# --- set_build(items=[...]) ----------------------------------------------------------------------------------------

DWARF = {"str": 14, "dex": 12, "con": 14, "int": 10, "wis": 10, "cha": 8}


def _fighter(srd35_call, **scores):
    sheet = {"cls": "Fighter", "level": 1, "race": "Human", "hp_max": 12, "ability_scores": {**DWARF, **scores}}
    out = srd35_call("create_character", name="Thorin", sheet=sheet)
    assert "error" not in out, out
    return out


def test_set_build_reads_items_by_their_names(srd35_call):
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Thorin", weapon="longsword", armor="chain shirt",
                     items=["ring of protection +2", "+1 flaming longsword", "+2 chain shirt", "cloak of resistance +1",
                            "gauntlets of ogre power"])  # fmt: skip
    assert "error" not in out, out
    items = out["build"]["items"]
    assert items[0] == {"id": "protection", "kind": "worn", "name": "Ring of Protection +2", "bonus": 2}
    assert items[1] == {"id": "longsword", "kind": "weapon", "name": "+1 flaming longsword", "bonus": 1,
                        "abilities": ["flaming"]}  # fmt: skip
    assert items[2] == {"id": "chain-shirt", "kind": "armor", "name": "+2 chain shirt", "bonus": 2}
    assert items[4] == {"id": "gauntlets-of-ogre-power", "kind": "worn", "name": "Gauntlets of Ogre Power",
                        "bonus": 2}  # fmt: skip
    # AC 10 + chain shirt 4 + 2 + Dex 1 + deflection 2 = 19; Fort 2 + Con 2 + 1 = 5.
    assert (out["derived"]["ac"], out["derived"]["fort"]) == (19, 5)
    # The sheet's numbers list them, in use or not, and the Str the gauntlets enhance (14 + 2).
    numbers_shown = srd35_call("get_character", ref="Thorin", brief=True)["d20"]
    assert numbers_shown["abilities"] == {"str": 16}
    shown = numbers_shown["items"]
    assert [(i["name"], i.get("in_use")) for i in shown] == [
        ("Ring of Protection +2", None), ("+1 flaming longsword", True), ("+2 chain shirt", True),
        ("Cloak of Resistance +1", None), ("Gauntlets of Ogre Power", None)]  # fmt: skip


def test_an_item_without_an_effect_is_a_note(srd35_call):
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Thorin", items=["bag of holding", "+1 speed longsword"])
    assert "error" not in out, out
    bag, sword = out["build"]["items"]
    assert bag == {"id": "bag-of-holding", "kind": "note", "name": "Bag of Holding"}
    # A special ability the engine has no numbers for stays on the weapon, and the sheet says it is the DM's.
    assert sword["abilities"] == ["speed"]
    listed = {entry["name"]: entry for entry in out["derived"]["items"]}
    assert listed["Bag of Holding"]["note"] and "speed" in listed["+1 speed longsword"]["dm"]


def test_set_build_refuses_unknown_and_wrong_items(srd35_call):
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Thorin", items=["ring of protektion +2"])
    assert "Unknown item 'ring of protektion +2'" in out["error"] and "Ring of Protection" in out["error"]
    out = srd35_call("set_build", character="Thorin", items=["ring of protection +7"])
    assert "Ring of Protection comes as +1, +2, +3, +4 or +5" in out["error"]
    out = srd35_call("set_build", character="Thorin", items=["ring of protection"])
    assert "Ring of Protection: name its bonus" in out["error"]
    out = srd35_call("set_build", character="Thorin", items=["flaming longsword"])
    assert "a weapon with a special ability must have at least a +1 enhancement bonus" in out["error"]
    out = srd35_call("set_build", character="Thorin", items=["+5 holy speed vorpal longsword"])
    assert "an effective bonus higher than +10" in out["error"]
    out = srd35_call("set_build", character="Thorin", items=["holy"])
    assert "Holy is a weapon special ability" in out["error"]


def test_a_magic_weapon_takes_an_empty_hand(srd35_call):
    # With nothing in hand, a magic weapon named in the items is the weapon in hand; with another in hand, it is
    # carried.
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Thorin", items=["+1 longsword", "+1 chain shirt"])
    assert (out["build"]["weapon"], out["build"]["armor"]) == ("longsword", "chain shirt")
    out = srd35_call("set_build", character="Thorin", weapon="dagger", items=["+1 longsword"])
    assert out["build"]["weapon"] == "dagger"


def test_an_amulet_of_health_raises_hit_points_while_worn(srd35_call):
    # Fighter 1, Con 14 (+2), 12 hp. An amulet of health +2: Con 16 (+3), 1 more hit point a Hit Die: 13. Off: 12.
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Thorin", items=["amulet of health +2"])
    assert "error" not in out, out
    shown = srd35_call("get_character", ref="Thorin", brief=True)
    assert (shown["hp_max"], shown["hp"]) == (13, 13)
    srd35_call("set_build", character="Thorin", items=[])
    shown = srd35_call("get_character", ref="Thorin", brief=True)
    assert (shown["hp_max"], shown["hp"]) == (12, 12)


def test_a_headband_earns_no_skill_points(srd35_call):
    # "This enhancement bonus does not earn the wearer extra skill points": a human fighter 1 with Int 10 has
    # (2 + 0 + 1) × 4 = 12 points, a headband of intellect +2 (Int 12, +1) or not.
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Thorin", items=["headband of intellect +2"],
                     skills={"climb": 4, "jump": 4, "intimidate": 4})  # fmt: skip
    assert out["skill_points"] == {"spent": 12, "total": 12}


# --- the treasure's names (final review) ----------------------------------------------------------------------------

ROLLED = ("weapon", "armor", "shield", "ring", "rod", "staff", "item")
"""The random magic items a character can wear or wield: weapons, armour, shields, rings, rods, staffs, wondrous."""


def test_every_rolled_wearable_item_is_accepted_by_set_build():
    # 200 seeded hoards, EL 1 to 20 (10 each, double standard): every weapon, armour, shield, ring, rod, staff and
    # wondrous item the treasure rolls is a build item, as an effect or a note, and no refusal.
    from delve_srd35.engine import tools
    from delve_srd35.treasure import TREASURE

    from delve.dice import SeededRng

    seen = 0
    for n in range(200):
        dice = Dice(SeededRng(n), MemoryRollLog(), "c", "beat")
        for item in TREASURE.generate(dice, f"EL {n % 20 + 1}, double standard").magic:
            if item.category.split()[-1] not in ROLLED:
                continue
            problems: list[str] = []
            entry = tools._item(item.name, problems)
            assert entry is not None and not problems, (item.name, problems)
            seen += 1
    assert seen > 150


def test_the_treasure_grammar_reads_as_the_builds(srd35_call):
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Thorin", weapon="dagger", items=[
        "+3 greataxe (shock)", "+1 heavy steel shield (bashing)", "+4 full plate (fortification, moderate)",
        "+3 chain shirt (spell resistance (13); wild)", "Cold iron longsword, masterwork", "Mithral shirt",
        "Ring of spell storing, minor", "Ring of wizardry (I)", "Feather token, tree",
        "Carpet of flying, 5 ft. by 5 ft.", "Rod of metamagic, Extend, lesser", "Staff of frost"])  # fmt: skip
    assert "error" not in out, out
    got = {i["name"]: i for i in out["build"]["items"]}
    assert got["+3 greataxe (shock)"]["abilities"] == ["shock"]
    assert got["+1 heavy steel shield (bashing)"]["id"] == "shield-heavy-steel"
    assert got["+4 full plate (fortification, moderate)"]["abilities"] == ["fortification"]
    assert got["+3 chain shirt (spell resistance (13); wild)"]["abilities"] == ["spell-resistance", "wild"]
    # A masterwork cold iron longsword: both kept (cold iron isn't always masterwork).
    assert got["masterwork cold iron longsword"] == {"id": "longsword", "kind": "weapon", "bonus": 0,
        "name": "masterwork cold iron longsword", "material": "cold iron", "masterwork": True}  # fmt: skip
    # The SRD's mithral shirt: "This extremely light chain shirt is made of very fine mithral links."
    assert (got["mithral chain shirt"]["id"], got["mithral chain shirt"]["material"]) == ("chain-shirt", "mithral")
    for name, id in (("Ring of spell storing, minor", "spell-storing-minor"), ("Feather token, tree", "feather-token"),
                     ("Carpet of flying, 5 ft. by 5 ft.", "carpet-of-flying"), ("Staff of Frost", "frost-staff"),
                     ("Rod of metamagic, Extend, lesser", "metamagic-extend")):  # fmt: skip
        assert (got[name]["kind"], got[name]["id"]) == ("note", id), name
    assert got["Ring of wizardry (I)"]["kind"] == "note"


def test_potions_wands_and_scrolls_are_notes_for_the_inventory(srd35_call):
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Thorin", items=["Potion of cure light wounds", "Wand of fireball (5th)",
                                                             "Scroll (arcane): magic missile"])  # fmt: skip
    assert "error" not in out, out
    assert [i["kind"] for i in out["build"]["items"]] == ["note", "note", "note"]
    assert any("belongs in the inventory" in w for w in out["warnings"])


def test_a_composite_bows_strength_rating():
    # Str 16 (+3). A +1 composite longbow (+2 Str bonus): "add your Strength bonus to damage, up to the maximum bonus
    # indicated for the bow": 1d8 + 1 + 2. Fighter 1: BAB 1 + Dex 1 + 1 = +3. Str 12 (+1) with the same bow: "less
    # than the strength rating ... a -2 penalty on attacks": +1, and 1d8 + 1 + 1.
    bow = {"id": "longbow-composite", "kind": "weapon", "name": "+1 composite longbow (+2 Str bonus)", "bonus": 1,
           "str_rating": 2}  # fmt: skip
    strong = form(fighter([bow], weapon="longbow, composite", scores={"str": 16}))
    assert (strong["bonus"], strong["damage"]) == (3, "1d8+3")
    weak = form(fighter([bow], weapon="longbow, composite", scores={"str": 12}))
    assert (weak["bonus"], weak["damage"]) == (1, "1d8+2")
    # Rated +0, as the plain bow: no Strength to damage.
    plain = form(fighter([{**bow, "str_rating": 0}], weapon="longbow, composite", scores={"str": 16}))
    assert (plain["bonus"], plain["damage"]) == (3, "1d8+1")


def test_ghost_touch_on_a_weapon_and_on_armour(srd35_call):
    # Ghost touch is a +1 weapon ability and a +3 armour one: the SRD names both "Ghost Touch".
    effects = data.load("item_effects")
    assert (effects["ghost-touch-weapon"]["on"], effects["ghost-touch-weapon"]["price"]) == ("weapon", 1)
    assert (effects["ghost-touch"]["on"], effects["ghost-touch"]["price"]) == ("armor", 3)
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Thorin", items=["+2 ghost touch longsword", "+1 ghost touch chain shirt"])
    assert "error" not in out, out
    sword, shirt = out["build"]["items"]
    assert sword["abilities"] == ["ghost-touch-weapon"] and shirt["abilities"] == ["ghost-touch"]
    out = srd35_call("set_build", character="Thorin", items=["+2 longsword (ghost touch)"])
    assert out["build"]["items"][0]["abilities"] == ["ghost-touch-weapon"]
    # +4 and ghost touch +1 on a weapon is +5; on armour +3 it would be +7, both within +10.
    out = srd35_call("set_build", character="Thorin", items=["+5 ghost touch vorpal longsword"])
    assert "+11 in all" in out["error"]


# --- aligned weapons and smite against characters (fix round 1) ------------------------------------------------------


def _villain(alignment: str) -> Combatant:
    built = dataclasses.replace(sheet("Fighter", {"fighter": 1}, []), label="Villain", alignment=alignment)
    filled = ENGINE.fill_derived(built, REF)
    character = Character("pc_2", "c", "Villain", sheet=filled)
    return ENGINE.combatant_from_sheet(character, Combatant("pc_2", "Villain", "enemy", character_id="pc_2", hp=30))


def test_a_holy_longsword_against_a_chaotic_evil_character():
    # A combatant made from a sheet carries the sheet's alignment in words ("CE" is chaotic evil). A +1 holy
    # longsword at it (AC 10): 12 + 4 hits; 6 + 3 = 9, holy 2 + 5 = 7: 16. At a lawful good one, no 2d6: 9.
    villain = _villain("CE")
    assert villain.d20["alignment"] == "chaotic evil"
    holy = combatant(fighter([{"id": "longsword", "kind": "weapon", "bonus": 1, "abilities": ["holy"]}],
                             weapon="longsword"))  # fmt: skip
    out = swing(holy, villain, 12, 6, 2, 5)
    assert out.damage == 16 and "holy: +2d6 against an evil target (7)" in out.notes
    good = swing(holy, _villain("Lawful Good"), 12, 6)
    assert good.damage == 9 and "holy: no +2d6 (lawful good)" in good.notes
    # Without an alignment on the sheet, the DM's note.
    unaligned = swing(holy, _villain(""), 12, 6)
    assert "holy: +2d6 against an evil target: the DM's (not rolled)" in unaligned.notes


def test_smite_evil_lands_on_an_evil_character():
    # Paladin 1's waiting smite (+2 to hit, +1 damage) on a neutral evil PC: it lands.
    from delve_srd35.engine import class_features

    melee = {"name": "longsword", "ranged": False, "touch": False}
    smite = {"smite": {"to_hit": 2, "damage": 1}}
    assert class_features.smite(smite, melee, _villain("NE"))[:3] == (2, 1, "smite evil: +2 to hit, +1 damage")
    assert class_features.smite(smite, melee, _villain("NG"))[0] == 0


def test_holy_against_a_monster_of_any_alignment_is_the_dms():
    # A row whose alignment is "Any (same as creator)" says nothing of evil: the DM's note, not "no +2d6".
    any_row = next(r["id"] for r in data.load("monsters") if str(r.get("alignment", "")).lower().startswith("any"))
    holy = combatant(fighter([{"id": "longsword", "kind": "weapon", "bonus": 1, "abilities": ["holy"]}],
                             weapon="longsword"))  # fmt: skip
    target = dataclasses.replace(monster(any_row), d20={**monster(any_row).d20, "ac": 0, "touch": 0, "flat_footed": 0})
    out = swing(holy, target, 12, 6)
    assert "holy: +2d6 against an evil target: the DM's (not rolled)" in out.notes
