# Delve: Open fixes and PC names, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PCs the DM makes get their names from Delve's dice, and the walkthrough's small open fixes are done: the
sheet on a phone, the empty campaign, a scene told twice, hold back, Dutch terms, module audiences, a misplaced
encounter key, a compact print, the other screens, one missing test and the react-router upgrade.

**Architecture:** No new subsystem. Each task is a small, separate fix in the code that already owns the behaviour.
The tasks don't depend on each other's interfaces, so most of them can run in parallel (see "Order and parallel
work").

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core over SQLite, React 18 + TypeScript + React Query, vitest,
Playwright. No new Python dependency and no migration. One npm change: `react-router-dom` 6.30 → 7.18 (Task 12).

**Spec:** there is no design doc of its own. The requirements are `docs/backlog.md` (Features 18, and Fixes 2, 3, 4, 7
and 8) and the findings they cite in `docs/review/2026-10-18-walkthrough.md` (E6, E8, P5, P8, D3, T6, T7 and §6).
Each item was checked against master 35f8a16 on 2026-10-22. Items already fixed there are left out: the sheet opening
from the card, ability scores on the sheet, the play screen's "Ask the DM to build the party", and house rules on a
phone.

**Not in this plan** (owner, 2026-10-22): C6 (misread digits in stat lines), C7 (NPC stats left in the prose), E4 (a
"key this heading" picker) and E5 (`start` on sketched maps, and exits between maps). They go to a later conversions
and maps quest. Also left out: hiding other players' sheets (it needs an owner decision), Features 26 (a character
leaves the party), and the faithful-modules items in Fixes 2 (caption placement, errata, unresolved monster ids).

**Runs after:** the Carry the party on quest (20261022-3684addd), delivered as 3f2b21b, and the desktop UX branch,
merged before it. The references were checked again on 3f2b21b. The files and names hold, but line numbers moved by a
few lines, so find each reference by name. Three later changes matter:
- `delve.play.table` now makes the story entries of a `batch`'s steps (`STORY_MAKERS`, `_made_by`, `_make`), which
  touches Task 4;
- a tool row opens for the host (`tool_call_of`, `GET …/story/{entry}/tool`);
- the play state carries the party's purse (`coin`).

The desktop branch also changes these:
- Task 7: a module's Texts and entity lists are `PickList`s (`web/src/desktop/PickList.tsx`, drawn in view from 100 rows)
  inside `ListAndEditor`. The checkboxes go in each `render` row.
- Tasks 10 and 11:
  - a campaign or module row's actions are in its `RowMenu` (`web/src/components/RowMenu.tsx`);
  - a conversion's end is a sonner notification (`components/Toasts.tsx`, `Nav.tsx`'s `ConversionEnded`);
  - New module also takes dropped files (`desktop/useFileDrop.ts`), so the bad-`.dscn` message names a dropped file too.
- Task 12: `desktop/Desktop.tsx`, `components/RowMenu.tsx` and `desktop/Split.tsx` import from `react-router-dom` as well.

## Global Constraints

- **Earlier plans still apply:** `GUILD.md`, and the Global Constraints of plateaus 0–7, faithful modules, settings,
  portraits and images, novelization, looks and banners, and Carry the party on.
- **Every task leaves `make ci` green on its own,** tests first.
- **UI strings:** every new string is in both `web/src/i18n/en.json` and `nl.json`, next to its area's existing keys.
  The Dutch follows the existing words (DM, "afwachten", "uiterlijk"). Never "theme" or "skin" in the UI.
- **The fourth wall holds:** nothing in this plan shows a seat DM-only text, a dice-named character's hidden stats, or
  a tool's arguments that it didn't see before.
- **A looked-up term never breaks a page:** an unknown race, class, model or warning code falls back to the raw value.
- **The owner's live install keeps its data:** no task deletes or rewrites existing house rules, modules or
  characters. Task 10's house-rules change applies to fresh installs only.

## Review Focus

1. **A PC name the player gave in their act** ("I'm Brother Anselm") or one printed in the book (pregens). It's kept
   exactly. Only a PC with no name gets the dice's name. (Task 1, `test_create_character_keeps_a_given_name`.)
2. **A race the name generator doesn't know** ("half-ogre", "Aasimar", empty). The PC still gets a name, from the
   generator's fallback, and no error. (Task 1, `test_create_character_names_an_unknown_race`.)
3. **The same paragraph told twice because the model repeated itself across a tool call.** It shows once. A second
   paragraph that only starts the same way still shows. (Task 4.)
4. **A bulk audience change that names a ref that isn't in the module,** or mixes texts, entities and attachments.
   It's all or nothing: 422 naming the unknown ref, and nothing saved. (Task 7, `test_bulk_audience_unknown_ref_changes_nothing`.)
5. **A map with `room_numbers on` and book labels.** It still prints the number once, so the key reads "4. The
   Destroyed Caravan" whether the number comes from the label or from the renderer. (Task 9.)

## Decisions taken in this plan

1. **PC names:** `create_character`'s `name` becomes optional. Without a name, `characters.create` rolls one with
   `names.generate(ctx.dice.rng, race=…, female=…)` from the sheet's `race` and `gender`, as `introduce_npc` does for
   NPCs. The reply says `"named_by": "dice"`, so the DM uses the name instead of renaming the character.
2. **D3:** the cause isn't known (no walkthrough DB is kept). The plan pins the stream parser's orders with tests and
   adds one guard: a beat's `dm_text` whose text, with whitespace collapsed, equals an earlier `dm_text` of the same
   beat is dropped and logged. Prefixes are not dropped (Review Focus 3).
3. **T6:** only the wording changes. The timer closing the beat for the host too is by design.
4. **T7:** races, classes, genders and alignments get Dutch names through a lookup with a raw fallback. Item, weapon
   and spell names stay as the DM or the book wrote them. Settings warnings get codes, and the web translates them.
5. **E6:** a bulk audience action, not a per-blockquote audience. Read-aloud boxes keep their text's audience.
6. **E8:** texts flow without a page break each. Page breaks stay before maps and before each top-level part. One
   note on the title page says that everything is DM material unless it's marked **Players**, and only player items
   carry a tag.
7. **§6 house rules:** a fresh install starts with an empty library. The House rules page offers "Import the example
   rules", which runs the import `delve house-rules import` runs today.
8. **§6 Preferences:** "Side passes" becomes **Helper tasks** / **Hulptaken**. The fake image backend stays the
   default for scenes and possessions, but its row shows a warning. The claude-cli models get labels, and EN/NL is
   also switchable from the sidebar's footer.
9. **react-router:** 7.18, the newest 7.x. Not 8.x, which is a later decision.

---

## File structure

```
src/delve/dm/tools/party.py, play/characters.py, dm/prompt/dm.md            PC names from the dice     (Task 1)
web/src/campaign/CharacterSheet.tsx, styles.css                             the sheet on a phone       (Task 2)
web/src/routes/CampaignDetail.tsx, campaign/MapStatePanel.tsx               the empty campaign page    (Task 3)
src/delve/play/table.py, dm/claude_cli/stream.py                            a scene told once          (Task 4)
web/src/play/HostControls.tsx                                               hold back's wording        (Task 5)
web/src/i18n/terms.ts (new), CharacterSheet.tsx, Join.tsx, PregenPicker.tsx,
  src/delve/domain/settings.py, web/routes/preferences.py, Preferences.tsx  Dutch terms and warnings   (Task 6)
src/delve/web/routes/module_source.py, web/src/routes/ModuleDetail.tsx,
  web/src/module/AudienceBar.tsx (new)                                      bulk audiences             (Task 7)
src/delve/modules/books/convert.py                                          "from area 2"              (Task 8)
web/src/routes/ModulePrint.tsx, MapPrint.tsx, *.module.css, maps/dsl/render/classic_bw.py  print     (Task 9)
src/delve/__main__.py, play/house_rules.py, web/routes/house_rules.py, HouseRules.tsx,
  styles.css, App.tsx, Preferences.tsx, Nav.tsx, dm/claude_cli/provider.py  house rules, links, Preferences (Task 10)
web/src/routes/Campaigns.tsx, Play.tsx, NewModule.tsx, module/ConversionProgress.tsx,
  web/routes/campaigns.py, modules.py, conversions/runner.py, modules/dscn/container.py  forms and pages (Task 11)
web/package.json and every react-router import                              react-router 7             (Task 12)
docs/backlog.md, docs/progress.md, README.md                                docs                       (Task 13)
```

---

### Task 1: PC names from the dice (Features 18)

**Files:**
- Modify: `src/delve/dm/tools/party.py` (`create_character`, ~93-112), `src/delve/play/characters.py` (`create`, 128-135),
  `src/delve/dm/prompt/dm.md` (the pregens paragraph ~238-243, and the NPC-naming rule ~331-338)
- Test: `tests/play/test_characters.py`, `tests/dm/tools/test_tools.py`, `tests/dm/test_prompt.py`

**Interfaces:**
- Produces: `characters.create(ctx, *, name: str = "", kind: Kind = "pc", sheet: dict) -> Character`, which names an
  unnamed character by the dice. `create_character`'s reply gains `"named_by": "dice" | "given"`.

- [ ] **Step 1: Write the failing tests** in `tests/play/test_characters.py`:
  - `test_create_character_names_by_dice`: `create(ctx, sheet={"race": "dwarf", "gender": "female", "cls": "fighter", …})`
    with a seeded dice. The name is non-empty, and it equals `names.generate(<same seed>, race="dwarf", female=True)`.
  - `test_create_character_keeps_a_given_name`: `name="  Brother Anselm "` gives `"Brother Anselm"`, and no dice are
    drawn (the rng's state is unchanged).
  - `test_create_character_names_an_unknown_race`: `race="half-ogre"` and `race=""` both give a non-empty name.
  - In `tests/dm/tools/test_tools.py`, `test_create_character_name_is_optional`: `name` is not in the tool schema's
    `required`, and a call without it answers `named_by == "dice"`.
- [ ] **Step 2: Run them:** `uv run pytest tests/play/test_characters.py tests/dm/tools/test_tools.py -k "name" -v`.
  Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `create`: an empty name is rolled with `names.generate(ctx.dice.rng, race=str(sheet.get("race", "")),
    female=str(sheet.get("gender", "")).strip().lower() == "female")`.
  - `create_character`: use `params("sheet", name=string(…))`. The description: "The name the player or the book gives.
    Leave it out and the dice name the character for its sheet's race and gender."
  - `dm.md`: next to the NPC rule, add "A PC you make up gets no name from you: leave `name` out. Pass a name only when
    the player gave it or the book prints it (pregens)."
- [ ] **Step 4: Run the tests.** Then add one line to `tests/dm/test_prompt.py` asserting that the new rule is in the
  prompt, and run `uv run pytest tests/dm tests/play -q`. Expected: PASS.
- [ ] **Step 5: Commit:** `git commit -m "A PC the DM makes up is named by the dice"`

### Task 2: The sheet on a phone (P5)

**Files:**
- Modify: `web/src/campaign/CharacterSheet.tsx` (the stats `<dl>`, ~131-152), `web/src/styles.css` (`.sheet-stats`,
  `.sheet-stats dd`, ~1416-1438)
- Test: `web/src/campaign/CharacterSheet.test.tsx`, `web/e2e/phone.spec.ts`

- [ ] **Step 1: Write the failing test** `"formats XP and HP with the reader's separators"`: XP 12345 reads "12,345"
  in en and "12.345" in nl, and HP reads "61 / 62" inside one element with class `nowrap`.
- [ ] **Step 2: Run it:** `cd web && npx vitest run src/campaign/CharacterSheet.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Format XP and HP with the `Intl.NumberFormat(useLanguage())` that `XpProgressLine` already uses.
  - In CSS, `.sheet-stats` becomes `grid-template-columns: repeat(auto-fit, minmax(4.5rem, 1fr))`. Its `dd` gets
    `white-space: nowrap`, and its `dt` gets `overflow-wrap: anywhere`.
- [ ] **Step 4: Run the test.** Add a 390 px sheet screenshot to `phone.spec.ts` (`sheet-390.png`) with a check that
  no `.sheet-stats dd` is taller than one line (`boundingBox().height < 2 * line-height`). Run `make ci`.
- [ ] **Step 5: Commit:** `git commit -m "The sheet's stats fit a phone, and its numbers have separators"`

### Task 3: The empty campaign's page (P8)

**Files:**
- Modify: `web/src/routes/CampaignDetail.tsx` (~164-218), `web/src/campaign/MapStatePanel.tsx`
- Test: `web/src/routes/CampaignDetail.test.tsx`, `web/src/campaign/MapStatePanel.test.tsx`

- [ ] **Step 1: Write the failing tests.**
  - `"an empty campaign's first step is play"`: with no characters, the page shows a primary link,
    `campaign.firstStep` ("Start play: the DM builds the party"), to `/play/<id>`.
  - `"the map state tool waits for a placed party"`: with maps but no one placed, there's no `MapStatePanel`. With
    someone placed, it's inside a closed `<details>` whose summary is `campaign.mapStateFix` ("Fix a map by hand").
  - In `MapStatePanel.test.tsx`, `"doors and secrets are picked from the map"`: the door and secret fields are
    `<select>`s with the current map's doors and secrets, and there's no free-text input for them.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** The door and secret lists come from the map state the panel already reads. If the map
  has none, the select shows one disabled option, `mapState.none`.
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit:** `git commit -m "An empty campaign starts from play, and the map state tool waits for a party"`

### Task 4: A scene is told once (D3)

**Files:**
- Modify: `src/delve/play/table.py` (`_shown` 289, `_end_reply` 299, `PendingCalls`), and possibly
  `src/delve/dm/claude_cli/stream.py` (`deltas_seen`, ~58)
- Test: `tests/dm/claude_cli/test_stream.py`, `tests/play/test_table.py`

**Interfaces:**
- Produces: `PendingCalls.told: set[str]`, the beat's shown `dm_text` texts with whitespace collapsed. It's kept for
  the beat, not reset per reply.

- [ ] **Step 1: Write the stream tests** in `test_stream.py`:
  - `test_text_after_a_tool_use_without_deltas_shows_once`: deltas, then a `tool_use`, then a second assistant message
    whose full text block came with no deltas.
  - `test_full_block_before_its_deltas_shows_once`.
  
  Each asserts that the joined text events equal the text exactly once.
- [ ] **Step 2: Run them:** `uv run pytest tests/dm/claude_cli/test_stream.py -v`. If one fails, fix `stream.py`: reset
  `deltas_seen` per assistant message (`message_start`), not only at `result`. Run them again until they PASS.
- [ ] **Step 3: Write the table tests** in `test_table.py`:
  - `test_a_paragraph_told_again_after_a_tool_is_dropped`: feed text P, a tool call and its result, then P again with
    different whitespace. One `dm_text` holds P, and the log has a warning.
  - `test_a_paragraph_that_starts_the_same_still_shows`: P, then a tool, then P + " More." gives two entries.
- [ ] **Step 4: Implement** the guard in `_shown`/`_end_reply`. Collapse whitespace with `" ".join(text.split())`, and
  drop and `log.warning` an exact repeat. Run `uv run pytest tests/play tests/dm -q`. Expected: PASS.
- [ ] **Step 5: Commit:** `git commit -m "A paragraph the DM repeats across a tool call is told once"`

### Task 5: Hold back says what it holds back (T6)

**Files:**
- Modify: `web/src/play/HostControls.tsx` (~139-151); `en.json`/`nl.json` (keys at ~1188-1190)
- Test: `web/src/play/HostControls.test.tsx`

- [ ] **Step 1: Write the failing test** `"the timer's choice names the characters it applies to"`. The select's label
  is "When the time runs out, characters whose player hasn't acted:". Its options are "Do nothing (hold back)" and
  "Are played cautiously by the DM". A hint under it reads "The timer closes the beat for the host's characters too."
- [ ] **Step 2: Run it.** Expected: FAIL.
- [ ] **Step 3: Implement** the new strings. The Dutch: "Als de tijd om is, doen personages van wie de speler niet
  handelde:", "Niets (afwachten)", "Voorzichtig gespeeld door de DM", and "De timer sluit de beurt ook voor de
  personages van de host." Add the hint under the select.
- [ ] **Step 4: Run the test and `make ci`.**
- [ ] **Step 5: Commit:** `git commit -m "Hold back says whose characters it holds back"`

### Task 6: Dutch terms and translated warnings (T7)

**Files:**
- Create: `web/src/i18n/terms.ts`, `web/src/i18n/terms.test.ts`
- Modify:
  - Web: `web/src/campaign/CharacterSheet.tsx` (~64-73), `web/src/routes/Join.tsx` (~227),
    `web/src/play/PregenPicker.tsx` (~46), `web/src/routes/Preferences.tsx` (~91-96, 227-239), `styles.css`
    (`.join-characters`, ~3115-3144), `en.json`/`nl.json`
  - Python: `src/delve/domain/settings.py` (82-142), `src/delve/web/routes/preferences.py` (~86)
- Test: `tests/domain/test_settings.py`, `web/src/routes/Preferences.test.tsx`, `web/src/routes/Join.test.tsx`

**Interfaces:**
- Produces: `term(t: TFunction, kind: "race" | "class" | "gender" | "alignment", value: string): string`. It
  normalises `value` (lowercase, with spaces and hyphens removed) and looks up `${kind}.${key}`, falling back to
  `value`. Settings warnings become `{code: str, args: dict[str, str], text: str}`, where `text` is today's English
  string.

- [ ] **Step 1: Write the failing tests.**
  - `terms.test.ts`: `term(nl, "race", "Half-Elf")` is "Halfelf", and `term(nl, "class", "Fighter")` is "Krijger".
    `term(nl, "race", "Half-ogre")` is "Half-ogre". In en, `term(en, "class", "fighter")` is "Fighter".
  - `test_settings.py`: an unavailable provider gives `code == "provider_unavailable"`, with `args["provider"]` and the
    old `text`.
  - `Preferences.test.tsx`: in nl, that warning renders the Dutch `settings.warning.provider_unavailable`.
  - `Join.test.tsx`: in nl, a fighter row reads "Krijger".
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Keys: the PHB races (human, elf, halfelf, dwarf, gnome, halfling) and classes (fighter, paladin, ranger, mage,
    illusionist, cleric, druid, thief, bard), `gender.male`/`gender.female`, and the nine alignments, in en and nl.
  - One code per warning that `settings.py` produces (read them all from 82-142).
  - Preferences renders `t("settings.warning." + code, args)`, falling back to `text` for an unknown code. Provider
    `problem` strings stay as they are.
  - `.join-characters label` becomes `display: grid; grid-template-columns: minmax(8rem, max-content) 1fr`.
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit:** `git commit -m "Races, classes and settings warnings in the reader's language"`

### Task 7: Setting many audiences at once (E6)

**Files:**
- Create: `web/src/module/AudienceBar.tsx`, `web/src/module/AudienceBar.test.tsx`
- Modify: `src/delve/web/routes/module_source.py` (new route), `web/src/api.ts`, `web/src/routes/ModuleDetail.tsx`
  (`TextsTab` ~462-560, `EntitiesTab` ~616), `web/src/module/AttachmentsPanel.tsx`
- Test: `tests/web/test_module_source_api.py`

**Interfaces:**
- Produces: `POST /api/modules/{id}/audience` with body `{refs: list[str], audience: "gm" | "player"}`. A ref is
  `text:<id>`, `<entity kind>:<id>` or `asset:<id>`. The reply is `{changed: int}`, from one source save (one revision
  bump). It answers 422 when a ref is unknown, and nothing changes. Drafts and published modules are handled as the
  per-item edits handle them today, with the same permission (organisers).
- Produces: `setAudiences(moduleId, refs, audience)` in `api.ts`, and
  `<AudienceBar selected={string[]} onDone={() => void} moduleId />`.

- [ ] **Step 1: Write the API tests.**
  - `test_bulk_audience_sets_texts_entities_and_assets`: three refs of three kinds change, `changed == 3`, and the
    revision is bumped once.
  - `test_bulk_audience_unknown_ref_changes_nothing`: one good ref and `text:nope` give 422 naming `text:nope`, and
    the good one is unchanged.
  - `test_bulk_audience_needs_an_organiser`: a player seat gets 403.
- [ ] **Step 2: Run them:** `uv run pytest tests/web/test_module_source_api.py -k bulk -v`. Expected: FAIL.
- [ ] **Step 3: Implement the route.** It reuses the per-item audience setters the existing PATCH routes use, inside
  one save.
- [ ] **Step 4: Write the web test,** then build the UI.
  - `AudienceBar.test.tsx`: `"sets the chosen items for the players"`. Ticking two texts shows the bar, and "For the
    players" posts both refs and clears the ticks.
  - Each row of the Texts, entity and attachments lists gets a checkbox, with "Select all" in each list's header.
  - The bar shows "N chosen" with **For the players** and **DM only**.
- [ ] **Step 5: Run `make ci`** and commit: `git commit -m "A module's texts, entities and pictures change audience together"`

### Task 8: "Guards from area 2" is a reference, not a key

**Files:**
- Modify: `src/delve/modules/books/convert.py` (`_PLACED` 165, `_placed_in` 773-793)
- Test: `tests/modules/books/test_convert.py` (next to `test_key_entities_links_an_encounter_named_by_area`, ~561)

- [ ] **Step 1: Write the failing tests.**
  - `test_key_entities_skips_an_area_named_as_a_source`: in room 5, an encounter whose summary reads "Guards from
    area 2 rush in" isn't keyed to room 2. It falls through to `_by_creature` or stays unkeyed, as an unplaced one does.
  - `test_key_entities_still_keys_in_area`: "Lurks in area 2" is keyed to 2.
- [ ] **Step 2: Run them.** Expected: the first FAILS.
- [ ] **Step 3: Implement.** In `_placed_in`'s loop, skip a match when
  `re.search(r"\b(from|of|to|towards?|near|beyond|past|than)\s+(the\s+)?$", summary[: m.start()], re.I)` matches, and
  go on to the next match.
- [ ] **Step 4: Run `uv run pytest tests/modules/books -q`.** Expected: PASS, the existing area-31 cases included.
- [ ] **Step 5: Commit:** `git commit -m "An area an encounter comes from doesn't key it"`

### Task 9: A compact print with single numbering (E8)

**Files:**
- Modify:
  - Web: `web/src/routes/ModulePrint.tsx` (~86-90, 180, 257, 351), `ModulePrint.module.css`, `MapPrint.tsx`
    (`MapKey`, ~162-216), `MapPrint.module.css` (~256-259)
  - Python: `src/delve/maps/dsl/render/classic_bw.py` (`_room_floor`, ~823-828)
- Test: `web/src/routes/ModulePrint.test.tsx`, `tests/maps/dsl/test_render_classic.py`

- [ ] **Step 1: Write the failing tests.**
  - Python: `test_room_floor_says_when_numbers_are_off`. A map with `room_numbers off` gives each floor path
    `data-numbered="false"` and keeps `data-number`. A map with `room_numbers on` gives no `data-numbered` attribute.
  - Web, `"the map key numbers each room once"`: an SVG fixture with `data-label="4. The Destroyed Caravan"` and
    `data-numbered="false"` shows "4. The Destroyed Caravan" and no "1.". With numbers on and a plain label, it shows
    "1. Hall".
  - Web, `"texts flow, and only player items are tagged"`: no text `.part` has the page-break class; maps do. The
    title page holds the note `print.dmUnlessMarked`. A player text shows the tag **Players**, and a gm text shows no
    tag.
  - Web, `"a text titled as the module isn't a second title"`: a text whose title equals the module's title shows
    no heading of its own.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `break-before: page` moves from `.part` to `.part.map` and to each top-level part.
  - The title page has no forced break after it when the first part is a text.
  - `MapKey` drops its number span when `data-numbered="false"`. When the label already starts with the number, it
    also drops the span (Review Focus 5).
- [ ] **Step 4: Run `make ci`.** Print the Tomb of Horrors (or any converted module in the dev DB) and note the page
  count in the commit body.
- [ ] **Step 5: Commit:** `git commit -m "The print flows its texts, tags only what players may see, and numbers rooms once"`

### Task 10: House rules, links and Preferences (§6)

**Files:**
- Modify:
  - House rules: `src/delve/__main__.py` (`_serve`, 154), `src/delve/play/house_rules.py`,
    `src/delve/web/routes/house_rules.py` (new route), `web/src/routes/HouseRules.tsx`
  - Links: `web/src/styles.css` (`:root`, the dark block, base `a`, `.skip-link`), `web/src/looks/gold-wood.css` (61),
    `dark-dungeon.css` (88), `web/src/App.tsx` (`Shell`, 214-225)
  - Preferences: `web/src/routes/Preferences.tsx`, `web/src/components/Nav.tsx`, `src/delve/web/routes/preferences.py`
    (~85), `src/delve/dm/claude_cli/provider.py` (49), `en.json`/`nl.json`
- Test: `tests/test_serve.py` (40-60, 110), `tests/web/test_house_rules_api.py`, `web/src/App.test.tsx`,
  `web/src/looks/contrast.test.ts`, `web/src/routes/Preferences.test.tsx`, `web/src/components/Nav.test.tsx`,
  `tests/web/test_preferences_api.py`

**Interfaces:**
- Produces: `POST /api/house-rules/import-example` (owner only). It runs `import_house_rules` from `SEED_DIR` and
  answers the bundle. It's idempotent: a second call answers the existing bundle.
- Produces: `development: bool` on each backend in the Preferences backends JSON.

- [ ] **Step 1: House rules.**
  - Change `tests/test_serve.py` so a fresh `serve` leaves the library empty. Add
    `test_import_example_house_rules_once` to the API test. Run them: FAIL.
  - Drop the seed call. Add the route, and an empty-library prompt on the House rules page with an **Import the
    example rules** button.
  - Run them: PASS.
- [ ] **Step 2: Links and a skip link.**
  - Tests: `App.test.tsx` `"the first Tab reaches Skip to content"`, which moves focus to `main#content`. In
    `contrast.test.ts`, `--link` on `--bg` is ≥ 4.5:1 in Delve today, its dark set and both looks.
  - Add `--link`/`--link-visited` tokens, the base `a` rule and the `.skip-link` (visually hidden until focused).
    The looks set `--link` instead of their own `a` rules.
  - Run the tests: PASS.
- [ ] **Step 3: Preferences.**
  - Tests: `job.side` reads "Helper tasks" / "Hulptaken". A scene row on a development backend shows
    `preferences.developmentWarning` ("Fake pictures: for development, not play"). Claude models read "Opus (most
    capable)", "Sonnet" and "Haiku (fastest)", with no bare "default". The Nav footer has an EN/NL toggle that saves
    `language`.
  - Update the old asserts in `Preferences.test.tsx` (114-118).
  - Implement: `model_info` on the claude-cli provider, without the "default" model, and `development` from the
    registry's `development(...)` wrapper.
  - Run the tests: PASS.
- [ ] **Step 4: Run `make ci`.**
- [ ] **Step 5: Commit**, one commit per step:
  - `"A fresh install starts with no house rules, and imports the example on request"`
  - `"Links follow the look, and a skip link leads to the content"`
  - `"Preferences: plain labels, a warning on fake pictures, and the language in the sidebar"`

### Task 11: Forms and pages (§6)

**Files:**
- Modify:
  - Web: `web/src/routes/Campaigns.tsx` (100-190), `web/src/routes/Play.tsx` (`PlayScreen` after ~282, `errorText`
    84-88), `web/src/routes/NewModule.tsx` (~177), `web/src/module/ConversionProgress.tsx` (69)
  - Python: `src/delve/web/routes/campaigns.py` (`create_campaign` 145-160), `src/delve/web/routes/modules.py`
    (`module_json` 41-47, the import error ~154), `src/delve/conversions/runner.py` (222),
    `src/delve/modules/dscn/container.py` (115)
- Test: `web/src/routes/Campaigns.test.tsx`, `web/src/play/Play.test.tsx`, `web/src/routes/NewModule.test.tsx`,
  `tests/web/test_campaigns_api.py`, `tests/conversions/test_runner.py` (382, 531),
  `tests/modules/dscn/test_scn_container.py` (111)

**Interfaces:**
- Produces: `module_json` gains `empty: bool` (no texts, no entities, and only maps with no rooms).
  `POST /api/campaigns` on an empty module answers 409 "This module is empty: write or import something first."

- [ ] **Step 1: Write the failing tests.**
  - **New campaign:**
    - An empty name submit shows `campaigns.nameNeeded`, sets `aria-invalid` and focuses the input.
    - With no playable modules, the select shows "No module yet", and the hint is inside the Module field.
    - Empty modules aren't offered.
    - API: an empty module gives 409.
  - **`/play/cmp_nope`:** a 404 renders a plain page with `play.notFound` and a link to `/play`, and no story or
    header.
  - **Generated dungeon:**
    - A 200-character request is cut at a word, with "…", within 80 characters.
    - The tag reads `newModule.makes.<mode>` ("Makes a playable module" / "Makes a draft").
  - **Bad `.dscn`:** the message is "this is not a .dscn file (it isn't a zip archive)", and the web shows "Not
    imported: <file name>: …".
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Use `textwrap.shorten(first_line, 80, placeholder="…")` for the title. Pass the file name
  to `modules.importFailed` as `{file}`.
- [ ] **Step 4: Run `make ci`.**
- [ ] **Step 5: Commit:** `git commit -m "Clear forms and pages: campaign names, empty modules, unknown campaigns, imports"`

### Task 12: The missing Generate test, and react-router 7

**Files:**
- Modify: `web/src/routes/NewModule.test.tsx`, `web/package.json`, `web/package-lock.json`, `web/src/App.tsx` (78-87),
  and the 33 source and 21 test files that import `react-router-dom`
- Test: the whole web suite and `make e2e-browser`

- [ ] **Step 1: Write the Generate test.** In `NewModule.test.tsx`, `"Generate waits for a conversion found after a
  reload"`: `GET /api/conversions` answers a running conversion. Choose "Describe the module you want" and type a
  request: Generate and Convert are disabled. A `done` event enables Generate. Run it (it may pass at once; it pins
  the reload path). Commit: `"Generate waits for a conversion found after a reload"`.
- [ ] **Step 2: Upgrade.** Run `cd web && npm install react-router@7.18 react-router-dom@7.18`. Drop the `future`
  options in `App.tsx` (all of them are v7 defaults). Imports can stay on `react-router-dom`, which 7 re-exports.
- [ ] **Step 3: Check `useBlocker`** (`MapEditor.tsx:480`) and the two `lazy` routes (`App.tsx:65, 70`) against the v7
  changelog. Run `npx tsc --noEmit` and fix the type changes.
- [ ] **Step 4: Run `make ci` and `DELVE_E2E_PORT=20000 make e2e-browser`.** Expected: everything passes, and
  `npm audit --omit=dev` lists no react-router advisory.
- [ ] **Step 5: Commit:** `git commit -m "react-router 7.18"`

### Task 13: Docs

**Files:**
- Modify:
  - `docs/backlog.md`: strike Features 18, and the done lines in Fixes 2, 3, 4, 7, 8 and 9, as earlier plans did
    ("Done in the open fixes plan, Task N").
  - `docs/progress.md`: an entry for this plan.
  - `README.md`: house rules start empty with an example to import, the bulk audience action, and the language
    switch in the sidebar.
  - `docs/glossary.md`: **helper tasks**, if the glossary has "side pass".

- [ ] **Step 1: Write the docs** in each file's own style.
- [ ] **Step 2: Run `make ci`.**
- [ ] **Step 3: Commit:** `git commit -m "Open fixes and PC names: docs"`

---

## Order and parallel work

- Tasks 1–11 touch separate files, apart from `en.json` and `nl.json`, where each task adds its keys next to its own
  area's keys. They can run in parallel.
- Tasks 2 and 6 both touch `CharacterSheet.tsx`, in different parts. Tasks 10 and 2 both touch `styles.css`, in
  different rules. Merge them one after the other.
- Task 12 runs after Tasks 1–11 are merged, because it touches every router import.
- Task 13 runs last.

## Owner's hand checks after delivery

- Ask the real DM to "make me a party of four" for a new campaign. Do the names read like Delve's, not the model's?
- The sheet on a real phone, in Dutch.
- Print a converted module. Is it compact enough, and are its maps keyed once?
- A fresh install, or a scratch `DELVE_HOME`: the House rules page and Import the example rules.
