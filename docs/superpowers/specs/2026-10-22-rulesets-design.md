# Rulesets: looking up a ruleset's spells, monsters, items and tables

Date: 2026-10-22. Status: design. Backlog Features 29, on master after "Open fixes and PC names" (delivered
2026-10-22, 4ff328c).

## Intent

Today only the DM reads the ruleset's reference, through its lookup tools (`delve.dm.tools.lookups`). A player who
wants to know what *Web* does, or which wizard spells belong to the school of Alteration, has to ask the DM. ttrpg2 had
a Reference page whose lookups the owner used: Monsters, Spells, Classes, Items, Ability Scores, Proficiencies and
Turning Undead. Delve should have the same lookups, arranged around Delve's own term **ruleset** (glossary: a campaign
is set up from a module, a ruleset, a setting and house rules).

There are two kinds of lookup, in the owner's words: **"check details of a spell, item or monster"** (one entry,
read in full) and **"check which spells are available e.g. in a school"** (a list narrowed by category).

## Owner decisions (2026-10-22)

1. **A Rulesets area**, a new item in the main navigation. Inside it, each ruleset has **structured subsections**.
   The area can be completed later with other rules (more subsections, or a second ruleset).
2. **The subsections are those of ttrpg2's Reference page:** Spells, Monsters, Items, Classes, Ability scores,
   Proficiencies and Turning undead. The owner used all of them.
3. **Greyhawk and Lore Facts are not part of it.** They belong to the setting, not the ruleset (the Settings area
   already has them).
4. **Monsters are for the owner and organisers only.** No one else reaches the Monsters subsection, a monster's
   page, a monster in a search result or a monster's link. The test is the organiser role, not having a seat: the
   owner has a seat at every table, and a seat made an organiser keeps its rights (my reading).
5. **Spells, items, classes, ability scores, proficiencies and turning undead are for every seat**: they are the
   players' books.
6. **House rules' homebrew is shown beside the book's entries**, marked as a house rule. It follows the campaign's
   choice of house rules, not every house rule on the install.
7. **No links from the sheet or the story to entries, and no panel on the play screen.** A player who wants to read
   *Web* goes to the Rulesets area, or asks the DM for a summary.
8. **A player reaches Rulesets through a link in the play screen's header that opens a new tab.** Today a seat's
   browser is held to its table (`SeatsStayAtTheirTable` in `web/src/App.tsx` sends every other path back to
   `/play/{campaign}`, and a seat has no navigation and no Ctrl K). That rule is loosened for the Rulesets area only:
   a seat may open `/rulesets/...` and finds there the ruleset's pages, their search and a way back to its table,
   and nothing else of the app.
9. **A house rule's `## DM Notes` section is never shown to a reader without the organiser role.** The rest of the
   rule (description, mechanics, rarity and value) is shown. Every homebrew item the campaign chose is listed for its
   seats, whether or not the party has found it, just as the book's magic items are.

## Goals

- **Rulesets** (`/rulesets`) lists the installed rulesets. Today there is one, AD&D 2nd Edition (`adnd2e`). The page
  still shows the list (one card) rather than jumping straight in, so a second ruleset changes nothing (my call).
- **A ruleset's page** (`/rulesets/adnd2e`) shows its subsections as cards, each with a line saying what it holds and
  how many entries (ttrpg2's Reference page did the same). A seat doesn't see the Monsters card.
- **Each subsection is a list with its own filters**, kept in the address (`?q=…&school=…`), so a filtered list can be
  linked, reloaded and reached with Back. The filters come from the data, not from a hand-kept list:
  - **Spells:** name, caster (wizard, priest, or either), level, school. A row shows name, caster, level, school.
    The store has no priest spheres: priest spells carry school names too, as ttrpg2's filter used them. `caster` is
    in mixed case (`wizard`/`Wizard`), so compare it without case. `school` holds compound values ("Alteration/
    Necromancy", "Enchantment, Necromancy"), so the filter splits them into single schools and a spell shows under
    each of its schools. A spell for both casters is two rows, and 57 names occur more than once, so an entry's
    address is its id (stable, from the snapshots), not its name.
  - **Monsters:** name, size, alignment, terrain, tag. A row shows name, size, alignment, HD, XP. The raw columns
    can't be dropdowns as they stand (`size` has 1,231 distinct values such as "M (6' tall)", `climate_terrain` 1,393,
    `alignment` 185), so `delve reference build` normalises them into filter columns: size to T/S/M/L/H/G, alignment
    to the nine alignments plus "any" and "other", terrain to a short list of terrain words (my call). Tags come
    from `monsters.categories` (a JSON list, on 3,338 rows). Soft-deleted rows (`deleted_at`) stay hidden, as
    `SqliteReference.monster()` hides them.
  - **Items:** name, type, rarity, from `adnd_items`, which holds both mundane equipment and magic items (about 5,300
    of its 5,653 rows are magic: Wondrous Item, Magic Weapon, Potion & Oil, Ring…). A row shows name, type, cost,
    weight. `osric_magic_items` (one JSON row of OSRIC random-treasure tables) is not shown: it belongs to another
    ruleset and is the DM's treasure tool (my call).
  - **Classes:** the 2e classes (`adnd_classes`), each with its page.
  - **Ability scores:** the six abilities, each a table by score (`adnd_ability_scores`, its columns and notes).
  - **Proficiencies:** by group, with name, slots, relevant ability, check modifier and the class crossover table.
  - **Turning undead:** the one table (DMG Table 47), with ttrpg2's note that paladins turn as priests two levels
    lower.
- **Each entry has a page of its own** with a stable address to share: a spell's full block (level, school, range,
  components, casting time, duration, area, save, description, source and page), a monster's full stat block, an
  item's stats and text, a class's progression (THAC0, saves, spell slots, XP by level).
- **Search across a ruleset**, with a box on the ruleset's page and, for the owner and organisers without a seat,
  through the command palette (Ctrl K). Seats don't get the palette (decision 8). It finds entries by name in every subsection the reader may see. A reader without the
  organiser role never gets a monster back.
- **House rules beside the book** (decision 6). A house rule of kind `item` appears in Items and one of kind `class` in
  Classes, marked "House rule" and opening the rule's text without its `## DM Notes` section (decision 9; the
  server cuts it, not the page). A house rule of kind `race` appears in a **Races**
  subsection. With no book races in the reference store, that subsection appears only when a house rule supplies
  races (my call; see "Left to the builder"). "The campaign's choice" means:
  - **a seat** sees the house rules its campaign was set up with;
  - **an organiser** with no campaign in hand sees the book alone, and can choose a campaign to see its house rules
    beside the book (my call; the area isn't tied to a campaign, but an organiser runs several).
- **Phone layouts** for every page, at 390 px wide, as the other areas have.
- **Interface text in English and Dutch**, like the rest of Delve. The entries themselves stay in the book's English
  (my call: the reference store holds only English, and translating 10,000 entries is not asked for).

## Non-goals

- Links from the character sheet, the story or the module editor to an entry (decision 7).
- A rules panel on the play screen (decision 7).
- Greyhawk, the setting's pages, Lore Facts (decision 3).
- Monster portraits. ttrpg2 painted one per monster. Delve's portraits are for characters, NPCs, houses and mounts,
  and are not asked for here (my call).
- Editing the reference. The book's data is read-only; homebrew is added through House rules, as today.
- The rule texts (PHB, DMG chapters from the `rules` table). The owner foresees "other rules" later. This design only
  keeps the subsections open to more being added; it does not add the rule texts now (my call, keeping to the seven
  the owner named).
- A second ruleset.

## Anti-goals

- **A reader without the organiser role finds a monster** by any route: the list, a page, the search, the palette, an API answer, a count or a 403
  that names the monster. That would break the fourth wall the owner asked for. Such a reader asking for a monster's
  address gets the same "not found" as for an id that doesn't exist.
- **Copying ttrpg2's code.** The backlog says never copy it. Its page list and its filters are the reference; its
  code is not.
- **A second copy of the reference.** The pages read the reference store (`delve.storage.reference.sqlite_reference`)
  that the DM's lookups read, so the DM and the table always agree on what *Web* does.
- **A seat sees another campaign's house rules**, or a rule its campaign has disabled or tied to another ruleset or
  setting. `play.house_rules.effective_rules` already gives a campaign's rules that way; use it.

## Constraints

- The reference store is read-only and is built by `delve reference build` (`make install`). The pages must work on
  it as built. Add indexes or helper views in the build step if a filter needs them, never by writing to it at run
  time.
- The store's connection is shared under a lock (master 927d9b0: the multi-seat 500s). New queries go through the
  same `SqliteReference` and its lock.
- Access follows Delve's roles (glossary: organiser, seat, host, co-host, player, observer). Monsters require the
  organiser role. Everything else needs any principal with a seat or an organiser, like the rest of the app.
- Lists can be long (887 spells, 3,826 monsters, 5,653 items in today's store). Page them on the server, using the
  existing Pager or the virtual list the desktop UX added from 100 rows, rather than sending everything.
- The project's rules hold: test first, import contracts (`lint-imports`), `make ci` and `make e2e-browser` green, the
  glossary and data dictionary updated with any new term or value, en.json and nl.json with the same keys.

## Left to the builder

- Whether the seat's API sits under its campaign (`/api/campaigns/{id}/rulesets/...`, which names the campaign whose
  house rules apply) or is global with a dependency that accepts any seat. Either way a seat's rights stay those of
  its own campaign.
- How the `## DM Notes` cut is made (by heading, up to the next heading of the same level or the end) and tested,
  including a rule with no such section.

- The API's shape (routes under `/api/rulesets/...` are expected) and how the web app's routes nest.
- Whether a list filters as the reader types (ttrpg2 did) or on submit.
- The exact columns of each list row, and the layout of the stat blocks, as long as an entry's page shows every
  field the store holds for it.
- How the Races subsection shows when it has only house-rule races, or whether the builder finds book races in the
  rules data worth adding to it. If it finds them, that is a decision to bring back, not one to take.
- The navigation icon, and where Rulesets sits in the navigation (beside House rules and Settings is the natural
  place).
