---
title: Weapon proficiency
source: pg
section: "1.0.1"
---
Each class starts with a set number of weapon proficiencies and gains more at fixed levels. A proficiency covers one entry on the weapons table: "longsword", not "swords". Attacking with a weapon the character is not proficient in applies the class's non-proficiency penalty to the to-hit roll.

| Class | Starting slots | Penalty |
|---|---|---|
| Fighter | 4 | −2 |
| Paladin, ranger | 3 | −2 |
| Assassin | 3 | −3 |
| Cleric | 2 | −3 |
| Druid | 2 | −4 |
| Thief | 2 | −3 |
| Monk | 1 | −3 |
| Magic-user, illusionist | 1 | −5 |

The levels at which slots are added are in `class_lookup`; Delve folds the penalty into the character's to-hit when a weapon is not in `weapon_profs`.

Proficiency never overrides a class's list of allowed weapons: a cleric with a sword is breaking a class rule, not merely taking a penalty. Brawling with fists, feet or a pommel needs no slot. A weapon whose Strength requirement the wielder fails is used as if non-proficient.

OSRIC has no nonweapon proficiencies; ordinary tasks are handled with `ability_check` or a thief's `skill_check`, or simply succeed.
