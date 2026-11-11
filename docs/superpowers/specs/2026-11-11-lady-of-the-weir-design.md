# The Lady of the Weir: Delve's sample OSRIC module (design)

2026-11-11. Agreed with the owner in conversation; the calls marked **(Claude's call)** are mine and open to change.

## Intent

Delve's public release (CounterClockTTRPG/delve) needs a sample adventure that a new group can import and play
through in one sitting, and that people can take as a basis for their own modules. The one it has, the Crypt of Saint
Vellis, is thin as a story and written for AD&D 2e, which the public copy doesn't ship. The new module replaces it as
the module the README and INSTALL guide point to.

It should feel like the setting it's set in: Aun, Delve's own world (`docs/settings/aun-bible.md`), in the tone of
early roleplaying and 1970s sword-and-sorcery: concrete, wry, a little cruel, with gods that bargain.

**Success:** a group new to Delve imports it, plays it start to finish in about three to four hours, meets NPCs they
remember, has used every class's tricks at least once, and is surprised by the twist. Someone reading the bundle can
see how a good module is put together and copy the pattern.

## Goals

- **A starter OSRIC adventure** for 4–6 characters of 1st–2nd level, completable in **one session of 3–4 hours**.
- **One outdoor map** as the main stage, and **two small indoor sites of a handful of rooms each** (about 5–6).
- **Maps that look real**: irregular walls, natural cave and bank edges, furniture, rubble, doors where people would
  put them. Not rectangles glued together with corridors.
- **Random encounter tables** by place and time of day, about a third of them non-combat meetings.
- **Memorable NPCs**, each with a want, a secret or a quirk the DM can play at once.
- **A twist**, and **an ending chosen by the players** (three ways out).
- **Something for every class**: undead to turn, traps and locks, an inscription and a scroll, fights, and talk.
- **XP for side quests** as well as OSRIC's XP for monsters and treasure.
- **A small magical reward**: *Eelbite*, a +1 short sword.
- **A cover and NPC portraits**, in one consistent style.
- **English only.** The engine translates on the fly.
- **Licence CC BY 4.0** for the module's text, maps and pictures; the code stays AGPL-3.0.

## Non-goals

- No translations shipped.
- No long campaign or sequel hooks beyond a line or two; it stands alone.
- No changes to the engine. If something in the module can't be expressed in the `.dscn` format, simplify the
  module rather than extend the format (note it for the backlog).
- The Crypt of Saint Vellis isn't deleted: the tests use it **(Claude's call)**.

## Anti-goals (failure even if it "works")

- **No underwater or flooded maps**, no swimming rooms, no water levels. Water is scenery on the outdoor map only.
- **No boxy maps** of rectangles joined by straight corridors.
- **Nothing from a published setting, module or novel**: no names, places, gods or text (the bible's **Never** list).
  No verbatim OSRIC guide prose (its licence allows only monsters, spells and magic items verbatim; Delve's packs
  paraphrase).
- **No high-fantasy register**: no prophecy, chosen ones, or good-versus-evil taken at face value; no modern idiom.
- **No railroad**: the ending must be the players' choice, and talking must move the story as well as fighting.
- **Nothing that can't be finished in an evening**: no sprawling dungeon, no session-long travel.

## The adventure

### Premise

Ambresleigh is an eel-fishing village a day's walk up the Ambre from Hask. It lives under a small god, **the Lady of
the Weir** (a named small god in the bible, jealous of **the Ferryman** of Hask Ford), and leaves offerings at her pool
each new moon. This spring the pool below the weir has turned black, the eels are dying, and three people have
vanished on the river path. **Reeve Haldan** posts a notice at the Drowned Toe in Hask: 50 gp to whoever sets it right.
The campaign starts in early spring 1188 RY, as Aun's campaigns do.

### The truth (DM's)

Every fifty years the Lady takes a mortal spouse: the chosen one lives on as her **consort in the pool**, alive but no
longer human, seen at dusk among the reeds, never coming home (owner's decision). Sorrel was the last; his body lies in
the mound because he tried to leave her, and that is what his ghost can tell. This spring she chose the Reeve's daughter, **Wenna**. To keep her,
Haldan broke the Lady's **offering-stone** at the weir. The Lady weakened and the pool fouled. At the same time **Odo
Tesk**, who leases the weir, pumped the pool down to dig into the old sorcerer-era **Sluice-House** in the bank for
loot. That opened a seal the Lady had kept for centuries. Behind it lay **the Sluice-Warden**, the sorcerer-era
overseer of the works, buried alive with his labourers when the Lady first claimed the river and risen as a ghoul. Free
again, he has been taking people from the river path at night: **the three vanished are among his zombies now**, and at
least one is recognisable (the miller's son), which gives the DM a grief beat. His old labourers are the skeletons.
**(Claude's call.)**

Everyone blames Odo. He is greedy, not the cause. The twist is that the man who hired the party caused it.

### The three endings

1. **Restore the stone** (mend or replace it, with an offering): the Lady recovers, seals the Warden and his dead again
   (those still standing fall still), and takes Wenna as her consort as promised. This ending does not count as
   "Wenna alive and free".
2. **A new bargain** with the Lady at the pool: another price for Wenna, such as a secret, a life's service, a toe from
   each villager, or Odo. The DM sets the price from what the party has learned.
3. **Let the Lady fade**: put down the Warden and his dead by force, and leave the stone broken. The pool
   becomes ordinary water, Wenna is free, the village loses its god, and the Ferryman downriver grows stronger.

### Places

**The Ambresleigh valley (outdoor map, the main stage).** The village (a dozen houses, the Reeve's hall, the eel-smoke
sheds), **the mill** on its race, **the weir** with the blackened pool and the broken offering-stone, the **reed marsh**,
the old **Thaumarch road**, a ruined **watchtower**, **the burial mound** where Sorrel lies, **the ford** where smugglers
cross, and **Weirholt** and the **Sluice-House** marked for their own maps. About a mile or two across: walkable in an
hour or two of game time, so travel never eats the session.

**Weirholt (indoor, about 5–6 rooms).** Odo Tesk's small fortified manor: a walled yard and gatehouse, a hall where he
dines guests, his study (a locked desk; a locked strongbox with the leases, coin and his scrolls), the kitchen, a guard
room for his two men-at-arms, and a cellar with the pumps and the tunnel he is cutting.

**The Sluice-House (indoor, about 5–6 rooms, dry).** A vaulted works cut into the riverbank beside the weir, emptied
by Odo's pumping: a dry intake channel (the way in, behind a locked iron grille), a valve gallery of rusted Thaumarch
machinery (the trap), a hall of the drowned dead (skeletons and zombies to turn), an inscription in the sorcerer
tongue (for a magic-user to read: it names what is sealed and how the Lady bound it), and the **seal chamber** with the
broken seal and the Sluice-Warden himself: a ghoul, with a few more hit points than the book's and the Warden's
keys and chain, the module's toughest fight, sized for a 1st–2nd level party with a cleric. Stone floors throughout; nothing is underwater.

### NPCs

| NPC | Where | What they want, hide or do |
|---|---|---|
| **Reeve Haldan** | the Reeve's hall | Hires the party. Loves his daughter; broke the stone. Lies well until cornered. |
| **Wenna** | the hall, later the pool | Chosen by the Lady. Half-willing: she has heard the Lady sing and isn't sure she wants rescuing. |
| **Odo Tesk** | Weirholt | Charming, greedy younger son of House Tesk (Hask river trade). Wants the Sluice-House loot. Dines the party and tries to hire them away. |
| **The Lady of the Weir** | the pool at dusk | A small god: proud, cold, playful, bound by her bargains. Bargains rather than fights. |
| **Sorrel's ghost** | the burial mound | The Lady's last spouse, fifty years dead. Only talks. Knows what the Lady is and what the "marriage" costs. |
| **Brother Aldo, a Sunward friar** | random, then the shrine | Wants to burn the Lady's shrine (the Sunward Church calls small gods demons). Polite and stubborn; ally or menace. |
| **Pim, a pedlar of charms** | random, the road | Sells "Lady's blessings" of river-glass. A harmless fraud; trades a true rumour for a drink. |
| **The miller (Wenna's aunt)** | the mill | Knows about the betrothal; tells only once trusted. |
| **Odo's surveyor** | random, the weir | Honest, with a grudge against Odo; can be bribed for the Sluice-House key. |
| **The eel-catcher's child** | random, the reeds | Lost; saw "the wet men" walk out of the Sluice-House at night. |

The NPC names here other than the bible's are **(Claude's call)**; the builder may change them, keeping them Aun-like
and original. Each NPC gets OSRIC stats where it may fight (by `monster:` reference with overrides where it fits, in an
`osric` stats block), and a disposition.

### Something for every class

- **Clerics:** skeletons and zombies in the Sluice-House to turn; a ghoul at the seal; Sorrel's ghost (not hostile).
- **Thieves:** the locked desk and strongbox at Weirholt, the locked iron grille, the valve trap, and listening at
  Odo's doors.
- **Magic-users:** the inscription; Odo's scrolls (one with a 1st-level magic-user spell the party may learn).
- **Fighters:** the smugglers, Odo's men-at-arms if it comes to blows, and the dead.
- **Everyone:** the Lady, and the non-combat meetings.

### Random encounters

Tables by place and time of day (the format's `encounters` with a `kind` and the place they belong to, as Delve's
modules now place their wandering tables): **the road**, **the reeds**, **the river path by night**, and **the
Sluice-House**. Starter-level OSRIC creatures (giant frogs, stirges, wild dogs, smugglers, skeletons, zombies), with
about a third of the rows non-combat: Pim, Brother Aldo, the lost child, Odo's surveyor, and **the heron** that watches
the party (the Lady's eye; kindness to it is remembered at the bargain). A check every so often, as OSRIC has it
(Delve's `encounter_check` does the dice).

### XP for side quests

On top of OSRIC's XP for monsters and treasure, shared by the party:

| Side quest | XP |
|---|---|
| Bring the lost child home unharmed | 100 |
| Lay Sorrel's ghost to rest (find his ring, return it to the mound) | 150 |
| Talk Brother Aldo out of burning the shrine, or recruit him against the dead | 75 |
| Keep Odo from looting the seal chamber without killing him | 100 |
| Settle the Lady's matter (any ending) | 300 |
| …with Wenna alive and free | +150 |

Aim **(Claude's call, after the builder check)**: a good share of the way to 2nd level, with a thief or cleric who
finishes the side quests able to reach it. OSRIC's 2nd level costs 1,250–2,400 XP, so reaching it for all would take
treasure far beyond a starter's; the treasure stays small rather than chasing the level. The side quests go in the format's `quests` with their XP in
the text.

### Treasure

*Eelbite*, a +1 short sword from the Lady's hoard (given at a bargain or found in the seal chamber), plus modest coin
and goods for OSRIC's XP for treasure: Odo's strongbox, the smugglers' cache, the Sluice-House's old fittings. Kept
small, as a starter's.

## Pictures

A **cover** and **portraits** of the Reeve, Wenna, Odo, the Lady, Sorrel's ghost, Brother Aldo and Pim, in one
consistent style, made with Delve's own picture tools (Replicate). The model must allow its output to be published
under CC BY 4.0: **check the model's terms before generating anything**. FLUX.1 [schnell] (Apache-2.0) is the safe
default; a pro model only if its terms grant the output rights. The style is **(Claude's call)**: painted, muted, in
keeping with Aun's tone, not a brand-named style. Maps are drawn by the map language, not generated pictures.

## How it gets made

- **The format:** a `.dscn` scenario bundle (`docs/maps/scenario-format.md`), as a directory form in the repo, with
  `system: osric`, `setting: aun`, `license: {spdx: CC-BY-4.0}`, authors credited, the OSRIC third-party notice in
  the text (the same as `OsricRuleset.notice`), and a note that the pictures were made with the named model.
- **Maps** in the DungML map language (`docs/maps/dsl*.md`), drawn by hand for an organic look: study the outdoor
  samples (`tests/fixtures/samples/outdoor_glade.dmap`, `river_crossing.dmap`, `overland.dmap`) and the map-design
  guidance in `src/delve/modules/books/prompts/design-map.md`. Render each and look at it before calling it done.
- **Keyed text** for every numbered area of each map; player-visible text separate from DM sections, as the format
  has it. The writing follows the bible's **Tone and writing**.
- **Where it ships:** in the repo beside the old sample, e.g. `samples/lady-of-the-weir/` **(Claude's call; the
  builder picks the exact path)**. The public export (`~/claude/delve-public-tools/export.sh`) builds a ready `.dscn`
  zip from it into the tree, and the README (in the repo) and INSTALL guide (in `delve-public-tools/INSTALL.md`) point
  to it in place of the Crypt. It goes out with the next public release, which is pushed only after the owner says so.
- **Canon:** the module is self-contained and doesn't change the Aun bible or pack **(Claude's call)**. It must not
  contradict them: the Lady and the Ferryman are the bible's; Ambresleigh sits on the Ambre upriver of Hask without
  clashing with places the bible already sets there (the Pale Tower, a day upriver).
- **Time of day:** the engine's wandering tables have no time filter, so "the river path by night" is its own table,
  named and noted as night-only.
- **Checked by play (owner's decision):** import it into a scratch Delve (never the live one's data) as an OSRIC/Aun
  campaign and play it through once with Delve's Claude DM, start to one ending; then replay only the finale from a
  saved point before it for each of the other two endings. Fix what the DM stumbles on. A test imports the bundle and checks it
  loads with its maps, keys, NPCs, encounters and quests.

## Left to the builder

The NPCs' exact stats, the room-by-room contents within the shapes above, the encounter odds, the treasure amounts,
the exact map layouts, names not given here, the inscription's wording, Odo's scroll's spell, the picture prompts, and
the exact repo path.
