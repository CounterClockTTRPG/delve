---
title: Reading a monster entry
source: gmg
section: "2.10.1"
---
`monster_lookup` returns OSRIC's entry for a creature. The fields:

- **Frequency:** unique to common; change it freely.
- **Number encountered:** for wilderness encounters only. In dungeons, use the dungeon tables' numbers.
- **Size:** tiny (under 3 ft), small (3–5 ft), medium (5–7 ft), large (7–19 ft), huge (20–39 ft), gigantic (40 ft and up). Size governs spacing, weapon damage against it (tiny uses the small column), unarmed combat, and who can shoot over it.
- **Move:** feet per round; flyers also have an aerial agility class.
- **Armour Class:** "5 [15]", descending then ascending. It need not be armour; hide or speed counts.
- **Hit Dice:** d8s unless stated. "3−1" is 3d8−1; "2+2" is 2d8+2; every die gives at least 1 hp. "1d4 hit points" or "1d8−1 hp" means less than a full die, which lets high-level fighters strike several times a round. "1–4" means individuals vary from 1 to 4 HD.
- **Melee attacks:** a creature that attacks in melee cannot also use a ranged attack that round unless listed as special.
- **Senses:** standard, keen (may notice by smell or sound, the DM decides), infravision, sixth sense (chance to feel scrying), and detect invisible (a percentage chance; it lets the creature target an invisible foe, still at −4). Monsters of 7+ HD with high Intelligence can detect invisible creatures on a d100 roll that grows with HD and Intelligence.
- **Lair chance:** wilderness only; the chance the party has found its home.
- **Intelligence:** from non- (0) up to genius and beyond; mindless monsters save on their own table and never check morale.
- **Morale:** a percentage for `morale_check`; N/A means no checks.
- **Loot:** its loot class (see treasure).
- **Experience:** base plus per hit point (`xp_earned`).
