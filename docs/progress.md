# Delve: where the build stands

The single place to see which plateau is where, and how to pick up after a break. Update it when a plateau is
delivered or a quest starts.

**Sources:**
- design: `docs/superpowers/specs/2026-10-17-unified-app-design.md` (§14 lists the plateaus);
- plans: `docs/superpowers/plans/`;
- what each quest built: `docs/chronicles/`;
- words: `docs/glossary.md`.

**How it's built:**
- Each plateau is an edit-mode Guild quest under the Guild application **Delve** (id `delve`), from its plan.
- It runs with plan review, and the result is checked before delivery to `master` (Gitea `raf/delve`).
- Guild runs at `http://localhost:7777`, and its quest state lives in `~/.guild/quests/<id>/`.

| Plateau | Plan | Quest | Status | Chronicle |
|---|---|---|---|---|
| 0 Foundation | `plans/2026-10-17-plateau-0-foundation.md` | `20261017-78263c6a` | delivered 2026-10-17 | `chronicles/plateau-0-foundation.md` |
| 1 Maps | `plans/2026-10-17-plateau-1-maps.md` | `20261017-c6b622fd` | delivered 2026-10-17 | `chronicles/plateau-1-maps.md` |
| 2a Game engine (with house rules) | `plans/2026-10-17-plateau-2a-game-engine.md` | `20261017-7822addf` | delivered 2026-10-17 | `chronicles/plateau-2a-game-engine.md` |
| 2b Solo play: the DM through `claude -p`, the play screen, the eval gate | `plans/2026-10-17-plateau-2b-solo-play.md` | `20261017-0fd9e57d` | delivered 2026-10-18; eval gate passed; first real session played 2026-10-18 | `chronicles/plateau-2b-solo-play.md` |
| 3 Writing modules | `plans/2026-10-18-plateau-3-writing-modules.md` | `20261018-99fcebd9` | delivered 2026-10-18 (built unattended) | `chronicles/plateau-3-writing-modules.md` |
| 5 Books and quick dungeons (before 4, owner, 2026-10-18) | `plans/2026-10-18-plateau-5-books-and-quick-dungeons.md` | `20261018-0d2585ae` | delivered 2026-10-18 (built unattended) | `chronicles/plateau-5-books-and-quick-dungeons.md` |
| 4 The table: multiplayer, translation, the phone | `plans/2026-10-18-plateau-4-the-table.md` | `20261018-9e22e1f5` | built 2026-10-18 (unattended); to check, then deliver | `chronicles/plateau-4-the-table.md` (at delivery) |
| Walkthrough fixes (after the UK7 walkthrough) | `plans/2026-10-18-walkthrough-fixes.md` | `20261018-1fae65b2` | built 2026-10-18 (unattended); to check, then deliver | at delivery |
| 6 The rest of the world | `plans/2026-10-18-plateau-6-the-rest-of-the-world.md` | `20261018-3eab4105` | built 2026-10-18 (unattended); to check, then deliver | at delivery |
| 7 Maps: world maps from GeoJSON or a picture, travel by mode, dungeon-map drafts, the small items | `plans/2026-10-18-plateau-7-maps.md` | `20261018-71388f18` | built 2026-10-19 (overnight, unattended); to check, then deliver | at delivery |
| Faithful modules: a converted book exported and played as printed (scoped keys, read-aloud, book-page map drafts, handouts, pregens, hidden rolls, costs) | `plans/2026-10-19-faithful-modules.md` | `20261019-05010c2e` | built 2026-10-19 (unattended); to check, then deliver | at delivery |
| Settings: the setting as an area (Lore, Facts, Maps, Calendar, Proposals), the play screen's Setting tab, setting-owned world maps, the DM's proposals, Preferences where Settings were | `plans/2026-10-19-settings.md` | `20261019-54c4380e` | built 2026-10-20 (unattended); to check, then deliver | at delivery |
| Portraits and images: a portrait style per campaign, emotes (said lines, the sheet's state), Preferences' Connections (the Replicate token, assetgen) and assetgen as a picture backend | `plans/2026-10-20-portraits-and-images.md` | `20261020-88bf6e1b` | built 2026-10-20 (unattended, with Novelization); to check, then deliver | at delivery |
| Novelization: a module or a campaign told as a recap, short story or novella, a job read in Delve and printed to PDF, for the owner alone | `plans/2026-10-20-novelization.md` | `20261020-88bf6e1b` | built 2026-10-20 (unattended, with Portraits and images); to check, then deliver | at delivery |
| Looks and banners: three looks per browser (Delve today, Gold and wood, Dark dungeon), applied before the first paint, in Preferences and the play screen's header; a wide painted banner for every campaign, waiting while paid images are off | `plans/2026-10-21-looks-and-banners.md` | `20261021-315c54be` | built 2026-10-21 (unattended); to check, then deliver | at delivery |
| Desktop UX (owner, 2026-10-22): dragged splits, the command palette and shortcuts, tips and menus, a dragged marching order and dropped files, notifications in the corner, long lists drawn in view | none (built by hand on `feat/desktop-ux`) | none | built 2026-10-22; to merge after the Carry the party on quest | none |
| Carry the party on (owner, 2026-10-22): a host takes a campaign's party, with all it owns, into a new campaign on another module; Claude writes the party's history, the DM's and the table's | `plans/2026-10-22-carry-the-party-on.md` | `20261022-3684addd` | built 2026-10-22 (unattended); to check, then deliver | at delivery |
| Rulesets (owner, 2026-10-22): a Rulesets area where every seat looks up the book's spells, items, classes, ability scores, proficiencies and the turning table, with filters; monsters for organisers only; the campaign's homebrew beside the book's | `plans/2026-10-22-rulesets.md` | `20261022-6aa4ba8e` | built 2026-10-22 (unattended); to check, then deliver | at delivery |
| Thorough conversion (owner, 2026-10-23): a PDF converted by default as the hand QA passes did it, by agents in a lasting job folder (texts cleaned against the pages, maps traced from the book, levels joined, pictures described), with a doubts list and the cost at the end, paused and resumed instead of failing; the conversions queue | `plans/2026-10-23-thorough-conversion.md` | `20261023-8d9d5f4e` | built 2026-10-24; U1 converted with the real Claude ($23.24, 55 min of running, resumed after the usage limit and two stops: `docs/review/2026-10-23-thorough-conversion-u1.md`); to check, then deliver | at delivery |

## Decisions made during the build

These came up as check-ins during the quests, were answered, and are recorded in the chronicles. The ones that
change rules or shapes are listed here so later plans don't undo them.

**Plateau 0**
- A Protocol member that returns an async iterator is written `def …() -> AsyncIterator[...]`, not `async def`.

**Plateau 1**
- An unmet `requires` version in a `.dscn` manifest is a warning, as in dungml.
- Includes resolve only from the module's library maps, then the built-in libraries, never from the filesystem
  (a security fix).
- The module routes answer 201 for creating and 204 for deleting. An import answers the module plus `warnings`.
- The map editor has no Play button. Its breadcrumb links back to the module.
- Unknown-node candidates are `[{id, label}]`. A campaign lists only `map`-role maps.

**Plateau 2a** (the full list is in its chronicle)
- `Dice.table(n)` rolls one exact die up to 1,000,000 sides, for table picks only. DM notation stays capped at 100
  dice, 1,000 sides and 20 repeats.
- `turning_undead` and every other check take an actor and a combat round, so the no-re-roll key is per actor per round.
- A surprised side loses one round (2e). Segments are a 1st-edition mechanic.
- `play.characters.create` returns the character. The house rules for creation, level-up and items come back through
  the tool results, under `house_rules`.
- Treasure has a `source`, which is part of the roll key. Awarding the same source twice in one beat is refused, and
  different sources roll separately.
- Loot items have a `qty`. Map parsing lives in `delve/maps/sources.py`.
- **Initiative ties are simultaneous (PHB ch. 9).** Each initiative value is resolved as one group against the state
  at the start of that group, and its damage is applied together.
- Morale is a one-shot `morale_due` notice that the DM resolves with `morale_check`.
- Character lists carry an `encumbrance` that the server computes.
- A fight's rolls are keyed under `<beat>/<combat id>`, so a second fight in the same beat rolls fresh.
- Tools can mark result keys as DM-only (`dm_only_keys`). `room` takes `characters`. `rules_lookup` takes `ruleset`.
- Saving throws come from PHB Table 60 in `rules/adnd2e/tables.py`. The reference's `class_levels` save columns are
  wrong for every class. All four groups were checked against Table 60 on 2026-10-17.
- `module_lookup` is deferred to 2b.

**Plateau 3** (the full list, with the 15 decisions taken without the owner, is in its chronicle)
- **Audiences are `gm` and `player` everywhere** (owner, 2026-10-18, `314d2d9`): texts, sections, attachments and
  entity records store the format's values, and the UI shows "DM only" and "Players". Migration `0008_audience_gm`
  rewrote the `dm` the quest had stored. The stored values are listed in `docs/data-dictionary.md`.
- The export refuses a module with dangling `asset:` or entity refs (409). Headings that link themselves are exported
  as `keys[]`. A module's empty maps are left out of its export (`6570b61`).
- Who may see a campaign image before plateau 4: organisers; the 404 rule holds for them too.

**Plateau 4** (built unattended; the chronicle lists every decision taken without the owner, with its reason)
- **The host plays every PC nobody has claimed** (the party's decision): the host's act covers them by default, the
  host holds a beat up while there are such PCs, and the fallback goes only to PCs no submission covered. Solo play
  is unchanged, and those PCs stay free to claim (`controller_id` stays null).
- `0010_seats`, `0011_story_audience` and `0012_translations` follow `0009_conversions`.
- `GET /api/me?campaign=<id>` gives the owner their owner seat at that table, and every seat object has
  `campaign_name`: a seat may not read the campaign itself.
- Ask the DM moved into the table panel (on a phone, the Table screen). A player's map asks only for their own
  characters; the marching-order arrows and Table settings are the organisers'.
- The fake `claude` answers translation side calls by their prompt, and the table keeps time by `DELVE_CLOCK_FILE`
  under `delve serve` in tests (`FileClock`).

**Plateau 6** (built unattended; the designer's twelve decisions for the owner are in spec §10.1, and the chronicle
lists every decision taken without the owner)
- **Days pass in one place** (`play/days.py`): `advance_time` past midnight, `advance_days`, a whole-party `rest` and
  `travel` run the new-day hooks (clocks, weather) once per day crossed. The calendar is the setting's; the date and
  the season are derived from the campaign's day. `set_season` and `pre_turn_check` are not ported.
- `0013_world` is plateau 6's one migration: factions, clocks, quests, campaign facts, possessions, world maps,
  merchants and campaign images, and `campaign_state`'s `start_date`, `weather` and `world`.
- A campaign owns copies of its module's and its setting's world maps (the module's wins a name clash); the party has
  one place on them. A seat's world-map SVG leaves hidden places out entirely.
- A progress clock moves only when the DM advances it (ttrpg2 counted segments as days).
- Portraits are portraitgen's by default (`web/vendor/portraitgen/`, commit `e6a94a3`). Paid images are off per
  campaign until the host turns them on, and are painted in the background, never inside a beat. The Replicate token
  is never stored in the database or sent to a browser.
- The journey e2e (`tests/e2e/test_a_journey.py`) rides one beat per leg, since `delve serve` rolls with the system's
  dice and an encounter stops a journey: its assertions hold for any roll.

**Plateau 7** (built overnight without the owner; the plan's 61 decisions are in its last section and in the
design's "Decided in the plan", and the chronicle lists every decision taken during the build)
- **A world map is a geo map** (`delve.maps.geo`): GeoJSON in km over a grid of terrain cells, with an optional
  picture; `0014_maps` only adds columns and two tables. Plateau 6's `.map` maps convert on first read, and a
  converted campaign knows everything it knew.
- **What the party knows is the campaign's**, and a seat's view and tiles hold only that: no hidden place, nothing in
  unknown land, no `dm_notes`. A `world` event carries only the campaign's id. A new campaign's maps start unknown.
- A map read from a picture is in review until accepted; the reading is deterministic, and its tests use synthetic
  pictures, never the owner's `greyhawk.jpg`.
- `travel` goes one leg by one mode (`foot`, `horse`, `cart`, `river`, `ship`); `route` previews a leg;
  `miles_per_day` carries a house rule's pace. `edit_world_map` is gone; the DM has `add_place`, `hide_place` and
  `reveal_area(…, forget=true)`.
- The fourth raw-body exception: `POST /api/conversions/worldmap` (PNG, JPEG or WebP, 64 MB). Tests set
  `DELVE_OCR=off`.

## The walkthrough fixes (2026-10-18)

The UK7 walkthrough (`docs/review/2026-10-18-walkthrough.md`, finding ids C1–C11, E1–E10, P1–P8, D1–D4, T1–T9) and
the owner's hand checks of plateaus 3–5 led to a pass of nine tasks. T1 (the reference under one lock, `927d9b0`) and
T2 (translation refuses replies that are no translation, `13657aa`) were fixed before it.

**The owner's hand checks so far:**
- **Writing a module from scratch works.**
- **The empty-module mix-up:** fixed by the pick-first screen (`b57e9a0`): New module asks for a way first, then
  shows only its form.
- **Converting UK7** (`/tmp/TSR 9151 UK7 Dark Clouds Gather.pdf`, scanned throughout): see the walkthrough, §1.
- **Converting Tomb of Horrors** (TSR 9022A, `mod_481e37c6ea6d`, 4 minutes; a text layer on pages 3–13, a scanned
  booklet, the map on page 46): see `docs/review/2026-10-18-tomb-of-horrors.md`, which also says which tasks fix what.

**What the pass did:**
1. **Scanned pages** (C1, C2, C5): a scanned page is text only when OCR reads 150 real words or more, mostly words;
   any other is kept as a picture, and what OCR read reaches no text. A picture page with a map's legend or room
   numbers is a map page. Pages with a text layer are unchanged. A scanned page of 40 to 149 real words kept as a
   picture warns `page-text-as-picture`.
2. **Book maps and sketches** (C1, C2, C10): a map page is the attachment `map-page-<n>` with a `book-map` warning. A
   sketched map's source starts with `# Sketched from the room key: an invented layout.` (the map language's comments
   are `#`) and names the book's map page; the Maps tab and the map editor say so, with "Show the book's map". It is
   named after the map's title, never the module's. A picture page starts a chapter only when its first line is a
   short title, it holds 15 real words or fewer, and the title is neither the module's nor a line that repeats on
   other pages (a running header).
3. **The book's numbers and the entities** (C3, C4, C6, C11, E3): the prompt keeps numbers and table rows as the
   book has them, and a `numbers-changed` warning lists those that changed (a page's header and footer lines are
   not counted). Same-name NPCs, factions, quests and
   encounters merge (exact name only). Encounters and NPCs are keyed to the room the book places them in. The NPC
   form has a "Where". A generated module gets its party's size and levels, and names from the rolled lists.
4. **Progress and warnings** (C8, C9, E2): "Step 2 of 4", a page count during OCR, the time taken; a running or
   finished conversion on Modules, a dot in the nav, a notice when it ends. Warnings are folded, grouped by kind and
   linked, with the module's derived ones. The conversion event and JSON carry `steps: {index, count}`.
5. **The play screen** (P1, P2, P4, P5, P7, T4, T5): the party, then the map, then the table, then the host's
   controls (folded); the invite open only while the host is alone. **Tool rows reach only the host and co-hosts,
   and a refused one only the host**, on the server (story, stream and replay). The story follows the newest entry.
   The phone map fits what is known. "Choose your character" for a player without one. The invite link uses the
   browser's address unless it is loopback. The role value is `cohost` everywhere (the web had `co-host`).
6. **The DM and Ask the DM** (D1, D4, T3): the DM is told never to narrate its own process and to send host notes as
   a `tell`, or, when the host plays no character, as a paragraph starting `(ooc, for the host:`; the table holds
   that paragraph back while it streams and stores it for the host's seat alone. Ask the DM sees the asker's last 8 visible story entries and the items' notes, and answers rules with
   figures. **T3's cause was in the web panel:** it built Ask's entries from the stored English and ignored their
   translation (`Play.tsx`, before the fix); the server translated correctly. The shared answer in table talk
   renders its Markdown, clipped to three lines.
7. **Phones** (E9, §6): the module page and its tabs, the map editor (Code and Drawing as tabs), House rules (a rule
   as its own view) and the print pages fit 390 px; `web/e2e/phone.spec.ts` checks each.
8. **The sheet, map rename, the DM log** (owner item 1, E1, P3): the full character sheet (abilities, proficiencies,
   thief skills, background, a THAC0 per attack); an NPC's story and disposition for the organiser only, through the
   new organiser route `GET /api/campaigns/{id}/dm/characters` (seats lose `notes_md` and `disposition` from PCs
   too); a map rename updates its texts and keys; the campaign page's DM log with tokens and cost per beat; SQLite's
   `busy_timeout` set to 5000.
9. **Docs and a scanned book's shape:** `tests/e2e/test_conversion_shapes.py` converts a three-page scanned book (text,
   map, handout) with a fake OCR and the fake `claude`, and checks the book map, the handout, no OCR junk in a text and
   the sketch's label.

**What is left** (from the walkthrough, not in this pass; now items in `docs/backlog.md`, Features 2 and Fixes):
- **Maps:** sketching from the book's map image (backlog); a heading with a key and no name ("31.") has no room;
  `start` on a sketched map places nobody, and maps have no exits between them (E5); a "key this heading" picker
  (E4).
- **Conversions:** misread digits in stat lines (C6, only the counts are checked); NPC ability scores and stat fields
  left in the prose (C7); every text and read-aloud box starts DM only, with no bulk action (E6); the cost of a
  conversion is not shown.
- **Print:** a 73-page print with the title alone on page 1 and "DM only" on every text; the map print numbers rooms
  twice (E8).
- **Play:** the sheet at 390 px (HP wraps; XP has no thousands separator) (P5); an empty campaign's first step and the
  campaign page's raw map-state tool (P8); a scene told twice (D3); the hold-back label (T6); the Dutch UI's English
  race, class and item names and server warnings (T7); Ask the DM's usage isn't logged; a shared Ask answer stays
  English in table talk for a Dutch reader.
- **Other screens (§6):** the new campaign form with an empty name; `/play/<unknown>`; the seeded house rules on a
  fresh install; themed links and a skip link; Settings' labels.
- **Tests:** ~~`tests/web/test_fourth_wall_per_seat.py`'s `tell()` helper reads the current beat twice and failed once
  when the beat ended between the reads (flaky, seen in Task 4).~~ Fixed in the review fixes (8d34738): `tell()` goes
  through `act_and_wait`, which takes a beat closing between the reads.

**To check by hand** (none of it was tried with the real `claude` or real devices during the quest):
- reconvert UK7 and Tomb of Horrors, and look at the map pages, the numbers and the keyed encounters;
- a table of two on a phone;
- the play screen at 1280×800;
- the full character sheet;
- the DM log's costs.

## Carried after plateau 4

- **To check by hand** (none of it was tried with the real `claude` or on real devices during the quest): a table of
  two or three devices on the LAN with the real `claude`:
  - joining by the QR code from a phone, and New link stopping the old one;
  - a beat with everyone acting, the seat indicators (typing, acted), and Go;
  - the beat timer running out, with each fallback (hold back, in character);
  - a private `tell` (does the real DM use it for a split party, and keep it out of its reply?);
  - Dutch translation as it streams: its speed, the game terms, and names left as they are;
  - table talk, and sharing an Ask the DM answer;
  - the phone layout (Map, Party, Table), and the new dialogs (New link, Leave the table, the editors' unsaved
    changes).

## Carried after plateau 6

- **To check by hand** (nothing of it was tried with the real `claude`, a real Replicate token or on a real phone
  during the quest):
  - a journey with the real `claude`: Greyhawk to Hardby on a horse (does the DM call `travel` rather than narrate
    the miles, run a road encounter from the result, and leave the clock and the date to the tools?);
  - the World panel on a phone (the fourth screen, "World");
  - portraits on the party sidebar;
  - one paid scene with a real Replicate token (paid images on, "Paint this scene");
  - the setting lookups for a few Greyhawk names (`setting_lookup`, `setting_search`).

## Carried after plateau 7

- **To check by hand** (nothing of it was tried with the real `claude`, the real tesseract or a real phone during the
  quest; `greyhawk.jpg` went through the reading once with the fake `claude` and `DELVE_OCR=off`: the review opened
  after 85 s, at a peak of 1.5 GB):
  - importing `~/claude/refactoring-assets/greyhawk.jpg` with 1 hex = 30 miles and reviewing it: the grid, the
    colours, the rivers' flow (the Selintan's, the Neen's), the places' names Claude reads, Greyhawk, Hardby and
    Dyvers among them;
  - on that map, Greyhawk to Hardby on foot and by river boat down the Selintan, and Greyhawk to Dyvers by ship
    across the Nyr Dyv;
  - a seat's fog on a phone;
  - generating a dungeon map from a description, and drawing one from a book's map page, with the real `claude`;
  - importing a real Azgaar export (the test fixture is synthetic), to check the biome ids;
  - the small items: pending and private acts at a table, Ask the DM in the story and a shared answer in Dutch, the
    campaign status and the richer campaigns list, the modules list's actions, THAC0 per attack on a sheet (a bow
    takes Dexterity), the questions after making a module, "## 31." keyed with no title, the hidden tool count, and
    the notice for a lost event stream.

## Carried after faithful modules

- **Rebuild the reference once:** `make install` (or `uv run delve reference build`) after Task 24. The snapshots now
  hold `corrections.sql.gz`, Delve's own fixes to rows of the pinned data (the giant centipede is the giant
  centipede, no longer a copy of the megalo-centipede), loaded before the full-text index is built. The snapshot set
  changed, so `delve serve` refuses with exit code 4 until `reference.db` is rebuilt. Migration `0015_costs` runs on
  its own at the next start.
- **Rules now in force:**
  - players see each other's sheets (owner decision 4); hiding them is in the backlog;
  - the book is followed as printed, errata and contradictions included (owner decision 5: "gnolls in area 30");
  - every boxed text of a keyed section is read-aloud (Delve's reading of R13).
- **Decisions taken without the human** are in the quest's chronicle, under that heading; the owner may overrule them.
- **To check by hand with the real `claude`** (nothing of it was tried with the real `claude`, tesseract or a real
  phone during the quest):
  - converting U1 again and judging the drafts of pages 2, 35 and 37;
  - exporting it, and importing the export into a fresh data dir;
  - offering its pregens at party creation (page 29's roster, "½E", "18/76", "3/3");
  - a short play through the house with fog and the secret trapdoor in room 4 (the DM finds it with `door(found=True)`);
  - Caine's "½E" (filled only if the vision answer adds it; otherwise a `text-gap` warning);
  - the conversion's cost on the done screen, and an Ask in the DM log's costs.
- **Browser check:** `make e2e-browser`. The specs share one server and run in file order, so
  `web/e2e/zz-faithful.spec.ts` sorts last and makes its own module, campaign and story at its start, never in
  `prepare()`; the earlier specs' expectations changed only where the new screens did (the module page's Pregens tab).

## Carried after portraits and images

- **To check by hand** (nothing of it was tried with the real `claude`, Replicate or assetgen during the quest):
  - a campaign's portrait style changed on its page, and the party, sheets and story redrawn in it;
  - an NPC speaking in the story: the portrait talks while the line appears, then shows its mood;
  - a PC's sheet at a third of its HP (upset) and at 0 (asleep);
  - the Replicate token saved and removed under Connections in Preferences without a restart (the state reads Set,
    Not set, or From the environment);
  - assetgen started (`assetgen serve --port 8765`), its URL saved under Connections, and a portrait painted through it;
  - merging portraitgen's play-once change (commit `cf0c60f`, branch `play-once`, worktree
    `~/claude/portraitgen-play-once`, not pushed); Delve vendors it in `web/vendor/portraitgen`.
- **New names:** the play setting `portrait_style`, the story kind `say`, the character field `emote`, the files
  `replicate-token` and `assetgen.json` (`docs/data-dictionary.md`); portrait style, emote, said line and Connections
  (`docs/glossary.md`).
- **Backlog:** item 12 is done; item 10 (portraits on map tokens) stays open; "a local image model in assetgen" is new
  and is assetgen's own project.

## Carried after novelization

- **To check by hand** (nothing of it was tried with the real `claude` during the quest; the tests use the fake):
  - a played campaign novelized as a recap;
  - the Crypt of Saint Vellis novelized as a short story (Novels tab of the module);
  - one novel printed to PDF from its print page (the tests check the print CSS, not a print dialog);
  - an organiser seat (made by the owner) sees no Novels and gets 403 on `/api/novels`.
- **New names:** the table `novels` (migration `0017_novels`), the conversion kind `novel` with the steps
  `condensing`, `outlining`, `writing`, the Preferences job `novel`, the package `delve.novels`, the routes under
  `/api/novels` and the pages `/novels/{id}` and `/novels/{id}/print` (`docs/data-dictionary.md`); novel, Novelize,
  recap, short story, novella and Continue (`docs/glossary.md`).
- **Known small points:** the session range inputs show "1 to 1" until a range is chosen (the form has no upper limit
  from the server); a private act appears as "Host (in secret)" in the material, because the host plays the PCs
  nobody claimed.
- **Backlog:** "Illustrations in a novel" is new and a non-goal for now.

## Carried after looks and banners

- **To check by hand** (nothing of it was tried with Replicate or assetgen during the quest; the browser checks use
  the free fake images, whose banner is one slate-blue pixel):
  - each look on a real phone and on a large screen: does the texture tile well, and is the story readable?
  - a real banner with Replicate: a new campaign with paid images off (the campaign's page says the banner waits),
    then paid images on (it's painted), then **Paint again** with a hint;
  - an organiser seat's Paint again, and a player seat's empty story with the banner;
  - a module, a map and a novel printed while a look is chosen: they print as in Delve today.
- **New names:** the image kind `banner`, the image status `waiting`, the campaign JSON's `banner`, the event
  `banner`, the local-storage key `delve.look` and `ImageRequest.aspect` (`docs/data-dictionary.md`); look and banner,
  and "theme" or "skin" avoided (`docs/glossary.md`).
- **Browser checks:** `web/e2e/looks.spec.ts` (first by file order; it leaves Delve today set and no campaign of its
  own). Its screenshots: `look-delve-1280x800.png`, `look-gold-wood-1280x800.png`, `look-dark-dungeon-1280x800.png`,
  `look-dark-dungeon-play-1280x800.png`, `look-dark-dungeon-editor-1280x800.png`, `banner-campaign-1280x800.png` and
  `banner-module-1280x800.png` in `web/e2e/screenshots/`.
- **Changed after the review:** print views take the look off while open (and `look.js` sets none on a `/print`
  page); the play screen's picker is an icon-sized swatch, and from 1200 px the play header keeps one line, the
  session line giving way first; the fake images paint an opaque pixel.
- **Backlog:** "The banner's why not, in the reader's language" and "Map-preview highlights keep their colour in a
  look" are new (Interface 5 and 6).
| Open fixes and PC names (owner, 2026-10-22): a PC the DM makes up is named by Delve's dice; the walkthrough's small open fixes (the sheet on a phone, the empty campaign's page, a scene told once, hold back's words, Dutch terms and warnings, bulk audiences, a compact print, house rules not seeded, themed links, plain Preferences, clear forms) and react-router 7.18 | `plans/2026-10-22-open-fixes-and-pc-names.md` | `20261022-03488bf4` | built 2026-10-22 (unattended); to check, then deliver | at delivery |

## Carried after Open fixes and PC names

- **To check by hand** (nothing of it ran with the real `claude`):
  - ask the real DM to "make me a party of four" for a new campaign: do the names read like Delve's, not the model's?
  - the sheet on a real phone, in Dutch;
  - print a converted module: is it compact enough, and are its maps keyed once?
  - a fresh install, or a scratch `DELVE_DATA_DIR`: the House rules page and **Import the example rules**;
  - the sidebar's EN / NL switch on an install whose Preferences name a backend that isn't loaded at that moment: the
    stored choices must stay.
- **What it does:**
  - **Task 1:** `create_character` with no name takes one from `delve.rules.adnd2e.names` for the race and gender,
    and answers `named_by` (`dice`, or `given` for a name kept as given).
  - **Tasks 2 and 3:** the sheet's stats fit 390 px and its numbers have separators; an empty campaign starts from
    play, and the map state tool is in the Maps tab, there whenever the party is on a map.
  - **Tasks 4 and 5:** a paragraph the DM repeats across a tool call is told once; hold back says whose characters
    it holds back ("Do nothing (hold back)", "Are played cautiously by the DM").
  - **Task 6:** races, classes, genders and alignments, and the settings warnings (`coded_warnings`), in the
    reader's language; item, weapon and spell names stay as written.
  - **Tasks 7 and 8:** **Select all** and a bulk audience in the module editor (`POST /api/modules/{id}/audience`);
    "guards from area 2" is a reference, not a key.
  - **Task 9:** the print flows its texts, tags only what players may see, and numbers rooms once.
  - **Task 10:** a fresh install has no house rules and imports the example on request; links follow the look and a
    skip link leads to the content; Preferences' plain labels; the language switch in the sidebar.
  - **Tasks 11 and 12:** clear forms and pages (empty names, empty modules, unknown campaigns); the Generate-after-
    reload test; react-router 7.18.4.
- **After the review:** the bulk route refuses a change that would take a record out of its schema (a secret stays
  `gm`); the sidebar switch stores the language alone; the import route never changes a library in use (409); the
  print tags the players' images; a map key never numbers a room its label already numbers; "the far end of area 12"
  still keys 12; a stored `default` claude-cli model still reads as the CLI's own, which `claude-cli` no longer lists;
  the map state tool shows whenever anyone is placed on any map, and a failing query shows an alert; the checkboxes of the module editor keep their own size.
- **Deviations the engineers reported:** `react-router` is also a direct dependency, `package.json` says `"7.18"`
  (the lockfile pins 7.18.4); the browser specs open the campaign page's tabs (`?tab=maps`, `party`, `novels`),
  since the campaign page has tabs; each e2e run rewrites about 45 tracked screenshots, so they were restored and
  the committed ones still show the layout before the review fixes.
- **Noted, not done:** Noor's review of Tasks 1-11 (`abc77b5`) found no fourth-wall leak; the fixes above answer her
  findings. Item, weapon and spell names stay as written in Dutch.
- **Browser checks:** `web/e2e/phone.spec.ts` (the sheet at 390 px, `sheet-390.png`) and the module editor's
  and print page's specs; `DELVE_E2E_PORT=… make e2e-browser` passed 18 of 18 on `f539be7`.

## Carried after Carry the party on

- **To check by hand** (nothing of it ran with the real `claude`; the tests and the browser checks use the fake):
  - carry a real party into Barrowmaze: read both histories (DM's and table's) on the new campaign's page and check
    the table's holds nothing the whole table wasn't told;
  - check the DM brings someone back from the history in the first session, unprompted;
  - Write again on an edited history (the confirm), and a carry made while a novel is being written (the campaign is
    made, the history says to write it again);
  - Dutch "Geschiedenis" on the six-tab phone bar: it probably gets cut off with an ellipsis; only English was checked.
- **What it does:** `POST /api/campaigns/{id}/carry` makes the new campaign as `POST /api/campaigns` does, copies the
  chosen PCs (sheet and state, less effects and fight conditions, faction cleared, no seat), their possessions, the
  party's unowned possessions, coin and loot pile, and a painted portrait's picture; records the carry; sets the old
  campaign to `complete`; and starts the history job. The old campaign's rows are never moved or deleted. A live fight
  is 409 "End the fight first."; a draft module 409; an empty party or a stranger's id 422.
- **The history:** a job of the kind `history`, two Claude calls (the DM's from the full material, the table's from
  material filtered at the source in `delve.histories.material`: no private acts, DM notes, unrevealed secrets or
  reputation numbers, a word for each standing), each held to 6000 characters. The old module's unplayed text is left
  out. Histories stack: the earlier one's DM text goes into the DM's, its table text into the table's.
  Carrying on never fails because of it: a failed start stores a `failed` history and Write again.
- **Who reads it:** the DM through `session_primer`'s new `history` (the stored DM text whenever it is non-empty, whatever the status, else null; `dm.md`
  says to bring people and debts back and to keep Loose ends from the players); Ask the DM and the play screen's
  **History** tab read the table's text; the host's History section shows both and edits them. A seat's `GET
  …/history` holds only `{status, table_md}`.
- **After the review:** the history's material has a "What the party carries" part (the carried PCs' inventories,
  the coin, the loot pile and the possessions; the table's without possession notes); only the host reads, edits or
  writes again the DM's history (a co-host gets `{status, table_md}` and 403, as for a tool reply); a Write again
  keeps `edited` until it ends `done`; the History tab reads the history again every 5 s while it is being written.
- **New names:** the job kind `history`, the tables `campaign_histories` and `campaign_carries`, the campaign JSON's
  `carried_from` / `carried_to`, `HISTORY_MAX_CHARS`, migration `0018_histories` (`docs/data-dictionary.md`); carry the
  party on, history, the DM's and the table's history, Loose ends and Write again (`docs/glossary.md`).
- **Deviations from the plan** (from the builders' reports):
  - `STEPS["history"]` in `conversions/runner.py`, and `Nav.tsx`'s link label, because the kinds are typed;
  - Write again while another job runs is refused in the route (409 "A conversion is running."), so a `done` history
    is never turned `failed`; only the carry goes through `start_history`'s failed path;
  - `PUT …/history` on a campaign with no history is 404, and Write again keeps the old texts until the new ones
    replace them;
  - an empty table text adds no part to Ask's prompt;
  - the History section also shows on the old campaign, for its "Carried on to" links; the campaign list's row menu
    has Carry the party on (`?carry`); six phone tabs share the bar at 0.8rem.
- **Browser checks:** `web/e2e/y-carry.spec.ts` (after `x-novels`, before `zz-faithful`). Its screenshots:
  `carry-form-1280x800.png`, `carry-form-390x844.png`, `history-host-1280x800.png`, `history-host-390x844.png`,
  `history-tab-1280x800.png`, `history-tab-390x844.png` in `web/e2e/screenshots/`; `desktop-row-menu-1280x800.png`
  was regenerated (four items).

## Carried after Rulesets

- **The reference build is now version 2** (`BUILD` in `delve.storage.reference.build`, kept in `meta.build`). It adds
  the tables `monster_facet` and `spell_school`. A `reference.db` of another build (an older one has none) is stale:
  `delve serve` refuses with exit code 4, as for other snapshots. **Run `make install` (or
  `uv run delve reference build`) on the live install before restarting it.** Nothing in `delve.db` changes.
- **The area:** `/rulesets`, `/rulesets/<ruleset>`, `…/<section>` and `…/<section>/<id>` (`web/src/rulesets/`), over
  `GET /api/rulesets…` (`delve.web.routes.rulesets`), `delve.play.rulebook` (the reader's view, with the campaign's
  homebrew and the DM Notes cut) and `delve.rules.adnd2e.rulebook`. A seat's play header has a "Rulesets" link that opens
  a new tab; the nav, `g b` and the command palette are for organisers. The play state carries the campaign's `ruleset`
  so a seat knows where to link.
- **Monsters are for the organiser role.** A reader without it gets the same 404 as for an unknown id, and the
  search skips monsters. A house rule's DM Notes section is cut for such a reader too.
- **Facet values are computed at build time from free text, so some are approximate** (`delve.storage.reference.build`;
  the list is in the data dictionary):
  - **Schools:** the PHB's four slash names count as one school each, so the real data has exactly the eight schools.
  - **Terrain:** the word list was widened (plurals, `water`/`waters`, `woodland(s)`, `marsh(es)`/`wetland(s)`, the
    demiplane, quasiplane and paraplane words, and the Outer Planes by name). What matches none is `other`.
  - **Book:** the values are the monsters' `categories` entries, literally, less " Creatures". Some are topic names,
    not books.
  - Counts on the real reference (Sam's report): size M 1224, L 838, S 478, H 324, G 296, T 289; alignment N 1399,
    CE 482, NE 389, LE 238, any 204, CN 170, LN 117, NG 104, other 96, none 90, CG 83, LG 72; terrain any 1019,
    other 519, water 330, subterranean 322, forest 312, planes 311, mountains 183, plains 139, swamp 125, hills 122,
    jungle 95, space 88, desert 85, arctic 69, urban 36.
- **Rarity bands look lopsided on the real data:** common 322, uncommon 320, rare 101, very_rare 314, legendary 4596,
  artifact none. The bands are ttrpg2's labels over the store's `rarity` number (0–100); most items sit between 56 and
  70. Left as it is; a different cut is a one-line change in `RARITY_BANDS` (`delve.domain.reference`), no rebuild.
- **Spell text** is shown as stored, as Markdown: a stored line that starts with "- " becomes a bullet, and some
  descriptions break in odd places (*Web*'s page shows it). Cleaning the text is not done.
- **Joins from one address are limited to 10 a minute** (`JOINS_PER_MINUTE`); the browser specs together are close to it.
  A new spec that joins should join with one `POST /api/join/{token}`, as `y-carry.spec.ts` and `rulesets.spec.ts` do.
- **To check by hand:**
  - `make install` on the live install rebuilds `reference.db`, and Delve starts;
  - as a player, on a phone: the Rulesets link in the play header, *Web* through School = **Evocation** (it is
    Evocation in the real data), and no Monsters;
  - as the owner: Monsters by terrain and size, and an item house rule whose DM Notes you see and the player doesn't.
- **Browser checks:** `web/e2e/rulesets.spec.ts` (after `play`, before `settings`). Its screenshots in
  `web/e2e/screenshots/`: `rulesets-spell-390x844.png`, `rulesets-owner-1280x800.png`.

## Carried after Settings

- **Migration `0016_setting_content`** runs on its own at the next start (four new tables: `setting_pages`,
  `setting_facts`, `proposals`, `setting_maps`). At that start `adopt_pointers` copies each "use as the setting's map"
  pointer of plateau 7 into the setting's own maps and deletes it; one whose module map is gone or in review is
  dropped. The reference isn't rebuilt: nothing of it changed.
- **Words now in force:** Settings is the area for game worlds; the install's options page is **Preferences**
  (`/preferences`, nl "Voorkeuren"), and a campaign's are **Table options** (`…/play/options`, nl "Tafelopties").
  The stored names `settings`, `Storage.settings` and `play_settings` keep their old word (`docs/data-dictionary.md`).
- **Decisions taken without the human** are in the quest's chronicle, under that heading; the owner may overrule them.
- **To check by hand** (the design's hand checks; nothing was tried with the real `claude` or the real picture during
  the quest):
  1. Settings in the sidebar, then Greyhawk. Search "Hardby", read the page, follow a link.
  2. Add a page for a homebrew village, add a DM-only fact, and override a shipped page. Revert the override.
  3. Look as a player seat. The play screen's Setting tab shows the lore and maps. No DM-only content shows there, in
     Ask, or in "Did you know", and that includes hidden map features.
  4. In play, the DM proposes a fact. It shows in that campaign, and in no other campaign until it is accepted. Accept
     it, and a second campaign sees it.
  5. Import greyhawk.jpg into Greyhawk (picture, 1 hex = 30 miles), review it, and accept it. A new Greyhawk campaign
     copies it. Then travel from Greyhawk to Hardby.
  6. Preferences is where the old Settings were. Nothing else is still called "Settings" for options.
- **The delivery step, with the owner** (the picture's licence keeps it out of the repository, backlog item 11): with
  `delve serve` running on this install,

      uv run delve setting import-map greyhawk ~/claude/refactoring-assets/greyhawk.jpg \
          --name flanaess --title "The Flanaess" --cell hex --distance 30 --units miles

  then review and accept it in the app (Settings > Greyhawk > Maps, or the link the command prints), and travel from
  Greyhawk to Hardby in a new Greyhawk campaign. Existing Greyhawk campaigns keep the maps they were made with.

## Carried into plateau 2b

From the 2a chronicle:
- **Every tool result** in the players' feed goes through `player_view`. Errors show their message only, because
  candidates can name hidden rooms.
- **Tool-host writes send no `characters` events yet.** The play screen needs them, or sheets won't refresh.
- **Spell effects aren't applied automatically.** The DM rules them with `adjudicate` and conditions.
- **`GET …/characters` returns NPC `notes_md`.** That's fine for organisers; plateau 4's player routes must redact it.
- **THAC0 in the reference looks wrong for priests and thieves.** Fix it from the PHB before using that column.

- **Module text:** unpack a `.dscn`'s text, keys and entities, which plateau 1 kept only in the stored bundle, and add
  `module_lookup`. The first real session needs the module's text.
- **The speed guideline (spec §6.4):** the first words appear within 30 s of a beat closing; only very complex requests
  may take longer, and they show progress.
- **Maps without a start:** none of the samples declares `party_start`, so `start` places nobody on them. Use maps that
  declare one, or add a fallback.
- **The eval gate:** compare against ttrpg2 before plateau 2b ships, to prove that removing file tools doesn't hurt play.
- **Upgrades aren't atomic:** a campaign upgrade isn't one transaction yet. Use `Storage.transaction()` from 2a.

**Plateau 2b** (the chronicle has the full list, including the ten decisions taken overnight without the owner)
- `0005_beats_story` follows `0004_module_text`, and also holds `dm_sessions` and the campaign's `play_settings`.
- The rehydrate and handover texts live in `delve.dm.prompt` only; the `claude -p` provider imports them.
- A failed reply shows "The DM didn't answer: <cause>"; the stderr tail goes to the DM log only.
- The thinking indicator times a beat from `opened_at`.
- `PUT /api/campaigns/{id}/marching-order {order}` is the host's route over `set_marching_order`.
- Modules imported before 0004 have no module text; there is no backfill, re-import them.

**Plateau 3** (built unattended; the chronicle lists every decision taken without the owner, with its reason)
- `0006_module_source` follows `0005_beats_story`, and `0007_campaign_world` follows `0006_module_source`. 0007 uses
  plain `ALTER TABLE`: a batch rebuild of `campaigns` would cascade-delete its characters.
- The `dscn` package's `VERSION` (3, since faithful modules: pregens) is in `dscn/container.py`; the reader takes 1 to 3. From v2 an `attachment` asset needs
  a `description` (`asset-description`; an empty string counts).
- A text's `markdown` is its whole file, front matter included; the editor keeps the front matter byte for byte and
  never shows it. Entity records keep the format's `gm`/`player`; texts and attachments say `dm`/`player`.
- A keyed heading also links to the one room whose label equals its title, when `match_node` finds none
  ("## 2. Throne Room" finds `throne_chamber` labelled "Throne Room"). `key-without-room` is warned only when the
  text's map exists and parses.
- An old module's revisions without a source get the one built from its bundle (`pin_legacy`), so they don't look
  changed.
- The export refuses (409, with the warnings) a module with `missing-attachment` or `missing-entity` warnings. It
  writes each heading that links itself as a `keys[]` entry, since `key:` refs resolve only there in a bundle; after
  an import those links are explicit keys.
- `PATCH /api/modules/{id}` refuses all of the importer's structural keys (also `title`, `worldmaps`, `start`). The
  text and entity PUTs answer the whole module's `links` and `warnings`.
- The editor writes an unchanged block back as it was read, and an edited block in the style of
  `fixtures/everything.md`. A PDF is inserted as a link, not an image. The module title is edited in Details.
- `show_image` refuses an unknown id, then a DM-only one, then a PDF. The table checks the pinned revision again
  before it writes an `image` entry. The campaign image route is for organisers until plateau 4's players.
- The SPA has one `EventSource`, shared through `EventsContext` (`web/src/api.ts`).
- `POST /api/campaigns`: `ruleset: null` counts as left out; only `setting` may be null.

## Carried into plateau 4

From plateau 5 (books and quick dungeons):
- **What it does:** "New module" offers an empty module, a `.dscn`, a PDF (ready to play or a draft) and "Describe
  the module you want". Conversions run in the background with progress, one at a time, and make the module at the
  end; a draft can't start a campaign until it is marked ready. Every module prints whole (`/modules/{id}/print`).
- **To check by hand** (none of it was tried with the real `claude` during the quest):
  - `make convert-live PDF=<a real module PDF>` (spends tokens): the timings per chunk, the warnings and the word
    coverage, then import the `.dscn` it leaves in `evals/recordings/conversions/` and read the texts against the
    book. They should be the book's own words, chapter by chapter, with no summary.
  - Each sketched map against its page in the book (the `map-sketched` warning names the page): the rooms, how they
    connect, and that every keyed heading links its room.
  - A PDF through the New module screen, with a reload and a Cancel in the middle of it.
  - A generated dungeon ("a dungeon with kobolds, no plot") played for a few beats with the real `claude`.
  - The print view in the browser's print dialog, saved as a PDF: page breaks before each text, map and section, and
    the maps' keys.
  - A scanned PDF on a machine without tesseract (every page a `page-not-read` warning and an image).
  - A large real PDF: the render cap (`page-too-large`), a vector-drawn map page, and a Cancel during the reading.
- **Fixed after the review** (the follow-ups):
  - The print view names a text once: a text whose Markdown starts with a `#` heading equal to its title has no part
    heading (a DM-only text keeps its "DM only" tag).
  - The module page keeps its conversion's warnings after a reload: without them in its navigation state, it shows
    those of the newest finished conversion that made the module (`GET /api/conversions`).
  - Side calls send their prompt on stdin, so a long prompt fits; the e2e fakes read it there.
  - A failed chunk stops the whole conversion at once (no more Claude calls). The entity pass is chunked like the
    text, and a failed entity call is an `entities-not-read` warning, not a failed job. An answer of one fenced block
    with prose around it keeps the block. A title without letters or digits gives the text id `text`.
  - What the conversion marks for the players is an `audience-player` warning (`text:<id>`, or `npc:<id>` and the
    like), to check.
  - Reading a PDF: a page rendered over 50 million pixels is lowered, with a `page-too-large` warning; a page drawn
    in vectors (10 or more lines, curves and rects, little text, no raster image) is kept as a picture page.
  - A cancel stops the reading of the PDF between pages (`read_pdf(should_stop=…)`, `ReadStopped`), and the job ends
    `cancelled`. An ended job stays ended: a late progress call writes nothing.
  - The PDF and the pictures go into the blob store streamed (`put_file`), not read whole into memory.
  - A text whose keys repeat (three or more keyed headings) isn't sketched: `map-not-drawn`, "The keys repeat in
    this text…".
  - `POST /api/conversions/pdf` checks the title and mode (422) before it reads the body; uploads left in
    `uploads/` by a stopped Delve are removed at start.
- **Still open:** a blob written just before a failed or cancelled job stays, unlinked (the store tolerates it, as for
  attachment uploads); nothing collects unlinked blobs yet.

From plateau 3:
- **To check by hand:** write a module in the editor from nothing; open, save unchanged and re-export a real module
  (the round-trip); show an image in a real session with the real `claude`.
- The players' routes (plateau 4) must serve campaign images to players, and keep the 404 rule.
- A revision from before plateau 3 writes its pinned source on its first image lookup, even from a GET.
- Still open from the first session: no tool deletes a character; the monster reference data is cut short; items
  without a weight count as 0 lb; the DM named the monster in a progress line.

## Carried into plateau 3

- **The eval gate passed on 2026-10-18** (`make evals-live EVAL_ARGS="--compare-ttrpg2"`, claude 2.1.302):
  - Delve has no findings on any of the four cases, and its DM called only `mcp__delve__` tools (ttrpg2's starts
    with 211 tools).
  - The first words come in 2–4 s on action beats. After the fix below, every beat both apps played is as fast as
    ttrpg2's or faster (`locked_door`: 27.8 s and 3.1 s, against 31.0 s and 6.5 s).
  - **A fix came out of it (`2f4bbf9`):** the provider took the DM's context from the `result` line, which adds up
    every API request of a reply. One beat with ten tool calls counted 346k for a 43k context, so the auto-reset
    fired after a single beat, and the next beat re-ran `session_primer`. The context now comes from the last
    request's usage, as in ttrpg2.
  - **Still open:** in `--compare-ttrpg2`, Delve's checks run on ttrpg2's recordings too, so `no_state_bypass` flags
    ttrpg2's own `mcp__ttrpg__*` and `ToolSearch` calls. Only the timings compare fairly until the checks map tool
    names per app.
  - Each case ran only once, so the timings are noisy.
- **The first real session was played on 2026-10-18** (the crypt, a dwarf fighter/cleric, through the trap, the
  seal puzzle and the fight with the wight, to his death). Fixed on the way, each with a test:
  - **The DM didn't know its module** (`24ccede`): ttrpg2's DM read it from the campaign's files, and nothing
    replaced them. The primer now has a `module` block (title, opening, headings, each map's start: its
    `party_start`, else its first room; `offline` when it doesn't parse), and the procedure says to run it. A module
    may have no maps.
  - **Sheet guesses refused** (`15ed426`): the tool schemas now type the sheet's collection fields.
  - **The players' map** (`df93db6`) opens framed on the party's room and follows it.
  - **No Known spells column for priests** (`2c174c7`).
  - **The players' feed leaked** (`fe7a00a`): it showed `setup_combat`'s monster stat block, the DM's inputs and
    refusal messages. A tool row is now `{name}` or `{name, failed}` (a real allow-list, spec §7.5), and old rows are
    served the same way. `DM_ONLY_KEYS` and `ToolSpec.dm_only_keys` are now unused by the feed: plateau 4's player
    routes (sheets, `GET …/characters` with NPC `notes_md`) should use them, or they go.
  - **`rules_lookup` crashed on a hyphen** (`7884899`): its words are now quoted terms.
- **Not tried yet in a real session:** a reload in the middle of a beat, and a `claude` killed during a beat.
- **Seen in the session, still open:**
  - No tool deletes a character (the DM renamed and overwrote one).
  - The monster reference data is cut short: the wight's special defences read "Hit only by silver or +1 or", its
    magic resistance "See below".
  - Items without a weight count as 0 lb (the medium shield).
  - A sheet stored with short save keys (`para`, `rsw`) rolls correctly, but the sheet shows those saves blank:
    `Sheet` should normalise save keys when it's written.
  - The DM named the monster in a progress line ("Ruling on the wight's touch"), and it didn't scale the module's
    fight for one 5 hp character. Both are prompt matters; an eval case could catch the first.
  - The Campaigns page doesn't say a module must be imported first, and the import hint still says the text "follows
    in a later plateau".
  - The campaign page's name-only character form invites the wrong path: characters are made in play.
  - A live eval writes its recordings into `evals/fixtures/`, where the offline evals then fail on them.
- **The session-start beat** is a long message, so `auto` effort makes it high, and the next beat respawns the resident
  (resuming the conversation) when its effort is low, as ttrpg2 does when its arguments change.

## Open questions for the owner

1. **Monsters under 1 HD:** a "1-2 hp" or "½ HD" creature saves as a 0-level warrior, and "1-1" counts as 1 HD. Is
   that how you play?
2. **THAC0 in the reference:** fix it from the PHB tables when 2b needs it?

## Next steps (as of 2026-10-18)

1. **Check plateau 4 by hand** (above, "Carried after plateau 4") and read its chronicle's decisions, then deliver it.
   Check the walkthrough fixes the same way ("To check by hand" above), then deliver them.
2. **Check plateaus 3 and 5 by hand** (above, "Carried into plateau 4").
3. ~~Write the plan for plateau 6~~ (done, built 2026-10-18 by quest `20261018-3eab4105`). **Check plateau 6 by
   hand** (above, "Carried after plateau 6") and read its chronicle's decisions, then deliver it.

4. **Check plateau 7 by hand** (above, "Carried after plateau 7") and read its chronicle's decisions, then deliver
   it.
5. **Check Settings by hand** (above, "Carried after Settings"), import the Darlene map with the owner as its
   delivery step, and read the quest's decisions taken without the human, then deliver it.

## Earlier next steps (as of the evening of 2026-10-17, done)

1. ~~Deliver 2a~~ (done, 2026-10-17 evening).
2. **Write the 2b plan** (`docs/superpowers/plans/…-plateau-2b-solo-play.md`):
   - the `claude -p` provider, as a resident process that is isolated (`--strict-mcp-config`, no file tools);
   - the tool host served over MCP on localhost with a secret;
   - the DM prompt from ttrpg2's hard constraints (DM procedure only);
   - module text and `module_lookup`;
   - the play screen with Act and Ask the DM, the players' feed through `player_view`, and recaps;
   - the eval gate against ttrpg2, and the 30 s first-words guideline.
   - The ttrpg2 DM-driver survey is in `docs/notes/2026-10-17-ttrpg2-dm-driver-survey.md`. Re-survey
     `ttrpg2/tools/dm_session.py` if needed.
3. **Add a browser check to 2b's "Done when"**, since nothing has been tried in a real browser yet.
4. **Route rules and design check-ins to the owner;** keep technical ones.

## Resuming after a break

1. Read this file, then the chronicle of the last delivered plateau.
2. In Guild (`/api/quests?app=delve`, or the Delve application page), check the running quest.
   - A quest stopped by a server restart is `interrupted`: resume it.
   - A quest that failed on a usage limit can be resumed by marking it `interrupted` (see
     `guild-self-analysis.md` backlog item 22).
3. Before delivering, check the result on a fresh clone with `make install && make ci`.
4. After delivering:
   - copy the chronicle into `docs/chronicles/`;
   - update the table and the decisions here;
   - commit and push.
