---
title: Character classes
source: pg
section: "1.3"
---
OSRIC has ten classes: the fighter, paladin and ranger; the cleric and druid; the magic-user and illusionist; the thief, assassin and monk. Each has minimum ability scores, a hit die, an alignment requirement, allowed armour and weapons, weapon proficiencies, starting gold, and level tables for experience, saving throws, to-hit and (for casters) spells. All of that is in `class_lookup`; `create_character` fills saves and to-hit from it.

In brief:

- **Fighter** (d10): any armour, any weapon, the best to-hit and the most proficiencies; may specialise. Extra attacks at higher level.
- **Paladin** (d10, lawful good only) and **ranger** (d8, any good): fighter-types with extra powers and strict requirements.
- **Cleric** (d8): any armour, blunt weapons only; divine spells and turning undead.
- **Druid** (d8, neutral only): leather armour and wooden shields; nature spells.
- **Magic-user** and **illusionist** (d4): no armour, a handful of weapons, spellbooks.
- **Thief** (d6, neutral or evil) and **assassin** (d6, evil): light armour, thief skills (`skill_check`); assassins also kill by surprise.
- **Monk** (d4, lawful): no armour, unarmed fighting, some thief skills.

A prime requisite of 16 or more usually earns 10% bonus experience; some classes need two or three such scores, and some get no bonus.

**Optional: below the minimums.** The DM may allow a class whose minimums the character misses, at a cost to all experience earned: 10% short of one score, 15% for two, 20% for three. The penalty stops once the scores reach the minimums.
