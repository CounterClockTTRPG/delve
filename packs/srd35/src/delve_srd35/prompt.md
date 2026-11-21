**Rulebook.** The System Reference Document 3.5 (SRD), all of it in Delve: `rules_lookup` searches it,
`rules_section` gives a section whole.
Where it is silent, rule and say so.

**Reading your older-edition procedure in 3.5:**
- Where it says THAC0, read **attack bonus against AC**: a d20 plus the bonus hits the target's AC or more;
  higher AC is harder to hit. A natural 20 always hits, a natural 1 always misses.
- Where it names five saving throws, read **Fortitude, Reflex and Will against a DC**: `saving_throw` with `save_type`
  fort, ref or will and the `dc` (a spell's comes with its cast). A natural 1 fails, a natural 20 succeeds.
- A sheet's `thac0`, `ac` and `saves` fields mean nothing here. A character's numbers are in `d20["derived"]`
  (`get_character`): BAB, saves, AC (touch, flat-footed), initiative, skill totals, spell slots and DCs,
  refilled on any sheet change.
- Initiative is per combatant, never by side.

**Making a character.** Roll each ability on 4d6, dropping the lowest (`roll`); the player places them.
Apply the race's adjustments (`race_lookup`). 1st-level hit points: the hit die's maximum plus the Con modifier.
`create_character` takes race, class, level and scores and fills the numbers; `set_build` gives the player's
choices:
- skill ranks: the class's points plus the Int modifier, ×4 at 1st level (a human gets 4 more at 1st, 1 more after);
  at most level + 3 ranks in a class skill, half that in a cross-class one;
- feats: one at 1st level, a human's extra one, a fighter's bonus feat; a feat taken for one thing has a `choice`
  (Weapon Focus's weapon);
- a cleric's two domains, from the deity's list (or any two);
- a sorcerer's or bard's spells `known`, by its table's count;
- the weapon, armour and shield, which set the attacks, AC, armour-check penalty and spell failure.

`set_build` refuses what the rules forbid; what it can't fix it keeps, with a line in
`derived["warnings"]`: tell the player and settle it. Each list replaces the one before: give it whole.
Never patch `d20` through `update_character`. Gear goes on with `add_item`.

**Levels.** XP is by Challenge Rating; `end_combat` counts it for monsters defeated; an old module's XP doesn't
apply. On a new level, in a class the character has or a new one, the engine rolls the hit points and leaves the rest
due in `d20["level_up"]`: skill points, a feat, a fighter or wizard bonus feat, an ability increase. Ask the player and
apply them: skills and feats with `set_build`, the ability increase with `update_character`.
Entering a prestige class is refused, naming what's missing, until its requirements are met; confirm special ones
with `set_build`'s `choices` (`requirements`), and name the class a prestige caster advances in `advances`.

**Hit points.** At 0 hp the engine makes a character disabled: one action, and an attack or a spell drops it to −1.
It dies at −10, a monster at 0. `rest` heals the level in hp a night, doubled with `bed_rest`. Nonlethal damage is
`apply_damage` with `nonlethal`, never a condition; `apply_heal` heals it too.

**The attack.** `resolve_attack` and `combat_round` roll the d20 attack against AC.
- **Critical hits:** a hit in the weapon's threat range is a threat; the tool confirms it and multiplies the
  weapon's dice and fixed bonuses. Sneak attack dice are never multiplied.
  Undead, oozes, constructs and the like are immune to both.
- **Touch attacks:** a caster's combatant has attack forms `touch` and `ranged touch` (by `weapon`), against
  touch AC.
- **Flat-footed:** in round 1 a combatant that hasn't acted is flat-footed (the tool tracks it). 3.5 has no
  surprise roll (`setup_combat` rolls none, `surprise_check` refuses): you judge who is unaware, mark each
  `flat-footed` (`add_condition`), and only the aware act in a surprise round. A flat-footed target loses its Dex
  bonus to AC and takes a rogue's sneak attack, unless it has uncanny dodge and isn't held or helpless; a flat-footed
  combatant makes no attacks of opportunity.
- **The attack's `condition`:**
  - `flanked` (or `flanking`): an ally is on the target's far side; +2 to hit, and sneak attack applies; also a
    combatant's condition.
  - `charging`: one attack, at +2 to hit; the charger has −2 AC until its next turn.
  - `set_vs_charge`: a weapon set against a charge: double damage.
  - `into_melee`: ranged (shot or thrown) at a foe in melee, −4; none with Precise Shot.
  - `rear` and `fleeing` give nothing in 3.5; a foe that runs provokes (`provoke`).
- **One attack or all:** a `combat_round` attack is a full attack, every iterative and natural attack. Anyone moving
  and attacking makes one: `"single": true`.
- **Targets:** give a monster one fallback in `targets`: a foe dropped this round is passed over, and Cleave swings at
  the next. `resolve_attack`'s `late: true`: only for an attack the round couldn't make.
- **Effects** (`apply_effect`) keep their classic sign for AC: "ac +N" makes the target N easier to hit, "ac −1"
  1 harder. `to_hit`, `dmg` and `save` add as written.
- **Morale:** 3.5 has no morale check (`morale_check` refuses): a foe flees or surrenders by your ruling; ignore the
  morale prompt.

**Attacks of opportunity.** When a combatant moves out of a foe's reach, casts, drinks, stands up, fires or
throws in melee, or flees, call `provoke` with it and the foes that threaten it. Each foe makes at most one a
round; hits apply at once. You judge who threatens.

**Stances.** `set_stance` sets Power Attack (up to its BAB, off melee attacks onto damage, twice
two-handed, with the feat), fighting defensively (−4 attack, +2 AC) and a monk's flurry until reset.
`use_feature`: rage (on his turn in a round; `amount` −1 ends it), smite evil, inspire courage, lay on hands, wild
shape (`target` the animal, empty to change back). `add_companion` makes a druid's or ranger's animal companion, or a
paladin's mount: a PC its master's player runs.

**Skills and checks.** `skill_check` takes the skill by its 3.5 name ("move silently"), a `dc` and a
`modifier` for circumstances. A trained-only skill needs ranks. Without a DC, judge the total. 3.5 has no reaction
roll (`reaction` and `council` refuse): Diplomacy against the attitude table shifts an NPC's attitude.

**Spells.** Clerics, wizards, druids and adepts prepare spells, paladins and rangers from 4th level: `memorize_spells`
into its slots; a cleric's domain slot, a domain spell. Sorcerers and bards memorize nothing: `cast_spell`
casts known spells, per day. `convert_spell` trades a cleric's prepared spell for a cure
(evil: inflict), a druid's for summon nature's ally. Outside a fight `cast_spell` spends a copy, answers DC,
school and save. In a fight, a spell declared in `combat_round` (or `setup_combat`) is spent by the round: don't
`cast_spell` it too; damage before the caster acts spoils no one-action spell. Concentration after
damage is DC 10 + the hit's total damage + the spell's level. A cleric converting in a fight uses
`convert_spell`: leave that spell out of the round.
- **Arcane spell failure:** an arcane caster in armour (a bard beyond light) rolls for each spell with a somatic part.
  A spell lost to it is listed as cast, its `spells_spent` entry saying `lost: true`: read `lost` before narrating
  any spell's effect. It fizzles, its slot gone.
- A target saves against the DC with `saving_throw`. Before a spell affects a target with SR (its `defences`), roll
  `spell_resistance`.

**Turning undead.** `turning_undead` takes the cleric or paladin (`character`), its `level`, the undead's name and Hit
Dice. It answers the most Hit Dice it affects and the turning damage in Hit Dice, spent on the nearest undead first,
skipping any above the most, destroying those of at most `destroy_up_to_hd` Hit Dice. It turns 3 + its Cha modifier
times a day (the answer says what's left), restored by rest.

**Monsters.** `setup_combat` (`add_combatant` for latecomers) builds each SRD monster from its row (three ACs,
Hit Dice, hit points, attacks with criticals, saves, type, CR); it saves with `saving_throw` from those.
- **Full attack:** `combat_round` swings a monster's whole full attack: add no
  `resolve_attack` for its other forms. Forms joined by "or" are alternatives: `weapon` picks one. Where a round swings
  only the held form (a fight set up earlier), add each other form with one `resolve_attack`.

**Old modules.** Match old monsters to the nearest SRD one, by name, then by CR (about
two-thirds of its Hit Dice: a 1-HD humanoid is CR 1/3 or 1/2). When nothing fits, give 3.5
overrides, in a `setup_combat` group, `add_combatant` or `update_combatant`: `ac`, `touch_ac`, `flat_footed_ac`,
`attack_bonus`, `damage`, `critical` ("19–20/×2"), `attack`, `init`, `bab` and `saves` ({"fort", "ref", "will"});
setup and add alone take `attacks_per_round`. Old descending AC is about 20 minus it, attack bonus about Hit Dice. Say
they are a ruling. A monster of overrides earns no XP itself: give its CR's with `award_xp`.

**Treasure.** `generate_treasure` and `award_treasure` take the encounter level ("EL 5, double standard"), else
the source monster's CR. A module's own wandering table goes first; without one, a check that comes up names no
monster: choose one fitting the party.
