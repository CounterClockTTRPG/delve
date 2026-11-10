# Walkthrough fixes: book pages kept, books' numbers kept, entities keyed, and the screens that slowed play

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix what the UK7 walkthrough (`docs/review/2026-10-18-walkthrough.md`) and the owner's hand checks of plateaus 3–5 found, in nine tasks that can mostly run side by side.

**Architecture:** No new subsystem; each task changes one area.
- The PDF reader keeps the pictures of scanned pages that aren't text, and recognises map pages.
- The conversion keeps the book's numbers, merges same-name entities, keys entities to rooms, and labels sketched maps as invented.
- The web app gets usable warnings and progress, a play screen with the party in view, phone layouts, and a complete character sheet.
- The DM prompt and Ask the DM get what they lack.

**Tech Stack:** Python 3.12 (FastAPI, SQLAlchemy, pdfplumber, tesseract via `delve.modules.books.pdf`), React + TypeScript (vitest, Playwright e2e).

**Spec:** `docs/superpowers/specs/2026-10-17-unified-app-design.md`, and the evidence:
- `docs/review/2026-10-18-walkthrough.md`: the finding ids C1–C11, E1–E10, P1–P8, D1–D4 and T1–T9 below are its;
- `docs/review/2026-10-18-tomb-of-horrors.md`: Task 9 writes it from the notes in this plan.

## Global Constraints

- Read `GUILD.md`, `docs/glossary.md` (it wins on words: DM, beat, map state, seat, organiser, host) and `docs/data-dictionary.md` first.
- `make ci` must pass before each commit. Work test-first: a failing test, the code, the passing test, a commit with the task's message.
- Tests never run the real `claude` or tesseract. Use `delve.dm.fake`, the fake `claude` executable and the `ocr` callable that `read_pdf` takes.
- Use the temporary `DELVE_DATA_DIR` Guild gives every agent, and never touch `~/.local/share/delve`. Don't use ports 5000, 7777, 7790, 7810 or 8000.
- Every user-visible string goes in `web/src/i18n/en.json` and `nl.json`, and `nl` has every key `en` has.
- No new dependency, Python or web.
- A new or changed stored value is documented in `docs/data-dictionary.md`. A new migration goes after the latest in `src/delve/storage/migrations/versions/`.

## Review Focus

1. **A scanned text page with a picture on it** (a column of text beside an illustration) must still become text. Keeping pictures must not turn real text pages into images. (Task 1 test: an OCR result of 400 real words keeps its text.)
2. **A born-digital PDF** (the Tomb of Horrors kind: a text layer on pages 3–13) must convert exactly as today. Only scanned pages change. (Task 1 test: a text-layer page goes the old path, unchanged.)
3. **Two NPCs with one name who are really two people** ("Bernhardt the elder" / "Bernhardt"): merging by exact name only, after trimming and case-folding, never fuzzy. (Task 3 test.)
4. **A seat that isn't the host** must not see tool rows or OOC notes for the host after Task 5 and Task 6. The host still sees tool rows. (Task 5 and Task 6 tests.)
5. **A phone at 390 px:** no screen this plan touches may scroll sideways. (Task 7 e2e check of `document.documentElement.scrollWidth <= 390` on each screen.)

---

### Task 1: Keep the pictures of scanned pages that aren't text, and recognise map pages (C1, C2, C5)

**Files:** Modify `src/delve/modules/books/pdf.py`. Test `tests/modules/books/test_pdf.py`.

**Interfaces:**
- Produces, in `pdf.py`:
  - `MIN_TEXT_WORDS = 150`, and `MIN_REAL_SHARE = 0.6`.
  - `real_share(text: str) -> float`: the share of tokens of three or more characters that look like words. A word here is letters only, with a vowel, and is not one letter repeated.
  - A scanned page (fewer than `MIN_PAGE_CHARS` characters in its text layer, and an image) **is text** only when its OCR has at least `MIN_TEXT_WORDS` words and a `real_share` of at least `MIN_REAL_SHARE`.
    - Otherwise it is a picture page: `PdfPage(number, "", True, [Picture(number, render, 1.0)])`.
    - Its OCR text is **not** kept as page text, so no OCR junk reaches a text.
  - `PdfPage` gains `map_page: bool` (default `False`). It is True for a picture page when either:
    - its OCR holds at least two of the map words (`door`, `secret`, `stairs`, `trap`, `pit`, `scale`, `map`, `north`, `corridor`, `legend`), case-insensitive; or
    - it holds at least 8 tokens that are 1–3-digit numbers.
  - `PdfPage` gains `ocr_text: str`: what OCR read, kept for map detection and Task 2's headings, never as module text.
  - `MIN_OCR_CHARS` and its rule go.

- [ ] **Step 1: Write the failing tests** (a fake `ocr` returns the text; a PDF made of one scanned image per page, as in the existing tests):
  - `test_a_scanned_map_page_with_a_legend_is_kept_as_a_picture`: OCR text `"FALSE DOOR SECRET DOOR STAIRS UP COVERED PIT 1 2 3 4 5 6 7 8 9 10 11 12"` gives a page with no text, one 1.0 picture, and `map_page` True.
  - `test_a_handout_read_as_junk_is_kept_as_a_picture`: `"Ue A A NE OM TON NIL ON b i 10 wePr. Wena Sylar"` repeated 20 times gives a picture, text `""`, and `map_page` False.
  - `test_a_scanned_text_page_stays_text`: 400 words of real English gives text and no pictures (Review Focus 1).
  - `test_a_text_layer_page_is_unchanged`: the existing behaviour for born-digital pages (Review Focus 2).
- [ ] **Step 2: Run** `uv run pytest tests/modules/books/test_pdf.py -q`: the new tests fail.
- [ ] **Step 3: Implement** the Interfaces above.
- [ ] **Step 4: Run** `make ci`; it passes.
- [ ] **Step 5: Commit** `git commit -m "Scanned pages that aren't text keep their picture, and map pages are recognised"`

### Task 2: Book map pages in the module, sketches labelled as invented, and chapter title pages (C1, C2, C10)

**Files:**
- Modify `src/delve/modules/books/convert.py` (`_attachments`, `_headings`), `src/delve/conversions/runner.py` (`_sketch_maps`, `_keyed`), `web/src/routes/ModuleDetail.tsx` (the Maps tab) and `web/src/routes/MapEditor.tsx`.
- Test `tests/modules/books/test_convert.py`, `tests/conversions/test_runner.py` and the web tests of the Maps tab.

**Interfaces:**
- Consumes: `PdfPage.map_page` and `PdfPage.ocr_text` from Task 1.
- Produces:
  - **A map page becomes an attachment** with id `map-page-<n>` and description `"Page <n>: a map from the book"`, plus the OCR's first title-like line when there is one (for example `"Page 46: a map from the book (Map C – The Cloud Castle)"`). It gets a `book-map` warning naming it, instead of `image-to-describe`.
  - **Sketched maps:**
    - Each one's DSL source begins with the comment `// Sketched from the room key: an invented layout. The book's map is asset:map-page-<n>.` It names the nearest map page, or says `No map page was found in the book.`
    - Its `map-sketched` warning says "invented layout".
    - A sketched map is named after the map page's title when there is one (slugified, as maps are named today), and otherwise after its text's title. It is never named after the module's title.
  - **On the Maps tab and in the map editor,** a map whose source starts with that comment shows a notice: "Sketched from the room key: the layout is invented." With a book page, the notice adds a "Show the book's map" link that opens the attachment.
  - **Chapter title pages:** a picture page whose `ocr_text` holds a title-like line (one to six words, at most 60 characters, no full stop) starts a new text at that title. So "Death in the Skies" is its own chapter again.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_map_page_becomes_a_book_map_attachment`
  - `test_a_sketch_says_it_is_invented_and_names_the_book_page`
  - `test_a_sketched_map_is_named_after_the_map_page_title`
  - `test_a_picture_title_page_starts_a_chapter`
  - and a web test: the Maps tab shows the notice and the link for a sketched map, and no notice for a drawn one.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the Interfaces above.
- [ ] **Step 4: Run** `make ci`; it passes.
- [ ] **Step 5: Commit** `git commit -m "Book map pages kept in the module, sketched maps labelled as invented, and picture title pages start chapters"`

### Task 3: The book's numbers kept, same-name entities merged, entities keyed to rooms (C3, C4, C6, C11, E3)

**Files:**
- Modify `src/delve/modules/books/convert.py` (`_checked`, `_entities`, `_records`), `src/delve/modules/books/prompts/convert.md` and `entities.md`, `src/delve/modules/books/generate.py` with `prompts/generate.md`, `web/src/module/EntityForm.tsx` (an NPC's room field).
- Test `tests/modules/books/test_convert.py`, `tests/modules/books/test_generate.py` and `web/src/module/EntityForm.test.tsx`.

**Interfaces:**
- **The prompts:**
  - `convert.md` gains a rule: "Copy every number, die roll and table row exactly as the book has it, even when it looks wrong or a sequence has gaps; never renumber, never fill in a row."
  - `entities.md` gains:
    - one record per person, faction or quest, however often they're mentioned;
    - each record's `location`, as `text:<id>#<key>`, when the book places it;
    - pregenerated characters are left out ("characters for the players are not NPCs").
- **A numbers check:** `numbers_changed(source: str, markdown: str) -> list[str]` in `convert.py`. It returns the 1–3-digit numbers whose count in the Markdown is lower than in the source, ignoring page numbers. A chunk with any gives a `numbers-changed` warning that lists up to 10 of them and names the pages.
- **Merging:** `merge_entities(records: list[dict]) -> list[dict]` in `convert.py`.
  - Records of one kind whose `name`s are equal after `casefold().strip()` become one, keeping the first `id`.
  - Their `summary`s are joined with a blank line, skipping duplicates, and the first non-empty value of every other field is kept.
  - It applies to NPCs, factions, quests and encounters.
- **Keying:** `key_entities(source: ModuleSource) -> ModuleSource` in `convert.py`, run after merging.
  - An encounter or NPC with a `location` naming a keyed heading, or whose `name` equals a heading's title after casefolding, or whose summary says "area N", "room N" or "in N." for a keyed N, gets a key.
  - That means a `keys` entry for that heading: `{key, text, npcs: [...], encounter}` (the existing manifest shape), plus the entity's `location`.
  - The first match wins, and an entity with none stays unkeyed.
- **The generator:**
  - `generate.py`'s plan carries `party: {size, levels, notes}` from the request, written into the manifest's `party`. It is left empty when the request doesn't say.
  - The generator rolls 12 names per race with `delve.rules.adnd2e.names.generate` and gives them to `generate.md`, which requires every person to be named from that list.
- **The NPC form** gets a "Where" select of the module's keyed rooms, like the encounter form's, without the doubled numbers: "4. The Destroyed Caravan", not "4. 4. …".

- [ ] **Step 1: Write the failing tests:**
  - `test_numbers_changed_finds_a_renumbered_sequence`: source rounds `1 4 5 7 8 9 10` and Markdown `1 4 5 6 7 8 9` gives `["10"]`, and the warning.
  - `test_merge_entities_joins_same_name_records`: three "Tcho'eh" become one, while "Bernhardt" and "Bernhardt the elder" stay two (Review Focus 3).
  - `test_key_entities_links_an_encounter_named_by_area`.
  - `test_key_entities_leaves_an_unplaced_encounter_unkeyed`.
  - `test_generate_writes_party_size_and_levels`.
  - `test_generate_names_come_from_the_rolled_list` (FakeDM plan).
  - The web test of the NPC "Where" select.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the Interfaces above.
- [ ] **Step 4: Run** `make ci`; it passes.
- [ ] **Step 5: Commit** `git commit -m "Keep the book's numbers, merge same-name entities, key entities to rooms, and give generated modules party size and rolled names"`

### Task 4: Warnings you can read, and progress you can see from anywhere (C8, C9, E2, owner item 14)

**Files:**
- Modify `src/delve/modules/books/pdf.py` (a `progress` callback per page read), `src/delve/conversions/runner.py`, `web/src/module/ConversionProgress.tsx`, `web/src/routes/Modules.tsx`, `web/src/components/Nav.tsx`, and `web/src/routes/ModuleDetail.tsx` (only the warnings block, lines 160–170 today).
- Test `tests/conversions/test_runner.py` and the web tests of those components.

**Interfaces:**
- **Progress counts:**
  - `read_pdf` takes `progress: Callable[[int, int], None] | None`, called after each page.
  - The runner reports it as step `reading`, with `done` and `total`, so OCR shows "12 of 38 pages".
  - The conversion JSON gains `steps: {index: int, count: int}`: "Step 2 of 4" (reading, converting, entities, maps; `generate` has generating and maps).
- **`ConversionProgress`** shows:
  - "Step N of M · <step>";
  - an indeterminate animated bar when `total` is 0;
  - the elapsed time, updated every second.
- **A running or finished conversion is visible from anywhere:**
  - **The Modules list:** a running conversion is a row at the top, with its title, "Converting…", its step and count, and a link to New module. The latest finished one stays as a row until its module is opened, with "Done: open the module" or "Failed: <reason>".
  - **The nav:** a dot on Modules while one runs.
  - **On any screen,** when it ends, a small notice with a link to the module.
- **Module warnings:**
  - Grouped by code, with a count ("13 pages too large to render whole").
  - Collapsed to one summary line by default.
  - Each warning links to its `ref` where it can: a text, an asset, a map or a room.
  - The module page also shows the source's derived warnings, such as `key-without-room`, which today appear only in the source's warnings.

- [ ] **Step 1: Write the failing tests:**
  - the runner emits `reading` counts from a three-page fake book;
  - `ConversionProgress` renders "Step 1 of 4" and the elapsed time;
  - Modules shows a running conversion's row;
  - the nav has the dot;
  - warnings collapse and group (13 `page-too-large` give one line "13 ×").
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the Interfaces above.
- [ ] **Step 4: Run** `make ci`; it passes.
- [ ] **Step 5: Commit** `git commit -m "Conversion progress with steps, counts and time, visible from Modules and the nav, and grouped, linked warnings"`

### Task 5: The play screen: party and map in view, quieter for players (P1, P2, P4, P5, P7, T4, T5)

**Files:**
- Modify `web/src/routes/Play.tsx`, `web/src/play/Story.tsx` (`ToolRow`), `web/src/play/PartySidebar.tsx`, `web/src/play/TablePanel.tsx`, `web/src/play/InvitePanel.tsx`, `web/src/play/MapPanel.tsx` and `web/src/play/Composer.tsx`, plus the play section of `web/src/styles.css`.
- Test the web tests of those components and `web/e2e/play.spec.ts`.

**Interfaces:**
- **Desktop order (900 px and over):** the side column's order is the party, then the map, then the table panel (table talk and questions), then the host's controls.
  - The host's controls and the invite are collapsed `<details>`.
  - The invite is open only while the host is alone at the table.
  - At 1280×800 the party's first card and the map's top are above the fold (an e2e assertion on their bounding boxes).
- **Tool rows** show only to a seat with the host or co-host role, and to the owner playing alone. Other seats don't get them. A refused tool shows to the host only.
- **The story** scrolls to its newest entry on load and when a new entry arrives, unless the reader has scrolled up.
- **The "Acting for" picker** is a compact row of chips. The timer's fallback select is wide enough for its longest option in both languages.
- **The phone map** fits the whole known map to the screen on open, not a 369% zoom on one room.
- **Party cards:** tapping a whole card opens the sheet.
- **A player with no character** (T4) sees a "Choose your character" action, which opens the free-PC picker the join page uses.
- **The invite link** uses the address the host's browser is on when that isn't loopback. On loopback, the panel says that other devices need the LAN address that `delve serve` prints.

- [ ] **Step 1: Write the failing tests:**
  - `ToolRow` is hidden for a player seat and shown for the host (Review Focus 4);
  - the side column order;
  - the invite is collapsed once a second seat is present;
  - "Choose your character" shows for a seat with no PC;
  - the e2e fold assertion.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the Interfaces above.
- [ ] **Step 4: Run** `make ci` and `make e2e-browser`; both pass.
- [ ] **Step 5: Commit** `git commit -m "Play screen: party and map in view, host panels folded, tool rows for the host only, and a way for a player to choose a character"`

### Task 6: The DM in character, and Ask the DM that knows what the characters know (D1, D4, T3, owner items 3 and 7)

**Files:**
- Modify `src/delve/dm/prompt/dm.md`, `src/delve/play/ask.py`, `src/delve/play/sessions.py` (`primer`'s inventory), `src/delve/play/translate.py` (only if the cause of T3 is there), and `web/src/play/TalkPanel.tsx` (the shared answer).
- Test `tests/dm/test_prompt.py`, `tests/play/test_ask.py`, `tests/play/test_translate.py` and `web/src/play/TalkPanel.test.tsx`.

**Interfaces:**
- **`dm.md`:**
  - Never narrate your own process ("I'm now…", "Now the gear."). Tool calls are not part of the story.
  - Out-of-character notes for the host (setup questions, rules choices) go through `tell` to the host's characters, or, when the host plays none, as a short final paragraph starting `(ooc, for the host:`.
  - Questions that are only questions belong in Ask the DM, so suggest it once when a player asks one in an act.
- **`sessions.primer`:** the inventory digest keeps each item's notes: `name xN (notes)`.
- **`ask_prompt`:**
  - gains `RECENT = 8`: the asker's last 8 story entries they could see, as `can_see` allows, in English, as "WHAT HAPPENED LATELY";
  - its rules ask for the actual figures from the rules snippets when the question is about rules, and never for "the DM should confirm".
- **T3, Ask answers in English for a Dutch seat:** find the cause and fix it.
  - The test plays a Dutch seat's Ask through the routes and asserts that the stored `nl` translation of the answer, and the answer event that seat gets, are Dutch.
  - The cause goes in the chronicle.
- **The shared answer in table talk** renders through `renderMarkdown`. It is clipped to three lines, with "Show all".

- [ ] **Step 1: Write the failing tests:**
  - the prompt holds the rules above (string checks, the way `tests/dm/test_prompt.py` checks rules today);
  - `primer` keeps notes ("Long sword x1 (Vessa, a talking sword)");
  - `ask_prompt` holds the recent entries the asker could see and **not** a tell addressed to another seat (fourth wall);
  - a Dutch Ask comes back Dutch;
  - the shared preview renders bold.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the Interfaces above.
- [ ] **Step 4: Run** `make ci`; it passes.
- [ ] **Step 5: Commit** `git commit -m "The DM stays in character, and Ask the DM sees recent events and item notes, answers with figures, and in the asker's language"`

### Task 7: Phone layouts for the module editor, map editor, house rules and print (E9, §6)

**Files:**
- Modify the non-play sections of `web/src/styles.css`, `web/src/routes/ModuleDetail.tsx` and `web/src/routes/MapEditor.tsx` (layout only), and `web/src/routes/HouseRules.tsx` (on a phone, the editor opens as its own view with a back link).
- Test the new `web/e2e/phone.spec.ts`.

**Interfaces:**
- **Under 600 px:**
  - every two-column layout of those screens stacks;
  - the map editor shows the DSL and the drawing as two tabs, not side by side;
  - the print views fit the width.
- **The e2e** opens each of Modules, a module (each tab), the map editor, House rules (with a rule picked) and the print view at 390×844. On each it asserts `document.documentElement.scrollWidth <= 390` (Review Focus 5) and takes a screenshot into `web/e2e/screenshots/`.

- [ ] **Step 1: Write** `phone.spec.ts`.
- [ ] **Step 2: Run** `make e2e-browser` and see the width assertions fail.
- [ ] **Step 3: Implement** the Interfaces above.
- [ ] **Step 4: Run** `make ci` and `make e2e-browser`; both pass.
- [ ] **Step 5: Commit** `git commit -m "Phone layouts: module editor, map editor, house rules and print stack on a narrow screen"`

### Task 8: The character sheet in full, map rename that keeps links, and the organiser's cost and DM log (owner item 1, E1, P3)

**Files:**
- Modify `web/src/campaign/CharacterSheet.tsx`, `web/src/api.ts` (the `Sheet` type), `src/delve/web/routes/maps.py` (`update_map`), `web/src/routes/CampaignDetail.tsx` (a "DM log" section), `src/delve/storage/sqlite/engine.py`, and `README.md` (the character sheet).
- Test `web/src/campaign/CharacterSheet.test.tsx`, `tests/web/test_modules_api.py`, `tests/web/test_characters_api.py`, `web/src/routes/CampaignDetail.test.tsx` and `tests/storage/test_sqlite.py`.

**Interfaces:**
- **The sheet:**
  - An abilities row at the top (STR to CHA, exceptional strength as `18/76`).
  - Sections for weapon proficiencies, nonweapon proficiencies, thief skills (as %), natural abilities, and background.
  - Gender, size and the bonus against larger attackers in the header.
  - The weapon in prose under the attacks.
  - For an NPC, its story (`notes_md`) and disposition are shown to the organiser only.
  - **The redaction stays:** a test asserts the seat routes still strip them.
  - `README.md` gets a short note on what the sheet shows.
- **`update_map` with a new name** also rewrites every text whose `map` is the old name, and every key `node` that names it, in the same transaction. The response lists the texts it updated.
- **"DM log" on the campaign page:** organiser only, from the existing `GET /api/campaigns/{id}/dm/log`. It shows one row per beat: the time, the tool count, the input and output tokens, and `usage.cost_usd` summed, with a total for the campaign.
- **`create_sqlite_engine`** sets `PRAGMA busy_timeout=5000` on every connection.

- [ ] **Step 1: Write the failing tests:**
  - the sheet shows "18/76", a thief skill as "85%" and the background;
  - an NPC's story is visible to the organiser, and a seat's characters route still has no `notes_md`;
  - renaming a map keeps its texts' links (the 52 → 49 case, reduced to two headings);
  - the DM log section shows a beat's cost and the total;
  - `PRAGMA busy_timeout` reads 5000.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the Interfaces above.
- [ ] **Step 4: Run** `make ci`; it passes.
- [ ] **Step 5: Commit** `git commit -m "The full character sheet, map rename that keeps its texts, the organiser's DM log with cost, and a busy timeout"`

### Task 9: The docs, and a check with a real book's shape (last; consumes Tasks 1–8)

**Files:**
- Modify `docs/progress.md`, `docs/backlog.md`, `docs/glossary.md` and `README.md`.
- Create `docs/review/2026-10-18-tomb-of-horrors.md`.
- Modify `web/e2e/` screenshots.
- Test `tests/e2e/test_conversion_shapes.py`.

**Interfaces:**
- **`test_conversion_shapes.py`** builds a small PDF with:
  - one scanned text page, one scanned map page with a legend, and one scanned handout (images made with Pillow, which pdfplumber's stack already brings);
  - a fake `ocr` and the fake `claude`.
  - It asserts that the map page is a `map-page-*` attachment, the handout is a picture, no OCR junk is in any text, the sketched map's source carries the invented-layout comment, and the module's warnings include `book-map`.
- **The Tomb of Horrors notes** (`docs/review/2026-10-18-tomb-of-horrors.md`):
  - The owner's hand check of converting TSR 9022A on 2026-10-18 (module `mod_481e37c6ea6d`, 4 minutes).
  - **Pages 3–13** have a text layer and converted well: the room key 1–33 with sub-areas, the legend, the DM notes and the roster tables.
  - **Pages 14–45** are image handouts, each with a printed number such as "25c". The page images of 14 were kept; the rest became OCR junk appended to the player-audience roster text.
  - **Page 46** is the map, and it was lost. The sketch was a chain 1→33, and room 31 was missing because its heading has no name.
  - **The entities:** Acererak ×6, the 20 pregenerated characters filed as NPCs, 38 encounters with none keyed, and `keys: []`.
  - Then which of these Tasks 1–3 fix.
- **`progress.md`:**
  - a section for this pass;
  - the owner's hand-check results so far: writing a module from scratch works; the empty-module mix-up (fixed by the pick-first screen); the conversions above;
  - what is left (below).
- **`backlog.md`** gains:
  - pending acts shown to the table before the beat closes;
  - private acts (owner: "I pocket the ring"), as a variant of Act resolved in the beat and told back through `tell`;
  - campaign status: In progress / Paused / Complete, with Pending later;
  - a richer campaigns list: module, players, last played, sessions, playtime;
  - follow-up questions and remarks while making a module;
  - module delete, export and import on the modules list;
  - sketching a map from the book's map image.
- **Re-take** the e2e screenshots, and attach them.

- [ ] **Step 1: Write** `test_conversion_shapes.py` and see it pass on the merged Tasks 1–3. If it fails, the failing task is named in the chronicle and fixed.
- [ ] **Step 2: Write** the docs above.
- [ ] **Step 3: Run** `make ci` and `make e2e-browser`; both pass.
- [ ] **Step 4: Commit** `git commit -m "Docs for the walkthrough fixes, the Tomb of Horrors notes, the backlog, and a conversion test with a scanned book's shape"`

## Order and parallelism

- Tasks 1, 3, 4, 5, 6, 7 and 8 can start at once.
  - Task 4 changes `pdf.py` only to add the `progress` callback, so Task 1 and Task 4 must keep their `pdf.py` changes in separate functions.
  - Tasks 5 and 7 split `styles.css` by section: play for Task 5, the rest for Task 7.
- Task 2 needs Tasks 1 and 3 (it builds on `map_page`, and both touch `convert.py`).
- Task 9 comes last.
