"""A scripted SRD 3.5 session against the SRD's monsters (DEL-389 part 3), through the tool host with seeded dice and
the tripwire on: the live party at 6th level, Bram with a +1 longsword and his shield, fights two gargoyles (DR
10/magic: the longsword overcomes it, Pip's short sword and Dorna's warhammer don't), a troll that regenerates until
Elowen's Fireball, a babau (Elowen's Magic Missile against its SR 14, the check logged; DR 10/cold iron or good), a
Large fire elemental (its slam's 2d6 fire, its DR 5/—, its burn), and a young red dragon (its full attack of six, its
XP); the troll's hoard is rolled and awarded at EL 6, standard, with a ring from `items.json`; Bram's ring of protection
+1 and cloak of resistance +1 raise his AC and saves; and a great wyrm black dragon is worth a CR 22 award.

The party is `engine/test_high_levels.build` (Phase 2's builds, seeds 1 on), not recorded: its sheets read as
`fixtures/live_party_level6.json`'s, by an assert. The DM reads the four monsters' entries first; the gargoyle and the
troll left standing flee (the DM's call); the young red dragon and the great wyrm are slain by the DM's ruling
(`apply_damage`), for their XP; the Fireball's and burn's saves and the Fireball's damage are the DM's tool calls, as
the engine leaves them; the troll's regeneration is the engine's (DEL-421) (the troll's rend, the babau's protective
slime, catching fire and the dragon's breath stay the DM's too). Ten days' rest between the fights heals the party
(level × days).

The session found two engine bugs, fixed in their own commits before it: a monster's full attack swung its held form
only (the gargoyle's two claws, never its bite and gore; the dragon's bite alone), and a monster's sneak attack was
dropped (the babau's +2d6). Its review found a third: a two-handed weapon kept a shield's AC (Bram's first build, a +1
greatsword beside his heavy steel shield); the rule is fixed in its own commit, and Bram takes a +1 longsword, his
Weapon Focus and Specialization weapon, keeping the fixture's AC 19 (the golden rewritten once, every number below
worked again). Nothing was dropped as impossible. Energy resistance and immunity against the elemental's fire are no
part of the session (no party member can carry fire resistance in the engine, and the monsters don't fight each other):
`engine/test_monster_defences.py::test_energy_damage_with_resistance_and_immunity` plays the Large fire elemental's slam
at a succubus (fire resistance 10) and a bearded devil (immune). One difference from the brief: it asks for the young
red dragon's XP "at CR 10", but the SRD's young red dragon is CR 7 ("Challenge Ratings: … young 7; juvenile 10"), and
the session awards CR 7's.

The golden was checked by hand against the SRD's RTF stat blocks (`MonstersD-De`, `MonstersDr-Dw`, `MonstersE-F`,
`MonstersG`, `MonstersT-Z`), the pack's data and the logged faces (`rolls`; `answers[i]` is the i-th call):

- **Bram with a +1 longsword** (`answers[1]`): human fighter 6, Str 17: BAB 6 + 3 + Weapon Focus 1 + 1 = +11/+6, 1d8 + 3
  + Weapon Specialization 2 + 1 = 1d8+6, 19–20/×2; banded mail 6 + heavy steel shield 2 + Dex 1 = AC 19, touch 11,
  flat-footed 18; Fort 9, Ref 3, Will 5 (the fixture's); no warning (one hand on the sword). Pip's short sword +8, Small
  1d4+1, sneak 3d6; Dorna's warhammer +7, 1d8+2, and 40 + Toughness 3 = 43 hp, her maximum in every fight. Bram's Jump
  −2 (`answers[1]`, `[31]`): banded mail's speed 20 takes 6 ("a –6 penalty for every 10 feet of speed less than 30
  feet").
- **The entries** (`answers[2..5]`): the gargoyle's DR 10/magic; the troll's regeneration 5 (fire or acid); the babau's
  DR 10/cold iron or good (`bypass_any`), SR 14, resistance to acid, cold and fire 10, immunity to electricity and
  poison; the young red dragon's immunity to fire, sleep and paralysis — the RTFs' lines.
- **The gargoyles** (`answers[6..9]`): SRD, AC 16, touch 12, flat-footed 14; 2 claws +6 (1d4+2) and bite +4 (1d6+1) and
  gore +4 (1d6+1), four attacks a round. 4d8+19: [4, 3, 4, 4] = 34 and [5, 7, 8, 6] = 45 hp. Initiative: Bram 19 + 5 =
  24, Elowen 13 + 7 = 20, Pip 9 + 7 = 16, Gargoyle 1 13 + 2 = 15, Dorna 12, Gargoyle 2 1 + 2 = 3. Round 1: Bram at
  Gargoyle 1, flat-footed (14): 9 + 11 = 20 hits, [1] + 6 = 7, the DR overcome (magic), at 27; 17 + 6 = 23 hits, [8] + 6
  = 14, at 13. Pip at Gargoyle 2, flat-footed: 12 + 8 = 20 hits, [4] + 1 = 5 and sneak [1, 2, 2] = 5, 10 less DR 10 = 0.
  Gargoyle 1 at Bram (19): claw 14 + 6 = 20 hits, [2] + 2 = 4, 55 → 51; claw 12 + 6 misses; bite 15 + 4 = 19 hits, [6] +
  1 = 7, 44; gore 1 misses. Dorna at Gargoyle 2, flat-footed: 2 + 7 misses. Gargoyle 2 at Pip (17): claws 18 + 6 hits,
  [4] + 2 = 6, 25 → 19; 15 + 6 hits, [1] + 2 = 3, 16; bite 8 + 4 and gore 3 + 4 miss. Round 2: Bram 20, confirmed 7 + 11
  = 18 ≥ 16, ×2: [8] + 6 + [8] + 6 = 28, Gargoyle 1 dead; his Great Cleave at Gargoyle 2 (`targets`), at the same
  +11: 17 + 11 = 28 hits, [6] + 6 = 12, 45 → 33; his second attack at it: 15 + 6 = 21 hits, [1] + 6 = 7, 26. Pip 2 + 8
  misses. Dorna 6 + 7 misses. Gargoyle 2 at Pip: 12 + 6 hits, [2] + 2 = 4, 16 → 12, 9 + 6, 2 + 4 and 6 + 4 miss. One
  gargoyle defeated, CR 4: 1,200.
- **The troll** (`answers[11..18]`): SRD, AC 16, touch 11, flat-footed 14; 2 claws +9 (1d6+6) and bite +4 (1d6+3);
  6d8+36: [1, 8, 5, 7, 4, 2] = 63. Initiative: Dorna 20, Pip 11 + 7 = 18, Bram 12 + 5 = 17, the troll 9 + 2 = 11, Elowen
  3 + 7 = 10. Round 1: Pip, flat-footed: 2 misses. Bram, flat-footed (14): 12 + 11 = 23 hits, [1] + 6 = 7, nonlethal
  (regeneration 5: fire or acid deals lethal), so its hp stays 63 and its nonlethal is 7; 8 + 6 = 14 hits, [6] + 6 = 12
  nonlethal, 19. The troll at Bram (19): 16 + 9 hits, [3] + 6 = 9, 55 → 46; 14 + 9 hits, [6] + 6 = 12, 34 (both claws:
  its rend 2d6+9 is the DM's); bite 13 + 4 misses. At the round's end the engine's regeneration 5: nonlethal 19 → 14.
  The DM reads the fight (`answers[13]`): hp 63, nonlethal 14, active. Round 2: Bram 8 + 11 = 19 hits, [2] + 6 = 8
  nonlethal, 22; 15 + 6 = 21, [1] + 6 = 7, 29. The troll: 5 + 9 misses; 10 + 9 = 19 hits, [6] + 6 = 12, 22; bite 1
  misses. Regeneration: 29 → 24. Elowen's Fireball, DC 10 + 3 + 4 + Spell Focus 1 = 18, two 3rd-level copies left. Its
  Reflex save: 10 + 4 = 14 fails; 6d6 [4, 2, 5, 2, 3, 3] = 19 fire, lethal: 63 → 44 (24 nonlethal, less than its hp: not
  staggered). It flees, standing.
- **The troll's hoard, EL 6, standard** (`answers[19]`), the rules file's Table: Treasure, 6th: coins d% 61 (38–95, 1d10
  × 100 gp): [2], 200 gp. Goods d% 81 (57–92, 1d4 gems): [4]. Table: Gems: 69 (51–70, 4d4 × 10) [1, 2, 3, 2] = 80 gp,
  example 1d10 [3], chrysoberyl; 11 (01–25, 4d4) [4, 4, 2, 1] = 11 gp, [2] azurite; 52: [1, 1, 2, 1] = 50 gp, [10]
  tourmaline; 6: [3, 2, 2, 1] = 8 gp, [1] banded, eye, or moss agate. Items d% 99 (60–99, 1d3 minor): [2]. Random Magic
  Item Generation, minor: 51 (47–81) a scroll, 28 arcane, 1d3 [2] spells: level 96 (3rd), spell 18, explosive runes;
  level 71 (2nd), spell 55 (53–55), knock. 46 (45–46) a ring: 66 (61–70) Ring of Counterspells, `items.json`'s
  `counterspells`. Coins to the party, the rest to the loot pile.
- **The babau** (`answers[21..24]`): SRD, AC 19, flat-footed 18; 2 claws +12 (1d6+5) and bite +7 (1d6+2), sneak attack
  +2d6; 7d8+35: [2, 5, 7, 4, 8, 5, 5] = 71. Initiative: Elowen 16 + 7 = 23, Bram 18 + 5 = 23 (tied: the higher modifier
  first), the babau 15 + 1 = 16, Pip 6 + 7 = 13, Dorna 4. Elowen's check against SR 14: d20 [3] + caster level 6 = 9,
  not overcome: Magic Missile fails on it (cast, DC 10 + 1 + 4 + 1 = 16, three 1st-level spells left). Bram, the babau
  flat-footed (18): 15 + 11 hits, [2] + 6 = 8, all of it to DR 10 (−8), at 71; 20, confirmed 19 + 6 = 25, ×2: [4] + 6 +
  [7] + 6 = 23 less 10 = 13, at 58 (+1 is magic, not cold iron or good). The babau at Dorna, flat-footed (16: Dex +0,
  denied it all the same): 16 + 12 hits, [3] + 5 and sneak [6, 6] = 20, 43 → 23; 11 + 12 hits, [4] + 5 and [5, 3] = 17,
  6; bite 6 + 7 = 13 misses.
- **The Large fire elemental** (`answers[26..29]`): SRD, AC 18, flat-footed 13, 2 slams +10 (2d6+2 plus 2d6 fire), DR
  5/—, immune to fire and criticals; 8d8+24: [6, 1, 5, 3, 4, 5, 2, 4] = 54. Initiative: Elowen 20 + 7 = 27, the
  elemental 17 + 9 = 26, Bram 17 + 5 = 22. At Bram, flat-footed (18): 3 + 10 misses; 20 hits, confirm 6 + 10 = 16 fails,
  [3, 6] + 2 = 11 and fire [5, 5] = 10, 21: 55 → 34. Bram: 12 + 11 = 23 hits, [5] + 6 = 11 less DR 5 = 6, at 48; 20, a
  threat (immune to criticals), [3] + 6 = 9 less 5 = 4, at 44. Burn, a Large one's DC 17: Reflex 9 + 3 = 12 fails (he
  catches fire; the DM's).
- **The ring and the cloak** (`answers[31]`): ring of protection +1 (deflection) and cloak of resistance +1 (resistance
  on saves), different types: AC 19 + 1 = 20, touch 12, flat-footed 19; Fort 10, Ref 4, Will 6. No other deflection or
  resistance bonus is on him.
- **The young red dragon** (`answers[32..39]`): the SRD's Red Dragons by Age, young: Large, 13d12+39, AC 21 (−1 size,
  +12 natural), flat-footed 21; bite +19 (2d6+7), 2 claws +14 (1d8+3), 2 wings +14 (1d6+3), tail slap +14 (1d8+10): the
  dragons' secondary attacks at −5 and ½ (1½ for the tail) × Str +7; six attacks. 13d12+39: 73 + 39 = 112. Initiative:
  Bram 17 + 5 = 22, Elowen 9 + 7 = 16, the dragon 16, Pip 1 + 7 = 8, Dorna 1. Bram, the dragon flat-footed (21): 7 + 11
  and 4 + 6 miss. The dragon at Bram (20): bite 10 + 19 hits, [6, 6] + 7 = 19, 55 → 36; claw 9 + 14 hits, [7] + 3 = 10,
  26; claw 2 + 14 misses; wing 5 + 14 = 19 misses (the ring's +1); wing 13 + 14 hits, [6] + 3 = 9, 17; tail slap 7 + 14
  = 21 hits, [8] + 10 = 18, −1, dying; his d% to stabilise (10 or less) is 49, so he bleeds to −2. Slain: CR 7, 3,600
  XP (Table 6-14), shared by the four, 900 each. Each had 15,000, below 6th level's 16,000 (Phase 2's build): raised
  first, 16,900.
- **The great wyrm black dragon** (`answers[41..43]`): CR 22 (the SRD's "great wyrm 22"), 37d12+296 = 224 + 296 = 520
  hp, DR 20/magic, SR 28; slain, 2 × CR 20's 310,000 = 620,000 (SOURCES.md: "Beyond CR 20, twice the award of CR − 2").
  Initiative: Elowen and Pip tied on 7 + 7 = 14 with the same modifier, so they roll again: Elowen [13], Pip [9].

Every answer is compared with `golden/scripted_session_monsters.json`. The test writes the golden when it is missing and
fails; the first one was checked by hand against the working above, and rewritten once in its review (Bram's longsword
and shield), checked again, and once more for DEL-420: initiative ties now go to the higher modifier, then to a
roll-off, as the SRD says. Only the babau fight's order and the great wyrm's two roll-off faces changed; no outcome
did. It was rewritten once more, by the owner's leave, for DEL-456: Dorna's Toughness (+3, 40 → 43 throughout) and
Bram's Jump; no outcome moved. And once, by the owner's leave, for DEL-431: Bram's and the babau's `cleave` in their
numbers, and Bram's Great Cleave in round 2 of the gargoyles (worked above, its swing noted "great cleave: the extra
attack"), which moves that round's later faces on by one; Gargoyle 2 ends at 26, not 33, and flees as before. And once,
by the owner's leave, for DEL-442: Bram's roll to stabilise at the end of the black dragon's round is new (d% 49, not
stable: he bleeds to −2 as before, and no later face moved), the round's end says it ("bleeds 1 HP (hp now −2; d% 49,
not stable)"), and the tail slap that drops him notes the roll ("Dying: each round 10% to become stable …"). And once,
by the owner's leave, for DEL-421: the troll's sword wounds are nonlethal damage, tracked apart from its hit points,
and its regeneration is the engine's at each round's end, so the DM's heal (`apply_heal` 5, `answers[13]`) is now a
`combat_status`. Bram's four hits on it (7, 12, 8, 7) have `damage` 0, `nonlethal` 7, 12, 8, 7 and `hp_after` 63 (were
56, 44, 41, 34); the round's status has its hp 63 (were 44, 34) and nonlethal 14 and 24; the rounds' `defences` notes
say the regeneration done ("nonlethal 19 → 14", "nonlethal 29 → 24"), not the DM's heal to come; the Fireball's 19 takes
it 63 → 44 (was 34 → 15), and `end_combat` has it standing at 44 (was 15). No roll moved, nor any other answer. And
once, by the owner's leave, in the final review of the SRD 3.5 combat fixes: a cleave's rolls are under purposes of
their own, so Bram's Great Cleave at Gargoyle 2 (round 2) rolls `attack#1:cleave` (17) and `damage#1:cleave` (12), were
`attack#1` and `damage#1`; no face, total or answer moved. It is never regenerated."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest
from engine.test_high_levels import FIXTURE, build
from srd35_phase3 import without_phase3

GOLDEN = Path(__file__).resolve().parent / "golden" / "scripted_session_monsters.json"
SEED = 1
"""The first call's seed; each call after takes the next."""
PARTY = ("Bram", "Dorna", "Elowen", "Pip")


def play(call) -> list[tuple[str, dict, dict]]:
    """The session: each call as (tool, args, answer). `call(tool, **args)` runs one tool call in a beat of its own."""
    said: list[tuple[str, dict, dict]] = []

    def run(tool, **args):
        out = call(tool, **args)
        assert "error" not in out, (tool, out)
        said.append((tool, args, out))
        return out

    # 1. The live party at 6th level, built as Phase 2's engine built it (not recorded): its sheets read as the
    # fixture's. Bram's longsword is a +1 one; the DM reads the entries.
    party = build(call)
    fixture = json.loads(FIXTURE.read_text())
    assert without_phase3(party) == without_phase3(fixture)
    run("memorize_spells", character="Elowen", spells=["Detect Magic", "Light", "Magic Missile", "Magic Missile",
        "Shield", "Sleep", "Web", "Glitterdust", "Invisibility", "Mirror Image", "Fireball", "Lightning Bolt",
        "Haste"])  # fmt: skip
    run("set_build", character="Bram", items=["+1 longsword"])
    for name in ("gargoyle", "troll", "babau", "young red dragon"):
        run("monster_lookup", name=name)

    # 2. Two gargoyles, DR 10/magic: the +1 longsword overcomes it, Pip's short sword and Dorna's warhammer don't.
    run("setup_combat", enemies=[{"name": "gargoyle", "count": 2}], surprise=False)
    run("combat_round", actions=[
        {"attacker": "Bram", "target": "Gargoyle 1"},
        {"attacker": "Pip", "target": "Gargoyle 2"},
        {"attacker": "Dorna", "target": "Gargoyle 2"},
        {"attacker": "Gargoyle 1", "target": "Bram"},
        {"attacker": "Gargoyle 2", "target": "Pip"},
    ])  # fmt: skip
    run("combat_round", actions=[
        {"attacker": "Bram", "target": "Gargoyle 1", "targets": ["Gargoyle 2"]},
        {"attacker": "Pip", "target": "Gargoyle 2"},
        {"attacker": "Dorna", "target": "Gargoyle 2"},
        {"attacker": "Gargoyle 1", "target": "Bram"},
        {"attacker": "Gargoyle 2", "target": "Pip"},
    ])  # fmt: skip
    run("end_combat")
    run("rest", days=10)

    # 3. A troll regenerates until the fireball.
    run("setup_combat", enemies=[{"name": "troll", "count": 1}], surprise=False)
    run("combat_round", actions=[
        {"attacker": "Bram", "target": "Troll"},
        {"attacker": "Pip", "target": "Troll"},
        {"attacker": "Troll", "target": "Bram"},
    ])  # fmt: skip
    run("combat_status")  # the DM reads the troll's nonlethal damage: the engine regenerates it (DEL-421)
    run("combat_round", actions=[
        {"caster": "Elowen", "spell": "Fireball", "target": "Troll"},
        {"attacker": "Bram", "target": "Troll"},
        {"attacker": "Troll", "target": "Bram"},
    ])  # fmt: skip
    run("saving_throw", character="Troll", save_type="ref", dc=18)
    fire = run("roll", notation="6d6", purpose="Elowen's fireball on the troll")["total"]
    run("apply_damage", character="Troll", amount=fire)
    run("end_combat")
    # The troll's cave: EL 6, standard.
    run("award_treasure", treasure_types="EL 6, standard", source="the troll's cave")
    run("rest", days=10)

    # 4. A babau: SR 14, DR 10/cold iron or good.
    run("setup_combat", enemies=[{"name": "babau", "count": 1}], surprise=False)
    run("spell_resistance", caster="Elowen", target="Babau", spell="Magic Missile")
    run("combat_round", actions=[
        {"caster": "Elowen", "spell": "Magic Missile", "target": "Babau"},
        {"attacker": "Bram", "target": "Babau"},
        {"attacker": "Babau", "target": "Dorna"},
    ])  # fmt: skip
    run("end_combat")
    run("rest", days=10)

    # 5. A Large fire elemental's slam with its fire; DR 5/— against the +1 longsword.
    run("setup_combat", enemies=[{"name": "large fire elemental", "count": 1}], surprise=False)
    run("combat_round", actions=[
        {"attacker": "Large Fire Elemental", "target": "Bram"},
        {"attacker": "Bram", "target": "Large Fire Elemental"},
    ])  # fmt: skip
    run("saving_throw", character="Bram", save_type="ref", dc=17)  # burn: a Large one's DC 17, or catch fire
    run("end_combat")
    run("rest", days=10)

    # 6. Bram's ring of protection +1 and cloak of resistance +1.
    run("set_build", character="Bram", items=["+1 longsword", "ring of protection +1", "cloak of resistance +1"])

    # 7. A young red dragon's full attack, and its XP.
    run("setup_combat", enemies=[{"name": "young red dragon", "count": 1}], surprise=False)
    run("combat_round", actions=[
        {"attacker": "Young Red Dragon", "target": "Bram"},
        {"attacker": "Bram", "target": "Young Red Dragon"},
    ])  # fmt: skip
    run("apply_damage", character="Young Red Dragon", amount=200)
    run("end_combat")
    for name in PARTY:
        run("award_xp", character=name, amount=900)
    run("rest", days=10)

    # 8. A CR 22 award.
    run("setup_combat", enemies=[{"name": "great wyrm black dragon", "count": 1}], surprise=False)
    run("apply_damage", character="Great Wyrm Black Dragon", amount=600)
    run("end_combat")
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


def test_the_monsters_session_matches_its_golden(seeded_call, srd35_storage, srd35_campaign):
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
