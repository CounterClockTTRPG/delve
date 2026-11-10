---
title: Healing, subdual and temporary damage
source: pg
section: "1.6.6.1"
---
**Natural healing.** A character recovers 1 hp per day of rest without interruption.

- A character with a Constitution hit point penalty must first rest as many days as the penalty before healing starts.
- A character with a Constitution bonus who rests a full week regains, during the second week, extra hit points equal to that bonus.
- Four weeks of rest restore anyone to full hit points, however hurt.

Remember that a character who fell to 0 or below also needs a week of rest before strenuous action, even after magical healing.

**Subdual damage.** A player may choose to beat a foe down rather than kill: half the damage dealt is real, half subdual. Subdual damage returns at 1 hp per hour. A creature dropping to 0 or below only because of subdual damage is knocked out, not dying. If the real damage alone reaches its hit points, it is treated as normal damage: the blows were harder than meant. Only humanoids and some special creatures (dragons, notably) can be subdued; tourney fighters may agree beforehand to accept defeat this way.

**Temporary damage** comes from unarmed combat and heals much faster, 1 hp per round. If it takes a creature to 0 or below, the creature is unconscious until it recovers. Unarmed attacks cannot be declared as subdual; their temporary damage serves instead.

Healing spells and potions (`spell_lookup`, `item_lookup`) are instantaneous and several can be stacked on the same creature, even in the same segment.
