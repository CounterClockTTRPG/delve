"""Every monster in a fight, size in combat and XP above CR 20 (DEL-389 part 3, Task 4). Each number is worked by
hand in its comment from the SRD rows (monsters.json), the weapons table (weapons.json) and the SRD's Table: Tiny and
Large Weapon Damage and Table: Increased Damage By Size."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from delve_srd35 import data
from delve_srd35.engine import Srd35Engine, attack_line, combat, progress
from delve_srd35.reference import Srd35Reference
from test_combat import dice, hero, monster, target
from test_wild_shape_and_companions import Table

from delve.domain.campaigns import Character
from delve.domain.characters import CharacterState, Sheet
from delve.rules.classic.combat import AttackBlock, Combatant, CombatError

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
SOURCES = Path(__file__).resolve().parents[2] / "SOURCES.md"


def _listed(heading: str) -> set[str]:
    """The names of a SOURCES.md list: each "- **Name:** reason." line under the heading."""
    section = SOURCES.read_text(encoding="utf-8").split(f"### {heading}", 1)[1].split("\n#", 1)[0]
    return set(re.findall(r"^- \*\*(.+?):\*\* ", section, re.MULTILINE))


def _core(row: dict) -> Combatant:
    return Combatant("mon_1", row["name"], "enemy", hp=10, hp_max=10, attacks=(AttackBlock("", "1d6", "1d6"),))


@pytest.fixture
def table(srd35_call, srd35_storage, srd35_campaign):
    return Table(srd35_call, srd35_storage, srd35_campaign)


# --- every monster ------------------------------------------------------------------------------------------------


def test_every_monster_becomes_a_combatant():
    refused, unarmed, unread = {}, set(), {}
    for row in data.load("monsters"):
        try:
            made = ENGINE.combatant_from_monster(row, _core(row), {})
        except CombatError as error:
            refused[row["name"]] = str(error)
            continue
        if made.d20.get("warnings"):
            unread[row["name"]] = made.d20["warnings"]
        if not made.d20["attacks"]:
            unarmed.add(row["name"])
            assert made.d20["no_attack"], row["name"]
    assert unread == {}  # every attack line reads
    families = {r["name"] for r in data.load("monsters") if r.get("variants")}
    # The refused ones are the families; SOURCES.md's other rows without a stat block (templates and race entries)
    # and its monsters whose line is "—" fight with no attack, and nothing else has none.
    assert set(refused) == families
    assert unarmed == (_listed("Rows with no attacks of their own") - families) | _listed("Monsters with no attack")


def test_the_pixies_longbow_reads_its_critical_after_the_dice():
    # "longbow +5 ranged (1d6–2)/x3": the SRD prints the pixie's ×3 outside the parentheses.
    forms, warnings = attack_line.read("Short sword +5 melee (1d4–2/19–20) or longbow +5 ranged (1d6–2)/x3")
    assert warnings == []
    bow = forms[1]
    assert (bow["name"], bow["bonus"], bow["damage"], bow["mult"], bow["ranged"]) == ("longbow", 5, "1d6-2", 3, True)


def test_a_template_or_race_entry_has_no_attack_and_names_the_monsters_built_on_it():
    werebear = next(r for r in data.load("monsters") if r["name"] == "Werebear")
    said = ENGINE.combatant_from_monster(werebear, _core(werebear), {}).d20["no_attack"]
    assert "Werebear is a template, with no stat block of its own" in said and "Human Form Werebear" in said
    drow = next(r for r in data.load("monsters") if r["name"] == "Drow")
    said = ENGINE.combatant_from_monster(drow, _core(drow), {}).d20["no_attack"]
    assert "Drow is a race entry" in said and "1st-level Warrior Drow" in said
    lich = monster("lich")
    die, _ = dice(15)
    with pytest.raises(CombatError, match="Lich is a template"):
        combat.swing(lich, target(), "", die, 2)


def test_a_bat_has_no_attack_to_swing():
    # The SRD bat's Attack and Full Attack are "—": it has no attack, and doesn't swing core's 1d6.
    bat = monster("bat")
    assert bat.d20["attacks"] == [] and "no_attack" in bat.d20
    die, _ = dice(15)
    with pytest.raises(CombatError, match="no attack"):
        combat.swing(bat, target(), "", die, 2)


def test_a_bat_in_setup_and_its_swing_refused(srd35_call, table):
    table.character("Bram", "Fighter", 1)
    out = srd35_call("setup_combat", enemies=[{"name": "bat", "count": 1, "hp": 2}], surprise=False)
    assert "error" not in out, out
    refused = srd35_call("resolve_attack", attacker="Bat", target="Bram")
    assert "no attack" in refused["error"]


# --- size ---------------------------------------------------------------------------------------------------------


def test_weapon_damage_by_size():
    # Table: Tiny and Large Weapon Damage: 1d8 is 1d4 Tiny, 2d6 Large; 1d12 is 3d6 Large. Huge is Large stepped once
    # more by Table: Increased Damage By Size: 1d8 → 2d6 → 3d6; 1d6 → 1d8 → 2d6. Small is the table's own column.
    longsword = attack_line.weapon("longsword")
    assert attack_line.sized(longsword, "medium") == ("1d8", None)
    assert attack_line.sized(longsword, "small") == ("1d6", None)
    assert attack_line.sized(longsword, "tiny") == ("1d4", None)
    assert attack_line.sized(longsword, "large") == ("2d6", None)
    assert attack_line.sized(longsword, "huge") == ("3d6", None)
    assert attack_line.sized(attack_line.weapon("greataxe"), "large") == ("3d6", None)
    assert attack_line.sized(attack_line.weapon("short sword"), "huge") == ("2d6", None)
    # 2d6 is 3d6 Large; past Table: Increased Damage By Size, Improved Natural Attack's progression: 3d6, 4d6, 6d6, 8d6.
    greatsword = attack_line.weapon("greatsword")
    assert [attack_line.sized(greatsword, size) for size in ("huge", "gargantuan", "colossal")] == [
        ("4d6", None), ("6d6", None), ("8d6", None)]  # fmt: skip
    # The bastard sword's 1d10 is 2d8 Large, then 3d8 and 4d8.
    assert attack_line.sized(attack_line.weapon("bastard sword"), "gargantuan") == ("4d8", None)


SRD = Path(os.environ.get("DELVE_SRD35_MARKDOWN", "/nonexistent"))  # a local Markdown copy of the SRD, if any


def _rows(text: str, start: str, end: str) -> list[list[str]]:
    """The cells of each table row between `start` and `end` in an SRD Markdown file: the lines of dice words."""
    section = text.split(start, 1)[1].split(end, 1)[0]
    return [line.split() for line in section.splitlines() if re.match(r"\s*\d+d\d+\s", line)]


@pytest.mark.skipif(not SRD.is_dir(), reason="set DELVE_SRD35_MARKDOWN to a Markdown copy of the SRD")
def test_the_typed_size_tables_are_the_srds():
    equipment = (SRD / "Basic Rules and Legal" / "equipment.md").read_text(encoding="utf-8")
    rows = _rows(equipment, "Table: Tiny and Large Weapon", ": Table: Tiny and Large Weapon Damage")
    assert len(rows) == 11
    assert attack_line.LARGE == {medium: large for medium, _, large in rows}
    assert attack_line.TINY == {medium: tiny for medium, tiny, _ in rows if tiny != "---"}  # 1d2's Tiny is "—"
    improving = (SRD / "Monsters" / "Improving Monsters.md").read_text(encoding="utf-8")
    rows = _rows(improving, "Old Damage (Each)", ": Table: Increased Damage By Size")
    assert attack_line.STEP_UP == {old: new for old, new in rows}
    feats = (SRD / "Monsters" / "Monster Feats.md").read_text(encoding="utf-8")
    benefit = " ".join(feats.split("## Improved Natural Attack", 1)[1].split("##", 1)[0].split())
    chains = [tuple(re.findall(r"\d+d\d+", said)) for said in re.findall(r"category: ([^.]+)\.|follows: ([^.]+)\.", benefit)
              for said in said if said]  # fmt: skip
    assert attack_line.PROGRESSIONS == tuple(chains)


def test_improved_natural_attack_steps_down_past_the_table():
    # Backwards along the progressions: 4d6 is 3d6's step, 6d8 is 4d8's.
    assert (attack_line.STEP_DOWN["4d6"], attack_line.STEP_DOWN["6d8"], attack_line.STEP_DOWN["2d6"]) == (
        "3d6", "4d8", "1d8")  # fmt: skip


def test_large_centaur_longbow_and_lance():
    # A centaur fighter 1, Str 18 (+4), Dex 14 (+2): racial BAB +4 + fighter +1 = +5; Large: -1 on attacks.
    # Longbow (its Large one, the race's size): 5 + Dex 2 - 1 = +6, 1d8 Medium is 2d6 Large, ×3; no Str on a longbow.
    bow = hero("Fighter", {"fighter": 1}, {"str": 18, "dex": 14}, race="Centaur", weapon="longbow")
    form = bow.d20["attacks"][0]
    assert (form["bonus"], form["damage"], form["mult"]) == (6, "2d6", 3)
    assert bow.size == "L"
    # Lance (two-handed): 5 + Str 4 - 1 = +8, 1d8 → 2d6, + 1½ × Str 4 = 6, ×3.
    lance = hero("Fighter", {"fighter": 1}, {"str": 18, "dex": 14}, race="Centaur", weapon="lance")
    form = lance.d20["attacks"][0]
    assert (form["bonus"], form["damage"], form["mult"], form["hands"]) == (8, "2d6+6", 3, 2)


def test_a_centaur_pc_kicks_with_its_hooves_beside_its_weapon():
    # The SRD centaur's "Longsword … and 2 hooves +3 melee (1d6+2)": a centaur fighter 1 with a longsword, Str 18 (+4),
    # BAB +5. Beside a weapon its hooves are secondary: 5 + 4 - 1 (Large) - 5 = +3, 1d6 + ½ × 4 = 1d6+2, two of them.
    centaur = hero("Fighter", {"fighter": 1}, {"str": 18, "dex": 14}, race="Centaur", weapon="longsword")
    forms = {f["name"]: f for f in centaur.d20["attacks"]}
    sword, hoof = forms["longsword"], forms["hoof"]
    assert (sword["bonus"], sword["damage"]) == (8, "2d6+4")
    assert (hoof["bonus"], hoof["damage"], hoof["count"]) == (3, "1d6+2", 2)
    assert [b.name for b in centaur.attacks][:2] == ["longsword", "hoof"]
    # A human has no natural attacks.
    assert [f["name"] for f in hero("Fighter", {"fighter": 1}, {}, weapon="longsword").d20["attacks"]] == ["longsword"]


def test_a_troll_pc_unarmed_claws_and_bites_by_its_line():
    # The SRD troll: "2 claws +9 melee (1d6+6) and bite +4 melee (1d6+3)". A troll fighter 1 with no weapon, Str 22
    # (+6), racial BAB +4 ("+4/+14") + 1 = 5: claws primary 5 + 6 - 1 = +10, 1d6+6; bite secondary +5, 1d6 + 3.
    troll = hero("Fighter", {"fighter": 1}, {"str": 22}, race="Troll")
    forms = {f["name"]: f for f in troll.d20["attacks"]}
    assert (forms["claw"]["bonus"], forms["claw"]["damage"], forms["claw"]["count"]) == (10, "1d6+6", 2)
    assert (forms["bite"]["bonus"], forms["bite"]["damage"]) == (5, "1d6+3")


def test_an_ogre_fighter_swings_a_large_greatclub():
    # An ogre fighter 1, Str 21 (+5): racial BAB +3 + 1 = +4; greatclub 4 + 5 - 1 = +8; 1d10 Medium is 2d8 Large,
    # + 1½ × 5 = 7: 2d8+7, the SRD ogre's own greatclub damage.
    ogre = hero("Fighter", {"fighter": 1}, {"str": 21}, race="Ogre", weapon="greatclub")
    form = ogre.d20["attacks"][0]
    assert (form["bonus"], form["damage"]) == (8, "2d8+7")


def test_a_medium_fighter_with_a_large_longsword():
    # Human fighter 1, Str 16 (+3): BAB 1 + 3, -2 for a weapon one size too big; a Large longsword is two-handed for a
    # Medium wielder (one step of effort), so 1½ × Str: 2d6 + 4.
    big = hero("Fighter", {"fighter": 1}, {"str": 16}, weapon="large longsword")
    form = big.d20["attacks"][0]
    assert (form["bonus"], form["damage"], form["hands"], form["threat"]) == (2, "2d6+4", 2, 19)
    assert "warnings" not in big.d20
    # A Large greatsword would be beyond two-handed: it can't be wielded, and says so.
    huge = hero("Fighter", {"fighter": 1}, {"str": 16}, weapon="large greatsword")
    assert any("can't be wielded" in w for w in huge.d20["warnings"])
    die, _ = dice(15)
    with pytest.raises(CombatError, match="can't be wielded"):
        combat.swing(huge, target(), "", die, 2)
    # A Medium character's plain longsword is Medium: as before.
    plain = hero("Fighter", {"fighter": 1}, {"str": 16}, weapon="longsword")
    assert (plain.d20["attacks"][0]["bonus"], plain.d20["attacks"][0]["damage"]) == (4, "1d8+3")


def test_a_small_halfling_is_as_before():
    # Halfling fighter 1, Str 10, Dex 10: BAB 1 + size 1 = +2; a Small short sword 1d4.
    pip = hero("Fighter", {"fighter": 1}, {}, race="Halfling", weapon="short sword")
    assert (pip.d20["attacks"][0]["bonus"], pip.d20["attacks"][0]["damage"], pip.size) == (2, "1d4", "S")


# --- companions ---------------------------------------------------------------------------------------------------


def test_a_companions_secondary_bite_half_str(srd35_call, table):
    # A druid 9's brown bear (6 levels lower on the 7th-level list: a druid 3's block, +2 HD, +1 Str). The SRD brown
    # bear: 6 HD, Str 27 (+8): "2 claws +11 melee (1d8+8) and bite +6 melee (2d6+4)", the bite secondary (−5 and ½
    # Str, in the line). Str 28 (+9): BAB 3/4 of 8 HD = 6 (+2), claws 11 + 2 + 1 = +14 for 1d8 + 9; bite 6 + 2 + 1 =
    # +9 for 2d6 + ½ × 9 = 4, as it was.
    table.character("Ash", "Druid", 9)
    assert "error" not in (out := srd35_call("add_companion", master="Ash", animal="brown bear", name="Bruin")), out
    table.enemies("orc")
    forms = {f["name"]: f for f in table.combatant("Bruin").d20["attacks"]}
    assert (forms["claw"]["bonus"], forms["claw"]["damage"]) == (14, "1d8+9")
    assert (forms["bite"]["bonus"], forms["bite"]["damage"]) == (9, "2d6+4")


def test_a_companions_sole_bite_takes_one_and_a_half_str(srd35_call, table):
    # A druid 3's wolf: Str 13 (+1) → 14 (+2); its bite is its only natural attack, so 1½ × Str: the SRD's "1d6+1"
    # (1½ × 1 = 1) becomes 1d6 + 3 (1½ × 2).
    table.character("Ash", "Druid", 3)
    srd35_call("add_companion", master="Ash", animal="wolf", name="Grey")
    table.enemies("orc")
    assert table.combatant("Grey").d20["attacks"][0]["damage"] == "1d6+3"


def test_a_companion_horses_hooves_are_secondary(srd35_call, table):
    # The light horse: "2 hooves –2 melee (1d4+1)", Str 14 (+2): its hooves are secondary (½ Str is the line's +1).
    # A druid 3's: Str 15, still +2, so ½ × 2 = 1: 1d4+1, as it was.
    table.character("Ash", "Druid", 3)
    srd35_call("add_companion", master="Ash", animal="light horse", name="Dun")
    table.enemies("orc")
    assert table.combatant("Dun").d20["attacks"][0]["damage"] == "1d4+1"


# --- wild shape ---------------------------------------------------------------------------------------------------


def _shaped(animal: str, **d20) -> Combatant:
    sheet = ENGINE.fill_derived(
        Sheet(label="Ash", cls="Druid", race="Human", levels={"druid": 8}, ability_scores={
            "str": 10, "dex": 10, "con": 10, "int": 10, "wis": 14, "cha": 10}, d20=d20), REF,
    )  # fmt: skip
    character = Character("pc_1", "c", "Ash", sheet=sheet, state=CharacterState(d20={"shape": {"monster": animal}}))
    return ENGINE.combatant_from_sheet(character, Combatant("pc_1", "Ash", "party", character_id="pc_1", hp=10))


def test_wild_shape_keeps_her_dodge_bonus():
    # A druid 8 with Dodge as a wolf: the wolf's AC 14, touch 12, flat-footed 12, and her dodge +1 on AC and touch
    # (not flat-footed): 15, 13, 12. Her armour melds; non-armour bonuses stay.
    wolf = _shaped("wolf", feats=["dodge"])
    assert (wolf.ac, wolf.d20["ac"], wolf.d20["touch"], wolf.d20["flat_footed"]) == (15, 15, 13, 12)
    plain = _shaped("wolf")
    assert (plain.d20["ac"], plain.d20["touch"], plain.d20["flat_footed"]) == (14, 12, 12)


def test_wild_shape_strips_improved_natural_attack():
    # The SRD rhinoceros: "Gore +13 melee (2d6+12)", Improved Natural Attack (gore): without it its gore is one step
    # less (Table: Increased Damage By Size, 1d8 → 2d6, backwards): 1d8+12. Its BAB +6, hers +6 (druid 8): +13.
    gore = _shaped("rhinoceros").d20["attacks"][0]
    assert (gore["name"], gore["bonus"], gore["damage"]) == ("gore", 13, "1d8+12")


def test_wild_shape_strips_multiattack():
    # The SRD roc (feats: Multiattack): "2 talons +21 melee (2d6+12) and bite +19 melee (2d8+6)": its bite secondary at
    # −2. Without the feat, −5: 3 less. Its BAB +13, hers +6: talons 21 − 7 = +14, bite 19 − 7 − 3 = +9.
    forms = {f["name"]: f for f in _shaped("roc").d20["attacks"]}
    assert (forms["talon"]["bonus"], forms["bite"]["bonus"]) == (14, 9)


# --- XP -----------------------------------------------------------------------------------------------------------


def test_xp_for_cr_22_and_25():
    # Unearthed Arcana's Table 6-14: CR 20 is 310,000; beyond, twice the award of CR − 2: 21 is 2 × 230,000 = 460,000,
    # 22 is 2 × 310,000 = 620,000, 23 is 920,000, 25 is 2 × 920,000 = 1,840,000.
    assert [progress.cr_award(c) for c in ("22", "23", "25")] == [620000, 920000, 1840000]
    # The great wyrm blue dragon's CR 25 (its row).
    wyrm = next(r for r in data.load("monsters") if r["name"] == "Great Wyrm Blue Dragon")
    assert progress.cr_award(progress.cr_for(wyrm)) == 1840000


def test_a_cr_with_a_variant_in_parentheses_is_the_blocks_own():
    # "8 (elder 9)": the stone giant's block is CR 8, its elder 9; the pixie's "4 (5 with irresistible dance)" and the
    # djinni's "5 (noble 8)" likewise; the satyr's "2 (without pipes) or 4 (with pipes)" the first.
    rows = {r["name"]: r for r in data.load("monsters")}
    assert [progress.cr_for(rows[n]) for n in ("Stone Giant", "Pixie", "Djinni", "Satyr")] == ["8", "4", "5", "2"]
    for row in rows.values():
        if str(row.get("full_attack") or "").strip():
            assert progress.cr_for(row) is not None, row["name"]


# --- the setup's summary ------------------------------------------------------------------------------------------


def test_setup_summary_shows_iterative_count(srd35_call, table):
    # The SRD hill giant's "Greatclub +16/+11 melee (2d8+10)": two attacks a round, as its combatant swings them.
    table.character("Bram", "Fighter", 1)
    out = srd35_call("setup_combat", enemies=[{"name": "hill giant", "count": 1, "hp": 100}], surprise=False)
    group = out["enemies"][0]
    assert group["attacks_per_round"] == 2.0
    giant = table.combatant("Hill Giant")
    assert giant.attacks[giant.weapon].rate == 2.0
