# Delve: faithful modules, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A module converted from a published PDF (U1 is the test case) plays as the book does.
- Every map page becomes an editable map drawn from its picture: one map per level, joined by its exits.
- Every keyed area is reachable by its own key and linked to its room.
- The records are clean enough to export.
- The DM neither invents a layout nor gives away a hidden roll.
- Pregenerated characters are a module section that party creation offers.
- A late joiner can read the whole story back.

**Architecture:**
- **The conversion gains three vision steps, all in the background job, never in a beat:**
  - classifying the picture pages (`delve.modules.books.classify`);
  - filling the text layer's lost glyphs (`delve.modules.books.gaps`);
  - drawing each map page's levels (`sketch.draw_from_page`).

  Each reaches Claude only through an injected `Look`, as plateau 7's `sketch_from_page` does.
- **One pure clean-up pass after extraction:** `delve.modules.books.repair` rewrites or drops dangling refs, and
  `delve.modules.books.dedupe` merges the records Claude groups as one, so the export never meets a dangling ref.
- **Keys are scoped to their part in one place:** `source.scoped_keys`. Derive, the export, the converter, Keep and
  `module_key` all use it.
  - The `.dscn`'s `keys[].key` stays unique. A key is written as printed when it is unique, else as `<part>-<n>`.
  - A drafted level's rooms are linked by explicit `keys[]` entries with a `node`, so one text can span several maps.
- **Pregens are a seventh entity kind,** `pregens`, in the format, the source, the editor and the table. The DM reads
  them with one new DM-only tool. A seat lists the players' pregens through one new route.
- **The rest is small:**
  - dice keys get an occasion;
  - the DM's prompt is settled on hidden rolls and on parts with no map;
  - the story pages back on scroll;
  - costs come from the provider's usage.

**Tech Stack:**
- No new dependency, Python or web.
- Pillow 13.0.0 (already direct) crops the handouts. pdfplumber (already direct) gives each word's `fontname` for bold
  and italic, and renders a page for the gap reading.
- One migration, `0015_costs` (`conversions.cost_usd REAL NULL`), in Task 26.

**Spec:**
- `docs/superpowers/specs/2026-10-19-faithful-modules-design.md`, all of it: A1–A3, B1–B5, C1–C4, D1–D6, E, F1–F6
  and G1–G3, in that priority order.
- Its source, `docs/review/2026-10-19-saltmarsh-playthrough.md` (finding ids S, C, F, E, P, D, T). Its file and line
  references were checked on master 9a550de, and the tasks below cite functions, not lines.
- The Archmage's rulings for this quest (scoped keys, read-aloud, pregens, vision calls, errata), recorded in
  "Decisions taken in this plan" (rows 1–5).
- Plateau 7's plan (`docs/superpowers/plans/2026-10-18-plateau-7-maps.md`) for what this builds on: `vision_call`,
  `Look`, `fit_for_vision`, the `book-map` jobs and their drafts, and `PdfPage.map_page`.

## Global Constraints

- **Earlier plateaus still apply:** `GUILD.md`, and the Global Constraints of plateaus 0–7.
- **Every task leaves `make ci` green on its own once its prerequisites are merged.**
  - A task that changes a name changes every caller, test, prompt line and doc in the same task.
  - The callers were checked on 9a550de. A builder who finds another one fixes it in the same task.
- **The fourth wall wins.** When in doubt, a seat sees less.
  - **The one exception:** players see each other's sheets (owner decision 4), and the pregens offered at the table
    (they are the players').
  - A new route or event a seat can reach gets a planted `SECRET-XYZZY` in `tests/web/test_fourth_wall_per_seat.py`.
  - A new DM-only tool goes into `DM_ONLY_TOOLS` in `tests/dm/tools/test_fourth_wall.py`.
  - No key number reaches a player: no "room 4" in Ask's answers, and no key in a seat's map notice.
- **The book is followed as printed** (owner decision 5): the gnolls "in area 30", Oceanus NG/CG and the typos stay.
  - No task corrects them or asks about them.
  - Filling a glyph the text layer lost (½, ¼) isn't a correction: it restores what is printed.
- **Single-player play stays as fast as it is.**
  - No vision call, side pass or extra storage read runs inside a beat.
  - A beat with one present seat still closes on its submission.
  - The tool timing test (`tests/e2e/test_tool_timing.py`) stays under 50 ms at the 95th percentile.
- **Tests use only fakes:**
  - `FakeDM` (`side_answers`, `vision_answers`, `vision_handler`), the fake `claude` executable, fake OCR and `Look`
    callables, and pages drawn with Pillow or built with `tests/fixtures/pdfs.py`.
  - No test runs the real `claude`, `tesseract` or the network. `DELVE_OCR=off` stays autouse.
  - Never commit the U1 PDF or its page images.
  - An agent may try the real U1 copy under `/tmp/delve-salt-base` by hand, outside `make ci`, and never edits it.
- **The dependency rules hold:**
  - `delve.modules.books` imports none of `web`, `dm`, `storage`, `play` or `conversions`: `classify`, `gaps`,
    `repair` and `dedupe` take a `Look` or a `Complete`.
  - `delve.maps` still doesn't import `delve.modules`.
  - Only `delve.web` imports fastapi.
- **The copied `dscn` package** changes only in Task 16 (the `pregens` kind: schema, container, refs), and
  `GUILD.md` records it (Task 30). Its version stays 2.
- **The editor's round-trip** (`web/src/module/roundtrip.test.ts`) stays byte-exact. Task 11 changes only the
  read-aloud decoration, never the Markdown.
- **Words** (glossary): DM (never GM), beat, map state, part (a text of the module: "the house", "the ship"), level
  (one map of a plate: ground floor, cellar, main deck), pregen (pregenerated character), handout, read-aloud, draft.
  - Attachment and image in the UI, never "asset".
  - The UI never says "turn" or "round" for a beat.
- **UI strings:** every one is in `en.json` and `nl.json`, and `nl` has every key.
  - **The rule for parallel builders:** each web task adds its keys as **one block, right after its named anchor**,
    in both files, and never moves, reorders or reformats another key.

  | Task | Anchor (the key its block follows) |
  |---|---|
  | 2 | `conversion.step.places` |
  | 3 | `mapDrafts.fromBook` |
  | 4 | `mapDrafts.replaces` |
  | 5 | `newModule.conversionsFailed` |
  | 6 | `mapDrafts.drafts` |
  | 7 | `module.map.showBookMap` |
  | 13 | `conversion.step.generating` |
  | 14 | none (no UI string) |
  | 15 | `entity.hp` |
  | 18 | `entity.related` |
  | 19 | `play.noParty` |
  | 20 | `mapState.offline` |
  | 25 | `play.loadEarlier` |
  | 26 | `dmLog.noCost` |
  | 27 | `modules.deleteFailed` |
  | 28 | `campaigns.toModules` |

  These anchors are distinct, and no two sit on neighbouring lines.
- **`src/delve/dm/prompt/dm.md`** is edited by Tasks 8, 21, 20 and 19, in that order (waves 1, 2, 4, 5), each only
  in the section it names. `tests/dm/test_prompt.py` (`test_prompt_names_only_existing_tools`) runs on every one.
- **Shared test fixtures:**
  - `tests/e2e/fake_play_server.py`, `web/e2e/*.spec.ts` and `web/e2e/screenshots/` are Task 29's alone.
  - `tests/fixtures/scripts/first_session.golden.json` is regenerated only by Tasks 22 and 21, the two that change roll
    keys, each reviewing the diff as its docstring asks.
  - `tests/fixtures/pdfs.py` is Task 14's (bold and italic runs). Task 2 uses its `picture_page` as it is.

## Review Focus

1. **A converted module that still can't be exported.** Planted cases:
   - a ref to a merged-away id (`npc:bosun-2` after `bosun-2` merged into `the-bosun`);
   - a ref to an id nothing has (`npc:bosun` with only `the-bosun`): rewritten, because one record matches;
   - a ref that two records could match (`npc:smuggler` with `smuggler-2` and `smuggler-3`): dropped and warned,
     never guessed;
   - an `asset:` ref to a picture that was dropped;
   - a ref inside a Markdown link of a text, and one in a faction's `members` list.

   `GET …/export.dscn` answers 200 for each, and the bundle passes `dscn validate` with no `duplicate-id` (two parts
   that share key numbers) and no unresolved ref. (Task 1 and Task 8 tests, and Task 29's end-to-end test.)
2. **A draft kept onto the wrong part.**
   - The page-35 case: a draft labelled with house names kept for the ship part is refused with 409 and its problems.
     Keep anyway (`force`) is the organiser's explicit choice.
   - Keeping a two-level draft makes two maps and links each key once, on its own level.
   - Neither drafting nor keeping links a room of the house to a heading of the ship.

   (Task 3 and Task 4 tests.)
3. **Key 7 in two parts.**
   - `module_key("7")` refuses, and its candidates name the part and the key as written (`sea-ghost-7`), so the hint
     can be followed.
   - `module_key("7", part="ship")`, `module_key("sea-ghost-7")` and `module_key("22")` (unique) each answer one key.
   - Export, re-import and derive give the same keys.
   - A converted ship encounter keyed `key:sea-ghost-7` is listed under the ship's 7, never the house's.

   (Task 8 and Task 9 tests.)
4. **What a player learns by accident:**
   - a failed hidden search (`skill_check(…, hidden=True)`) leaves no tool row in any seat's story, and the DM's
     prompt says to narrate it as finding nothing;
   - `encounter_check` makes no row;
   - the seat's map notice for an unmapped part carries no key number;
   - Ask's prompt holds only entries the asker may see, however long the session;
   - the pregens route lists no `gm` pregen and no DM notes.

   (Task 21, 20, 23 and 19 tests; `test_fourth_wall_per_seat.py` gains the pregens route and Ask's session block.)
5. **A conversion that meets a page it can't read:**
   - the vision call fails or answers prose: the page stays a picture with `page-not-classified`, and the job goes on;
   - a fake vision answer that changes a word as well as filling a ½ is refused (`text-gap` warned, never applied);
   - a handout box outside the page is clamped;
   - a book with no picture page sends no vision call at all;
   - a book with no map page still gets its room-key sketches, labelled as invented.

   (Task 2, 12, 13 and 5 tests.)

---

## File structure

```
src/delve/modules/books/repair.py          dangling refs rewritten or dropped (Task 1)
src/delve/modules/books/classify.py        picture pages: map, handout, art, blank; handout crops (Tasks 2, 12)
src/delve/modules/books/prompts/classify-page.md   the classifying vision prompt (Task 2)
src/delve/conversions/dungeon_maps.py      drafts from any book picture, per part, per level; Keep checks (3, 4, 5)
src/delve/modules/books/sketch.py, prompts/book-map.md   one map per level, joined by exits (Task 4)
web/src/module/DraftReview.tsx             a draft over its page, large (Task 6)
web/src/module/ProvenanceNotice.tsx        the one-line notice and the book's page beside the editor (Task 7)
src/delve/modules/source.py                scoped_keys, part_slug; derive with scoped keys (Task 8)
src/delve/modules/books/dedupe.py, prompts/dedupe.md   records Claude groups as one (Task 9)
src/delve/modules/books/gaps.py, prompts/fill-gaps.md  lost glyphs read from the page image (Task 13)
src/delve/modules/dscn/scenario.schema.json   the pregens kind (Task 16)
src/delve/web/routes/pregens.py, src/delve/dm/tools/pregens.py   pregens at the table (Task 19)
web/src/play/PregenPicker.tsx              the pregens offered at party creation (Task 19)
reference/snapshots/corrections.sql.gz     the reference's row fixes (Task 24)
src/delve/storage/migrations/versions/0015_costs.py   conversions.cost_usd (Task 26)
tests/e2e/test_a_faithful_book.py, web/e2e/zz-faithful.spec.ts end to end, and the screenshots (Task 29)
```

---

### Task 1: A1, export never fails on a converted module

**Files:**
- Create: `src/delve/modules/books/repair.py`, `tests/modules/books/test_repair.py`,
  `tests/web/test_export_converted.py`
- Modify: `src/delve/modules/books/convert.py` (`merge_entities`, `_entities`, `convert_book`),
  `src/delve/modules/books/generate.py` (`generate_module`'s end), `tests/modules/books/test_convert.py`

**Interfaces:**
- Produces:
  - `merge_entities_mapped(records) -> tuple[list[dict], dict[str, str]]`: `merge_entities`'s merge, and
    `{dropped id: kept id}`. `merge_entities(records)` stays, returning its first value.
  - `_entities(...)` returns a third value: `renamed: dict[str, str]`, full refs (`"npc:bosun-2": "npc:the-bosun"`).
  - **`repair_refs(source: ModuleSource, renamed: Mapping[str, str] = {}) -> tuple[ModuleSource, list[Warning]]`**
    in `repair.py`. It covers every ref `source._missing_refs` would flag: `asset:` refs, and the kinds of
    `source.CHECKED_ENTITY_REFS`, imported so that Task 16's `pregen` is covered too. They come from texts, entity
    records and `keys[]` entries, read with `refs_in_markdown` and `refs_in_value`.
    - **A ref in `renamed`** is rewritten to its kept id, with a `ref-rewritten` warning.
    - **A ref to an id nothing has** is rewritten when exactly one record of its kind matches, with a
      `ref-rewritten` warning. A record matches when its `id`, or `slugify(name)`, equals the ref's id after the
      ref's id loses a trailing `-<digits>` and a leading `the-` or `a-`, or equals `the-<id>`.
    - **Otherwise the ref is dropped,** with a `ref-dropped` warning naming where it was:
      - removed from a list;
      - its field removed when it is a scalar (`faction`, `location`, `encounter`, `portrait`);
      - in Markdown, `[label](kind:id)` becomes `label`, `[[kind:id]]` becomes the id with its hyphens as spaces, and
        `![…](asset:id)` is removed.
  - `convert_book` ends with `repair_refs(key_entities(...), renamed)`, and `generate_module` with
    `repair_refs(source)`. The warnings join the job's.
  - The export route's 409 stays, for a hand-edited module.
- [ ] **Step 1: Write the failing tests:**
  - `test_repair_rewrites_a_merged_id` (`npc:bosun-2` → `npc:the-bosun`, in a faction's `members` and a key's
    `npcs`);
  - `test_repair_rewrites_the_one_match` (`npc:bosun` with only `the-bosun`);
  - `test_repair_drops_an_ambiguous_ref` (`npc:smuggler` with `smuggler-2` and `smuggler-3`: dropped,
    `ref-dropped`);
  - `test_repair_drops_a_markdown_link_to_its_label` and `test_repair_drops_a_missing_picture`;
  - `test_merge_entities_mapped_names_the_dropped_ids`;
  - in `test_export_converted.py`, `test_a_converted_module_exports`: `convert_book` with a `FakeDM` whose entity
    answers leave `npc:bosun` dangling, saved as a module, then `GET /api/modules/{id}/export.dscn` → 200, and
    `dscn.validate` on the bundle has no error.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `uv run pytest tests/modules/books tests/web/test_export_converted.py tests/web/test_assets_api.py` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "A converted module always exports: dangling refs rewritten or dropped, with warnings"`

---

### Task 2: A2, every map page detected

**Files:**
- Create: `src/delve/modules/books/classify.py`, `src/delve/modules/books/prompts/classify-page.md`,
  `tests/modules/books/test_classify.py`
- Modify: `src/delve/modules/books/pdf.py` (`PdfPage`, `_is_map`, `_page`), `src/delve/conversions/runner.py`
  (`STEPS`, `_convert_pdf`), `tests/modules/books/test_pdf.py`, `tests/conversions/test_runner.py`, `en.json`/`nl.json`
  (anchor `conversion.step.places`)

**Interfaces:**
- Produces:
  - **`pdf.py`:**
    - `PLATE_WORDS = frozenset({"house", "cellar", "cellars", "floor", "floors", "deck", "decks", "level",
      "levels", "map", "plan", "cavern", "caverns", "caves", "dungeon"})`.
    - `plate_title(read: str) -> str | None`: the first line of OCR with 1–8 words and at most 60 characters that
      holds a `PLATE_WORDS` word (as a whole word, case-insensitive), whitespace collapsed.
    - `_is_map(read)` is also true when `plate_title(read)` is not None.
    - `PdfPage` gains `plate_title: str | None = None` (the plate's title, from OCR or the vision reading) and
      `handouts: tuple[HandoutBox, ...] = ()`. `HandoutBox` is defined in `pdf.py`, so that `classify` and `convert`
      share it without a cycle:
      `HandoutBox(box: tuple[float, float, float, float], title: str, key: str | None = None, part: str | None = None)`.
      `box` is `(x0, y0, x1, y1)` as fractions of the page.
    - `_page` sets `plate_title` on the scanned-with-OCR branch.
  - **`classify.py`:**
    - `PAGE_KINDS = ("map", "handout", "art", "blank", "text")`.
    - `async def classify_pages(book: PdfBook, look: Look | None, progress: Progress) -> PdfBook`.
      - **It asks** about every page that holds a whole-page picture (`area >= 1.0`) and isn't `map_page` already.
        It sends the picture, fitted with `fit_for_vision`, and `prompts/classify-page.md`.
      - **The answer is one JSON object:** `{"kind": <PAGE_KINDS>, "title": str | null, "handouts": [{"box": [x0, y0,
        x1, y1], "title": str, "key": str | null, "part": str | null}]}`. A fenced or prose-wrapped answer is read
        as convert's `_unfenced` reads one.
      - **A `map` answer** sets `map_page=True` and `plate_title` (the answer's title, else the OCR's). A `handout`
        answer sets `handouts`, each box clamped to `[0, 1]` and dropped when empty.
      - **A failed call, or an answer that isn't such an object,** leaves the page as it was, with a
        `page-not-classified` warning (`ref` `page:<n>`). The job goes on.
      - With `look` None, nothing is sent and the book is returned as it is.
      - `progress("classifying", done, total)` counts the pages sent.
  - **`runner.py`:**
    - `STEPS["pdf"] = (("reading",), ("classifying",), ("converting",), ("entities", "pictures"), ("maps",))`.
    - `_convert_pdf` runs `book = await classify_pages(book, look_for(services), progress)` after the reading.
  - **i18n:** `conversion.step.classifying` "Looking at the picture pages" / "De afbeeldingspagina's bekijken".
- [ ] **Step 1: Write the failing tests:**
  - `plate_title("HAUNTED HOUSE\nGround floor")` is "HAUNTED HOUSE", and `_is_map` is true for it with no legend
    word and no room number;
  - `test_classify_marks_a_map_page`: a Pillow page, with a `FakeDM(vision_handler=…)` whose `look` answers
    `{"kind": "map", "title": "The Sea Ghost: decks"}`, gives `map_page` and the title, and `vision_images` holds one
    PNG;
  - `test_classify_reads_handouts`: a handout answer with two boxes, one reaching past the page, gives two clamped
    `HandoutBox`es;
  - `test_classify_survives_a_bad_answer`: prose, or a raised error, gives `page-not-classified` and an unchanged
    page;
  - `test_classify_sends_nothing_without_pictures`;
  - in `test_runner.py`, a PDF job's steps are the five above, "Step 2 of 5" while classifying.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `uv run pytest tests/modules/books tests/conversions` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Every map page found: plate titles in the OCR, and Claude's look at the picture pages it leaves in doubt"`

---

### Task 3: A2 and A3, any book picture drafted for its part; Keep refuses a mismatch

**Files:**
- Modify: `src/delve/conversions/dungeon_maps.py` (`start_book_map`, `_on_map`, `_rooms`, `drafts`, `keep_draft`),
  `src/delve/web/routes/map_drafts.py` (`FromBookIn`, `KeepIn`, `keep`), `web/src/module/mapDrafts.ts`,
  `web/src/module/MapDrafts.tsx`, `web/src/module/AttachmentsPanel.tsx`, their tests
  (`tests/conversions/test_dungeon_maps.py`, `tests/web/test_map_drafts_api.py`, `MapDrafts.test.tsx`,
  `AttachmentsPanel.test.tsx`), `en.json`/`nl.json` (anchor `mapDrafts.fromBook`)

**Interfaces:**
- Produces:
  - **What can be drawn:** `BOOK_PICTURE = re.compile(r"(?:map-)?page-\d+(?:-\d+)?")`. Any image attachment
    whose id matches it may be drawn, so the organiser can draft a page the detector missed. `MAP_PAGE` stays for
    `SKETCH_OF_PAGE`.
  - **`start_book_map(services, module_id, map_name: str | None, page_asset: str, *, part: str | None = None) ->
    Conversion`:**
    - `map_name` None draws a new map. Its name is `text_id` of the title in the attachment's description (the part
      in parentheses that `_attachments` writes), else `page_asset`.
    - `part` is a text id. An unknown one is a `KeyError` (404).
    - `target` adds `part`.
  - **`_part_texts(storage, module, map_name: str | None, part: str | None) -> list[TextDoc]`** replaces `_on_map`:
    the text `part`, else the texts whose `map == map_name` (explicitly named), else none. There is no fallback to
    the default map: that fallback was C-c.
  - **The draft's result** gains `replaces: str | None` (the map it replaces; None for a new map), `part` and `page`.
    `drafts()` lists them too.
  - **`keep_draft(storage, module_id, conversion_id, name=None, *, force=False) -> ModuleMap`:**
    - Before saving, it compares the draft's rooms with its part, `mismatch(source, part_text) -> list[str]`.
    - A room named `r<key>` whose key is a keyed heading of the part, labelled with another title, is a problem.
      Titles are compared casefolded, alphanumerics only, the leading key removed.
    - So is a draft whose `r<key>` rooms are mostly (over half) not keys of the part.
    - With problems and no `force`, it raises `DraftMismatch(ValueError)` carrying `problems`. The route answers 409
      `{"error": "The draft's rooms don't match <part title>.", "problems": [...]}`.
    - A kept book draft with `replaces` None is a new map, like a description draft. It then points its part's
      text at the map when that text names none (`_point_texts`).
  - **The route:** `FromBookIn{map: str | None = None, page: str, part: str | None = None}` and
    `KeepIn{name?: MapName, force: bool = False}`.
  - **`mapDrafts.ts`:**
    - `startBookMap(moduleId, map: string | null, page: string, part?: string)` (SketchNotice's call stays valid);
    - `keepMapDraft(moduleId, id, name?, force = false)`;
    - `MapDraft` gains `replaces`, `part` and `page`.
  - **`MapDrafts.tsx`:** a 409 with `problems` lists them in a `useConfirm` dialog, "Keep anyway", which keeps with
    `force`.
  - **`AttachmentsPanel.tsx`:** an image attachment whose id matches `BOOK_PICTURE` has "Draw a map from this
    page", with a select of the module's texts that have keyed headings (the part).
  - **i18n:** `mapDrafts.fromPage`, `mapDrafts.part`, `mapDrafts.mismatch`, `mapDrafts.keepAnyway`.
- [ ] **Step 1: Write the failing tests:**
  - `test_from_book_takes_any_page_picture`: `page-37` → 202, `page-37-2` → 202, `source-pdf` → 422;
  - `test_a_new_map_from_a_page`: no `map`, kept as a new map named from the description's title;
  - `test_rooms_come_from_the_part_only`: a module with a house text (no map named) and a ship text on map `ship`.
    The ship's draft prompt holds no house heading.
  - `test_keep_refuses_house_labels_on_the_ship`: 409 with problems; `force` keeps it;
  - the web tests: Keep anyway calls keep with `force`, and the attachment's button posts `{map: null, page, part}`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Any page of the book can be drafted for its part, and Keep refuses a draft whose rooms don't match"`

---

### Task 4: B1, faithful drafts: one map per level, joined by exits

**Files:**
- Modify: `src/delve/modules/books/sketch.py` (`sketch_from_page` becomes `draw_from_page`),
  `src/delve/modules/books/prompts/book-map.md` (rewritten), `src/delve/conversions/dungeon_maps.py`
  (`start_book_map`'s work, `keep_draft`, `drafts`), `web/src/module/mapDrafts.ts`, `web/src/module/MapDrafts.tsx`
  (a tab per level), `tests/modules/books/test_sketch.py`, `tests/modules/books/test_describe_map.py` (its
  `sketch_from_page` cases move to `draw_from_page`), `tests/conversions/test_dungeon_maps.py`,
  `tests/web/test_map_drafts_api.py`, `MapDrafts.test.tsx`, `en.json`/`nl.json` (anchor `mapDrafts.replaces`)

**Interfaces:**
- Consumes: Task 3 (`_part_texts`, `mismatch`, the result's `part`, `replaces` and `page`); Task 8
  (`source.scoped_keys`).
- Produces:
  - **`sketch.py`:**
    - `Part(id: str, title: str, rooms: list[tuple[str, str]])`: a text and its keyed headings, `(key, "7. Dining
      Room")`. Headings only, never their paragraphs: the plate holds the layout.
    - `DraftLevel(name: str, title: str, source: str, part: str | None)`.
    - `async def draw_from_page(name: str, page: bytes, media_type: str, parts: list[Part], look: Look) ->
      tuple[list[DraftLevel], list[Warning]]`.
  - **The answer `book-map.md` asks for:**
    - **One fenced ```dmap block per level** that the plate shows: a house's ground floor, upper floor, cellar and
      caves; a ship's decks. Each block's first two lines are `# level: <the plate's words for it>` and
      `# part: <a part id given>`.
    - **Each level is its own map** named `{{name}}-1`, `{{name}}-2`… in order, titled with its level
      (`map "Ground floor"`).
    - **The printed scale** as `grid { units feet <n> }`, with one cell per printed square.
    - **Rooms** `r<key>` with the part's label, where the plate puts them. Secret doors are `secret`. Stairs,
      hatches, trapdoors and ladders are features (`stairs-up`, `stairs-down`, `floor-trapdoor`…).
    - **An `exit at X,Y { to "{{name}}-<n>" at X,Y }`** at each stair, hatch or ladder that leads to another level.
    - No other joins, no markers, no notes.
  - **Delve, after the answer:**
    - it renames each level to `text_id(f"{name} {level}")`, unique, and rewrites every `to "{{name}}-<n>"` to the
      new name, as an exact string;
    - it parses and validates each level (`map_error`), and asks once more with every error;
    - a level whose `# part:` isn't a given id gets `part` None;
    - each validation warning (severity `warning`, such as "map is not connected: 5 separate parts") becomes a
      `map-warning` warning with `ref` `map:<level name>`.
    - The warnings are `map-from-book` and those `map-warning`s, or `map-not-drawn`.
  - **The draft's result:**
    - `maps: [{name, title, source, part}]`, each source starting with `f"{FROM_BOOK} asset:{page}."`;
    - `name` and `source` stay, as the first level's, for old readers.
  - **`keep_draft` of a book draft:**
    - **Every level is saved.** The first replaces `replaces` when there is one; the others are new, with names
      made unique. The module's default map is unchanged unless it had none.
    - **Each level's rooms are linked by explicit `keys[]` entries:** `_link_levels(storage, module_id, levels)`.
      For each `r<key>` room, the keyed heading of its part with that key gets `{key: <scoped key>, title, text:
      "text:<id>#<anchor>", node: "map:<level>#room.r<key>"}`. An existing entry for that `text` is updated, keeping
      its `npcs`, `encounter` and `assets`.
    - `mismatch` runs per level, against its part.
  - **`mapDrafts.ts`:** `MapDraft.maps: {name, title, source, part}[]`. **`MapDrafts.tsx`:** a tab per level in the
    card. **i18n:** `mapDrafts.level`, `mapDrafts.levels`.
- [ ] **Step 1: Write the failing tests:**
  - `test_draw_from_page_reads_two_levels`: a fake `look` answers two blocks with an exit between them, and gives two
    levels with the exit's `to` renamed;
  - `test_draw_from_page_keeps_the_scale`: `units feet 5` stays;
  - `test_a_not_connected_level_is_warned`;
  - `test_a_level_with_a_bad_part_has_none`;
  - `test_keep_saves_every_level_and_links_each_key_once`: the house's 1–17 on ground and upper, 18–30 on cellar
    and caves. The house's keys get nodes on their own level, and the ship's keys are untouched.
  - `test_keep_runs_the_mismatch_per_level`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "A book page drawn as one map per level, with the printed scale, joined by its stairs, hatches and ladders"`

---

### Task 5: B2 and B5, every map page drafted during the conversion; the room-key sketch a fallback

**Files:**
- Modify: `src/delve/conversions/dungeon_maps.py` (`draw_book_maps`), `src/delve/conversions/runner.py`
  (`_sketch_maps`, a new `plate_matches`), `src/delve/web/routes/conversions.py` (the `then` follow-up stays, under
  `book_maps`), `web/src/routes/NewModule.tsx` (the done screen), `tests/conversions/test_dungeon_maps.py`,
  `tests/conversions/test_runner.py`, `tests/web/test_conversions_api.py`, `NewModule.test.tsx`,
  `en.json`/`nl.json` (anchor `newModule.conversionsFailed`)

**Interfaces:**
- Consumes: Task 2 (`map_page`, `plate_title`), Task 4.
- Produces:
  - **`runner.plate_matches(text_title: str, plate_title: str) -> int`:**
    - it counts the words of 4 letters or more the two share, casefolded;
    - the words of `PLATE_STOP = {"part", "map", "maps", "level", "levels", "floor", "floors", "deck", "decks", "plan",
      "page", "the", "and", "with"}` don't count;
    - "PART ONE — THE HAUNTED HOUSE" and "Haunted House" share 2.
  - **`_sketch_maps` (B5):**
    - **A keyed text is sketched only when no map page of the book matches it** (`plate_matches(...) > 0` for none).
      This happens when the book has no map page at all, or none titled like the text.
    - The sketch stays `SKETCHED` (labelled invented), and the `map-sketched` warning stays.
  - **`draw_book_maps(services, module_id) -> list[Conversion]` (B2):**
    - It drafts **every** `map-page-<n>` attachment of the module, in page order, not only the sketches'.
    - Each job gets `map_name` = the sketch that names that page, if any (it replaces it), else None.
    - `part` = the text with the highest `plate_matches` with the page's title, else None, letting Claude name the
      part per level.
    - `target` adds `batch: {index, count}`, and each job's title is `"page <n>"`.
    - The checkbox `book_maps` still turns it off.
  - **`NewModule.tsx`'s done screen (C-d):**
    - while the module's `book-map` jobs run, it shows "Drawing the map of page 37 (2 of 3)" from their `target`,
      updated by `conversion` events;
    - once they end, a link to the module's Maps tab, "Review the drafts";
    - "Done, with N warnings" links to the module page, where they are listed.
  - **i18n:** `newModule.drawingPage`, `newModule.reviewDrafts`, `newModule.seeWarnings`.
- [ ] **Step 1: Write the failing tests:**
  - `test_every_map_page_is_drafted`: three map pages and no sketch give three jobs, `batch` 1–3 of 3;
  - `test_a_sketch_is_replaced_by_its_page`;
  - `test_no_sketch_when_a_map_page_matches`: the house text and a "Haunted House" plate;
  - `test_a_text_with_no_map_page_is_sketched_as_invented`;
  - `plate_matches` cases;
  - the done screen shows "2 of 3" from a fake event.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Every map page drafted after a conversion, page by page, and the room-key sketch only for a part without one"`

---

### Task 6: B3, review a draft over its page

**Files:**
- Create: `web/src/module/DraftReview.tsx`, `web/src/module/DraftReview.module.css`, `web/src/module/DraftReview.test.tsx`
- Modify: `web/src/module/MapDrafts.tsx` (a "Review" button opens it), `en.json`/`nl.json` (anchor `mapDrafts.drafts`)

**Interfaces:**
- Consumes: Task 3 (`page`, `force`), Task 4 (`maps`, `map-warning`).
- Produces:
  - **`DraftReview({moduleId, draft, onClose})`** is a dialog, full screen under 600 px.
    - **The page and the draft side by side,** each at least 560 px wide, from 1200 px; stacked under 900 px:
      - the book's page: `<img alt=…>` of `attachmentUrl(moduleId, draft.page)`;
      - the level being looked at, drawn by `dsl.render` in `SvgPreview`, zoomable.
    - **A tab per level,** with its part's title.
    - **Its warnings,** the `map-warning`s first ("not connected").
    - **Keep** (with Task 3's Keep-anyway confirm), **Discard**, and, once kept, "Open in the map editor", a link to
      `/maps/{moduleId}/{first level}`.
  - The card's 9-box strip stays as the thumbnail.
  - **i18n:** `draftReview.title`, `draftReview.page`, `draftReview.draft`, `draftReview.open`, `draftReview.warnings`.
- [ ] **Step 1: Write the failing tests:** the dialog shows the page `<img>` with the attachment URL and the rendered
  level; a level tab switches the SVG; a `map-warning` is listed first; Keep calls `keepMapDraft`; the editor link
  appears after Keep.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `npm test` in `web/` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "A draft reviewed over the book's page, level by level, large enough to judge"`

---

### Task 7: B4, the map editor works for drafted maps

**Files:**
- Create: `web/src/module/ProvenanceNotice.tsx` and its test
- Modify: `web/src/module/SketchNotice.tsx` (it renders `ProvenanceNotice`; its exports stay),
  `web/src/routes/MapEditor.tsx`, `web/src/routes/MapEditor.module.css`, `MapEditor.test.tsx`, `en.json`/`nl.json`
  (anchor `module.map.showBookMap`)

**Interfaces:**
- Produces:
  - **`provenanceOf(source: string): {kind: "sketched" | "book" | "described"; page: string | null} | null`.** It
    reads the first line: `SKETCHED`, `FROM_BOOK` (`# Drawn from the book's map asset:<id>.`) or `DESCRIBED`.
  - **`ProvenanceNotice({moduleId, source, mapName, onShowPage})`:**
    - **One line:** its words ("Sketched from the room key: an invented layout", "Drawn by Claude from the book's
      page", "Drawn from a description"), then "Show the book's page" when there is a page, and the sketch's
      "Draw it from the book's map" button.
    - **It never wraps** to more than one line: `white-space: nowrap; overflow: hidden; text-overflow: ellipsis`.
      The full text is in its `title`.
  - **`MapEditor`:** "Show the book's page" toggles a panel with the page picture: beside the canvas from 1100 px,
    under it on narrower screens. The canvas and the DSL stay in the first screen at 1280×800 and 390×844.
  - **i18n:** `module.map.fromBook`, `module.map.described`, `module.map.showPage`, `module.map.hidePage`.
- [ ] **Step 1: Write the failing tests:**
  - `provenanceOf` for the three first lines and for an ordinary map;
  - the notice is one `<p>` with its full text in `title`;
  - the toggle shows an `<img>` with the attachment URL, and hides it again;
  - a `FROM_BOOK` map gets the notice too.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `npm test` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The map editor for drafted maps: a one-line notice, and the book's page beside the canvas"`

---

### Task 8: C1, keys scoped to their part

**Files:**
- Modify: `src/delve/modules/source.py` (`part_slug`, `scoped_keys`, `derive`), `src/delve/modules/text.py` (`Key`),
  `src/delve/modules/exporter.py` (`_keys`), `src/delve/dm/tools/module.py` (`module_key`, `_keyed`,
  `_key_candidates`), `src/delve/dm/prompt/dm.md` (the `module_key` line only), `tests/modules/test_source.py`,
  `tests/modules/test_export_round_trip.py`, `tests/dm/tools/test_module_tools.py`

**Interfaces:**
- Produces:
  - **`PART_LENGTH = 19`.**
  - **`part_slug(text: TextDoc) -> str`:**
    - `slugify(title)`'s words without `PART_STOP_WORDS = {"part", "chapter", "book", "one", "two", "three", "four",
      "five", "six", "seven", "eight", "nine", "ten", "the", "a", "an", "of", "i", "ii", "iii", "iv", "v"}` and
      without numbers;
    - joined by `-` and cut to `PART_LENGTH` at a hyphen; `text.id[:PART_LENGTH]` when nothing is left.
    - "PART ONE — THE HAUNTED HOUSE" gives `haunted-house`, and "Part Two — The Sea Ghost" gives `sea-ghost`.
  - **`scoped_keys(texts: Sequence[TextDoc]) -> dict[tuple[str, str], str]`:**
    - It maps `(text id, anchor)` to the key as written, for every keyed heading.
    - The printed key when no other text has a heading with that key (casefolded), else `f"{part_slug(text)}-{key}"`.
    - When two such texts share a part slug, their text id is used instead.
  - **`Key.part: str | None = None`** (appended): the `part_slug` of its text, set by `derive` for every key with a
    `text_anchor`.
  - **`derive`:**
    - A self-linked key is `scoped_keys`'s.
    - `explicit_keys` and `by_key` compare the heading's scoped key, never the bare one.
    - Keys parsed from a bundle keep the `key` they were written with.
  - **The export writes what derive gives,** so no two `keys[]` entries share a key.
  - **`module_key(ctx, room, part="")`:**
    - **`part`** is the text's id, its `part_slug` or one word of its title, casefolded. A `part` that names no
      text, or more than one, refuses with the parts as candidates.
    - **`room` matches** a key when it equals `k.key`, or when `k.key == f"{k.part}-{room}"`, filtered by `part`
      when given. The node and room fallbacks stay.
    - **More than one hit** refuses: `NotFound("The key '7' is in more than one part.", candidates=[{key, title,
      node, part}], hint="Name the part, as module_key(room='7', part='<part>'), or the key as written.")`.
    - **The answer** gains `part`.
  - **`dm.md`:** the `module_key` line says that a key two parts share takes `part`, or the key as written.
- [ ] **Step 1: Write the failing tests:**
  - two texts, each with "## 7. …", derive to `haunted-house-7` and `sea-ghost-7`, and a unique 22 stays `22`;
  - the export validates with no `duplicate-id`, and re-importing it gives the same keys;
  - `module_key("7")` refuses with candidates carrying `part`;
  - `module_key("7", part="ship")`, `module_key("7", part="sea-ghost")` and `module_key("sea-ghost-7")` give the ship's;
  - a pre-existing single-part module's keys are unchanged (`test_module_tools.py`'s current cases pass as they
    are).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `uv run pytest tests/modules tests/dm` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Keys scoped to their part: unique in the format, and module_key takes the part"`

---

### Task 9: C2 and C3, entities in their own part, and de-duplicated

**Files:**
- Create: `src/delve/modules/books/dedupe.py`, `src/delve/modules/books/prompts/dedupe.md`,
  `tests/modules/books/test_dedupe.py`
- Modify: `src/delve/modules/books/convert.py` (`_entities`, `_place`, `key_entities`, `convert_book`, `map_title`),
  `tests/modules/books/test_convert.py`

**Interfaces:**
- Consumes: Task 1 (`merge_entities_mapped`, `repair_refs`, `renamed`), Task 8 (`scoped_keys`).
- Produces:
  - **The record's own text:** `_entities` also returns `origins: dict[str, str]`, from `"<ref kind>:<id>"` to the
    text the record was read from. `key_entities(source, origins: Mapping[str, str] = {})`.
  - **`_place(record, headings, own: str | None)`:**
    - It tries the headings of the record's own text first, by its `location`/`key` (`key:N` only within the own
      text), title and summary.
    - It then accepts an exact `text:<id>#<anchor>` `location` in any text, and nothing else.
  - **A house encounter with no place** is keyed when the creatures it names appear in one keyed section of its own
    text and in no other (`_by_creature`). The creatures are its `fixed` creatures' ids as words, else the words of
    its name, without "group", "of" and "the".
  - **`key_entities`:**
    - it writes scoped keys: entries' `key`, and an encounter's `key` as `key:<scoped key>`;
    - it makes a `keys[]` entry for **every** keyed heading, placed or not (18, 19, 20, 25, 26).
  - **`map_title(page)`** answers `page.plate_title` first (Task 2), else the OCR title.
  - **`dedupe.py`, `async def dedupe_entities(entities, complete: Complete) -> tuple[dict[str, list[dict]],
    dict[str, str], list[Warning]]`:**
    - **One call per kind,** `npcs` and `factions`, when there are two records or more. It sends `prompts/dedupe.md`
      with one line per record: `id | name | role | the summary's first sentence`.
    - **The answer** is a JSON list of groups of ids, the record to keep first. Each group of two or more is merged
      by `merge_entities_mapped`'s rules, and `renamed` holds the dropped ids.
    - **Each merge** warns `entities-merged`: "Merged as one: A, B, C."
    - **An id not given, a record in two groups, or an answer that isn't such a list** merges nothing in that
      kind, with `entities-not-deduplicated`.
    - `convert_book` runs it after `_entities`, inside the concurrency limit. Its `renamed` joins `repair_refs`'.
    - `progress("entities", …)` stays as it is.
- [ ] **Step 1: Write the failing tests:**
  - **`test_ship_npcs_stay_on_the_ship`:** two texts each with 7, 11, 14 and 17. The ship text's bosun, smugglers,
    prisoner and boarding encounter key to the ship's headings (`key:sea-ghost-11`…), and none to the house's.
  - `test_every_keyed_heading_has_an_entry` (18, 19, 20, 25, 26);
  - `test_the_well_snake_is_keyed_by_its_creature`;
  - `test_dedupe_merges_what_claude_groups`: Ned ×3 and the Bosun ×2 merged, refs rewritten through `repair_refs`;
  - `test_dedupe_keeps_bernhardt_apart_when_not_grouped`;
  - `test_dedupe_survives_a_bad_answer`;
  - `map_title` prefers `plate_title`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `uv run pytest tests/modules/books` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Entities placed in their own part, a key entry for every keyed heading, and duplicates merged as Claude groups them"`

---

### Task 10: C4, front matter apart

**Files:**
- Modify: `src/delve/modules/books/convert.py` (`_texts`, `chapter_title`, `convert_book`), `src/delve/play/sessions.py`
  (`_module`'s opening), `tests/modules/books/test_convert.py`, `tests/play/test_sessions.py`

**Interfaces:**
- Consumes: Task 9 (convert.py).
- Produces:
  - **`FRONT_MATTER = "front-matter"`, titled "Front matter".**
  - **`BACK_PAGES = 1` and `FRONT_PAGES = 1`:** a chunk whose pages are all among the book's first `FRONT_PAGES`
    or its last `BACK_PAGES` is front matter. Its Markdown goes into the front-matter text, its `#` headings
    demoted to `##`, so it makes no chapter.
  - **The text before the first chapter** joins the front matter when it holds no keyed heading.
  - **The front-matter text** is `gm` and comes last among the texts.
  - **`chapter_title`** answers None for a page among the first `FRONT_PAGES` or the last `BACK_PAGES`. A map page
    was already refused, which covers U1's page 2 once Task 2 marks it.
  - **The DM's opening** (`sessions._module`) is the first text whose id isn't `FRONT_MATTER`.
- [ ] **Step 1: Write the failing tests:** a cover page and a back page of ads become the last text,
  `front-matter`, and no chapter; the opening is the first chapter; a book with a keyed heading on its first page
  keeps it as a chapter.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The cover, the title page and the back cover kept apart as front matter, and the DM opens on the first chapter"`

---

### Task 11: D1, every boxed text in a keyed section is read-aloud

**Files:**
- Modify: `src/delve/modules/text.py` (`sections_of`, `_without_read_aloud`), `web/src/module/TextEditor.tsx`
  (`ReadAloud`), `web/src/routes/ModulePrint.tsx` (the read-aloud marking), `tests/modules/test_text.py`,
  `tests/dm/tools/test_module_tools.py`, `TextEditor.test.tsx`, `ModulePrint.test.tsx`

**Interfaces:**
- Consumes: Task 8 (`text.py`).
- Produces:
  - **For a keyed section,** `TextSection.read_aloud` is every blockquote of the section's own lines, up to the
    next heading of any level, in order. Their markers are removed as `parse_text` removes them, and they are joined
    with a blank line.
  - **`markdown`** is the section's own lines without any blockquote line, with runs of blank lines collapsed.
  - **An unkeyed section** keeps the rule of today: the quotes straight after its heading.
  - **The copied `dscn/text.py` doesn't change.**
  - **The editor and the print** mark the same quotes: after a keyed heading (`headingKey`), every blockquote up to
    the next heading; after another heading, only the leading ones. Only decorations change, so the round-trip
    test is unchanged.
- [ ] **Step 1: Write the failing tests:**
  - a room with a quote, DM text, a quote and DM text has both quotes in `read_aloud` and neither in `markdown`;
  - `module_key` gives both;
  - an unkeyed "Background" section keeps a later quote in its DM text;
  - the editor and the print decorate the second quote only under a keyed heading;
  - `roundtrip.test.ts` passes unchanged.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Every boxed text of a keyed room is read-aloud, in the DM's text, the editor and the print"`

---

### Task 12: D2, handouts split, linked to their keys and shown to the players

**Files:**
- Modify: `src/delve/modules/books/classify.py` (`cut`), `src/delve/modules/books/convert.py` (`_attachments`, a new
  `link_handouts`, `convert_book`), `tests/modules/books/test_classify.py`, `tests/modules/books/test_convert.py`

**Interfaces:**
- Consumes: Task 2 (`PdfPage.handouts`, `HandoutBox`), Task 8 (`part_slug`, `scoped_keys`), Task 10 (convert.py).
- Produces:
  - **`cut(png: bytes, box: tuple[float, float, float, float]) -> bytes`:** the box of the picture, cropped with
    Pillow and saved as a PNG.
  - **`_attachments`** makes `handout-<page>-<n>` (`image/png`, audience `player`) for each of a page's handouts.
    - Its description is `f"Handout from page {page}: {title}"`.
    - Each handout gets the `audience-player` warning (`players_warning`), so the owner confirms it.
    - The page's whole picture stays `page-<n>`, `gm`.
  - **`link_handouts(source, handouts: list[tuple[str, HandoutBox]]) -> tuple[ModuleSource, list[Warning]]`:**
    - it runs after `key_entities`;
    - a handout with a `key` goes into the `assets` of the one keyed heading with that printed key;
    - when several have it, the one whose `part_slug` or title holds the handout's `part`;
    - else nothing is linked, with a `handout-not-linked` warning.
- [ ] **Step 1: Write the failing tests:**
  - a page with two handout boxes gives two `player` attachments of the boxes' sizes;
  - the parchment with key 22 links to the house's 22;
  - the chart with key 9 and part "ship" links to the ship's 9, not the house's;
  - a handout with key 9 and no part, in a module where both parts have a 9, is `handout-not-linked`;
  - `show_image` may show a linked handout (`player_images`).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Handouts cut from their page, linked to their room and shown to the players"`

---

### Task 13: D3, text-layer gaps filled from the page image

**Files:**
- Create: `src/delve/modules/books/gaps.py`, `src/delve/modules/books/prompts/fill-gaps.md`,
  `tests/modules/books/test_gaps.py`
- Modify: `src/delve/modules/books/pdf.py` (`render_page`), `src/delve/conversions/runner.py` (`_convert_pdf`,
  `STEPS`), `src/delve/modules/books/prompts/convert.md` (the questions' default), `tests/conversions/test_runner.py`,
  `en.json`/`nl.json` (anchor `conversion.step.generating`)

**Interfaces:**
- Consumes: Task 5 (runner.py), Task 14 (pdf.py, convert.md).
- Produces:
  - **`pdf.render_page(path: Path, number: int, dpi: int = OCR_DPI) -> bytes`:** page `number` as a PNG, under
    `MAX_RENDER_PIXELS`.
  - **`GAP = re.compile(r"\b(?:HD|AC|MV|hp|THAC0|#AT)\s+[;,]|\|[ \t]+\|")`:** a stat field with no value, or an empty
    table cell. `gap_lines(markdown) -> list[str]`.
  - **`async def fill_gaps(source: ModuleSource, book: PdfBook, look: Look | None, page_image: Callable[[int],
    Awaitable[bytes]]) -> tuple[ModuleSource, list[Warning]]`:**
    - **Finding the page:** each gap line's page is the one whose text (whitespace collapsed) holds the line's
      longest run of three or more words without a gap.
    - **Which lines go:** the gap lines of a page and, when one of them is a table row, every row of that table.
      At most `MAX_GAP_PAGES = 12` pages are sent.
    - **One vision call per page,** with the page's picture fitted and `prompts/fill-gaps.md`: the lines, numbered.
      The answer is `[{"n": <number>, "line": <the line as printed>}]`.
    - **A line is accepted only** when it equals the old line with each gap filled by at most 6 characters, or with
      only `½ ¼ ¾` added, whitespace aside (`_only_filled(before, after)`).
    - **An accepted line** replaces the old one in its text. Each gap's three words before and after are replaced
      where they appear verbatim in an entity record's strings. It warns `text-filled`: "Read from page N's picture:
      “HD ;” → “HD ½;”. Check it."
    - **A refused line, a failed call, or no `look`** warns `text-gap`: "Page N's text layer lost a character here:
      “…”. Check it against the page." It never assumes the line is right as printed.
  - **`runner`:**
    - After `convert_book`, it runs `fill_gaps(converted.source, book, look_for(services), page_image)`, where
      `page_image = lambda n: asyncio.to_thread(render_page, path, n)`.
    - The step is `gaps`, in the converting step: `STEPS["pdf"][2] == ("converting", "gaps")`.
  - **`convert.md`:** a question about a value the text layer lost (an empty field, a stray `;` or `,`) has the
    default "Unknown: read it from the page", never "as printed".
  - **i18n:** `conversion.step.gaps` "Reading lost characters from the page pictures".
- [ ] **Step 1: Write the failing tests:**
  - "AC 7; HD ; hp 4" filled to "HD ½;" from a fake look, and the encounter record's line too;
  - a roster row "| 19. Theodore Dobbins |  | M | T |" filled with "½";
  - a row whose answer adds "½" to the race cell ("E" → "½E") in the same table is accepted;
  - an answer that changes a word as well is refused, with `text-gap`;
  - no look gives `text-gap` and no call;
  - a page without gaps sends nothing.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `uv run pytest tests/modules/books tests/conversions` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Glyphs the text layer lost, such as the ½ and ¼ Hit Dice, read from the page's picture, never assumed"`

---

### Task 14: D4 and D5, bold and italic kept; small pictures kept or warned

**Files:**
- Modify: `src/delve/modules/books/pdf.py` (`_page_text`, `_lines`, `_line`, `PICTURE_SHARE`, `_pictures`),
  `src/delve/modules/books/prompts/convert.md` (keep emphasis), `tests/fixtures/pdfs.py` (a run's font:
  `Helvetica-Bold`, `Helvetica-Oblique`), `tests/modules/books/test_pdf.py`

**Interfaces:**
- Consumes: Task 2 (pdf.py).
- Produces:
  - **Bold and italic (D4):** `_page_text` reads words with `extra_attrs=["fontname"]`.
    - A word is bold when its font name, casefolded, holds `bold`, `black` or `heavy`, and italic when it holds
      `italic` or `oblique`.
    - A run of words of one style within a line is wrapped once: `**…**`, `*…*` or `***…***`.
    - A line wholly bold is left bare: it is a heading, and Claude makes it one.
    - **`convert.md`:** "Keep the book's `**bold**` and `*italic*` as they are."
  - **Small pictures (D5):**
    - `PICTURE_SHARE = 0.03`;
    - an image under it on a page is left out, with one `image-dropped` warning per page: "Page N: K small images
      (under 3 % of the page) were left out."
    - `PICTURE_PAGE_SHARE` stays.
- [ ] **Step 1: Write the failing tests:**
  - a page with a bold spell name and an italic book title reads `**sleep**` and `*The Codex*`;
  - an all-bold heading line stays bare;
  - a 5 % illustration is kept, and a 1 % ornament is dropped with `image-dropped`;
  - `numbers_changed` and the short check are unchanged by the marks.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `uv run pytest tests/modules/books` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Bold and italic kept from the PDF, and small illustrations kept or warned"`

---

### Task 15: D6, stat lines visible and editable

**Files:**
- Modify: `web/src/module/EntityForm.tsx` (`NPC_STATS`, the encounter's monsters and Where),
  `web/src/routes/ModulePrint.tsx`, `src/delve/modules/books/prompts/entities.md`, `EntityForm.test.tsx`,
  `ModulePrint.test.tsx`, `tests/modules/books/test_entities_prompt.py` (new: the prompt's text; `test_convert.py` is
  Task 10's in this wave), `en.json`/`nl.json` (anchor `entity.hp`)

**Interfaces:**
- Consumes: Task 8 (scoped keys), Task 11 (ModulePrint.tsx).
- Produces:
  - **`EntityForm`:**
    - an NPC's form shows and edits `stats.adnd2e.line` as "Stat line", a text area beside the six fields;
    - an encounter row's notes show its monster's stat line;
    - Where lists **every** keyed heading of the module, by `keys[]` and the derived keys, with its scoped key and
      title, and not only the linked rooms.
  - **`ModulePrint`:** an NPC's and an encounter's stat line printed under their name.
  - **`entities.md`:**
    - an encounter's creatures go in `fixed`, each with its count and, in `notes`, its stat line as printed;
    - an appendix stat block of a person named elsewhere is that person's NPC record, with the same name. Task 9's
      dedupe then merges it.
  - **i18n:** `entity.statLine`, `entity.statLineHint`.
- [ ] **Step 1: Write the failing tests:** Sanbalet's `line` shows and saves; the encounter's monster notes show; Where
  lists an unlinked key (`haunted-house-19`); the print shows the line; the prompt asks for `fixed`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `npm test`, `uv run pytest tests/modules/books` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Stat lines shown and edited in the NPC and encounter forms and in print, and appendix stat blocks joined to their people"`

---

### Task 16: E, pregens in the format

**Files:**
- Modify: `src/delve/modules/dscn/scenario.schema.json` (`entities.pregens`, `$defs.pregen`, `$defs.pregensFile`),
  `src/delve/modules/dscn/container.py` (`ENTITY_KINDS`), `src/delve/modules/dscn/refs.py` (`INTERNAL_KINDS`,
  `ENTITY_REF_KINDS`), `src/delve/modules/source.py` (`CHECKED_ENTITY_REFS`), `src/delve/web/routes/module_source.py`
  (`FORM_KINDS`), `docs/maps/scenario-format.md` (the pregens section), `tests/modules/dscn/` (a schema and container
  test), `tests/modules/test_export_round_trip.py`, `tests/web/test_module_source_api.py`

**Interfaces:**
- Consumes: Task 8 (source.py).
- Produces:
  - **The kind:** `pregens` in `ENTITY_KINDS` (last), with the ref `pregen:<id>` (`ENTITY_REF_KINDS["pregen"] =
    "pregens"`). Its file is `entities/pregens.yaml`. The format's version stays 2.
  - **`$defs.pregen`:** `entityCore` plus:
    - `race`, `class`, `alignment` and `background`, strings;
    - `level`, an integer or a string ("3/3");
    - `gear`, strings;
    - `stats`, `$defs/stats`, whose `adnd2e` holds the `Sheet` fields `create_character` takes (`ability_scores`,
      `hp_max`, `ac`, `cls`, `levels`, `race`, `alignment`, `weapon_profs`, `nwps`, `skills`, `spell_slots`).
  - **A pregen's default audience is `player`**, set by the source when the record has none. `gm` is allowed and
    hidden from seats (Task 19).
  - **`FORM_KINDS["pregens"] = "pregen"`**, so the source API's entity routes take them.
  - `CHECKED_ENTITY_REFS` gains `pregen`.
  - **An older reader** with the version-2 schema meets `entities.pregens` as an unknown property. That is a schema
    finding, never a crash. The format doc says so.
- [ ] **Step 1: Write the failing tests:**
  - a bundle with two pregens validates and round-trips (import, export, import);
  - a pregen without `name` is a schema error;
  - `pregen:x` resolves in a key's refs, and a missing one is `missing-entity`;
  - `PUT …/entities/pregens/{id}` stores one, `player` by default.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `uv run pytest tests/modules tests/web/test_module_source_api.py` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Pregenerated characters as a section of the module format: name, race, class, level, stats, gear and background"`

---

### Task 17: E, the converter fills the pregens from the roster

**Files:**
- Modify: `src/delve/modules/books/convert.py` (`ENTITY_KINDS`, `_records`), `src/delve/modules/books/prompts/entities.md`,
  `tests/modules/books/test_convert.py`

**Interfaces:**
- Consumes: Task 16, Task 15 (`entities.md`), Task 12 (convert.py).
- Produces:
  - **`ENTITY_KINDS["pregens"] = "pregen"`.**
  - **`entities.md`:** a roster table of pregenerated characters (U1's page 29) gives `pregens`, one per row:
    - name, race (as printed, "½E" included), class, level and alignment;
    - the ability scores and hit points in `stats.adnd2e`;
    - the gear, and the background or notes.
  - The roster's text stays as it is, a `gm` text, and gives no NPCs.
- [ ] **Step 1: Write the failing tests:** a fake entities answer with a roster gives `pregens` records, `player`,
  valid against `$defs.pregen`, and no NPC for a pregen; an invalid row is `entity-dropped`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The book's roster of pregenerated characters converted into the module's pregens"`

---

### Task 18: E, pregens in the module editor and the print

**Files:**
- Modify: `web/src/api.ts` (`ENTITY_KINDS`), `web/src/module/EntityForm.tsx` (the pregen form, `REF_KIND`),
  `web/src/routes/ModuleDetail.tsx` (`TABS`: `pregens` after `quests`), `web/src/routes/ModulePrint.tsx` (a
  "Pregenerated characters" section), their tests, `en.json`/`nl.json` (anchor `entity.related`)

**Interfaces:**
- Consumes: Task 16, Task 15 (EntityForm, ModulePrint), Task 27 (ModuleDetail).
- Produces:
  - **`ENTITY_KINDS = ["npcs", "encounters", "factions", "quests", "pregens"]` and `REF_KIND.pregens = "pregen"`.**
  - **The pregen form:**
    - name, race, class, level, alignment and background;
    - the six abilities and hit points, into `stats.adnd2e.ability_scores` and `hp_max`;
    - the gear, one per line;
    - the audience, Players by default.
  - **The print** lists the pregens as a table.
  - **i18n:** `module.tab.pregens` "Pregens" / "Voorgemaakte personages", and the form's labels (`entity.gear`,
    `entity.background`, `entity.abilities`).
- [ ] **Step 1: Write the failing tests:** the Pregens tab lists, adds, edits and deletes one; the abilities save into
  `stats.adnd2e`; the print's table shows them.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `npm test` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Pregens in the module editor, a tab of their own, and in the print"`

---

### Task 19: E, party creation offers the module's pregens

**Files:**
- Create: `src/delve/web/routes/pregens.py`, `src/delve/dm/tools/pregens.py`, `web/src/play/PregenPicker.tsx` with a
  test, `tests/web/test_pregens_api.py`, `tests/dm/tools/test_pregens.py`
- Modify: `src/delve/web/app.py` (the router), `src/delve/dm/tools/host.py` (`all_specs`),
  `tests/dm/tools/test_fourth_wall.py` (`DM_ONLY_TOOLS`), `tests/dm/tools/test_tools.py` (no ttrpg2 name: listed as
  Delve's own), `tests/web/test_fourth_wall_per_seat.py` (a planted `gm` pregen), `src/delve/dm/prompt/dm.md` (the
  party-creation paragraph), `web/src/play/PartySidebar.tsx` (mount), `web/src/play/api.ts`, `en.json`/`nl.json`
  (anchor `play.noParty`)

**Interfaces:**
- Consumes: Task 16; Task 20 (`dm.md`); Task 21 (`test_fourth_wall.py`).
- Produces:
  - **`GET /api/campaigns/{id}/pregens` (`TableSeat`):** the pinned revision's pregens with audience `player`, as
    `[{id, name, race, class, level, alignment, gear, background, stats}]`. It holds no `gm` record, no `summary` and
    no `description`.
  - **The DM-only tool `module_pregens()`:** the pinned revision's pregens, every audience, with the sheet each would
    make: `{id, name, sheet}`, `sheet` from `stats.adnd2e` plus race, class and alignment. Its description says to
    pass the sheet to `create_character`. It is not mutating, `player_visible=False`, and goes into `all_specs()`.
  - **`PregenPicker`:**
    - shown in the party sidebar's empty state to the host only, when the route lists pregens;
    - a checkbox per pregen, with its race, class and level, then "Ask the DM to make them".
    - That submits the host's act: "Create the party from the module's pregenerated characters: A, B, C."
    - Without pregens, the "No characters yet" line stays as it is.
  - **`dm.md`:** when asked to make the party from the pregens, call `module_pregens` and then `create_character`
    with each sheet as given, the book's race and class included.
  - **i18n:** `play.pregens`, `play.pregensMake`, `play.pregensAct`.
- [ ] **Step 1: Write the failing tests:**
  - the route lists a `player` pregen and leaves out a `gm` one holding `SECRET-XYZZY`, for the host, a player and an
    observer (`test_fourth_wall_per_seat.py`);
  - `module_pregens` gives the sheet, and `create_character` with it makes the PC;
  - the picker posts the act with the chosen names;
  - `test_prompt_names_only_existing_tools` passes.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `uv run pytest tests/web tests/dm`, `npm test` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Party creation offers the module's pregens, and the DM makes the party from them"`

---

### Task 20: F1, the DM is told when a part has no map

**Files:**
- Modify: `src/delve/play/sessions.py` (`_module`), `src/delve/dm/prompt/dm.md` (the primer's module paragraph),
  `web/src/play/MapPanel.tsx`, `web/src/play/MapPanel.test.tsx`, `tests/play/test_sessions.py`, `en.json`/`nl.json`
  (anchor `mapState.offline`)

**Interfaces:**
- Consumes: Task 10 (sessions.py), Task 21 (dm.md), Task 8 (`Key.part`).
- Produces:
  - **The primer's `module.unmapped`:** `[{text, title, keys: <how many>}]`, for each text with keyed headings of
    which none has a `node` on a played map that parses. The block's key set in `test_primer_shape` gains it.
  - **`dm.md`:**
    - a part listed in `unmapped` has no map: never invent its layout;
    - say so out of character to the host, once, and ask for a map (Draw it from the book's page);
    - until then, run it from the text alone, with no direction or room you can't read in it.
  - **`MapPanel`:** with no group on a map, it says "This part of the adventure has no map." (`mapState.noMap`).
    Only a 409 from the view is "Map offline". The text holds no key or room.
- [ ] **Step 1: Write the failing tests:**
  - a module with a mapped ship and an unmapped house lists the house in `unmapped`;
  - the primer shape test passes with `unmapped`;
  - the panel shows `mapState.noMap` without a position and "Map offline" on a 409;
  - `test_prompt_names_only_existing_tools` passes.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The DM told which parts have no map, to ask the host instead of inventing one, and the map panel says so"`

---

### Task 21: F2 and F4, a fresh roll per occasion; hidden rolls kept quiet

**Files:**
- Modify: `src/delve/rules/adnd2e/checks.py` (`skill_check`, `ability_check`, `encounter_check`),
  `src/delve/dm/tools/dice.py` (`roll`, `skill_check`, `ability_check`, `encounter_check`),
  `src/delve/dm/tools/composites.py` (`scout`), `src/delve/play/table.py` (`feed_entry_for`), `src/delve/dm/prompt/dm.md`
  ("Hidden State and the Fourth Wall", and the dice lines), `tests/rules/adnd2e/test_checks.py`,
  `tests/dm/tools/test_host.py`, `tests/dm/tools/test_fourth_wall.py` (`DM_ONLY_TOOLS` gains `encounter_check`),
  `tests/play/test_table.py`, `tests/fixtures/scripts/first_session.golden.json` (regenerated, reviewed)

**Interfaces:**
- Consumes: Task 8 (dm.md, wave 1), Task 22 (the golden).
- Produces:
  - **F2, the occasion:** `checks.skill_check(…, occasion: str = "")` and `ability_check(…, occasion: str = "")`.
    - The purpose is `f"skill:{skill}#{occasion}"` and `f"ability:{ability}#{occasion}"` when there is an occasion,
      else what it is today.
    - The tools take `occasion=string("What this check is for this time ('jump the gap', 'tie the knot'); a new
      occasion rolls fresh, the same one again is the stored roll.")`.
  - **Encounter checks per interval:** `checks.encounter_check(…, occasion: str = "")` keys `encounter:check`,
    `encounter:drift` and `encounter:table` with `#<occasion>`. The tool passes the game time, `f"day {state.day}
    {hh:mm}"`, so a check after `advance_time` rolls fresh.
  - **`scout`** passes each of its checks a distinct occasion (its step's name).
  - **F4, hidden rolls:**
    - `roll`, `skill_check` and `ability_check` take `hidden=boolean("A roll the players mustn't know failed: a
      search, listening, finding traps. It leaves no row in the story.")`.
    - `feed_entry_for` makes no tool row for a call whose arguments hold `hidden: true`.
    - `encounter_check` becomes `player_visible=False`: no row, ever.
  - **`dm.md`:**
    - `:141` and `:155` are settled: rolls show to the host and co-hosts as tool rows, never to the players.
    - A hidden roll (searching, listening, finding traps, a wandering-monster check) is made with `hidden`, and its
      failure is narrated as finding nothing ("You find nothing"), never as a failed roll.
    - A wandering-monster check that brings nothing isn't narrated at all.
    - Pass an `occasion` to checks that repeat in a beat.
- [ ] **Step 1: Write the failing tests:**
  - two `ability_check`s in one beat with occasions "jump" and "knot" roll twice (`ScriptedRng` 6 then 14), and the
    same occasion again is the stored roll;
  - three encounter checks an hour apart (`advance_time(60)` between) roll three times;
  - a `hidden` skill check makes no story row for any seat;
  - `encounter_check` makes no row;
  - the fourth-wall test passes with `encounter_check` DM-only;
  - `dm.md` no longer says "Rolls are public";
  - the regenerated golden's diff is the roll keys only.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**, then `DELVE_REGOLDEN=1 uv run pytest tests/e2e/test_scripted_session.py`, and review the
  golden's diff against the rules.
- [ ] **Step 4: Run `uv run pytest tests/rules tests/dm tests/play tests/e2e/test_tool_timing.py` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "A fresh roll per occasion and per encounter interval, and hidden rolls that leave the players nothing to read"`

---

### Task 22: F3, surprise kept when a fight is set up again

**Files:**
- Modify: `src/delve/play/combat.py` (`_setup`, a new `_surprise_dice`), `tests/play/test_combat.py`,
  `tests/fixtures/scripts/first_session.golden.json` (only if it moves; regenerated and reviewed)

**Interfaces:**
- Produces:
  - **`_surprise_dice(ctx) -> Dice`:** keyed `f"{ctx.beat}/surprise-{n}"`, where `n` is the number of this beat's
    `combat` events with `outcome == "ended"` and `rounds > 0`.
    - A fight set up and ended in round 0, which is a corrected fight, doesn't count. So setting the fight up again
      in the beat finds the stored surprise rolls.
    - After a fight that was played, the next fight rolls fresh.
    - `ctx.storage.events.list(campaign_id, types=["combat"])` is read once, filtered on the beat.
  - **Only surprise uses it.** Hit points and initiative stay on `_dice(ctx, id)`, so test 338's fresh second fight
    holds.
- [ ] **Step 1: Write the failing tests:**
  - `setup_combat`, `end_combat` at round 0, then `setup_combat` with another monster gives the same surprise result,
    with fresh hit points;
  - a played fight, then a second, rolls surprise fresh;
  - `test_combat.py`'s existing dice-order tests pass.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `uv run pytest tests/play tests/e2e/test_scripted_session.py tests/e2e/test_tool_timing.py` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "A corrected fight keeps the surprise it rolled"`

---

### Task 23: F5, Ask sees the session

**Files:**
- Modify: `src/delve/play/ask.py` (`ask_prompt`, `RECENT`, `ASK_RULES`), `tests/play/test_ask.py`,
  `tests/web/test_fourth_wall_per_seat.py` (Ask's session block, a planted entry for another seat)

**Interfaces:**
- Produces:
  - **`SESSION_CHARS = 8000`.**
  - **"WHAT HAPPENED THIS SESSION":**
    - every story entry of the current session (`_RECENT_KINDS`) that `can_see` lets the asker see, oldest first;
    - when over `SESSION_CHARS`, the newest that fit, with "(earlier entries left out)";
    - never fewer than the last `RECENT` (8) entries the asker may see.
  - **"LAST RECAP":** the last session's `recap_md`, which every seat sees.
  - **`ASK_RULES`** gains: "Never name a room by a key number ('room 4'): name it as the characters know it."
- [ ] **Step 1: Write the failing tests:**
  - after 13 beats of entries, the prompt holds the first beat's act;
  - an entry told to another seat isn't in it;
  - the recap is in it;
  - the rules line is there;
  - the planted secret for another seat never reaches the asker's prompt.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Ask the DM reads the whole session and the last recap, never a key number"`

---

### Task 24: F6, the giant centipede's own reference row

**Files:**
- Create: `reference/snapshots/corrections.sql.gz`
- Modify: `reference/snapshots/SHA256SUMS`, `src/delve/storage/reference/build.py` (load `corrections.sql.gz` last),
  `src/delve/storage/reference/sqlite_reference.py` (`monster`: `deleted_at IS NULL`), the reference tests
  (`tests/storage/`)

**Interfaces:**
- Produces:
  - **`corrections.sql.gz`** holds:

    ```sql
    UPDATE monsters SET name = 'centipede, giant' WHERE id = 337;
    UPDATE monsters SET name = 'centipede, huge' WHERE id = 338;
    UPDATE monsters SET deleted_at = '2026-10-19', deleted_reason = 'duplicate of centipede, megalo-' WHERE id = 339;
    UPDATE monsters SET deleted_at = '2026-10-19', deleted_reason = 'duplicate of centipede, tunnel worm' WHERE id = 340;
    ```

    Rows 337 and 338 hold the Monstrous Manual's giant centipede (2–24, AC 9, MV 15, 2 hp) and huge one (5–30,
    MV 21, 1 hp). Rows 339 and 340 are copies of the megalo-centipede and the tunnel worm.
  - **`SHA256SUMS` names it,** so a `reference.db` built before this is refused by `delve serve` (exit 4) until
    `make install` rebuilds it. `docs/progress.md` says so (Task 30).
  - **`monster(name)`** skips rows with `deleted_at`.
- [ ] **Step 1: Write the failing tests:** on the real reference (`real_reference_db`), `monster("centipede, giant")[0]`
  is row 337, with `hit_dice` "2 hp" and `thac0` 19 (not row 339's "3" and 17); `monster("centipede, megalo-")[0]` is
  still row 902429; no lookup answers row 339 or 340; `verify` covers the new file.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `uv run pytest tests/storage tests/rules` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The reference's giant centipede is the giant centipede, not a copy of the megalo-centipede"`

---

### Task 25: G1, the whole story, for any seat

**Files:**
- Modify: `web/src/play/Story.tsx`, `web/src/play/useStory.ts`, `Story.test.tsx`, `Play.test.tsx`, `en.json`/`nl.json`
  (anchor `play.loadEarlier`)

**Interfaces:**
- Produces:
  - **Scrolling to the top of the story loads the earlier page by itself,** through an `IntersectionObserver` on a
    sentinel above the first entry. The "Load earlier" button stays for keyboards and tests.
  - **The reader keeps their place:** the scroll position is kept across a load.
  - **"Back to the latest"** shows while the reader is more than a screen above the newest entry.
  - **A late joiner** reads back to the first entry their seat may see. The server's `story(…, before_seq, limit)`
    is unchanged.
  - **i18n:** `play.backToLatest`, `play.storyStart` ("The start of the story").
- [ ] **Step 1: Write the failing tests:** an observed sentinel calls `loadEarlier`; "The start of the story" shows
  when there is no more; "Back to the latest" scrolls down.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `npm test` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Any seat scrolls back through the whole story, loaded as it scrolls"`

---

### Task 26: G2, costs recorded and shown

**Files:**
- Create: `src/delve/storage/migrations/versions/0015_costs.py`
- Modify: `src/delve/dm/provider.py` (`side_call`, `vision_call`), `src/delve/dm/claude_cli/provider.py`,
  `src/delve/dm/claude_cli/stream.py` (`_result`), `src/delve/dm/fake.py`, `src/delve/domain/conversions.py`,
  `src/delve/storage/sqlite/{tables.py,conversions_repo.py}`, `src/delve/conversions/runner.py` (`_complete`,
  `look_for`), `src/delve/play/ask.py` (the DM log row), `web/src/api.ts` (`Conversion.cost_usd`),
  `web/src/routes/CampaignDetail.tsx` (`beatCosts`: Ask rows), `web/src/routes/NewModule.tsx` (the job's cost),
  `tests/fixtures/fake_claude.py` (a `total_cost_usd` on side calls), their tests, `tests/storage/contract.py`,
  `tests/storage/test_migrations.py`, `en.json`/`nl.json` (anchor `dmLog.noCost`)

**Interfaces:**
- Consumes: Task 13 (runner.py), Task 23 (ask.py), Task 5 (NewModule.tsx).
- Produces:
  - **The provider:** `side_call(…, on_usage: Callable[[Usage], None] | None = None)` and `vision_call(…, on_usage=…)`.
    The claude CLI calls it with the `result` line's usage and `total_cost_usd`. `FakeDM` calls it when given a
    `side_usage: Usage`.
  - **A beat's cost no longer resets (P-e):**
    - `stream._result` reports the cost of this reply: `total_cost_usd` minus the process's last one;
    - after a new process, the whole value;
    - `Usage.cost_usd` means "this reply" from here on.
  - **Migration `0015_costs`:** `conversions.cost_usd REAL NULL`. `Conversion.cost_usd: float | None = None`. The
    runner sums every call's cost into it, as it goes, saved with the progress.
  - **Ask:** an `ask` row in the DM log, `{"type": "ask", "usage": {"input_tokens", "output_tokens", "cost_usd"}}`,
    under no beat. `beatCosts` shows it as an "Ask" row.
  - **`NewModule`'s done screen** and the conversions list show the job's cost when known.
  - **i18n:** `dmLog.ask`, `conversion.cost`.
- [ ] **Step 1: Write the failing tests:**
  - two replies of one process at 0.10 then 0.25 cumulative give 0.10 and 0.15, and after a restart 0.05 is 0.05;
  - a conversion with three fake calls of 0.01 stores 0.03;
  - an Ask writes its DM log row;
  - the migration keeps existing rows with `cost_usd` null;
  - `beatCosts` lists the Ask.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `uv run pytest tests/dm tests/conversions tests/storage tests/play` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Costs: each beat's own, each Ask's in the DM log, and each conversion's"`

---

### Task 27: G3, the small module items

**Files:**
- Modify: `src/delve/__main__.py` (the start message), `web/src/routes/ModuleDetail.tsx` (warnings header, Maps tab
  links, head revision), `web/src/routes/Modules.tsx` (head revision), `tests/test_cli.py`, `ModuleDetail.test.tsx`,
  `Modules.test.tsx`, `en.json`/`nl.json` (anchor `modules.deleteFailed`)

**Interfaces:**
- Produces:
  - **S1, the start message:** "Delve is running. On this machine, open http://localhost:<port>/. From another
    device, sign in with the owner token in <data dir>/token; players join through the invites on the play
    screen."
  - **S4, the head revision:** a module with `head_revision` null shows "Not played yet: a campaign takes its own
    copy when it starts" (`modules.notPinned`) instead of nothing, in the list and on the module page.
  - **E-c, no dead map links:**
    - the Maps tab lists every played map, with a link to its editor and its DM view;
    - a link is only made to a map that exists, so a text whose `map` names a missing map shows "No such map" in
      plain text.
  - **E-d, the distinct-problem count:** the warnings header counts the distinct codes ("53 warnings, 4 kinds").
    Each group still lists its own.
- [ ] **Step 1: Write the failing tests:** the start message names the token's path; a module with no revision shows
  `modules.notPinned`; a text naming a missing map renders no link; the header counts kinds.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `npm test`, `uv run pytest tests/test_cli.py` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Small module items: the start message's token hint, the head revision, no dead map links, and a count of kinds"`

---

### Task 28: G3, the small play and editor items

**Files:**
- Modify: `web/src/routes/Campaigns.tsx` (S2), `web/src/play/Story.tsx` (P-b), `web/src/routes/Join.tsx` (T-a),
  `web/src/module/TextEditor.tsx` (E-b), `web/src/styles.css`, their tests, `en.json`/`nl.json` (anchor
  `campaigns.toModules`)

**Interfaces:**
- Consumes: Task 25 (Story.tsx), Task 11 (TextEditor.tsx).
- Produces:
  - **S2, the first screen:** with no module and no campaign, a first-run guide in three steps (Make or import a
    module; Start a campaign; Play), each a link, instead of the bare form.
  - **P-b, the host's tool rows:** consecutive tool rows fold into one chip, "3 tools", which opens to their names.
  - **T-a, the picker:** each checkbox has an `id`, and its label holds the name with its `htmlFor`. So
    `getByLabel(/Maud/)` finds it, and the box sits on its label's line.
  - **E-b, the key outline:** the text editor has an outline of its keyed headings, key and title, filtered by a
    search box. A click scrolls to the heading and puts the cursor there.
  - **i18n:** `firstRun.title`, `firstRun.module`, `firstRun.campaign`, `firstRun.play`, `story.tools`,
    `text.outline`, `text.outlineSearch`.
- [ ] **Step 1: Write the failing tests:** the guide shows with nothing yet; three tool rows fold into one chip;
  `getByLabel(/Maud/)` checks Maud's box; the outline lists "7. Dining Room" and the search filters it; the
  round-trip test passes.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `npm test` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Small play and editor items: a first-run guide, tool rows folded, the picker's labels, and a key outline"`

---

### Task 29: End to end, and the browser check

**Files:**
- Create: `tests/e2e/test_a_faithful_book.py`, `web/e2e/zz-faithful.spec.ts`
- Modify: `tests/e2e/fake_play_server.py`, `tests/e2e/test_books_and_quick_dungeons.py` (its answers, only where
  Tasks 2, 9 and 13 add calls), `Makefile` only if `e2e-browser` must name the spec (it runs `web/e2e/*.spec.ts`)

**What it covers:**
- **`test_a_faithful_book.py`, through `delve serve` with the fake `claude`:**
  - The book: a synthetic PDF from `tests/fixtures/pdfs.py` with:
    - a house text and a ship text, each keyed from 1, and 7 in both;
    - a roster;
    - two picture pages answered as maps (house: two levels; ship: one);
    - a handout page with two boxes;
    - a line with "HD ;".
  1. Convert it with `book_maps` on. The steps include classifying and gaps, and three drafts follow, page by page.
  2. Keep the house's two-level draft: two maps, and the house's keys on them. Keep the ship's draft too.
  3. `GET …/export.dscn` is 200, and `dscn validate` on it has no error.
  4. Make a campaign. `module_key("7", part="ship")` answers the ship's 7, and the primer's `unmapped` is empty.
  5. The pregens route lists the roster, and the DM's beat makes the party from `module_pregens`.
  6. `move_party` into the house's room 4 and `door(…, found=True)` on its secret trapdoor (an `exit` to the
     cellar). The second seat's fog view shows the trapdoor only once found.
- **`fake_play_server.py`:**
  - the faithful book's module, already converted, with its drafts open and one kept;
  - pregens, and a campaign without a party, for party creation;
  - a story of 120 entries, for a late seat to scroll back.
- **`web/e2e/zz-faithful.spec.ts`** runs last by file order (alphabetical), seeding its own data at its start, and writes:
  - `web/e2e/screenshots/draft-review-1280x800.png` and `draft-review-phone-390x844.png`: a book-page draft over its
    picture;
  - `map-editor-drafted-1280x800.png` and `map-editor-drafted-phone-390x844.png`;
  - `module-pregens-1280x800.png` and `module-pregens-phone-390x844.png`;
  - `party-pregens-1280x800.png` and `party-pregens-phone-390x844.png`: party creation;
  - `story-history-1280x800.png` and `story-history-phone-390x844.png`: a seat scrolled back.
- The earlier specs' expectations change only where the new screens change them (the module page's Pregens tab).
- [ ] **Step 1: Write the tests and the spec, and see them fail where parts are missing.**
- [ ] **Step 2: Make them pass: `make ci` and `make e2e-browser`.**
- [ ] **Step 3: Commit.** `git commit -m "Faithful modules end to end: a book converted, drafted, kept, exported and played, and the browser's screenshots"`

---

### Task 30: The docs

**Files:**
- Modify: `docs/glossary.md`, `docs/data-dictionary.md`, `docs/progress.md`, `docs/backlog.md`, `GUILD.md`,
  `docs/maps/scenario-format.md` (only to point to Task 16's section, if it needs it),
  `docs/superpowers/specs/2026-10-19-faithful-modules-design.md` (a closing "Decided in the plan" section)

**What it covers:**
- **The glossary:**
  - part, level, scoped key ("haunted-house-7"), pregen, handout, draft (a book-page draft), front matter;
  - **The current rule, from owner decision 4:** players see each other's sheets.
- **The data dictionary:**
  - **the pregens section:** `entities.pregens`, `$defs.pregen` and its fields, the default audience `player`, the
    ref `pregen:<id>`;
  - **scoped keys:** printed when unique, `<part>-<n>` otherwise, `PART_LENGTH`, `Key.part`, `module_key`'s `part`;
  - **Delve's reading of R13:** every blockquote of a keyed section is read-aloud;
  - **the new warning codes:** `ref-rewritten`, `ref-dropped`, `page-not-classified`, `entities-merged`,
    `entities-not-deduplicated`, `handout-not-linked`, `text-filled`, `text-gap`, `image-dropped`, `map-warning`;
  - **the conversion steps** `classifying` and `gaps`;
  - **the draft's result fields:** `maps`, `replaces`, `part` and `page`;
  - **`conversions.cost_usd`,** and `Usage.cost_usd` as "this reply";
  - **the DM log's `ask` row;**
  - **the roll purposes' `#<occasion>`,** and `hidden`.
- **`GUILD.md`, a "Faithful modules" section:**
  - the vision steps and their `Look`;
  - scoped keys, in one place;
  - the `dscn` change (pregens);
  - the dm.md and i18n rules for parallel builders;
  - the screenshots.
- **`docs/backlog.md`:**
  - strike the stale line 118 (fixed in plateau 7 Task 18), and "Ask the DM's usage isn't in the DM log";
  - add what this plan defers:
    - the spider picture's caption placement;
    - correcting errata, out of scope;
    - hiding other players' sheets (owner decision 4);
    - monster ids that nothing resolves.
- **`docs/progress.md`:**
  - the row for faithful modules;
  - "rebuild the reference (`make install`) after Task 24";
  - "to check by hand with the real `claude`":
    - converting U1 again and judging the drafts of pages 2, 35 and 37;
    - exporting it;
    - offering its pregens at party creation;
    - a short play through the house with fog and the secret trapdoor in room 4;
    - Caine's "½E" (filled only if the vision answer adds it).
- [ ] **Step 1: Write them.**
- [ ] **Step 2: Run `make ci`.**
- [ ] **Step 3: Commit.** `git commit -m "Faithful modules' docs: the glossary, the data dictionary's pregens and scoped keys, GUILD.md, progress and backlog"`

---

## Order and parallelism

Every task leaves `make ci` green once its prerequisites are merged. Within a wave, no two tasks edit the same file,
except `en.json` and `nl.json`, where each adds one block after its own anchor. So a wave's tasks can be built and
merged in any order. A and B start in wave 1 and are done by wave 3.

| Wave | Tasks | Waits for |
|---|---|---|
| 1 | **1**, **2**, **3**, **7**, **8**, **22**, **23**, **24**, **25**, **27** | nothing |
| 2 | **4**, **9**, **11**, **14**, **16**, **21** | 4: 3, 8. 9: 1, 8. 11: 8. 14: 2. 16: 8. 21: 8, 22 |
| 3 | **5**, **6**, **10**, **15**, **28** | 5: 2, 4. 6: 4. 10: 9. 15: 8, 11. 28: 11, 25 |
| 4 | **12**, **13**, **18**, **20** | 12: 2, 10. 13: 5, 14. 18: 15, 16, 27. 20: 10, 21 |
| 5 | **17**, **19**, **26** | 17: 12, 15, 16. 19: 16, 20, 21. 26: 5, 13, 23 |
| 6 | **29**, **30** | everything; Task 30 can be drafted from this plan during wave 5 |

**Shared files, and who touches them, in wave order:**

| File | Tasks (wave) |
|---|---|
| `src/delve/modules/books/convert.py` | 1 (1), 9 (2), 10 (3), 12 (4), 17 (5) |
| `src/delve/conversions/runner.py` | 2 (1), 5 (3), 13 (4), 26 (5) |
| `src/delve/conversions/dungeon_maps.py` | 3 (1), 4 (2), 5 (3) |
| `src/delve/modules/books/pdf.py` | 2 (1), 14 (2), 13 (4) |
| `src/delve/modules/books/classify.py` | 2 (1), 12 (4) |
| `prompts/convert.md` | 14 (2), 13 (4) |
| `prompts/entities.md` | 15 (3), 17 (5) |
| `src/delve/modules/source.py` | 8 (1), 16 (2) |
| `src/delve/modules/text.py` | 8 (1), 11 (2) |
| `src/delve/play/sessions.py` | 10 (3), 20 (4) |
| `src/delve/play/ask.py` | 23 (1), 26 (5) |
| `src/delve/dm/prompt/dm.md` | 8 (1), 21 (2), 20 (4), 19 (5): each in its own section |
| `tests/dm/tools/test_fourth_wall.py` | 21 (2), 19 (5) |
| `tests/web/test_fourth_wall_per_seat.py` | 23 (1), 19 (5) |
| `tests/fixtures/scripts/first_session.golden.json` | 22 (1), 21 (2) |
| `web/src/module/MapDrafts.tsx`, `mapDrafts.ts` | 3 (1), 4 (2), 6 (3: MapDrafts.tsx only) |
| `web/src/routes/ModulePrint.tsx` | 11 (2), 15 (3), 18 (4) |
| `web/src/module/EntityForm.tsx` | 15 (3), 18 (4) |
| `web/src/routes/ModuleDetail.tsx` | 27 (1), 18 (4) |
| `web/src/module/TextEditor.tsx` | 11 (2), 28 (3) |
| `web/src/play/Story.tsx` | 25 (1), 28 (3) |
| `web/src/routes/NewModule.tsx` | 5 (3), 26 (5) |
| `web/src/api.ts` | 18 (4), 26 (5) |
| `tests/e2e/fake_play_server.py`, `web/e2e/*`, `web/e2e/screenshots/` | 29 only |
| `tests/fixtures/pdfs.py` | 14 only |
| `src/delve/modules/dscn/*` (the copied package) | 16 only |
| `en.json`, `nl.json` | every web task, one block after its anchor |

**Work packages** (at most 14 agents; at most 6 packages at once). A package is one agent's consecutive tasks, one
commit per task, kept together because they touch the same files. Its prerequisites are other packages' tasks, as
the waves above give them. Within a package, a task waits until its own prerequisites are merged.

| Package | Tasks, in order | Owns (mainly) | Starts | Waits mid-way for |
|---|---|---|---|---|
| **P1 Book pages** | 2, 14 | `pdf.py`, `classify.py`, runner's classifying step | at once | none |
| **P2 Drafts** | 3, 4, 5, 6 | `dungeon_maps.py`, `sketch.py`, `book-map.md`, `MapDrafts`, `DraftReview` | at once | 4: P4's Task 8. 5: P1's Task 2 |
| **P3 Editor and module page** | 7, 27 | `MapEditor`, `ProvenanceNotice`, `ModuleDetail`, `Modules`, `__main__` | at once | none |
| **P4 Keys and text** | 8, 11 | `source.py`, `text.py`, `exporter.py`, `module_key`, `TextEditor`'s read-aloud | at once | none |
| **P5 Converter** | 1, 9, 10, 12, 17 | `convert.py`, `repair.py`, `dedupe.py`, `generate.py`, `sessions.py`'s opening | at once | 9: P4's 8. 12: P1's 2. 17: P7's 16 and 15 |
| **P6 Dice and fights** | 22, 21 | `combat.py`, `checks.py`, `dice.py`, `table.py`, the golden | at once | 21: P4's 8 (dm.md) |
| **P7 Pregens and forms** | 16, 15, 18, 19 | the `dscn` schema, `EntityForm`, `ModulePrint`, the pregens route and tool | after P4 | 18: P3's 27. 19: P8's 20 and P6's 21 |
| **P8 The DM at the table** | 23, 24, 20 | `ask.py`, the reference, the primer's `unmapped`, `MapPanel` | when a slot frees (Tasks 23 and 24 need nothing) | 20: P5's 10 and P6's 21 |
| **P9 Story and small play items** | 25, 28 | `Story.tsx`, `useStory`, `Campaigns`, `Join`, the editor's outline | when a slot frees | 28: P4's 11 |
| **P10 Gaps and costs** | 13, 26 | `gaps.py`, runner's gaps step, the provider's usage, migration 0015 | after P1 and P2's Task 5 | 26: P8's 23 |
| **P11 End to end** | 29 | `fake_play_server.py`, `web/e2e/`, the screenshots | after all of P1–P10 | none |
| **P12 Docs** | 30 | the docs | with P11 (drafted from this plan earlier) | none |

- **At once (6):** P1, P2, P3, P4, P5, P6, so A and B start first and C1 (P4) unblocks the drafts' linking.
- **Then:** P7 when P4 ends, P8 and P9 as slots free, and P10 after P2's Task 5.
- **Last:** P11 and P12.
- **Agents:** 12 packages leave 2 agents of the quest's 16 for review and verification.
- **If the budget runs short,** defer from the end of G backwards: Task 28, then 27, then 26.

## Done when

- `make ci` passed after every task's merge, and passes on a fresh clone at the end.
- `make e2e-browser` passes and writes, on the desktop (1280×800) and the phone (390×844):
  - a book-page draft over its picture;
  - the map editor on a drafted map;
  - the pregens in the module editor and in party creation;
  - a seat scrolling back the story.
- **A synthetic book with a house and a ship, each keyed from 1:**
  - it converts with its map pages found, drafted level by level and kept onto their own parts;
  - it exports and validates;
  - it plays with `module_key` by part, the pregens made into the party, and a secret trapdoor found under fog.
- No test runs `claude`, `tesseract` or the network, and no U1 page is in the repository.
- The chronicle lists each task's delivery, the test counts per area, the deviations, what was deferred and why, the
  decisions taken without the human, the screenshot paths, and the owner's hand checks (Task 30's list).

## Decisions taken in this plan

Taken by the quest's rules: the design's five owner decisions stand; the fourth wall wins, except that players see
each other's sheets; the book is followed as printed; single-player play stays as fast; existing names and shapes
stay unless the design replaces them; the smallest change. Rows 1–5 are the Archmage's rulings for this quest.

| # | Question | Answer | Why |
|---|---|---|---|
| 1 | Scoped keys in the `.dscn`, or only in Delve? (Archmage) | In the `.dscn`: `keys[].key` stays unique, printed when unique and `<part>-<n>` when two parts share it. `module_key` takes `part`, or the key as written. | The format refuses repeated keys (`validate.py`, `duplicate-id`). |
| 2 | Read-aloud after DM text? (Archmage) | Delve's derived `TextSection` gathers every blockquote of a keyed section; the copied `dscn` and the export are unchanged; the editor and the print mark the same quotes. Recorded as Delve's reading of R13. | Smallest change; the round-trip test stays byte-exact. |
| 3 | Pregens? (Archmage) | A seventh entity kind `pregens`, format version 2, `entityCore` plus race, class, level, alignment, gear, background and `stats.<system>`; default audience `player`; one deliberate format task (16). | Owner decision 2; as plateau 3 Task 2 changed the format. |
| 4 | Vision calls in the converter? (Archmage) | Only through an injected `Look`; `delve.modules.books` imports none of dm, storage, web, play or conversions. | The import contracts. |
| 5 | U1's errata and contradictions? (Archmage) | Kept as printed; no question asked. | Owner decision 5. |
| 6 | What is a part's slug? | The title's words without part numbers and articles, at most 19 characters ("haunted-house"); the text id when nothing is left or two parts share it. | Short, readable, and a key stays within the format's 32 characters. |
| 7 | How does one text span several maps (house ground, upper, cellar, caves)? | Keep writes explicit `keys[]` entries with each room's `node`; `TextDoc.map` stays for single-map texts. | Derive already takes explicit keys first; no new field. |
| 8 | How are levels joined? | The DSL's own `exit … to "<map>" at X,Y`, which `move_party(map=…)` already follows. | No new map feature. |
| 9 | How is a map page found when OCR fails? | Plate words in an OCR title line, then one vision call per remaining whole-page picture, which also returns its handout boxes. | One call serves A2 and D2; a failed call never fails the job. |
| 10 | Which pages can the organiser draft? | Any picture attachment from the book's pages (`(map-)?page-N(-M)?`), as a new map or over a sketch. | "accepts any full-page picture"; attachments don't keep their share of the page. |
| 11 | How does Keep know a draft doesn't fit? | Its `r<key>` labels against the part's headings; refused with 409 and the problems; Keep anyway is `force`. | "refuses (or warns and asks)": both, the organiser's choice. |
| 12 | Which part does a map page belong to? | The text sharing the most title words with the plate's title; else Claude names it per level from the parts' headings. | Deterministic first; vision only when the titles say nothing. |
| 13 | When is the room-key sketch made? | Only for a keyed text no map page matches. | B5: a fallback only, still labelled invented. |
| 14 | De-duplication by role, alias and number? | Exact names first (today's rule), then one Claude call per kind that groups ids; Delve merges and rewrites the refs. | Names alone can't tell "the Bosun" from "Bosun"; Claude can; tests use the fake. |
| 15 | Front matter? | The first and the last page's chunks, and an untitled text before the first chapter holding no key, become one `front-matter` text, last; the DM opens on the first other text. | Keeps every word, removes the false chapters and the junk opening. |
| 16 | Lost glyphs? | A strict gap pattern on the converted Markdown, the page re-read by vision, accepted only when only the gaps (or only ½ ¼ ¾) changed; else `text-gap`, never "as printed". | Restores what is printed without letting Claude rewrite the book. |
| 17 | Bold and italic? | From each word's font name in pdfplumber; a wholly bold line is left to be a heading. | No new dependency; the counts that check Claude's answer ignore `*`. |
| 18 | Small illustrations? | Kept from 3 % of the page; smaller ones dropped with one `image-dropped` warning per page. | "keep them, or warn"; ornaments stay out. |
| 19 | How does party creation offer pregens? | A host-only picker in the empty party sidebar submits an act; the DM reads `module_pregens` and calls `create_character`. Seats list the `player` pregens through one route. | The DM still builds the party (spec); no new mutating tool. |
| 20 | How is an occasion given? | An `occasion` argument on the checks, appended to the purpose as `#<occasion>`; encounter checks take the game time as theirs. | Keeps the no-re-roll rule and the key's shape. |
| 21 | Surprise after a correction? | Keyed per beat and per played fight (`surprise-<n>`, a fight ended in round 0 doesn't count). | A corrected fight keeps its roll; a second real fight rolls fresh, as test 338 asks. |
| 22 | `dm.md:141` against `:155`? | Rolls show to the host and co-hosts as tool rows, never to the players; hidden rolls use `hidden` and leave no row; a failure reads as finding nothing. | The fourth wall; the tool rows already reach only the host and co-hosts. |
| 23 | What does Ask see? | The asker's visible entries of the whole session (8,000 characters, never fewer than 8 entries) and the last recap; never a key number. | "the session's notes and recap"; DM notes stay out (fourth wall). |
| 24 | The centipede row? | A small `corrections.sql.gz` in the snapshots, loaded last, named in `SHA256SUMS`; lookups skip deleted rows. | The snapshots stay as pinned; a rebuild is needed once. |
| 25 | Story history? | The existing paging, loaded on scroll, with "Back to the latest". | The server already pages; G1 is the reader's side. |
| 26 | A beat's cost? | The CLI's cumulative `total_cost_usd` turned into this reply's; conversions sum theirs into `conversions.cost_usd`; Asks write a DM log row. | P-e; one column, no new table. |
| 27 | The tasks for parallel builders? | Six waves; convert.py, runner.py, dungeon_maps.py and dm.md each have one owner per wave; i18n by anchor; e2e and screenshots by Task 29 alone; twelve packages, six at once. | The quest's rules and the Archmage's budget. |
