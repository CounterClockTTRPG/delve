"""A scripted SRD 3.5 session at high level (DEL-389 part 2), through the tool host with seeded dice and the tripwire
on: the live party at 6th level fights two ogres (the fighter swings twice, the wizard casts Fireball, the rogue's
sneak attack is 3d6), takes the XP for 7th level and levels, rests; the wizard prepares 4th-level spells and the cleric
converts a prepared spell into Cure Serious Wounds. Then a sorcerer 6 casts from its pool until its 3rd-level spells
run dry, a cleric 3/wizard 3 memorizes into both pools, a barbarian 11 rages (greater rage) and a monk 11 flurries
(greater flurry) at a hill giant, a fighter 20 takes XP and stays 20th, and everyone rests: pools and uses come back.

The party is `engine/test_high_levels.build` (Phase 2's builds, seeds 1 on), not recorded: its sheets read as
`fixtures/live_party_level6.json`'s, by an assert (the fixture's numbers were checked there). Dorna is given her
alignment, Lawful Good (a Good-domain cleric; the build left it empty), so she converts into cure spells. The ogres
are left standing when the fight ends (they flee: the DM's call), and the 9,000 XP each is the DM's award.

The session found three engine bugs, fixed in their own commits before it: Weapon Specialization's +2 damage was
dropped (Bram), Spell Focus's +1 DC was dropped (Elowen's Fireball), and a monster's "+16/+11" swung once (the hill
giant). Nothing was dropped as impossible.

The golden was checked by hand against the SRD and the logged faces (`rolls`; `answers[i]` is the i-th call):

- **The live party at 6th** (`answers[3]`): Bram, human fighter 6, Str 17: banded mail 6 + heavy steel shield 2 + Dex
  1 (max Dex 1) = AC 19, touch 11, flat-footed 18; longsword BAB 6 + 3 + Weapon Focus 1 = +10/+5 (two attacks, count
  2, iterative), 1d8 + 3 + Weapon Specialization 2 = 1d8+5, 19–20; Fort 5 + 2 + Great Fortitude 2 = 9, Ref 2 + 1 = 3,
  Will 2 + 1 + Iron Will 2 = 5; initiative 1 + 4 = 5. Dorna, dwarf cleric 6, Str 14, Wis 16: scale mail 4 + shield 2 =
  AC 16; warhammer 4 + 2 + the War domain's Weapon Focus 1 = +7, 1d8+2 ×3; Fort 5 + 2 = 7, Ref 2, Will 5 + 3 = 8;
  40 + Toughness 3 = 43 hp. Bram's Jump −2: banded mail's speed 20 takes 6 ("a –6 penalty for every 10 feet of speed
  less than 30 feet", `answers[8]`); Elowen's Spellcraft 13 + 2 = 15, Knowledge (arcana) 5+ ranks' synergy, and a note
  for Use Magic Device on scrolls (`answers[12]`); Pip's note for Survival to track (Search 5+ ranks, `answers[14]`).
  Elowen, elf wizard 6, Dex 16, Int 18: AC 13, flat-footed 10; dagger 3 − 1 = +2, 1d4−1; ranged touch 3 + 3 = +6;
  Fort 2, Ref 2 + 3 + Lightning Reflexes 2 = 7, Will 5 + 1 = 6; initiative 3 + 4 = 7. Pip, halfling rogue 6, Dex 17:
  leather 2 + Dex 3 + size 1 + Dodge 1 = AC 17, touch 15, flat-footed 17 (uncanny dodge keeps his Dex); short sword
  (Weapon Finesse) 4 + 3 + 1 = +8, Small 1d4 + Str 1, 19–20; Fort 2 + 1 + 1 (halfling) = 4, Ref 5 + 3 + 1 = 9, Will 2
  + 0 + 1 = 3; sneak attack 3d6. BAB 4, 4 and 3 (cleric, rogue, wizard): one attack each.
- **Spells at 6th** (`answers[1..2]`): Elowen's slots 4 / 3 + 1 / 3 + 1 / 2 + 1 (Int 18): two cantrips, 4 + 4 + 3;
  Dorna's 5 / 3 + 1 + 1 / 3 + 1 + 1 / 2 + 1 + 1 (Wis 16 and the domain slot): 4 + 4 + 4, Magic Weapon, Spiritual
  Weapon and Magic Vestment the War domain's.
- **The ogres** (`answers[3]`): the SRD ogre, AC 16 (touch 8, flat-footed 16: Dex −1), greatclub +8 2d8+7, javelin +1
  1d8+5, at the module's 60 hp. Initiative: Pip 18 + 7 = 25, Bram 18 + 5 = 23, Ogre 1 18 − 1 = 17, Elowen 5 + 7 = 12,
  Dorna 11, Ogre 2 10 − 1 = 9.
- **Round 1** (`answers[4]`): Pip at Ogre 2, flat-footed (it hasn't acted; AC 16 either way): 3 + 8 = 11 misses. Bram
  at Ogre 1, flat-footed: 12 + 10 = 22 hits, 7 + 5 = 12, at 48; his second, at +5: 4 + 5 = 9 misses. Ogre 1 at Bram:
  11 + 8 = 19 hits AC 19, 1 + 1 + 7 = 9, Bram 55 → 46. Elowen's Fireball: DC 10 + 3 + Int 4 + Spell Focus
  (evocation) 1 = 18, Reflex half; two 3rd-level copies left. Dorna at Ogre 1 (it has acted): 9 + 7 = 16 hits, 3 + 2
  = 5, at 43. Ogre 2 at Pip: 15 + 8 = 23 hits, 1 + 4 + 7 = 12, Pip 25 → 13.
- **Round 2** (`answers[5]`): Pip flanks Ogre 1 with Bram: 16 + 8 + 2 = 26 hits, 3 + 1 = 4 and sneak attack 3d6 3 + 6
  + 2 = 11, 15, at 28. Bram, flanking: 16 + 10 + 2 = 28 hits, 6 + 5 = 11, at 17; 3 + 5 + 2 = 10 misses. Ogre 1 at
  Bram: 18 + 8 hits, 6 + 4 + 7 = 17, 46 → 29. Ogre 2 at Dorna: 18 + 8 hits, 2 + 3 + 7 = 12, 43 → 31. The fight ends
  (`answers[6]`).
- **7th level** (`answers[7..14]`): Unearthed Arcana's Table 6-13 (`data/xp.json`): 6th at 16,000, 7th at 24,000.
  Phase 2's build left each at 15,000, below 6th's floor: the award first raises it to 16,000 (`xp_note`), so 16,000
  + 9,000 = 25,000 makes each ready (`xp_next` is the level after the sheet's, still 6th: 24,000). Bram d10 [10] + 2 = 12, 55 → 67 (29
  → 41 hp), BAB 7 (+11/+6), saves unchanged (Fort 5 + 2 + 2 = 9); 3 skill points, no feat (3rd, 6th, 9th) and no bonus
  feat (even levels). Dorna d8 [2] + 2 = 4, 43 → 47, BAB 5, Fort 5 + 2 = 7, Will 5 + 3 = 8; slots 6 / 4 + 1 + 1 / 3 +
  1 + 1 / 2 + 1 + 1 / 1 + 1 (no Wis 16 bonus at 4th) = 6 / 6 / 5 / 4 / 2, the 4th-level DC 10 + 4 + 3 = 17; 2 skill
  points. Elowen d4 [1], 19 → 20, BAB 3, Ref 2 + 3 + 2 = 7, Will 5 + 1 = 6; slots 4 / 4 + 1 / 3 + 1 / 2 + 1 / 1 + 1 =
  4 / 5 / 4 / 3 / 2, the 4th-level DC 10 + 4 + 4 = 18; 6 skill points (2 + Int 4). Pip d6 [2] + 1 = 3, 25 → 28, BAB
  5, Fort 2 + 1 + 1 = 4, Ref 5 + 3 + 1 = 9, Will 3; sneak attack 4d6; 10 skill points (8 + 2).
- **The rest** (`answers[15]`): a day heals level × 1: Bram 41 → 48, Dorna 35 → 42, Pip 16 → 23; Elowen at her
  maximum. The spells are uncast again.
- **4th-level spells** (`answers[16..19]`): Elowen fills her two 4th-level slots and casts Ice Storm at DC 10 + 4 + 4
  + 1 (evocation) = 19 (it has no save; the DC is the class's own), one 4th-level copy left. Dorna gives up Dispel
  Magic (3rd) for Cure Serious Wounds (3rd, conjuration), DC 10 + 3 + 3 = 16, three 3rd-level copies left. Magic
  Vestment, with Prayer, Searing Light and the spent Dispel Magic in the three ordinary 3rd-level slots, holds the
  domain slot: refused.
- **Sela, human sorcerer 6, Cha 13** (`answers[20..26]`): Table: The Sorcerer, 6th: 6 / 6 / 5 / 3 a day, Cha 13 a
  bonus 1st: 6 / 7 / 5 / 3; Spells Known 7 / 4 / 2 / 1, her 14 spells; DC 10 + level + 1. AC 12, BAB 3, Fort 2 + 1 =
  3, Ref 2 + 2 = 4, Will 5. Fireball at DC 14 three times, 2, 1, 0 left; the fourth refused ("cast all 3 … come back
  with a rest of a day"); Magic Missile from the 1st-level spells, DC 12, 6 left.
- **Ansel, human cleric 3/wizard 3, Wis 14, Int 16** (`answers[27..31]`): BAB 2 + 1 = 3; Fort 3 + 1 + 1 = 5, Ref 1 +
  1 = 2, Will 3 + 3 + 2 = 8; ECL 6; turning 3 + Cha 0 = 3 a day. Cleric 3: 4 / 2 + 1 + 1 / 1 + 1 + 1 = 4 / 4 / 3, DC
  10 + level + 2; wizard 3: 4 / 2 + 1 / 1 + 1 = 4 / 3 / 2, DC 10 + level + 3; the sheet's `dc` the cleric's (first).
  Seven 1st-level spells fill four cleric and three wizard slots, five 2nd-level ones three and two. Hold Person (2nd
  for the cleric) is cast as cleric at DC 14; Web as wizard at DC 15.
- **Krug, human barbarian 11, Str 18, Con 14** (`answers[32..33]`): BAB 11; chain shirt: AC 10 + 4 + 2 = 16, touch
  12, flat-footed 16 (uncanny dodge), check penalty −2, max Dex 4; speed 30 + 10 = 40; Fort 7 + 2 = 9, Ref 3 + 2 = 5,
  Will 3; DR 2/— (10th), trap sense +3 (9th), improved uncanny dodge; rage 3 a day (8th; 4 from 12th). Greataxe 11 + 4
  = +15/+10/+5 (three attacks), 1d12 + 1.5 × 4 = 1d12+6, ×3.
- **Mei, human monk 11, Str 14, Dex 15, Wis 15** (`answers[34]`): BAB 8; AC 10 + 2 + 2 + monk 2 (10th) = 16, touch
  16, flat-footed 14; speed 30 + 30 = 60; Fort 7 + 1 = 8, Ref 7 + 2 = 9, Will 7 + 2 = 9; unarmed strike 1d10 + 2
  (8th–11th, Medium), ki strike magic and lawful (10th), slow fall 50 ft, diamond body, greater flurry.
- **The hill giant** (`answers[35]`): the SRD hill giant, AC 20 (touch 8, flat-footed 20), greatclub +16/+11 (two
  attacks, iterative) 2d8+10, at the module's 200 hp. Its group's `attacks_per_round` is 2, as its combatant swings
  (part 3 Task 4: core's group builder said 1.0, read from a classic row's number of attacks; the one change made to
  this golden, by hand). Initiative: Elowen 18 + 7 = 25, Pip 14 + 7 = 21, Krug 18 + 2 =
  20, Mei 13 + 2 = 15, Bram 9 + 5 = 14, Sela 12 + 2 = 14, Dorna 13, Ansel 12, the giant 12 − 1 = 11 (all the party's
  PCs join a fight).
- **Greater rage** (`answers[36]`): +6 Str and Con, +3 morale on Fortitude and Will; 3 + the raging Con's +5 = 8
  rounds; +3 hp a Hit Die, 110 → 143; −2 AC (the effect's `ac` 2, core's classic sign); 2 rages left today. On the
  swing (Str 24, +7): +3 to hit, two-handed 1.5 × 7 = 10, 4 more damage. No other morale bonus is on him. **Greater
  flurry** (`answers[37]`): monk 11, +8/+3 + 2 = +10/+5; flurrying, no penalty from 9th, a second extra attack at
  11th: +10/+10/+10/+5.
- **The round** (`answers[38]`), the giant flat-footed (it acts last): Krug 16 + 18 = 34 hits, 8 + 6 + 4 = 18, at
  182; 3 + 13 = 16 and 5 + 8 = 13 miss AC 20. Mei 13 + 10 = 23 hits, 1 + 2 = 3, at 179; 2 + 10, 7 + 10 and 7 + 5 miss.
  The giant at Krug (AC 16 − 2 = 14): 6 + 16 = 22 hits, 5 + 2 + 10 = 17 less DR 2 = 15, 143 → 128; its second, at
  +11: 2 + 11 = 13 misses. The fight ends with the rage still on (`answers[39]`).
- **Vorn, human fighter 20** (`answers[40..42]`): BAB 20, Fort 12 + 2 = 14, Ref 6 + 2 = 8, Will 6; eleven bonus feats
  (1st, 2nd and every even level). With 20th level's 2,600,000 XP, 50,000 more makes 2,650,000: still 20th, no next
  XP, no hints, and the note that 20th is the top.
- **The rest** (`answers[43]`): it ends Krug's rage (143 hp less 33: 128 → 95) and clears the fatigue it left; a day
  heals level × 1: Krug 95 → 106, Bram 48 → 55, Dorna 42 → 47 (her maximum, 5), Pip 23 → 28 (5). The spells are uncast
  again. **Pools and uses** (`answers[44..46]`): Sela's Fireball, 2 of 3 left again; Krug rages, 2 of 3 left again,
  106 → 139; Dorna's twelve spells all uncast, the converted Dispel Magic too.

Every answer is compared with `golden/scripted_session_high.json`. The test writes the golden when it is missing and
fails; the first one was checked by hand against the working above. It is never regenerated. It was rewritten once, by
the owner's leave, for DEL-456 (Toughness's +3 hp, Jump's speed modifier and the skill synergies), and once for DEL-431:
Bram's Great Cleave and the hill giant's Cleave in their numbers (`cleave`); no swing dropped a foe beside another."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest
from engine.test_high_levels import FIXTURE, build
from srd35_phase3 import without_phase3

GOLDEN = Path(__file__).resolve().parent / "golden" / "scripted_session_high.json"
SEED = 1
"""The first call's seed; each call after takes the next."""

SORCERER = {"str": 8, "dex": 14, "con": 12, "int": 10, "wis": 10, "cha": 13}
MYSTIC = {"str": 10, "dex": 10, "con": 12, "int": 16, "wis": 14, "cha": 10}
BARBARIAN = {"str": 18, "dex": 14, "con": 14, "int": 8, "wis": 10, "cha": 10}
MONK = {"str": 14, "dex": 15, "con": 12, "int": 10, "wis": 15, "cha": 8}
FIGHTER = {"str": 18, "dex": 14, "con": 14, "int": 10, "wis": 10, "cha": 8}
PARTY = ("Bram", "Dorna", "Elowen", "Pip")


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

    # 1. The live party at 6th level, built as Phase 2's engine built it (`test_high_levels.build`, not recorded): its
    # sheets and numbers read as the fixture's.
    party = build(call)
    fixture = json.loads(FIXTURE.read_text())
    assert without_phase3(party) == without_phase3(fixture)
    run("update_character", ref="Dorna", patch={"alignment": "Lawful Good"}, reason="a cleric of the Good domain")
    run("memorize_spells", character="Elowen", spells=["Detect Magic", "Light", "Magic Missile", "Magic Missile",
        "Shield", "Sleep", "Web", "Glitterdust", "Invisibility", "Mirror Image", "Fireball", "Lightning Bolt",
        "Haste"])  # fmt: skip
    run("memorize_spells", character="Dorna", spells=["Bless", "Bless", "Divine Favor", "Magic Weapon", "Hold Person",
        "Aid", "Bull's Strength", "Spiritual Weapon", "Prayer", "Dispel Magic", "Searing Light",
        "Magic Vestment"])  # fmt: skip

    # 2. The fight: two ogres.
    run("setup_combat", enemies=[{"name": "ogre", "count": 2, "hp": 60}], surprise=False)
    run("combat_round", actions=[
        {"attacker": "Bram", "target": "Ogre 1"},
        {"attacker": "Pip", "target": "Ogre 2"},
        {"caster": "Elowen", "spell": "Fireball", "target": "Ogre 2"},
        {"attacker": "Dorna", "target": "Ogre 1"},
        {"attacker": "Ogre 1", "target": "Bram"},
        {"attacker": "Ogre 2", "target": "Pip"},
    ])  # fmt: skip
    # Pip tumbles round Ogre 1 to flank it with Bram.
    run("combat_round", actions=[
        {"attacker": "Pip", "target": "Ogre 1", "condition": "flanking"},
        {"attacker": "Bram", "target": "Ogre 1", "condition": "flanking"},
        {"attacker": "Ogre 1", "target": "Bram"},
        {"attacker": "Ogre 2", "target": "Dorna"},
    ])  # fmt: skip
    run("end_combat")

    # 3. 7th level: 24,000 XP, a level each, a night's rest, and the new day's spells.
    for name in PARTY:
        run("award_xp", character=name, amount=9000)
        run("update_character", ref=name, patch={"level": 7}, reason="level 7")
    run("rest", days=1)
    run("memorize_spells", character="Elowen", spells=["Detect Magic", "Light", "Magic Missile", "Magic Missile",
        "Shield", "Sleep", "Web", "Glitterdust", "Invisibility", "Mirror Image", "Fireball", "Lightning Bolt",
        "Haste", "Ice Storm", "Stoneskin"])  # fmt: skip
    run("cast_spell", character="Elowen", spell_name="Ice Storm")
    # Dorna's spells are uncast again after the rest: she gives up Dispel Magic for Cure Serious Wounds. Magic
    # Vestment holds the 3rd-level domain slot and doesn't convert.
    run("convert_spell", character="Dorna", prepared="Dispel Magic", into="Cure Serious Wounds")
    refused("convert_spell", character="Dorna", prepared="Magic Vestment")

    # 4. A sorcerer 6 casts its one 3rd-level spell known until its day's three are spent.
    run("create_character", name="Sela", sheet={"cls": "Sorcerer", "level": 6, "race": "Human", "hp_max": 27,
                                                 "ability_scores": SORCERER})  # fmt: skip
    run("set_build", character="Sela", known={"sorcerer": ["Light", "Detect Magic", "Ray of Frost", "Mage Hand",
        "Daze", "Flare", "Read Magic", "Magic Missile", "Shield", "Sleep", "Mage Armor", "Scorching Ray",
        "Invisibility", "Fireball"]})  # fmt: skip
    for _ in range(3):
        run("cast_spell", character="Sela", spell_name="Fireball")
    refused("cast_spell", character="Sela", spell_name="Fireball")
    run("cast_spell", character="Sela", spell_name="Magic Missile")

    # 5. A cleric 3/wizard 3 memorizes into both pools.
    run("create_character", name="Ansel", sheet={"cls": "Cleric/Wizard", "levels": {"cleric": 3, "wizard": 3},
                                                  "race": "Human", "hp_max": 24, "ability_scores": MYSTIC,
                                                  "alignment": "Neutral Good"})  # fmt: skip
    run("set_build", character="Ansel", domains=["war", "good"])
    run("memorize_spells", character="Ansel", spells=["Bless", "Bless", "Bless", "Magic Weapon", "Magic Missile",
        "Shield", "Sleep", "Hold Person", "Aid", "Spiritual Weapon", "Web", "Glitterdust"])  # fmt: skip
    run("cast_spell", character="Ansel", spell_name="Hold Person")
    run("cast_spell", character="Ansel", spell_name="Web")

    # 6. A barbarian 11 and a monk 11 against a hill giant.
    run("create_character", name="Krug", sheet={"cls": "Barbarian", "level": 11, "race": "Human", "hp_max": 110,
                                                 "ability_scores": BARBARIAN})  # fmt: skip
    run("set_build", character="Krug", weapon="greataxe", armor="chain shirt")
    run("create_character", name="Mei", sheet={"cls": "Monk", "level": 11, "race": "Human", "hp_max": 70,
                                                "ability_scores": MONK})  # fmt: skip
    run("setup_combat", enemies=[{"name": "hill giant", "count": 1, "hp": 200}], surprise=False)
    run("use_feature", character="Krug", feature="rage")
    run("set_stance", combatant="Mei", flurry=True)
    run("combat_round", actions=[
        {"attacker": "Krug", "target": "Hill Giant"},
        {"attacker": "Mei", "target": "Hill Giant"},
        {"attacker": "Hill Giant", "target": "Krug"},
    ])  # fmt: skip
    run("end_combat")

    # 7. A fighter 20 at the top.
    run("create_character", name="Vorn", sheet={"cls": "Fighter", "level": 20, "race": "Human", "hp_max": 180,
                                                 "ability_scores": FIGHTER})  # fmt: skip
    run("update_character", ref="Vorn", patch={"xp": 2600000}, reason="20th level's XP")
    run("award_xp", character="Vorn", amount=50000)

    # 8. The rest: pools and uses come back.
    run("rest", days=1)
    run("cast_spell", character="Sela", spell_name="Fireball")
    run("use_feature", character="Krug", feature="rage")
    run("get_character", ref="Dorna")
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


def test_the_high_level_session_matches_its_golden(seeded_call, srd35_storage, srd35_campaign):
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
