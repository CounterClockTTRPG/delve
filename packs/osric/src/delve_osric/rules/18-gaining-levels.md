---
title: Experience and gaining levels
source: pg
section: "1.5.6"
---
Characters earn experience points (XP) three ways:

- **Treasure:** 1 XP per gold piece of coin, gems and jewellery, counted only once the party gets it safely back to a settlement. Income that wasn't won adventuring (taxes from a holding, say) gives none.
- **Magic items:** a kept item is worth a tenth of its gold value in XP (potions half); a sold one counts as money at full value.
- **Monsters:** defeating them, by killing, capture or any other way of overcoming them. `xp_earned` counts it at the end of a fight from each monster's entry ("135 +4/hp").
- **Missions:** a DM award when gold and monsters don't reflect what the adventure demanded.

A prime-requisite bonus (usually 10%) adds to everything earned. Multi-classed characters split every award; dual-classed characters put it all into the new class.

When the total reaches the next level on the class table (`class_lookup`), the character qualifies but must **train** before gaining it: 1d3 weeks and a fee of 1,500 gp per level the character already holds (1,500 gp to reach 2nd, 3,000 gp to reach 3rd, and so on). The time only matters in a hurry; otherwise it is board and lodging.

On levelling, roll the class's hit die with the Constitution adjustment (minimum 1 hp), until the class switches to fixed hit points at high level (which take no Constitution bonus). Check the ancestry's level limit first (`race_lookup`).
