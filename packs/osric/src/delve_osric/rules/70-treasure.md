---
title: Treasure and loot classes
source: gmg
section: "2.12"
---
Treasure is maps, coins, gems, jewellery and magic items. Not every challenge pays: most wandering monsters carry nothing, and many traps and tricks guard nothing. An intelligent monster carries what it may need quickly and hides the rest.

**Loot classes.** Each monster entry names a loot class (`monster_lookup`), and `generate_treasure` rolls it:

- **Individual** classes: a few coins carried by each creature (for example 3d8 cp apiece).
- **Hoard** classes: the lair's treasure (`in_lair`).
- **Cache** classes: valuables hidden away.

For a class, go down its lines in order and roll d100 for each; at or under the listed chance, that kind of treasure is there in the listed amount. Every line is rolled whatever the earlier ones gave, so a hoard can hold several kinds, or nothing at all.

**Unowned treasure**, belonging to no monster, rolls on d100 by dungeon level: 1,500 cp, 750 sp, 250 gp or 100 pp per level, 1d3 gems or one piece of jewellery per level, or a magic item (1d2 below level 6).

**Judgement over dice.** Treasure should match the risk; trim a fortune rolled for a sickly kobold. Shallow levels should mix copper and silver in with gold (a roll of 500 gp on level 2 could be paid as 10,000 cp, 2,000 sp and 200 gp); deeper ones run richer. Coins are heavy, so what to carry becomes a real choice; old or foreign coins that must be changed at a loss are a reason to visit a city.

**Gems** roll d100 for value: ornamental (base 10 gp), semi-precious (50), fancy (100), precious (500), gem (1,000), or on 00 a jewel (5,000), each varied by its own dice. **Jewellery** rolls type and material together. **Maps** are hand-placed, never random, and may point to treasure, a lair or a deadly trap.
