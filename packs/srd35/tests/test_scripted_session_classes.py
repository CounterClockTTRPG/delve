"""A scripted SRD 3.5 session for the base and NPC classes (DEL-389 part 1), through the tool host with seeded dice and
the tripwire on: a barbarian rages at an orc, a monk flurries, a paladin smites and lays on hands, a druid takes a
wolf, a bard inspires courage, a warrior fights beside them; then a dwarf rogue 3/wizard 1 takes XP at the multiclass
penalty, a gnoll fighter 1 is built at ECL 4, and the party rests, after which the barbarian rages again.

The warrior is a PC sheet of the NPC class (a hireling the party plays): a character of kind npc can't join a fight
with the tools as built (setup_combat brings the party's PCs, add_combatant only monsters by name).

The golden was checked by hand against the SRD and the logged faces (`rolls`; `answers[i]` is the i-th call):

- **Krug, human barbarian 1** (`answers[0..1]`): hp 12 + Con 2 = 14. BAB 1; Fort 2 + 2 = 4, Ref 0 + Dex 2 = 2, Will
  0. Speed 30 + fast movement 10 = 40. Studded leather: AC 10 + 3 + 2 = 15, touch 12, flat-footed 13, check penalty
  −1, max Dex 5. Greataxe +1 + Str 3 = +4, 1d12 + 1.5 × 3 = 1d12+4, ×3 (`answers[13]`). Rage 1 a day.
- **Mei, human monk 1** (`answers[2..3]`): AC 10 + Dex 2 + Wis 2 = 14 (the monk's AC bonus is +0 to 4th), flat-footed
  12. Fort 2 + 1 = 3, Ref 2 + 2 = 4, Will 2 + 2 = 4. Skill points (4 + 0) × 4 + 4 (human) = 20; Tumble 4 + Dex 2 = 6,
  Listen 4 + Wis 2 = 6. Unarmed strike +0 + Str 2 = +2, 1d6+2 (Medium, Improved Unarmed Strike granted).
- **Aldra, human paladin 2** (`answers[4..5]`): Fort 3 + Con 1 + Cha 2 (divine grace) = 6, Ref 0 + 0 + 2 = 2, Will
  0 + 1 + 2 = 3. Chainmail 5 + heavy steel shield 2: AC 17, check penalty −5 − 2 = −7, speed 20, max Dex 2.
  Longsword BAB 2 + Str 2 = +4, 1d8+2, 19–20. Smite 1 a day; lay on hands a pool, not uses (its `per_day` 0, its
  pool in `answers[20]`).
- **Ash, human druid 1** (`answers[6..7]`): Fort 2 + 1 = 3, Ref 0 + 1 = 1, Will 2 + 2 = 4; slots 0-level 3, 1st 1 +
  1 (Wis 15) = 2, DCs 12 and 13. Hide: AC 10 + 3 + 1 = 14, check penalty −3, speed 20.
- **Grey, the wolf** (`answers[8]`): the SRD wolf, 2d8+4 = 13 hp, AC 14 (Dex 2, natural 2), BAB 1, bite +3 1d6+1,
  Fort 5, Ref 5, Will 1, speed 50; at druid 1 the companion block adds nothing (0 bonus HD, natural armour, Str, Dex),
  1 bonus trick, link and share spells.
- **Lyra, human bard 1** (`answers[9..10]`): Fort 0, Ref 2 + 2 = 4, Will 2 − 1 = 1; skill points (6 + 1) × 4 + 4 =
  32, Perform 4 + Cha 2 = 6; bardic music 1 a day, inspire courage +1. Her spells wait for part 2 (no slots): her
  sheet and set_build warn "Delve doesn't cast a sorcerer's or bard's spells yet …".
- **Watch, human warrior 1** (`answers[11..12]`): BAB 1; Fort 2 + 1 = 3, Ref 0, Will 0. Scale mail 4 + heavy wooden
  shield 2: AC 16, check penalty −4 − 2 = −6, speed 20; longsword +1 + 1 = +2, 1d8+1.
- **The orcs** (`answers[13]`): the SRD orc (AC 13, falchion +4 2d4+4 18–20, javelin +1 1d6+3) at the module's 20 hp.
  Each monster combatant (the orcs, and the wolf Grey) carries its row's id as `monster`. Initiative, rolled once: Mei
  20 + 2 = 22, Aldra 17, Orc 2 15, Lyra and Grey 9 + 2 = 11 (tied on the bonus too, so they roll again: Lyra [15],
  Grey [10]), Watch 10, Ash 8 + 1 = 9, Krug 4 + 2 = 6, Orc 1 3.
- **Rage** (`answers[14]`): Con 14 + 4 = 18, +4: 3 + 4 = 7 rounds; +2 hp per Hit Die, 14 → 16; −2 AC as the effect's
  `ac` 2 in core's classic sign. **Flurry** (`answers[15]`): two unarmed strikes at +2 − 2 = +0. **Smite**
  (`answers[16]`): Cha 14's +2 to hit, paladin 2's +2 damage. **Inspire courage** (`answers[17]`): +1 to hit and
  damage on the seven of the party, the bard too, not the orcs; bardic music 1 a day, none left.
- **Round 1** (`answers[18]`): Mei's flurry at Orc 1, flat-footed at 13 (it hasn't acted): 2 + 0 + 1 = 3 misses; 17
  + 1 = 18 hits, 1 + 2 + 1 = 4, Orc 1 at 16. Aldra smites Orc 2 (chaotic evil), flat-footed: 17 + 4 + 2 + 1 = 24
  hits, 4 + 2 + 2 + 1 = 9, Orc 2 at 11. Orc 2 at Watch, flat-footed at 16 (no Dex to lose): 13 + 4 = 17 hits, 3 + 3
  + 4 = 10, Watch at −1, dying; at the round's end he rolls d% to stabilise (10 or less, DEL-442): 42, not stable,
  so he bleeds 1 to −2. Grey at Orc 2, which has acted (AC 13): 19 + 3 + 1 hits, 2 + 1 + 1 = 4, at 7. Ash at Orc 1:
  20, a threat (18–20); confirmation 9 + 0 + 1 = 10 < 13 fails; 1 + 1 = 2, at 14. Krug at Orc 1, flat-footed: 9 + 4
  + rage 2 + 1 = 16 hits, 7 + 4 + rage 3 (two-handed) + 1 = 15, Orc 1 at −1, slain (core slays a monster below 0, as
  in the levels 1–2 session).
- **Will save** (`answers[19]`): a fear effect, the DM's DC 12; Will 0 + rage's +2 morale bonus (rage's note:
  +2 on Fortitude and Will, the Rage effect still on in round 1). The song's +1
  against fear is a morale bonus too, and morale bonuses don't stack (the larger, rage's, counts), so no modifier:
  5 + 2 = 7 fails (needed 10). Inspire courage's note says so (`answers[17]`).
- **Lay on hands** (`answers[20]`): paladin 2 × Cha 2 = a pool of 4; 3 on Watch, −2 → 1, conscious again; 1 left.
- **Round 2** (`answers[21]`): Mei 5 + 1 = 6 and 8 + 1 = 9 miss AC 13. Orc 2 at Krug's AC 15 − rage 2 = 13: a natural
  1 misses. Watch, at 1 hp and conscious, swings his longsword at Orc 2 (7 hp): 20 threatens (19–20); confirmation
  15 + 2 + 1 = 18 ≥ 13, ×2: two damage rolls of 1d8+1 + 1, (3 + 2) + (2 + 2) = 9, Orc 2 at −2, slain. Krug's swing
  at it is not rolled: it is dead.
- **Rage ends** (`answers[22]`): 16 − 2 = 14 hp, fatigued (his combatant made again at −2 Str and Dex; no later
  answer shows its numbers). `answers[23..30]`: the fight ends with both orcs slain, Krug's fatigue with it (the
  rage's, "for the rest of the encounter", DEL-412), and the song's effect is taken off each of the seven.
- **Durin, dwarf rogue 3/wizard 1** (`answers[31..33]`): BAB 2 + 0 = 2; Fort 1 + 0 + Con 2 = 3, Ref 3 + 0 + Dex 2 = 5,
  Will 1 + 2 = 3; sneak attack 2d6, evasion, trap sense +1; wizard slots 0-level 3, 1st 1 + 1 (Int 14) = 2, DCs 12
  and 13; speed 20. ECL 4. The dwarf's favoured class is fighter, and wizard 1 is more than one level below rogue 3:
  −20%. With 4th level's 6,000 XP, 1,000 adds 800: 6,800, still 4th; the 5th needs 10,000.
- **Grak, gnoll fighter 1** (`answers[34..35]`): the gnoll's 2 humanoid Hit Dice (BAB +1, Fort +3) and fighter 1 (BAB
  +1, Fort +2): BAB 2, Fort 5 + Con 1 = 6, Ref 0, Will 0; AC 10 + natural 1 = 11, studded leather 3 → 14; ECL 2 HD +
  1 + level adjustment 1 = 4. hp 11 (the gnoll's 2d8+2) + 10 + 1 = 22. Skill points (2 + 0) × (2 + 3) racial + 2
  fighter = 12, max ranks 3 + 3 = 6: Climb 4 + Str 2 − 1 = 5, Listen 4, Spot 4. Feats at 1st and 3rd character level
  and the fighter's bonus feat: three.
- **The rest** (`answers[36]`): a day; no fatigue to clear, Watch heals 1 (level 1 × 1 day), 1 → 2, the uses
  spent come back. **Rage again** (`answers[37..38]`): 1 a day, the day's one; hp and hp_max 14 → 16.

Every answer is compared with `golden/scripted_session_classes.json`. The test writes the golden when it is missing and
fails; the first one was checked by hand against the working above. It was rewritten once for DEL-420 (initiative
ties go to the higher modifier, then to a roll-off, as the SRD says): Lyra and Grey's order and their two roll-off
faces changed, and no outcome did; once for DEL-456: every derived gains an empty `skill_notes`; and once for DEL-431:
Krug's Cleave in his numbers (`cleave`), and the swing that kills Orc 1 notes the extra attack due, no foe left in its
targets; and once, by the owner's leave, for DEL-442: Watch's roll to stabilise at the end of round 1 is new (d% 42,
not stable: he bleeds to −2 as before, and no later face moved), the round's end says it ("bleeds 1 HP (hp now −2;
d% 42, not stable)"), and the swing that drops him notes the roll ("Dying: each round 10% to become stable …");
and once, by the owner's leave, for DEL-412: Krug's rage ended in the fight, so `end_combat` (`answers[23]`) writes
him back with no `fatigued` (it had `["fatigued"]`), and the rest (`answers[36]`) clears none: its `fatigue_cleared`
(`["Krug"]`) and Krug's healing `fatigue_cleared: true` are gone. It is never regenerated."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parent / "golden" / "scripted_session_classes.json"
SEED = 1
"""The first call's seed; each call after takes the next."""

BARBARIAN = {"str": 16, "dex": 14, "con": 14, "int": 8, "wis": 10, "cha": 10}
MONK = {"str": 14, "dex": 15, "con": 12, "int": 10, "wis": 15, "cha": 8}
PALADIN = {"str": 15, "dex": 10, "con": 12, "int": 8, "wis": 12, "cha": 14}
DRUID = {"str": 10, "dex": 12, "con": 12, "int": 10, "wis": 15, "cha": 10}
BARD = {"str": 10, "dex": 14, "con": 10, "int": 12, "wis": 8, "cha": 15}
WARRIOR = {"str": 13, "dex": 11, "con": 12, "int": 9, "wis": 10, "cha": 8}
DWARF = {"str": 10, "dex": 14, "con": 14, "int": 14, "wis": 10, "cha": 8}
GNOLL = {"str": 15, "dex": 10, "con": 13, "int": 10, "wis": 11, "cha": 8}


def play(call) -> list[tuple[str, dict, dict]]:
    """The session: each call as (tool, args, answer). `call(tool, **args)` runs one tool call in a beat of its own."""
    said: list[tuple[str, dict, dict]] = []

    def run(tool, **args):
        out = call(tool, **args)
        assert "error" not in out, (tool, out)
        said.append((tool, args, out))
        return out

    def pc(name, cls, level, race, hp_max, scores, **build):
        run("create_character", name=name, sheet={"cls": cls, "level": level, "race": race, "hp_max": hp_max,
                                                   "ability_scores": scores})  # fmt: skip
        if build:
            run("set_build", character=name, **build)

    # 1. The party at 1st level (the paladin at 2nd), each at its hit die's maximum + Con at 1st level.
    pc("Krug", "Barbarian", 1, "Human", 14, BARBARIAN, feats=["power attack", "cleave"], weapon="greataxe",
       armor="studded leather")  # fmt: skip
    pc("Mei", "Monk", 1, "Human", 9, MONK, skills={"tumble": 4, "listen": 4})
    pc("Aldra", "Paladin", 2, "Human", 18, PALADIN, weapon="longsword", armor="chainmail", shield="heavy steel shield")
    pc("Ash", "Druid", 1, "Human", 9, DRUID, weapon="scimitar", armor="hide")
    run("add_companion", master="Ash", animal="wolf", name="Grey")
    pc("Lyra", "Bard", 1, "Human", 6, BARD, skills={"perform": 4}, weapon="rapier")
    # The warrior, an NPC class, as a hireling the party plays (a character of kind npc can't join a fight).
    pc("Watch", "Warrior", 1, "Human", 9, WARRIOR, weapon="longsword", armor="scale mail",
       shield="heavy wooden shield")  # fmt: skip

    # 2. The fight: two orcs, the module's 20 hp each.
    run("setup_combat", enemies=[{"name": "orc", "count": 2, "hp": 20}], surprise=False)
    run("use_feature", character="Krug", feature="rage")
    run("set_stance", combatant="Mei", flurry=True)
    run("use_feature", character="Aldra", feature="smite evil")
    run("use_feature", character="Lyra", feature="inspire courage")
    run("combat_round", actions=[
        {"attacker": "Krug", "target": "Orc 1"},
        {"attacker": "Mei", "target": "Orc 1"},
        {"attacker": "Aldra", "target": "Orc 2"},
        {"attacker": "Grey", "target": "Orc 2"},
        {"attacker": "Watch", "target": "Orc 2"},
        {"attacker": "Ash", "target": "Orc 1"},
        {"attacker": "Orc 1", "target": "Krug"},
        {"attacker": "Orc 2", "target": "Watch"},
    ])  # fmt: skip
    # A fear effect on Krug (the DM's ruling): rage's +2 morale bonus on Will. The song's +1 against fear is a morale
    # bonus too, and morale bonuses don't stack: no modifier.
    run("saving_throw", character="Krug", save_type="will", dc=12)
    run("use_feature", character="Aldra", feature="lay on hands", target="Watch", amount=3)
    run("combat_round", actions=[
        {"attacker": "Mei", "target": "Orc 2"},
        {"attacker": "Orc 2", "target": "Krug"},
        {"attacker": "Watch", "target": "Orc 2"},
        {"attacker": "Krug", "target": "Orc 2"},
    ])  # fmt: skip
    run("use_feature", character="Krug", feature="rage", amount=-1)
    run("end_combat")
    # The song stopped with the fight; 5 rounds later its effect ends.
    for name in ("Krug", "Mei", "Aldra", "Ash", "Grey", "Lyra", "Watch"):
        run("remove_effect", target=name, name="Inspire Courage +1")

    # 3. The multiclass dwarf and the gnoll.
    run("create_character", name="Durin", sheet={"cls": "Rogue/Wizard", "levels": {"rogue": 3, "wizard": 1},
                                                  "race": "Dwarf", "hp_max": 20, "ability_scores": DWARF})  # fmt: skip
    run("update_character", ref="Durin", patch={"xp": 6000}, reason="4th level's XP")
    run("award_xp", character="Durin", amount=1000)
    pc("Grak", "Fighter", 1, "Gnoll", 22, GNOLL, skills={"listen": 4, "spot": 4, "climb": 4},
       feats=["power attack", "cleave", {"id": "weapon focus", "choice": "battleaxe"}], weapon="battleaxe", armor="studded leather")  # fmt: skip

    # 4. The night's rest, and the rage again.
    run("rest", days=1)
    run("use_feature", character="Krug", feature="rage")
    run("get_character", ref="Krug")
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


def test_the_classes_session_matches_its_golden(seeded_call, srd35_storage, srd35_campaign):
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
