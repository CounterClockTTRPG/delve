**Rulebooks.** OSRIC 3.0's Player Guide (`pg`) and Gamemaster Guide (`gmg`). Delve carries their monsters, spells
and magic items as printed, and their rules as its own summary, section by section: `rules_lookup` searches it and
`rules_section` gives a section whole, by its title or number ("Surprise", "1.6.1.1"). When a rule isn't there, make
a ruling and say that it is one.

**Making a character.** Roll the abilities with the dice, then apply the race's adjustments and check its ranges
(`race_lookup`) and the class's minimum scores (`class_lookup`). A demi-human may take only its race's classes and
multi-classes, and stops at its level limits; humans don't multi-class. Hit points are the class's hit die with the
Constitution adjustment; starting gold is the class's. A thief, an assassin or a monk takes its skills from the
class's table at its level, with the race's adjustments, into `skills`. `create_character` fills the saves and THAC0
from the class tables. At level-up, check the race's limit before raising the level.

**No nonweapon proficiencies.** Resolve a task with `ability_check`, or a thief's `skill_check`; `proficiency_lookup`
has nothing for OSRIC. Weapon proficiencies (`weapon_profs`) still count: the tools fold a class's non-proficiency
penalty into THAC0.

**Monsters** are OSRIC's (`monster_lookup` gives the Gamemaster Guide's entry and its text). Armour Class reads
"5 [15]": descending, ascending in brackets. Experience reads "135 +4/hp": a base, and more for each hit point; the end
of a fight counts it for the monsters defeated (`xp_earned`). Morale is a percentage (65): when a check is due, call
`morale_check` with it as the rating (a d100, holding at or under it). Mindless monsters, most undead among them, never
check.

**Initiative** is a d6 a side, low first: the segment of the round the side acts in; a new campaign rolls it so.
Weapon speed doesn't add to it. A spell starts in its caster's segment and goes off after its casting time (Fast at
once); a hit before then spoils it.

**The tracker keeps the book's ways:** a natural 20 or 1 on an attack is no certain hit or miss, a natural 1 on a save
always fails, the unconscious bleed from 0 hp and die of any more damage, a fleeing foe is attacked at +4, and a
fighter, paladin or ranger gets its class's attacks per round. `award_xp` adds the prime-requisite bonus itself.

**Monsters save** on OSRIC's own tables by their Hit Dice, the mindless on theirs; `saving_throw` reads them.

**Turning undead** goes by the undead's Type, 1 (skeleton) to 13 (fiend): name the undead in `turning_undead`.

**Reaction** is a d100 (`reaction`), read against OSRIC's bands from very hostile to very friendly.

**Encounter checks** come every third turn underground at 1 in 6, and twice a day and once at night outdoors at
1 in 12 (`encounter_check`). When one comes, OSRIC's tables say what: underground by the dungeon level, outdoors by the
terrain's kinds of creature, in town by day or night. A module's own wandering monster table goes first, and
`encounter_check` rolls it itself where the module places one.

**Treasure** goes by OSRIC's loot classes as the bestiary prints them: an Individual on each creature, a Hoard in its
lair (`in_lair`), a Cache hidden away. Pass the loot line as the entry gives it ("Individual 3", "Hoard 2"); one
with both, roll each group on its own.

**A turn** is 10 minutes.
