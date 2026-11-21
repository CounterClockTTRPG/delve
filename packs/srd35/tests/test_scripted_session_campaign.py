"""A scripted SRD 3.5 campaign from 1st to 20th level (DEL-389 part 5), through the tool host with seeded dice and the
tripwire on: one party made at 1st by `create_character` and `set_build` (a dwarf fighter, a human sorcerer, a halfling
rogue, an elf cleric) fights three goblins, rolls their hoard and takes their XP; levels to 2nd, 3rd and 4th one at a
time, the rogue taking a fighter level and then a wizard level; fights an ogre with a +1 battleaxe and the sorcerer's
pool; levels to 7th, 9th and 10th, the rogue's XP penalised once his wizard levels leave his fighter level behind; the
cleric turns a wight; the rogue is refused as an arcane trickster for a missing requirement, given it by `set_build`,
and enters with `advances` set; at 15th the fighter's full attack meets a glabrezu's DR 10/good, which his weapon
doesn't overcome, and a young adult red dragon's DR 5/magic, which it does, the sorcerer's caster level checks against
their SR; at 20th one more level is refused, and a night's rest gives back the spells and the turning spent.

Each level-up's skills and feats are the DM's, given by `set_build` as `d20["level_up"]`'s hints ask (each build in the
step's own call: the skill points spent are the engine's total exactly, `skill_points`); an ability increase is an
`update_character` of the scores. Several levels in one patch (4th → 7th) are core's level-ups one by one, each rolling
its hit die; the answer's `level_up` is the last one's, and the DM gives the levels between their hints too. A new
class's first level is core's level-up as any other is (DEL-457), its hit die rolled and its hints given; two unrecorded
`get_character` calls after it (`entered`, as part 4's session has) hold the places of the DM's own roll and read the
session made before DEL-457, so the later calls keep their seeds and the level-up rolls the same face. A round spends a
sorcerer's declared spell from its spells a day (`spells_spent`), so the DM never casts it again: a `spell_status` call,
which rolls nothing, holds the place of the `cast_spell` call it replaced so the seeds don't move. The ogre is slain and
its 900 XP shared; the glabrezu and the dragon are left standing (they flee: the DM's call), and the XP to each level is
the DM's award, the same to all four.

Differences from the brief, the SRD deciding (accepted by the controller): one ogre is CR 3, so the fight is EL 3, not
the brief's EL 5 (two ogres, EL 5, killed the 4th-level party in a first draft); Pip is a halfling, whose favoured
class is rogue, so his fighter 1 and wizard 1 are within a level and no penalty applies until wizard 3 (−20% from his
6th level on), not at the first wizard level; and the arcane trickster needs sneak attack +2d6 (rogue 3) and a 3rd-level
arcane spell (wizard 5, Int 14), so with the fighter level Pip is rogue 3/fighter 1/wizard 5 at 9th and enters at
10th, after an award to 10th. The hoard's one magic item is a wand of levitate (to the loot pile: used up, not worn),
so the +1 battleaxe is the DM's, set beside it in the chest, and Borin's +3 full plate, +3 heavy steel shield and ring
of protection +2 at 15th are the DM's too. Toughness (+3 hp) is no feat of the party's and Jump no skill of Borin's, so
neither moves a number here (DEL-456). The skill synergies do: from 5 ranks of Knowledge (arcana) (`answers[30]`
on) Sela's Spellcraft is 2 higher than its ranks + Int (5 → 7 first, 23 → 25 at 20th), and the sheets list the
conditional ones in `skill_notes` (Sela's Use Magic Device on scrolls; Pip's from Decipher Script, Escape Artist and
Search: Use Magic Device on scrolls, Use Rope to bind, Survival to track).

The session found three engine bugs, fixed in their own commits before it: initiative ties acted simultaneously, so the
ogre slain on Borin's total still swung (DEL-420; core's additive `FightRules.ties_by_bonus`, on for srd35: the higher
modifier first, then a roll-off); Spell Penetration and Greater Spell Penetration were left out of the SR check; and 5
ranks of Knowledge (religion) didn't add +2 to the turning check. Nothing was dropped as impossible.

The golden was checked by hand against the pack's SRD copy (`classes.json`'s tables, `monsters.json`, `xp.json`,
`magic_tables.json`, the rules files' Table: Treasure and Table: Turning Undead) and the logged faces (`rolls`;
`answers[i]` is the i-th recorded call):

- **The party at 1st** (`answers[0..7]`): Borin, dwarf fighter 1, Str 16, Dex 13, Con 14, Cha 6: hp 10 + 2 = 12; BAB 1,
  Fort 2 + 2 = 4, Ref 0 + 1 = 1, Will 0 + 1 = 1; scale mail 4 + heavy steel shield 2 + Dex 1 = AC 17, touch 11,
  flat-footed 16, speed 20; battleaxe 1 + 3 + Weapon Focus 1 = +5, 1d8+3 ×3; 8 skill points ((2 + 0) × 4): Climb 4 + 3
  − 6 (armour check −4 − 2) = 1, Intimidate 4 − 2 = 2. Sela, human sorcerer 1, Cha 16, Dex 14, Con 12: hp 4 + 1 = 5;
  Fort 1, Ref 2, Will 2; initiative 2 + 4 = 6; Table: The Sorcerer 5/3 + Cha's bonus 1st = 5/4, known 4/2, DC 13/14; 12
  points ((2 + 0) × 4 + 4). Pip, halfling rogue 1, Dex 17, Int 14: hp 6 + 1 = 7; Fort 0 + 1 + 1 = 2, Ref 2 + 3 + 1 = 6,
  Will 0 + 0 + 1 = 1; leather 2 + Dex 3 + size 1 + Dodge 1 = AC 17, touch 15, flat-footed 13; short sword 0 + 0 + 1 =
  +1, 1d4; 40 points ((8 + 2) × 4): Hide 4 + 3 + 4 = 11, Move Silently 4 + 3 + 2 = 9. Ilen, elf cleric 1, Wis 16, Cha
  12: hp 8; Fort 2, Ref 0 + 1 = 1, Will 2 + 3 = 5; scale mail and shield AC 17, speed 20; warhammer 0 + 1 + the War
  domain's Weapon Focus 1 = +2, 1d8+1; slots 3 / 1 + Wis 1 + domain 1 = 3, DC 13/14; turning 3 + Cha 1 = 4 a day.
- **The goblins** (`answers[8..20]`): SRD, 1d8+1 [8] 9, [6] 7, [5] 6, AC 15, touch 12, flat-footed 14, morningstar +2
  1d6. Initiative: Goblin 3 20 + 1 = 21, Goblin 1 18, Goblin 2 16, Sela 6 + 6 = 12 and Ilen 11 + 1 = 12 (tied: Sela's
  higher modifier first), Borin 6, Pip 1 + 3 = 4. Round 1: Goblin 3 at Ilen, flat-footed: [19] + 2 hits, [1], 8 → 7;
  Goblin 1 at Borin [14] + 2 = 16 hits flat-footed 16, [4], 12 → 8; Goblin 2 at Pip [19] + 2 hits, [1], 7 → 6; Sela's
  Magic Missile (`spells_spent`: DC 10 + 1 + 3 + Spell Focus 1 = 15, 3 of 4 left); Ilen [7] + 2 misses; Borin [15] + 5 =
  20 hits, [8] + 3 = 11, Goblin 1 slain at −2; Pip [9] + 1 misses. The missile 1d4+1 [4] = 5: Goblin 3 6 → 1. Round 2:
  Goblin 3 [4] misses; Goblin 2's 20, confirmed [17] + 2 = 19 ≥ 17, ×2: [2] + [3] = 5, Pip 6 → 1; Ilen [9] misses;
  Borin [10] + 5 = 15 hits, [2] + 3 = 5, Goblin 2 7 → 2; Pip [15] + 1 = 16 hits, [3], slain at −1. Round 3: Goblin 3
  [7] misses; Ilen [1]; Borin [17] + 5 hits, [1] + 3 = 4, slain at −3. The hoard, EL 1: coins d% [47] (30–52: 1d8 ×
  100 sp) [8] = 800 sp, goods [62] and items [37] none. `end_combat`: 3 × CR 1/3's 100 = 300 XP, 75 each.
- **2nd to 4th** (`answers[21..53]`): 1,000 XP (`xp.json`'s 2nd), then 6,000 (4th). Borin d10 [4] + 2 = 6 → 18, [8] + 2
  → 28, [2] + 2 → 32; BAB 2/3/4, Fort 5/5/6, Ref and Will 1/2/2; hints "2 skill points, a fighter bonus feat" (2nd,
  4th), "a feat" (3rd), an ability increase (4th): Cleave, Blind-Fight, Weapon Specialization (battleaxe). Sela d4 [4] +
  1 → 10, [4] + 1 → 15, [3] + 1 → 19; Will 3/3/4; 6/5, 6/6, 6/7/4 a day (4th: 6/6/3 + Cha 1st), known 5/2, 5/3, 6/3/1;
  Combat Casting at 3rd. Ilen d8 [2] → 10, [2] → 12, [6] → 18; 4/4, 4/4/3, 5/5/4. Pip's fighter level d10 [9] + 1 = 10,
  7 → 17 (1 → 11), hints 2 + Int 2 = 4 skill points, a fighter bonus feat: BAB 1, Fort 0 + 2 + 1 + 1 = 4, 44 points (+
  (2 + 2)); Weapon Finesse, the fighter's bonus feat (BAB 1). His wizard level d4 [1] + 1 = 2 → 19, hints 2 + 2 = 4
  skill points, a feat (3rd): Will +2 = 3; wizard 1 3/1 + Int's 1st = 3/2, DC 12/13; 48 points. Rogue 2 by core's
  level-up, d6 [1] + 1 = 2 → 21; hints "10 skill points, an ability increase"; Ref 3 + 3 + 1 = 7; Improved Initiative
  (3rd); 58 points. The increases: Borin's Str 17, Sela's Cha 17, Pip's Dex 18 (AC 18, touch 16, Ref 8, initiative 4 + 4
  = 8), Ilen's Wis 17 (Iron Will: Will 4 + 3 + 2 = 9). Seven days' rest: level × 7.
- **The hoard and the ogre** (`answers[54..66]`): EL 5, double standard: coins [29] (20–38: 1d6 × 1,000 sp) [1] = 1,000
  sp and [84] (39–95: 1d8 × 100 gp) [8] = 800 gp; goods [3], [18] none; items [39] none and [92] (68–100: 1d3 minor)
  [1]: minor [88] (82–91) a wand, [80] (78–80) levitate. The +1 battleaxe: 4 + 3 + 1 + 1 = +9, 1d8 + 3 + 2 + 1 = 1d8+6.
  The ogre: 4d8+11 [8, 3, 4, 6] = 32, AC 16, touch 8, flat-footed 16, greatclub +8 2d8+7. Initiative: Sela 11 + 6 = 17,
  Ilen 16 + 1 = 17, Borin 10 + 1 = 11, the ogre 12 − 1 = 11 (Borin's +1 first), Pip 1 + 8 = 9. Round 1: Sela's Magic
  Missile (`spells_spent`: DC 15, 6 of 7 left); Ilen [19] + 5 = 24 hits, [3] + 1 = 4, 32 → 28; Borin [3] misses; the
  ogre at Borin [8] + 8 = 16 < 17; Pip flanking, [15] + 2 + 4 + 1 + 2 = 24 hits, [3] and sneak 1d6 [6] = 9, 19. Two
  missiles (caster level 4), 2d4+2 [4, 1] = 7: 12. Round 2: Ilen [3] misses; Borin flanking [10] + 9 + 2 = 21 hits, [7]
  + 6 = 13, slain at −1; the ogre, slain on Borin's total, draws no swing (DEL-420). CR 3: 900 XP, 225 each.
- **7th** (`answers[67..78]`): 6,225 + 17,775 = 24,000 (7th). Borin d10 [6], [8], [7] + 2 each: 32 → 59; BAB 7, Fort 5 +
  2 = 7, Ref 3, Will 3; Great Cleave and Improved Initiative (6th's feat and bonus feat; initiative 1 + 4 = 5). Sela d4
  [3], [3], [2] + 1 each: 19 → 30; 6/6/6/4 + Cha (1st–3rd) = 6/7/7/5, known 7/5/3/2, DC 16 at 3rd; Spell Penetration
  (6th). Ilen d8 [4], [2], [5]: 18 → 29; 6/4/3/2/1 + Wis (1st–3rd) + domain = 6/6/5/4/2; Lightning
  Reflexes: Ref 2 + 1 + 2 = 5. Pip rogue 3 d6 [2] + 1, wizard 2 and 3 d4 [4], [3] + 1: 21 → 33; BAB 2 + 1 + 1 = 4, Fort
  1 + 2 + 1 + 1 + 1 = 6, Ref 3 + 0 + 1 + 4 + 1 = 9, Will 1 + 0 + 3 + 0 + 1 = 5; wizard 3 4/2/1 + Int = 4/3/2; the
  multiclass penalty 20% (wizard 3 against fighter 1, the favoured rogue aside), in the level-up; Mobility (6th); 76
  points. Skill points: Borin 2 × 7 + 6 = 20, Sela 3 × 7 + 9 = 30, Ilen 20, each skill at 7 + 3 = 10.
- **9th, the turning** (`answers[79..95]`): +35,000: 59,000 (9th, 52,000); Pip's 35,000 − 20% = 28,000, 24,000 →
  52,000, exactly 9th. Borin [7], [4] + 2: 74; BAB 9; Greater Weapon Focus (8th bonus), Great Fortitude (9th): Fort 6
  + 2 + 2 = 10. Sela [1], [3] + 1: 36; 6/6/6/6/4 + Cha (1st–3rd) = 6/7/7/7/4, and with Cha 18 (8th) the 4th's too: 5, DC
  10 + 4 + 4 = 18; known 8/5/4/3/2; Greater Spell Penetration. Ilen [4], [2]: 35; 6/4/4/3/2/1 + Wis + domain =
  6/6/6/5/3/2, Wis 18: 4th 4, DC 19 at 5th; Great Fortitude: Fort 6 + 2 = 8, Will 6 + 4 + 2 = 12. Pip wizard 4 and 5 d4
  [1], [2] + 1: 38; BAB 5; wizard 5 4/3/2/1 + Int = 4/4/3/1; hints "4 skill points, a feat, a wizard bonus feat": Combat
  Reflexes, Empower Spell; Dex 19 (8th); 80 of 84 points spent, none in Knowledge (arcana). Turning a wight (4 HD): d20
  [5] + Cha 1 + 2 (Knowledge (religion) 12 ranks) = 8, Table: Turning Undead 7–9: level − 1 = 8 HD; damage 2d6 [4, 4] +
  9 + 1 = 18; destroyed (4 HD ≤ 9 / 2 = 4); 3 of 4 attempts left.
- **10th, the arcane trickster** (`answers[96..109]`): +30,000: 89,000 (10th, 76,000); Pip's 24,000: 76,000. Borin d10
  [10] + 2: 86, Fort 11, Improved Critical (battleaxe, the 10th's bonus feat): 19–20. Sela [4] + 1: 41; 6/6/6/6/5/3 +
  Cha (1st–4th) = 6/7/7/7/6/3, known 9/5/4/3/2/1. Ilen [4]: 39; 6/6/6/5/5/3. Pip refused: "Knowledge (arcana) 4 ranks
  (it has 0)", the one requirement unmet (Decipher Script, Disable Device, Escape Artist 10 or 11 each; mage hand and a
  3rd-level spell as a wizard 5; sneak attack 2d6; chaotic neutral). The four points given: 84 of 84, Knowledge (arcana)
  4 + 2 = 6 (a wizard's class skill). Arcane trickster 1: d4 [4] + 1 = 5, 38 → 43; hints 4 + Int 2 = 6 skill points
  (10th: no feat or increase); Ref +2 = 11, Will +2 = 8; warned until `advances` names the wizard: caster level 6,
  Table: The Wizard 6th 4/3/3/2 + Int = 4/4/4/2; 90 points (+ 4 + 2).
- **15th** (`answers[110..127]`): +455,000: 544,000 (15th, 440,000); Pip's 364,000: 440,000, exactly. Borin d10 [2],
  [4], [10], [7], [3] + 2 each: 122; BAB 15, Fort 9 + 2 + 2 = 13; Greater Weapon Specialization (12th), Iron Will, Dodge
  (14th), Lightning Reflexes (15th): AC 18, Ref 5 + 1 + 2 = 8, Will 5 + 1 + 2 = 8; Str 19. Sela d4 [2], [3], [1], [3],
  [2] + 1 each: 57; Table: The Sorcerer 15th 6/6/6/6/6/6/6/4 + Cha (1st–4th) = 6/7/7/7/7/6/6/4, known 9/5/5/4/4/4/3/2,
  DC 21 at 7th. Ilen d8 [1], [5], [2], [7], [5]: 59; 6/5/5/5/4/4/3/2/1 + Wis (1st–4th) + domain = 6/7/7/7/6/5/4/3/2;
  Fort 11, Ref 8, Will 15. Pip arcane trickster 2–6 d4 [3], [1], [2], [1], [4] + 1 each: 59; BAB 8, Fort 1 + 2 + 1 +
  2 + 1 + 1 = 8, Ref 3 + 0 + 1 + 5 + 4 + 1 = 14, Will 1 + 0 + 4 + 5 + 1 = 11; wizard caster level 11, 4/4/4/4/3 + Int,
  no 5th or 6th at Int 14 ("10 + the spell level") = 4/5/5/4/3; Dex 20 (12th), Iron Will, Lightning Reflexes: Ref 17,
  Will 13; 120 points. Borin's gear: +3 full plate 8 + 3, +3 heavy steel shield 2 + 3, Dex 1 (max 1), deflection 2,
  Dodge 1 = AC 30, touch 14, flat-footed 28; the battleaxe 15 + 4 + 1 + 1 + 1 = +22/+17/+12, 1d8 + 4 + 2 + 2 + 1 =
  1d8+9, 19–20 ×3.
- **The glabrezu** (`answers[128..134]`): SRD, 12d8+120 [6, 5, 8, 5, 2, 8, 5, 1, 3, 6, 5, 6] = 180, AC 27, touch 8,
  flat-footed 27, DR 10/good, SR 21; 2 pincers +20 2d8+10, 2 claws +18 1d6+5, bite +18 1d8+5. Initiative: Ilen 19 + 1
  = 20, Pip 9 + 9 = 18, Borin 12 + 5 = 17, Sela 10 + 6 = 16, the glabrezu 9. Sela's check: d20 [19] + 15 + Spell
  Penetration 2 + Greater 2 = 38 ≥ 21. Round 1, the glabrezu flat-footed: Borin [3] + 22, [6] + 17, [14] + 12 miss
  27. It at Borin (30): [11] + 20 hits, [4, 4] + 10 = 18, 122 → 104; [16] + 20, [6, 1] + 10 = 17, 87; claw [13] + 18,
  [5] + 5 = 10, 77; claw [11] + 18 = 29 misses; bite [13] + 18, [8] + 5 = 13, 64. Cone of Cold (`spells_spent`: DC 10 +
  5 + 4 + 1 + 1 = 21, 5 of 6 left; its cold the DM's, against resistance 10). Round 2: Borin [1]; [20], confirmed [18]
  + 17 = 35, ×3: [5] + [1] + [6] + 27 = 39 less DR 10 = 29 (+1 is magic, not good), 180 → 151; [9] + 12 misses. It:
  [12] + 20, [3, 5] + 10 = 18, 46; [8] + 20 = 28 misses; claws [19], [16] + 18 hit, [3] + 5 = 8, [2] + 5 = 7, 31; bite
  [11] + 18 misses. A week's rest: 15 × 7, 31 → 122.
- **The young adult red dragon** (`answers[135..139]`): SRD, 19d12+95: 129 + 95 = 224, AC 26, touch 8, flat-footed 26,
  DR 5/magic, SR 19; bite +27 2d8+10, 2 claws +22 2d6+5, 2 wings +22 1d8+5, tail slap +22 2d6+15. Initiative: Pip 16 + 9
  = 25, Borin 18 + 5 = 23, Ilen 9, Sela 2 + 6 = 8, the dragon 4. Sela: [6] + 19 = 25 ≥ 19. Borin, it flat-footed: [15]
  + 22 hits, [1] + 9 = 10, the DR overcome (magic), 224 → 214; [15] + 17 hits, [2] + 9 = 11, 203; [6] + 12 misses. Cone
  of Cold (`spells_spent`: DC 21), 5 left. The dragon at Borin: bite [13] + 27, [2, 7] + 10 = 19, 122 → 103; claws [16],
  [15] + 22, [5, 2] + 5 = 12, [6, 2] + 5 = 13, 78; wing [8] + 22 = 30 hits, [7] + 5 = 12, 66; wing [2] misses; tail [15]
  + 22, [1, 2] + 15 = 18, 48.
- **20th** (`answers[140..156]`): +2,700,000: 3,244,000; Pip's 2,160,000: 2,600,000 (20th). Borin d10 [7], [4], [6],
  [5], [6] + 2 each, 122 → 160 (48 → 86); BAB 20, Fort 12 + 2 + 2 = 16, Ref 6 + 1 + 2 = 9, Will 9; hints at 20th "a
  fighter bonus feat, an ability increase"; Str 21 (16th, 20th); Climb 23 + 5 − 6 = 22, Intimidate 23 − 2 = 21; 46
  points. Sela d4 [4], [2], [4], [2], [1] + 1 each: 75; 6 a day of each level + Cha 21's bonus (1st two, 2nd–5th one) =
  6/8/7/7/7/7/6/6/6/6, known 9/5/5/4/4/4/3/3/3/3, DC 24 at 9th; Lightning Reflexes: Ref 6 + 2 + 2 = 10; 69 points. Ilen
  d8 [8], [2], [1], [5], [7]: 82; 6/5/5/5/5/5/4/4/4/4 + Wis 21 (1st two, 2nd–5th one) + domain = 6/8/7/7/7/7/5/5/5/5,
  DC 24 at 9th; Fort 12 + 2 = 14, Ref 6 + 1 + 2 = 9, Will 12 + 5 + 2 = 19; Improved Initiative: 5. Pip rogue 4 d6 [2] +
  1, arcane trickster 7–10 d4 [4], [4], [2], [4] + 1 each: 80; BAB 3 + 1 + 2 + 5 = 11; uncanny dodge (rogue 4):
  flat-footed 20 with Dex 22, AC 20, touch 18; Fort 1 + 2 + 1 + 3 + 1 + 1 + Great Fortitude 2 = 11, Ref 4 + 0 + 1 + 7 +
  6 + 1 + 2 = 21, Will 1 + 0 + 4 + 7 + 1 + 2 = 15; wizard caster level 15, 4/4/4/4/4 + Int = 4/5/5/4/4; sneak attack
  2d6 + 5d6 = 7d6 (the arcane trickster's 2nd, 4th … 10th); 154 points. Borin's 21st: "20th level, the top".
- **The rest** (`answers[157..161]`): Meteor Swarm, DC 10 + 9 + 5 + 1 + 1 = 26, 5 of 6 left; the turning: a dread
  wraith (16 HD), [1] + 1 + 2 = 4, 4–6: level − 2 = 18 HD, 2d6 [1, 6] + 20 + 1 = 28, turned, not destroyed (16 > 10),
  3 left. A day's rest: Borin 86 → 106 (20 a day); Meteor Swarm 5 of 6 left again; Ilen's turning used back to 0.

Every answer is compared with `golden/scripted_session_campaign.json`. The test writes the golden when it is missing and
fails; it was checked by hand against the working above, and is never regenerated. It was rewritten once, by the owner's
leave, for DEL-457: each entry's `update_character` without the DM's hit point patch, its answer with the level-up; and
once more for DEL-456: Sela's Spellcraft synergy and the `skill_notes`, no outcome moved; and once for DEL-431: Borin's
Cleave, later Great Cleave, and the glabrezu's in their numbers (`cleave`); the ogre his swing kills is the last foe,
so no extra attack is due; no outcome moved."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parent / "golden" / "scripted_session_campaign.json"
SEED = 1
"""The first call's seed; each call after takes the next."""

BORIN = {"str": 16, "dex": 13, "con": 14, "int": 10, "wis": 12, "cha": 6}
SELA = {"str": 8, "dex": 14, "con": 12, "int": 10, "wis": 10, "cha": 16}
PIP = {"str": 10, "dex": 17, "con": 12, "int": 14, "wis": 10, "cha": 10}
ILEN = {"str": 12, "dex": 12, "con": 10, "int": 10, "wis": 16, "cha": 12}
PARTY = ("Borin", "Sela", "Pip", "Ilen")
SPELLS = [
    ["Light", "Detect Magic", "Ray of Frost", "Daze", "Mage Hand", "Flare", "Read Magic", "Resistance",
     "Prestidigitation"],
    ["Magic Missile", "Sleep", "Shield", "Mage Armor", "Burning Hands"],
    ["Scorching Ray", "Invisibility", "Glitterdust", "Mirror Image", "Web"],
    ["Fireball", "Haste", "Lightning Bolt", "Dispel Magic"],
    ["Ice Storm", "Dimension Door", "Invisibility, Greater", "Stoneskin"],
    ["Cone of Cold", "Hold Monster", "Wall of Force", "Teleport"],
    ["Chain Lightning", "Disintegrate", "Dispel Magic, Greater"],
    ["Finger of Death", "Prismatic Spray", "Delayed Blast Fireball"],
    ["Polar Ray", "Horrid Wilting", "Sunburst"],
    ["Meteor Swarm", "Time Stop", "Wish"],
]  # fmt: skip
"""Sela's spells known, by level, in the order she learns them."""
BATTLEAXE = "battleaxe"
BORIN_FEATS = ["power attack", {"id": "weapon focus", "choice": BATTLEAXE}, "cleave", "blind fight",
               {"id": "weapon specialization", "choice": BATTLEAXE}, "great cleave", "improved initiative",
               {"id": "greater weapon focus", "choice": BATTLEAXE}, "great fortitude",
               {"id": "improved critical", "choice": BATTLEAXE},
               {"id": "greater weapon specialization", "choice": BATTLEAXE}, "iron will", "dodge",
               "lightning reflexes", "mobility", "spring attack", "endurance", "combat reflexes"]  # fmt: skip
"""Borin's feats in the order taken: 1st (two), 2nd, 3rd, 4th, 6th (two), 8th, 9th, 10th, 12th (two), 14th, 15th,
16th, 18th (two), 20th."""
SELA_FEATS = [{"id": "spell focus", "choice": "evocation"}, "improved initiative", "combat casting",
              "spell penetration", "greater spell penetration", "eschew materials",
              {"id": "greater spell focus", "choice": "evocation"}, "lightning reflexes"]  # fmt: skip
"""Sela's: 1st (two, the human's), 3rd, 6th, 9th, 12th, 15th, 18th."""
PIP_FEATS = ["dodge", "weapon finesse", "improved initiative", "mobility", "combat reflexes", "empower spell",
             "iron will", "lightning reflexes", "great fortitude"]  # fmt: skip
"""Pip's: 1st, 2nd (the fighter's bonus feat), 3rd, 6th, 9th (and wizard 5's bonus feat), 12th, 15th, 18th."""
ILEN_FEATS = ["combat casting", "iron will", "lightning reflexes", "great fortitude",
              {"id": "spell focus", "choice": "conjuration"}, "extend spell", "improved initiative"]  # fmt: skip
"""Ilen's: 1st, 3rd, 6th, 9th, 12th, 15th, 18th."""
CANTRIPS = ["Light", "Detect Magic", "Ray of Frost", "Daze", "Mage Hand", "Flare", "Read Magic", "Resistance",
            "Prestidigitation"]  # fmt: skip


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

    # 1. The party at 1st level.
    run("create_character", name="Borin", sheet={"cls": "Fighter", "level": 1, "race": "Dwarf", "hp_max": 12,
                                                  "alignment": "Lawful Neutral", "ability_scores": BORIN})  # fmt: skip
    run("set_build", character="Borin", skills={"climb": 4, "intimidate": 4},
        feats=[*BORIN_FEATS[:2]], weapon=BATTLEAXE,
        armor="scale mail", shield="heavy steel shield")  # fmt: skip
    run("create_character", name="Sela", sheet={"cls": "Sorcerer", "level": 1, "race": "Human", "hp_max": 5,
                                                 "alignment": "Chaotic Good", "ability_scores": SELA})  # fmt: skip
    run("set_build", character="Sela", skills={"concentration": 4, "spellcraft": 4, "knowledge arcana": 4},
        feats=[*SELA_FEATS[:2]], weapon="dagger",
        known={"sorcerer": [*CANTRIPS[:4], "Magic Missile", "Sleep"]})  # fmt: skip
    run("create_character", name="Pip", sheet={"cls": "Rogue", "level": 1, "race": "Halfling", "hp_max": 7,
                                                "alignment": "Chaotic Neutral", "ability_scores": PIP})  # fmt: skip
    run("set_build", character="Pip", skills={"hide": 4, "move silently": 4, "disable device": 4, "open lock": 4,
        "search": 4, "spot": 4, "listen": 4, "tumble": 4, "decipher script": 4, "escape artist": 4},
        feats=[*PIP_FEATS[:1]], weapon="short sword", armor="leather")  # fmt: skip
    run("create_character", name="Ilen", sheet={"cls": "Cleric", "level": 1, "race": "Elf", "hp_max": 8,
                                                 "alignment": "Neutral Good", "ability_scores": ILEN})  # fmt: skip
    run("set_build", character="Ilen", skills={"concentration": 4, "knowledge religion": 4}, feats=[*ILEN_FEATS[:1]],
        domains=["war", "good"], weapon="warhammer", armor="scale mail", shield="heavy steel shield")  # fmt: skip

    # 2. Goblins, EL 1.
    run("setup_combat", enemies=[{"name": "goblin", "count": 3}], surprise=False)
    run("combat_round", actions=[
        {"attacker": "Borin", "target": "Goblin 1"},
        {"attacker": "Pip", "target": "Goblin 2"},
        {"caster": "Sela", "spell": "Magic Missile", "target": "Goblin 3"},
        {"attacker": "Ilen", "target": "Goblin 3"},
        {"attacker": "Goblin 1", "target": "Borin"},
        {"attacker": "Goblin 2", "target": "Pip"},
        {"attacker": "Goblin 3", "target": "Ilen"},
    ])  # fmt: skip
    run("spell_status", character="Sela")  # the round spent it; a call that rolls nothing keeps the seeds
    missile = run("roll", notation="1d4+1", purpose="Sela's magic missile")["total"]
    run("apply_damage", character="Goblin 3", amount=missile)
    fight(run, {"Borin": ("Goblin 2", {}), "Pip": ("Goblin 2", {}), "Ilen": ("Goblin 3", {})},
          {"Goblin 2": "Pip", "Goblin 3": "Ilen"}, standing=["Goblin 2", "Goblin 3"])  # fmt: skip
    run("generate_treasure", treasure_types="EL 1")
    run("end_combat")
    for name in PARTY:  # the goblins' 300 XP, shared by four
        run("award_xp", character=name, amount=75)

    # 3. 2nd level, then 3rd and 4th, one at a time. Pip takes a fighter level, then a wizard level.
    for name in PARTY:
        run("award_xp", character=name, amount=925)
    for name in ("Borin", "Sela", "Ilen"):
        run("update_character", ref=name, patch={"level": 2}, reason="2nd level")
    entered("Pip", {"cls": "Rogue/Fighter", "levels": {"rogue": 1, "fighter": 1}}, "a fighter's first level")
    run("set_build", character="Borin", skills={"climb": 5, "intimidate": 5}, feats=[*BORIN_FEATS[:3]])
    run("set_build", character="Sela", skills={"concentration": 5, "spellcraft": 5, "knowledge arcana": 5},
        known={"sorcerer": [*CANTRIPS[:5], "Magic Missile", "Sleep"]})  # fmt: skip
    run("set_build", character="Pip", skills={"hide": 5, "move silently": 5, "tumble": 5, "disable device": 5,
        "escape artist": 5, "decipher script": 5, "open lock": 4, "search": 4, "spot": 3, "listen": 3},
        feats=[*PIP_FEATS[:2]])  # fmt: skip
    run("set_build", character="Ilen", skills={"concentration": 5, "knowledge religion": 5})
    for name in PARTY:
        run("award_xp", character=name, amount=5000)
    for name in ("Borin", "Sela", "Ilen"):
        run("update_character", ref=name, patch={"level": 3}, reason="3rd level")
    entered("Pip", {"cls": "Rogue/Fighter/Wizard", "levels": {"rogue": 1, "fighter": 1, "wizard": 1}},
            "a wizard's first level")  # fmt: skip
    for name in ("Borin", "Sela", "Ilen"):
        run("update_character", ref=name, patch={"level": 4}, reason="4th level")
    run("update_character", ref="Pip", patch={"levels": {"rogue": 2, "fighter": 1, "wizard": 1}}, reason="rogue 2")
    run("update_character", ref="Borin", patch={"ability_scores": {**BORIN, "str": 17}}, reason="4th level")
    run("update_character", ref="Sela", patch={"ability_scores": {**SELA, "cha": 17}}, reason="4th level")
    run("update_character", ref="Pip", patch={"ability_scores": {**PIP, "dex": 18}}, reason="4th level")
    run("update_character", ref="Ilen", patch={"ability_scores": {**ILEN, "wis": 17}}, reason="4th level")
    run("set_build", character="Borin", skills={"climb": 7, "intimidate": 7}, feats=[*BORIN_FEATS[:5]])
    run("set_build", character="Sela", skills={"concentration": 7, "spellcraft": 7, "knowledge arcana": 7},
        feats=[*SELA_FEATS[:3]],
        known={"sorcerer": [*CANTRIPS[:6], "Magic Missile", "Sleep", "Shield", "Scorching Ray"]})  # fmt: skip
    run("set_build", character="Pip", skills={"hide": 7, "move silently": 7, "tumble": 7, "disable device": 7,
        "escape artist": 7, "decipher script": 7, "open lock": 5, "search": 5, "spot": 3, "listen": 3},
        feats=[*PIP_FEATS[:3]])  # fmt: skip
    run("set_build", character="Ilen", skills={"concentration": 7, "knowledge religion": 7},
        feats=[*ILEN_FEATS[:2]])  # fmt: skip
    run("rest", days=7)

    # 4. The goblin chief's hoard, EL 5, its coin and a wand; the DM's +1 battleaxe beside it; an ogre, EL 3.
    run("award_treasure", treasure_types="EL 5, double standard", source="the goblin chief's chest")
    run("set_build", character="Borin", items=[f"+1 {BATTLEAXE}"])
    run("setup_combat", enemies=[{"name": "ogre", "count": 1}], surprise=False)
    run("combat_round", actions=[
        {"caster": "Sela", "spell": "Magic Missile", "target": "Ogre"},
        {"attacker": "Borin", "target": "Ogre"},
        {"attacker": "Pip", "target": "Ogre", "condition": "flanking"},
        {"attacker": "Ilen", "target": "Ogre"},
        {"attacker": "Ogre", "target": "Borin"},
    ])  # fmt: skip
    run("spell_status", character="Sela")  # the round spent it; a call that rolls nothing keeps the seeds
    missiles = run("roll", notation="2d4+2", purpose="Sela's magic missile, two missiles")["total"]
    run("apply_damage", character="Ogre", amount=missiles)
    flank = {"condition": "flanking"}
    fight(run, {"Borin": ("Ogre", flank), "Pip": ("Ogre", flank), "Ilen": ("Ogre", {})}, {"Ogre": "Borin"},
          standing=["Ogre"])  # fmt: skip
    run("end_combat")
    for name in PARTY:  # the ogre's 900 XP, shared by four
        run("award_xp", character=name, amount=225)

    # 5. 7th level; Pip's wizard levels leave his fighter level two behind: the multiclass penalty.
    for name in PARTY:
        run("award_xp", character=name, amount=17775)
    for name in ("Borin", "Sela", "Ilen"):
        run("update_character", ref=name, patch={"level": 7}, reason="7th level")
    run("update_character", ref="Pip", patch={"levels": {"rogue": 3, "fighter": 1, "wizard": 3}}, reason="7th level")
    run("set_build", character="Borin", skills={"climb": 10, "intimidate": 10}, feats=[*BORIN_FEATS[:7]])
    run("set_build", character="Sela", skills={"concentration": 10, "spellcraft": 10, "knowledge arcana": 10},
        feats=[*SELA_FEATS[:4]], known={"sorcerer": known(7, 5, 3, 2)})  # fmt: skip
    run("set_build", character="Pip", skills={"hide": 10, "move silently": 10, "tumble": 10, "disable device": 10,
        "escape artist": 10, "decipher script": 10, "open lock": 5, "search": 5, "spot": 3, "listen": 3},
        feats=[*PIP_FEATS[:4]])  # fmt: skip
    run("set_build", character="Ilen", skills={"concentration": 10, "knowledge religion": 10}, feats=[*ILEN_FEATS[:3]])

    # 6. 9th level: the same award, less Pip's 20%; 8th level's ability increases; the cleric turns a wight.
    for name in PARTY:
        run("award_xp", character=name, amount=35000)
    for name in ("Borin", "Sela", "Ilen"):
        run("update_character", ref=name, patch={"level": 9}, reason="9th level")
    run("update_character", ref="Pip", patch={"levels": {"rogue": 3, "fighter": 1, "wizard": 5}}, reason="9th level")
    increase(run, 18, 18, 19, 18, "8th level")
    run("set_build", character="Borin", skills={"climb": 12, "intimidate": 12}, feats=[*BORIN_FEATS[:9]])
    run("set_build", character="Sela", skills={"concentration": 12, "spellcraft": 12, "knowledge arcana": 12},
        feats=[*SELA_FEATS[:5]], known={"sorcerer": known(8, 5, 4, 3, 2)})  # fmt: skip
    # Pip leaves 4 points for the wizard's Knowledge (arcana), and forgets them.
    run("set_build", character="Pip", skills={"hide": 11, "move silently": 11, "tumble": 11, "disable device": 11,
        "escape artist": 10, "decipher script": 10, "open lock": 5, "search": 5, "spot": 3, "listen": 3},
        feats=[*PIP_FEATS[:6]])  # fmt: skip
    run("set_build", character="Ilen", skills={"concentration": 12, "knowledge religion": 12}, feats=[*ILEN_FEATS[:4]])
    run("turning_undead", level=9, undead="wight", character="Ilen")

    # 7. 10th level, and Pip's arcane trickster: refused for the Knowledge (arcana) ranks, given them, entered.
    for name in PARTY:
        run("award_xp", character=name, amount=30000)
    for name in ("Borin", "Sela", "Ilen"):
        run("update_character", ref=name, patch={"level": 10}, reason="10th level")
    at1 = {"cls": "Rogue/Fighter/Wizard/Arcane Trickster",
           "levels": {"rogue": 3, "fighter": 1, "wizard": 5, "arcane trickster": 1}}  # fmt: skip
    refused("update_character", ref="Pip", patch=at1, reason="the arcane trickster")
    pip_skills = {"hide": 11, "move silently": 11, "tumble": 11, "disable device": 11, "escape artist": 10,
                  "decipher script": 10, "knowledge arcana": 4, "open lock": 5, "search": 5, "spot": 3,
                  "listen": 3}  # fmt: skip
    run("set_build", character="Pip", skills=pip_skills)
    entered("Pip", at1, "the arcane trickster")
    run("set_build", character="Pip", advances={"arcane trickster": ["wizard"]},
        skills={**pip_skills, "open lock": 8, "search": 8})  # fmt: skip
    run("set_build", character="Borin", skills={"climb": 13, "intimidate": 13}, feats=[*BORIN_FEATS[:10]])
    run("set_build", character="Sela", skills={"concentration": 13, "spellcraft": 13, "knowledge arcana": 13},
        known={"sorcerer": known(9, 5, 4, 3, 2, 1)})  # fmt: skip
    run("set_build", character="Ilen", skills={"concentration": 13, "knowledge religion": 13})

    # 8. 15th level; a glabrezu (DR 10/good: the +1 battleaxe doesn't overcome it) and a young adult red dragon (DR
    # 5/magic: it does), each with SR; Borin's full attack.
    for name in PARTY:
        run("award_xp", character=name, amount=455000)
    for name in ("Borin", "Sela", "Ilen"):
        run("update_character", ref=name, patch={"level": 15}, reason="15th level")
    run("update_character", ref="Pip", patch={"levels": {"rogue": 3, "fighter": 1, "wizard": 5,
        "arcane trickster": 6}}, reason="15th level")  # fmt: skip
    increase(run, 19, 19, 20, 19, "12th level")
    run("set_build", character="Borin", skills={"climb": 18, "intimidate": 18}, feats=[*BORIN_FEATS[:14]])
    run("set_build", character="Sela", skills={"concentration": 18, "spellcraft": 18, "knowledge arcana": 18},
        feats=[*SELA_FEATS[:7]], known={"sorcerer": known(9, 5, 5, 4, 4, 4, 3, 2)})  # fmt: skip
    run("set_build", character="Pip", skills={**pip_skills, "hide": 18, "move silently": 18, "tumble": 18,
        "disable device": 18, "open lock": 10, "search": 8}, feats=[*PIP_FEATS[:8]])  # fmt: skip
    run("set_build", character="Ilen", skills={"concentration": 18, "knowledge religion": 18}, feats=[*ILEN_FEATS[:6]])
    run("set_build", character="Borin", items=["+1 battleaxe", "+3 full plate", "+3 heavy steel shield",
                                                "ring of protection +2"], armor="full plate")  # fmt: skip
    run("rest", days=7)
    run("setup_combat", enemies=[{"name": "glabrezu", "count": 1}], surprise=False)
    run("spell_resistance", caster="Sela", target="Glabrezu", spell="Cone of Cold")
    run("combat_round", actions=[
        {"attacker": "Borin", "target": "Glabrezu"},
        {"caster": "Sela", "spell": "Cone of Cold", "target": "Glabrezu"},
        {"attacker": "Glabrezu", "target": "Borin"},
    ])  # fmt: skip
    run("spell_status", character="Sela")  # the round spent it; a call that rolls nothing keeps the seeds
    run("combat_round", actions=[
        {"attacker": "Borin", "target": "Glabrezu"},
        {"attacker": "Glabrezu", "target": "Borin"},
    ])  # fmt: skip
    run("end_combat")
    run("rest", days=7)
    run("setup_combat", enemies=[{"name": "young adult red dragon", "count": 1}], surprise=False)
    run("spell_resistance", caster="Sela", target="Young Adult Red Dragon", spell="Cone of Cold")
    run("combat_round", actions=[
        {"attacker": "Borin", "target": "Young Adult Red Dragon"},
        {"caster": "Sela", "spell": "Cone of Cold", "target": "Young Adult Red Dragon"},
        {"attacker": "Young Adult Red Dragon", "target": "Borin"},
    ])  # fmt: skip
    run("spell_status", character="Sela")  # the round spent it; a call that rolls nothing keeps the seeds
    run("end_combat")

    # 9. 20th level, the top: one more refused; a spell and a turning spent, and a night's rest gives them back.
    for name in PARTY:
        run("award_xp", character=name, amount=2700000)
    for name in ("Borin", "Sela", "Ilen"):
        run("update_character", ref=name, patch={"level": 20}, reason="20th level")
    run("update_character", ref="Pip", patch={"levels": {"rogue": 4, "fighter": 1, "wizard": 5,
        "arcane trickster": 10}}, reason="20th level")  # fmt: skip
    increase(run, 21, 21, 22, 21, "16th and 20th levels")
    run("set_build", character="Borin", skills={"climb": 23, "intimidate": 23}, feats=BORIN_FEATS)
    run("set_build", character="Sela", skills={"concentration": 23, "spellcraft": 23, "knowledge arcana": 23},
        feats=SELA_FEATS, known={"sorcerer": known(9, 5, 5, 4, 4, 4, 3, 3, 3, 3)})  # fmt: skip
    run("set_build", character="Pip", skills={**pip_skills, "hide": 23, "move silently": 23, "tumble": 23,
        "disable device": 23, "escape artist": 12, "decipher script": 12, "open lock": 15, "search": 10, "spot": 5,
        "listen": 4}, feats=PIP_FEATS)  # fmt: skip
    run("set_build", character="Ilen", skills={"concentration": 23, "knowledge religion": 23}, feats=ILEN_FEATS)
    refused("update_character", ref="Borin", patch={"level": 21}, reason="21st level")
    run("cast_spell", character="Sela", spell_name="Meteor Swarm")
    run("turning_undead", level=20, undead="dread wraith", character="Ilen")
    run("rest", days=1)
    run("cast_spell", character="Sela", spell_name="Meteor Swarm")
    run("get_character", ref="Ilen")
    return said


def increase(run, borin, sela, pip, ilen, reason):
    """The ability increases: Borin's Str, Sela's Cha, Pip's Dex, Ilen's Wis, to these scores."""
    run("update_character", ref="Borin", patch={"ability_scores": {**BORIN, "str": borin}}, reason=reason)
    run("update_character", ref="Sela", patch={"ability_scores": {**SELA, "cha": sela}}, reason=reason)
    run("update_character", ref="Pip", patch={"ability_scores": {**PIP, "dex": pip}}, reason=reason)
    run("update_character", ref="Ilen", patch={"ability_scores": {**ILEN, "wis": ilen}}, reason=reason)


def known(*counts):
    """Sela's spells known, the first `counts[n]` of each level's list in `SPELLS`."""
    return [spell for level, count in enumerate(counts) for spell in SPELLS[level][:count]]


def fight(run, party, enemies, standing):
    """Rounds until no enemy stands: each of `party` standing swings at its target (with its condition, "flanking"),
    or the first enemy standing once that one is down; each enemy standing at its own target, or the first of the
    party standing once that one is down. Who stands is read from each round's status."""
    up = list(party)
    for _ in range(50):
        if not standing:
            break
        actions = [{"attacker": name, "target": target if target in standing else standing[0], **extra}
                   for name, (target, extra) in party.items() if name in up]  # fmt: skip
        actions += [{"attacker": e, "target": t if t in up else up[0]} for e, t in enemies.items() if e in standing]
        out = run("combat_round", actions=actions)
        active = {c["name"] for c in out["status"]["combatants"] if c["status"] == "active"}
        standing = [name for name in standing if name in active]
        up = [name for name in up if name in active]
    assert not standing, f"no end to the fight in 50 rounds: {standing} standing"


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


def test_the_campaign_session_matches_its_golden(seeded_call, srd35_storage, srd35_campaign):
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
