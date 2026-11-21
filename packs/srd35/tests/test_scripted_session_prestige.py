"""A scripted SRD 3.5 session for the prestige classes (DEL-389 part 4), through the tool host with seeded dice and the
tripwire on: a wizard 5/fighter 1 refused as an eldritch knight until a headband lets it cast 3rd-level spells, then
entering, advancing its wizard casting and rolling its caster level against a babau's SR; a rogue 5 refused as an
assassin with every requirement it lacks, then in once the DM confirms the kill, its sneak attack stacked; a dwarf
fighter 7 entering the dwarven defender and taking a defensive stance against an ogre, winded after; an elf ranger 6
refused as an arcane archer, then a wizard level and in, its arrows magic against a gargoyle's DR 10/magic; a cleric
3/wizard 3 entering the mystic theurge and casting 3rd-level spells from both advanced pools; the eldritch knight's XP,
penalised by its base classes only; and a rogue 10/assassin 10 at the top, which a bugbear can't flank.

Each class is entered as the DM enters one: `update_character` with a `levels` patch by the spaced names. A first level
in a new class is core's level-up as any other is (DEL-457): it rolls the hit die, adds it with the Con modifier to the
maximum and current hit points, and gives the level's hints in `d20["level_up"]` (its skill points, the eldritch
knight's bonus feat). Two unrecorded `get_character` calls after each entry (`entered`) hold the places of the DM's own
roll and read the session made before DEL-457, so every later call keeps its seed, and the level-up rolls on the seed
that roll had: the same faces. The whole party fights each fight (core joins every party character); those not named
in a round stand by. The ogre and the second bugbear are given hit points (60, 100) so they stand long enough.

Differences from the brief, the SRD deciding: the elf ranger 6 can't enter the arcane archer ("Spells: Ability to cast
1st-level arcane spells"; a ranger's spells are divine): it is refused, takes a wizard level, and enters as a ranger
6/wizard 1. The brief's fighter 6/wizard 1/eldritch knight 3 can't be built (a wizard 1 casts no 3rd-level spells): the
XP is the eldritch knight Ansel's, wizard 5/fighter 1/eldritch knight 3, where counting the prestige class would cost
20% (fighter 1 against eldritch knight 3). The session found one engine bug, fixed in its own commit before it: winded
outlived the fight (core's end_combat wrote it back to the character, and Thrain was winded in the next fight); "for the
duration of that encounter", the pack's end_combat now takes it off. Nothing was dropped as impossible. The final
review changed two numbers no swing turned on: the stance's +4 dodge AC is lost flat-footed, so the ogre's first swing
is against 20 (27 hits), and an attacker's rogue level against improved uncanny dodge is its rogue levels only (Vex 5,
Shade 10).

The golden was checked by hand against the pack's SRD copy (`classes.json`'s tables and texts, `monsters.json`,
`xp.json`) and the logged faces (`rolls`; `answers[i]` is the i-th recorded call):

- **Ansel** (`answers[0..8]`): human wizard 5/fighter 1, Int 12: BAB 2 + 1 = 3, Fort 1 + 2 + 1 = 4, Ref 1 + 0 + 2 = 3,
  Will 4; Table: The Wizard 5th 4/3/2/1, but "an Intelligence score equal to at least 10 + the spell level": 0–2nd, Int
  12's bonus 1st: 4/4/2, DC 11/12/13. Refused: "the ability to cast 3rd-level arcane spells (it casts arcane spells up
  to 2nd level)"; martial proficiency is the fighter's, met. The headband of intellect +2: Int 14, 4/4/3/1 (bonus 1st
  and 2nd), DC 12 + level; a longsword +6 (BAB 5 + Str 1 by the fight), 1d8+1. Eldritch knight 1: d6 [2] + 1 = 3, 30 →
  33; hints 2 + Int 1 + human 1 = 4 skill points, an eldritch-knight bonus feat (the table's 1st); BAB +1 = 4, Fort +2 =
  6; no caster level at 1st (the table's "+1 level of existing arcane spellcasting class" from 2nd). 2nd: the level-up's
  d6 [2] + 1 = 3, 36; BAB 5, Fort 7; the wizard at caster level 6, Table: The Wizard 6th 4/3/3/2 + 1st and 2nd =
  4/4/4/2; hints 2 + Int 1 (the headband's bonus "does not earn the wearer extra skill points") + human 1 = 4 skill
  points, an ability increase (8th character level). The babau (`monsters.json`): 7d8+35 [8, 6, 5, 3, 3, 1, 6] = 67, AC
  19, touch 11, flat-footed 18, SR 14; Ansel's check d20 [19] + caster level 6 = 25, overcome.
- **Vex** (`answers[9..20]`): human rogue 5, Dex 16, Int 14: BAB 3, Fort 1 + 1 = 2, Ref 4 + 3 = 7, Will 1; sneak 3d6.
  Refused with all four: Disguise 4, Hide 8, Move Silently 8 (0 each) and the DM's confirmation. The ranks: 88 points
  ((8 + 2 + 1) × 4 + 4 × 11), 20 spent; Hide 8 + 3 = 11; leather AC 10 + 2 + 3 = 15. Refused again with only the
  confirmation; confirmed, in: d6 [5] + 1 = 6, 28 → 34; hints 4 + Int 2 + human 1 = 7 skill points, a feat (6th
  character level); assassin 1 Ref +2 = 9, BAB +0; Table: The Assassin 1st, 0 1st-level spells a day + Int 14's bonus 1
  = 1, 2 known, DC 13; sneak 1d6 + 3d6 = 4d6 ("If an assassin gets a sneak attack bonus from another source the bonuses
  on damage stack"). The bugbear: 3d8+3 [3, 5, 2] = 13, AC 17, touch 11, flat-footed 16, morningstar +5 1d8+2, CR 2.
  Initiative: Vex 19 + 3 = 22, Ansel 11 + 2 = 13, bugbear 6 + 1 = 7. Ansel flanks without swinging. Vex's short sword
  BAB 3 + Str 1 = +4, +2 flanking: round 1 [6] + 6 = 12 misses (flat-footed 16); the bugbear [14] + 5 = 19 hits AC 15,
  [7] + 2 = 9, 34 → 25. Round 2: [5] + 6 and [8] + 5 miss; round 3: [10] + 6 = 16 < 17 and [3] + 5 miss; round 4: [13] +
  6 = 19 hits, [5] + 1 = 6 and sneak [2, 2, 2, 2] = 8, 14, 13 → −1, slain: 600 XP.
- **Thrain** (`answers[21..31]`): dwarf fighter 7, Str 16, Dex 13, Con 14: BAB 7, Fort 5 + 2 = 7, Ref 2 + 1 = 3, Will 2
  + 1 = 3; seven feats (3 + bonus 1st, 2nd, 4th, 6th); full plate 8 + heavy steel shield 2 + Dex 1 (max 1) + Dodge 1 =
  AC 22, touch 12, flat-footed 20; armour check −6 − 2 = −8; speed 20. Dwarven defender 1 (any lawful, BAB +7, Dodge,
  Endurance, Toughness, dwarf: met): Toughness's +3 first, 64 → 67 (`set_build`), then d12 [2] + 2 = 4, 67 → 71; hints 2 + Int 0 = 2 skill points, an ability increase
  (8th); BAB 8, Fort +2 = 9, Will +2 = 5; AC bonus +1 dodge: AC 23, touch 13, flat-footed 20; the waraxe 8 + 3 + Weapon
  Focus 1 = +12/+7, 1d10 + 3 + Specialization 2 = 1d10+5, ×3. The ogre at 60 hp: AC 16, touch 8, greatclub +8 2d8+7.
  Initiative: Vex 16 + 3 = 19, ogre 13 − 1 = 12, Thrain 4 + 1 = 5, Ansel 1 + 2 = 3. The stance: Con 18, "3 + the
  character's (newly improved) Constitution modifier" = 7 rounds, 2 hp × 8 levels = 16, 71 → 87 (maximum and current),
  the +4 AC as an effect. Round 1: the ogre at Thrain, flat-footed: [19] + 8 = 27 hits, [3, 4] + 7 = 14, 87 → 73. Thrain
  with Str 18: [9] + 12 + 1 = 22 hits AC 16, [8] + 5 + 1 = 14, 60 → 46; [18] + 7 + 1 hits, [9] + 6 = 15, 31. Fortitude
  in the stance: 9 + 2 resistance + 2 of the Con = 13, [17] + 13 = 30. Ended: 16 hp off, 73 → 57 (maximum 71), winded,
  Str 14. Round 2: the ogre [11] + 8 = 19 < 23; Thrain [2] and [1] miss. Round 3: the ogre's 20, confirm [3] + 8 = 11
  fails, [1, 6] + 7 = 14, 43; Thrain winded: [15] + 8 + 2 + 1 = 26 hits, [9] + 2 + 2 = 13 (1d10+4), 31 → 18; [4] + 6
  misses. The fight's end: Thrain no longer winded.
- **Ilsa** (`answers[32..39]`): elf ranger 6, Dex 18, Wis 12: BAB 6, Fort 5, Ref 5 + 4 = 9, Will 2 + 1 = 3; casts as a
  ranger of half her level, 3, one 1st-level slot + Wis 12's bonus = 2, DC 12. Studded leather 3 + 4 = AC 17. Point
  Blank Shot, Precise Shot, Weapon Focus (longbow). Refused: "the ability to cast 1st-level arcane spells (it casts no
  arcane spells)". A wizard level: d4 [1], 40 → 41; hints 2 + Int 1 = 3 skill points; Will +2 = 5; wizard 1 3/1 + Int
  12's 1st = 3/2, spell failure 15% (studded leather). Arcane archer 1: d8 [5], 46; hints 4 + Int 1 = 5 skill points, an
  ability increase (8th); BAB 7, Fort +2 = 7, Ref +2 = 11; the longbow 7 + 4 + 1 + enhance arrow 1 = +13/+8, 1d8+1, ×3.
  The gargoyle: 4d8+19 [6, 3, 5, 4] = 37, AC 16, DR 10/magic. Initiative: gargoyle 16 + 2 = 18, Ansel 16, Vex 9, Ilsa 4
  + 4 = 8, Thrain 6. Ilsa: [3] + 13 = 16 hits, [6] + 1 = 7, the arrows magic, 37 → 30; [14] + 8 = 22 hits, [2] + 1 = 3,
  27.
- **Mira** (`answers[40..47]`): human cleric 3/wizard 3, Int 14, Wis 14: BAB 2 + 1 = 3, Fort 3 + 1 + 1 = 5, Ref 1 + 1 +
  1 = 3, Will 3 + 3 + 2 = 8; cleric 4/2/1 + Wis (1st, 2nd) + domain = 4/4/3, wizard 4/2/1 + Int = 4/3/2; turning 3.
  Knowledge (arcana) and (religion) 6 each, + 2 = 8; 45 points ((2 + 2 + 1) × 4 + 5 × 5). Mystic theurge 1: d4 [2] + 1 =
  3, 28 → 31; hints 2 + Int 2 + human 1 = 5 skill points; Will +2 = 10; warned until its two classes are named; then
  cleric 4 5/3/2 + 2 + 2 = 5/5/4, wizard 4 4/3/2 + 2 = 4/4/3. 2nd: the level-up's d4 [1] + 1 = 2, 33; BAB 4, Will 11;
  cleric 5 5/3/2/1 + Wis (1st, 2nd) + domain = 5/5/4/2, wizard 5 4/3/2/1 + Int = 4/4/3/1, 3rd-level DC 10 + 3 + 2 = 15;
  hints 2 + 2 + 1 = 5 skill points, an ability increase (8th). Prayer (cleric, 3rd, no save) and Fireball (wizard, 3rd,
  Reflex half) at caster level 5.
- **Ansel's 3rd level and XP** (`answers[48..49]`): d6 [4] + 1 = 5, 36 → 41; BAB 6, Fort 7, Ref 1 + 1 + 2 = 4, Will 5;
  the wizard at caster level 7, Table: The Wizard 7th 4/4/3/2/1 + 1st and 2nd = 4/5/4/2/1, 4th-level DC 16; hints 4
  skill points and a feat (9th). Below 9th level's 52,000 (`xp.json`), raised first; 52,000 + 9,000 = 61,000, next at
  76,000, no penalty: the human's highest class (wizard 5) is its favoured, the fighter 1 stands alone, and the eldritch
  knight doesn't count ("Taking a prestige class does not incur the experience point penalties normally associated with
  multiclassing").
- **Shade** (`answers[50..58]`): human rogue 10/assassin 10, Dex 18, Int 14: BAB 7 + 7 = 14 (+14/+9/+4), Fort 3 + 3 + 1
  = 7, Ref 7 + 7 + 4 = 18, Will 6; AC 14; sneak 5d6 + 5d6 = 10d6; improved uncanny dodge at 20 (the classes' levels
  stacked); the assassin's 10th 3/3/3/3 + Int 14's 1st and 2nd = 4/4/3/3, known 4/4/4/4. Made so, it is warned of the
  unmet requirements until set_build gives the ranks (213 points: 11 × 4 + 9 × 11 + 10 × 7) and the confirmation. The
  bugbear at 100 hp. Initiative: Ilsa 21, Shade 15 + 4 = 19, Ansel 16, bugbear 15 + 1 = 16, Vex 13, Thrain 11, Mira 9.
  The bugbear flanking Shade: "can't be flanked (rogue level 0, needs 24)", [3] + 5 misses. Shade flanking, short sword
  14 + 1 + 2 = +17/+12/+7: [3] + 17 = 20 hits, [1] + 1 = 2 and sneak [4, 4, 4, 3, 5, 4, 4, 5, 3, 2] = 38, 40, 100 → 60;
  [2] + 12 and [6] + 7 miss. At 2,600,000 (20th, `xp.json`), +50,000 = 2,650,000: 20th is the top, no next.

Every answer is compared with `golden/scripted_session_prestige.json`. The test writes the golden when it is missing and
fails; it was checked by hand against the working above, and is never regenerated. It was rewritten once, by the owner's
leave, for DEL-457: each entry's `update_character` without the DM's hit point patch, its answer with the level-up; and
once more for DEL-456: Thrain's Toughness, +3 hp throughout (68 → 71 at entry), no outcome moved; and once for DEL-431:
Thrain's and the babau's Cleave in their numbers (`cleave`), no swing dropping a foe."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parent / "golden" / "scripted_session_prestige.json"
SEED = 1
"""The first call's seed; each call after takes the next."""

ANSEL = {"str": 13, "dex": 14, "con": 12, "int": 12, "wis": 10, "cha": 8}
VEX = {"str": 12, "dex": 16, "con": 12, "int": 14, "wis": 10, "cha": 10}
THRAIN = {"str": 16, "dex": 13, "con": 14, "int": 10, "wis": 12, "cha": 6}
ILSA = {"str": 12, "dex": 18, "con": 10, "int": 12, "wis": 12, "cha": 10}
MIRA = {"str": 10, "dex": 12, "con": 12, "int": 14, "wis": 14, "cha": 10}
SHADE = {"str": 12, "dex": 18, "con": 12, "int": 14, "wis": 10, "cha": 10}


def play(call) -> list[tuple[str, dict, dict]]:
    """The session: each call as (tool, args, answer). `call(tool, **args)` runs one tool call in a beat of its own."""
    said: list[tuple[str, dict, dict]] = []

    def run(tool, **args):
        out = call(tool, **args)
        assert "error" not in out, (tool, out)
        said.append((tool, args, out))
        return out

    def refused(tool, **args):
        out = call(tool, **args)
        assert "error" in out, (tool, out)
        said.append((tool, args, out))
        return out

    def entered(name, patch, reason):
        """A first level in a new class: core's level-up, which rolls the hit die (DEL-457). Two unrecorded reads after
        it hold the places of the DM's own roll and read it replaced, so the seeds of the calls after don't move: the
        level-up rolls on the seed the DM's roll had, the same face."""
        out = run("update_character", ref=name, patch=patch, reason=reason)
        call("get_character", ref=name)
        call("get_character", ref=name)
        return out

    # 1. A wizard 5/fighter 1 with Int 12 casts no 3rd-level spells: refused as an eldritch knight. A headband of
    # intellect +2 makes it Int 14; it enters, names the wizard its advanced class, takes a 2nd level, and its caster
    # level 6 rolls against a babau's SR 14.
    run("create_character", name="Ansel", sheet={"cls": "Wizard/Fighter", "levels": {"wizard": 5, "fighter": 1},
                                                  "race": "Human", "hp_max": 30, "ability_scores": ANSEL})  # fmt: skip
    ek1 = {"cls": "Wizard/Fighter/Eldritch Knight", "levels": {"wizard": 5, "fighter": 1, "eldritch knight": 1}}
    refused("update_character", ref="Ansel", patch=ek1, reason="the order of the blade")
    run("set_build", character="Ansel", items=["headband of intellect +2"], weapon="longsword")
    entered("Ansel", ek1, "the order of the blade")
    run("set_build", character="Ansel", advances={"eldritch knight": ["wizard"]})
    ek2 = {"cls": "Wizard/Fighter/Eldritch Knight", "levels": {"wizard": 5, "fighter": 1, "eldritch knight": 2}}
    run("update_character", ref="Ansel", patch=ek2, reason="eldritch knight 2")
    run("setup_combat", enemies=[{"name": "babau", "count": 1}], surprise=False)
    run("spell_resistance", caster="Ansel", target="Babau", spell="Fireball")
    run("end_combat")

    # 2. A rogue 5 is refused as an assassin with every requirement it lacks; then the ranks, and the DM confirms the
    # kill. Its sneak attack stacks, flanking a bugbear with Ansel.
    run("create_character", name="Vex", sheet={"cls": "Rogue", "level": 5, "race": "Human", "hp_max": 28,
                                                "alignment": "Neutral Evil", "ability_scores": VEX})  # fmt: skip
    as1 = {"cls": "Rogue/Assassin", "levels": {"rogue": 5, "assassin": 1}}
    refused("update_character", ref="Vex", patch=as1, reason="joins the guild")
    run("set_build", character="Vex", skills={"disguise": 4, "hide": 8, "move silently": 8}, weapon="short sword",
        armor="leather")  # fmt: skip
    refused("update_character", ref="Vex", patch=as1, reason="joins the guild")
    kill = "kill someone for no other reason than to join"
    run("set_build", character="Vex", choices={"requirements": {"assassin": [kill]}})
    entered("Vex", as1, "joins the guild")
    run("setup_combat", enemies=[{"name": "bugbear", "count": 1}], surprise=False)
    for _ in range(4):  # until Vex hits
        run("combat_round", actions=[
            {"attacker": "Vex", "target": "Bugbear", "condition": "flanking"},
            {"attacker": "Bugbear", "target": "Vex"},
        ])  # fmt: skip
    run("end_combat")

    # 3. A dwarf fighter 7 enters the dwarven defender and takes a defensive stance against an ogre; ended, he is
    # winded for the rest of the fight.
    run("create_character", name="Thrain", sheet={"cls": "Fighter", "level": 7, "race": "Dwarf", "hp_max": 64,
                                                   "alignment": "Lawful Neutral",
                                                   "ability_scores": THRAIN})  # fmt: skip
    run("set_build", character="Thrain", feats=["dodge", "endurance", "toughness", "power attack", "cleave",
        {"id": "weapon focus", "choice": "dwarven waraxe"},
        {"id": "weapon specialization", "choice": "dwarven waraxe"}], weapon="dwarven waraxe",
        armor="full plate", shield="heavy steel shield")  # fmt: skip
    dd1 = {"cls": "Fighter/Dwarven Defender", "levels": {"fighter": 7, "dwarven defender": 1}}
    entered("Thrain", dd1, "the defenders of the hold")
    run("setup_combat", enemies=[{"name": "ogre", "count": 1, "hp": 60}], surprise=False)
    run("use_feature", character="Thrain", feature="defensive stance")
    run("combat_round", actions=[
        {"attacker": "Ogre", "target": "Thrain"},
        {"attacker": "Thrain", "target": "Ogre"},
    ])  # fmt: skip
    run("saving_throw", character="Thrain", save_type="fort", dc=15)
    run("use_feature", character="Thrain", feature="defensive stance", amount=-1)
    for _ in range(2):
        run("combat_round", actions=[
            {"attacker": "Ogre", "target": "Thrain"},
            {"attacker": "Thrain", "target": "Ogre"},
        ])  # fmt: skip
    run("end_combat")

    # 4. An elf ranger 6 with the feats casts no arcane spells (a ranger's are divine): refused as an arcane archer. A
    # wizard level, then in; its arrows are magic against a gargoyle's DR 10/magic.
    run("create_character", name="Ilsa", sheet={"cls": "Ranger", "level": 6, "race": "Elf", "hp_max": 40,
                                                 "alignment": "Chaotic Good", "ability_scores": ILSA})  # fmt: skip
    run("set_build", character="Ilsa", feats=["point blank shot", "precise shot",
        {"id": "weapon focus", "choice": "longbow"}], weapon="longbow", armor="studded leather")  # fmt: skip
    aa1 = {"cls": "Ranger/Arcane Archer", "levels": {"ranger": 6, "arcane archer": 1}}
    refused("update_character", ref="Ilsa", patch=aa1, reason="the archers of the wood")
    entered("Ilsa", {"cls": "Ranger/Wizard", "levels": {"ranger": 6, "wizard": 1}}, "a wizard's first level")
    aa1 = {"cls": "Ranger/Wizard/Arcane Archer", "levels": {"ranger": 6, "wizard": 1, "arcane archer": 1}}
    entered("Ilsa", aa1, "the archers of the wood")
    run("setup_combat", enemies=[{"name": "gargoyle", "count": 1}], surprise=False)
    run("combat_round", actions=[{"attacker": "Ilsa", "target": "Gargoyle"}])
    run("end_combat")

    # 5. A cleric 3/wizard 3 enters the mystic theurge, takes a 2nd level, and casts 3rd-level spells from both pools.
    run("create_character", name="Mira", sheet={"cls": "Cleric/Wizard", "levels": {"cleric": 3, "wizard": 3},
                                                 "race": "Human", "hp_max": 28, "alignment": "Neutral Good",
                                                 "ability_scores": MIRA})  # fmt: skip
    run("set_build", character="Mira", domains=["war", "good"], skills={"knowledge arcana": 6,
                                                                      "knowledge religion": 6})  # fmt: skip
    mt1 = {"cls": "Cleric/Wizard/Mystic Theurge", "levels": {"cleric": 3, "wizard": 3, "mystic theurge": 1}}
    entered("Mira", mt1, "the theurges' circle")
    run("set_build", character="Mira", advances={"mystic theurge": ["wizard", "cleric"]})
    run("update_character", ref="Mira", patch={"cls": "Cleric/Wizard/Mystic Theurge",
        "levels": {"cleric": 3, "wizard": 3, "mystic theurge": 2}}, reason="mystic theurge 2")  # fmt: skip
    run("memorize_spells", character="Mira", spells=["Bless", "Bless", "Magic Weapon", "Magic Missile", "Shield",
        "Hold Person", "Aid", "Web", "Prayer", "Magic Vestment", "Fireball"])  # fmt: skip
    run("cast_spell", character="Mira", spell_name="Prayer")
    run("cast_spell", character="Mira", spell_name="Fireball")

    # 6. The eldritch knight's 3rd level, and XP: the penalty is the base classes' only.
    ek3 = {"cls": "Wizard/Fighter/Eldritch Knight", "levels": {"wizard": 5, "fighter": 1, "eldritch knight": 3}}
    run("update_character", ref="Ansel", patch=ek3, reason="eldritch knight 3")
    run("award_xp", character="Ansel", amount=9000)

    # 7. A rogue 10/assassin 10 at the top: made so, warned until its build meets the assassin's requirements; a
    # bugbear can't flank it; its 10d6 sneak attack; 20th level's XP.
    run("create_character", name="Shade", sheet={"cls": "Rogue/Assassin", "levels": {"rogue": 10, "assassin": 10},
                                                  "race": "Human", "hp_max": 110, "alignment": "Neutral Evil",
                                                  "ability_scores": SHADE})  # fmt: skip
    run("set_build", character="Shade", skills={"disguise": 13, "hide": 23, "move silently": 23},
        choices={"requirements": {"assassin": [kill]}}, weapon="short sword")  # fmt: skip
    run("setup_combat", enemies=[{"name": "bugbear", "count": 1, "hp": 100}], surprise=False)
    run("combat_round", actions=[{"attacker": "Bugbear", "target": "Shade", "condition": "flanking"}])
    run("combat_round", actions=[{"attacker": "Shade", "target": "Bugbear", "condition": "flanking"}])
    run("end_combat")
    run("update_character", ref="Shade", patch={"xp": 2600000}, reason="20th level's XP")
    run("award_xp", character="Shade", amount=50000)
    run("get_character", ref="Shade")
    return said


@pytest.fixture
def seeded_call(srd35_tripwire, srd35_storage, srd35_campaign):
    """`call(tool, **args)` on the srd35 campaign, each call in a beat of its own with the next seed."""
    from delve.dice import SeededRng
    from delve.dm.tools import ToolHost
    from tests.fixtures.rulesets import srd35_catalogs

    seeds = itertools.count(SEED)
    host = ToolHost(srd35_storage, lambda: SeededRng(next(seeds)), catalogs=srd35_catalogs())
    beats = itertools.count(1)

    def run(tool, /, **args):
        return host.call(srd35_campaign.id, f"beat-{next(beats)}", tool, args)

    return run


def _normalised(value, storage, campaign_id):
    """`value` with ids by name: characters by theirs, the fight as <fight>, roll ids and times as placeholders."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    for c in storage.characters.list(campaign_id):
        text = text.replace(c.id, c.name)
    for event in storage.events.list(campaign_id, types=["combat_started"]):
        text = text.replace(event.data["combat_id"], "<fight>")
    text = re.sub(r'"(roll|note|hr)_[0-9a-f]{12}"', r'"<\1 id>"', text)
    text = re.sub(r'"\d{4}-\d\d-\d\dT[^"]+"', '"<time>"', text)
    return json.loads(text)


def test_the_prestige_session_matches_its_golden(seeded_call, srd35_storage, srd35_campaign):
    said = play(seeded_call)
    rolls = [
        {"beat": r.key.beat, "purpose": r.key.purpose, "actor": r.key.actor, "target": r.key.target,
         "round": r.key.combat_round, "notation": r.notation, "faces": list(r.faces), "total": r.total}
        for r in srd35_storage.rolls.list(srd35_campaign.id)
    ]  # fmt: skip
    session = {"answers": [{"tool": t, "args": a, "answer": o} for t, a, o in said], "rolls": rolls}
    answers = _normalised(session, srd35_storage, srd35_campaign.id)
    if not GOLDEN.exists():
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(answers, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
        pytest.fail("golden written: check it by hand")
    assert answers == json.loads(GOLDEN.read_text())
