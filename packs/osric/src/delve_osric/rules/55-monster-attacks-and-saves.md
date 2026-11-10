---
title: Monster to-hit and saving throws
source: gmg
section: "2.1.2"
---
**Monster attacks.** Monsters have no classes; they hit by Hit Dice. The monster to-hit table runs from under 1−1 HD up to 24+ HD; read the row for the monster's Hit Dice and the column for the target's Armour Class, and roll a d20 that meets or beats it. A 1 HD monster needs 10 against AC 9 [11] and 19 against AC 0 [20]. The table repeats 20 over several AC steps before climbing again, as the character tables do. For ascending AC, the monster's Base To-Hit Bonus by Hit Dice works with the formula (see Armour Class). Delve's tools read the table.

Hit Dice with a plus count up a row: a 1+1 HD creature uses the 1+ row, and 3+3 uses the 2–3+ row.

**Monster saves.** Monsters save by Hit Dice on one of two tables, with the same five categories as characters (aimed magic items; breath weapons; death, paralysis and poison; petrifaction and polymorph; spells).

- Any monster with Intelligence above 0 uses the normal table.
- Mindless (Intelligence 0) monsters use their own table, which matches the normal one at low Hit Dice but improves more slowly, except against death, paralysis and poison where the two agree.
- Hit Dice are read as "up to": a 1+1 HD monster counts as 2 HD.

`saving_throw` reads both tables. Monster entries (`monster_lookup`) may add their own resistances: magic resistance, immunities, or bonuses against particular effects.

**NPCs with classes** attack and save as their class and level, like player characters. Which row an ordinary zero-level person uses is for the DM to decide; the lowest Hit Dice row is the natural choice.
