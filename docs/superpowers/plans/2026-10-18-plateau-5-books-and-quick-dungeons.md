# Delve plateau 5: books and quick dungeons, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The three ways to get a module (spec §8.3), all from "New module". A PDF becomes a module you can play at
once, or a draft to work on first. A request ("a dungeon with kobolds, no plot") becomes a small module. Every module
prints whole, through the browser's print dialog.

**Architecture:**
- **`delve.modules.books`** is pure: PDF reading (`pdf.py`), conversion (`convert.py`), map sketches (`sketch.py`) and
  generation (`generate.py`). Every Claude step goes through an injected `complete(prompt) -> str`, because
  `delve.modules` may not import `delve.dm`.
- **`delve.conversions`** runs them in the background. It keeps a `conversions` row per job, publishes `conversion`
  events with progress, survives a reload, and closes jobs that a stopped Delve left running. It calls the DM layer's
  `side_call` with the Settings choice for the `conversion` job.
- **The result is a module** written through plateau 3's `save_source`, with warnings the editor lists. A draft is a
  module with `draft = true`: it can't start a campaign until it's marked ready.
- **Maps:** each page that is mostly picture becomes an attachment. When a text has keyed rooms, Claude sketches a
  schematic map in the map language from the room key. Delve's parser checks it, and the module carries a warning to
  compare the sketch with its page. dungml's extractor isn't ported: spec §8.3 keeps it "a tool that can be run on its
  own, for hard maps".

**Tech Stack:**
- **New Python dependencies, exact versions:** `pdfplumber==0.11.10` (MIT, with pdfminer.six and pypdfium2) and
  `pytesseract==0.3.13` (Apache-2.0). Pillow comes with pdfplumber. **PyMuPDF is not used:** it is AGPL, and Delve will
  serve friends over the network.
- **System tools, optional:** the `tesseract` binary for OCR. Without it, scanned pages become warnings, never
  failures.
- No new web dependency.

**Spec:**
- `docs/superpowers/specs/2026-10-17-unified-app-design.md` §8.3 (getting a module, the PDF conversion, what "done"
  means for maps, the print export), §5.2 (Settings choose a backend per job), §6.4 (show progress) and §14.
- `docs/maps/` (the map language, which the sketch and generation prompts carry), `docs/maps/scenario-format.md`.
- `docs/progress.md`, `docs/glossary.md`, `docs/data-dictionary.md`.

**Source to port (read only):**
- `/home/raf/roleplaying/ttrpg3/packages/modules/src/dungeon_daemon/modules/ingest.py`:
  - `_order_page_blocks`: column detection by left-edge gaps over 15% of the page width;
  - `MIN_PAGE_CHARS = 40` as the OCR threshold;
  - `chunk_pages`: whole pages under a budget.
- ttrpg3's `adapters/author.py` `REFORMAT_CONTRACT`: "re-express faithfully".
- **Don't take over:**
  - its regex heading guessing;
  - its fixed section kinds;
  - its daemon threads with status flags;
  - its LiteLLM layer;
  - its `pdftotext` fallback.

## Global Constraints

- **Earlier plateaus still apply:** `GUILD.md` and the Global Constraints of plateaus 0 to 3.
- **Tests never run the real `claude`.** Conversion and generation tests use `FakeDM` with a side handler (Task 4).
  `make convert-live` (Task 8) is the owner's opt-in check and is never run by the quest.
- **Tests build their PDFs in code** (reportlab is not used; pdfplumber can't write PDFs). They use a tiny PDF
  writer in `tests/fixtures/pdfs.py` that makes text pages, two-column pages and image-only pages. No binary
  fixtures.
- **Dependency rules:** `delve.conversions` may import `delve.modules`, `delve.dm`, `delve.storage` and
  `delve.domain`. `delve.modules.books` imports none of `web`, `dm`, `storage`, `play`, `conversions`. Add the new
  package to the import-linter contracts.
- **The PDF upload:** `POST /api/conversions/pdf` is the third raw-body exception to the JSON rule.
  - Its `Content-Type` must be `application/pdf`; anything else is 415.
  - It may be at most 256 MB (413). Books are large; it streams to a temporary file, never to memory.
  - Bytes that don't start with `%PDF-` are 400.
- **Faithful text:** the conversion keeps the module's own words, as Markdown. It never summarises. A chunk whose
  Markdown has fewer than 70% of its source's words gets a `conversion-short` warning naming its pages.
- **Audiences** are `gm` and `player` (`docs/data-dictionary.md`). Everything converted is `gm` unless the text marks
  it as for the players (boxed read-aloud stays inside `gm` texts as blockquotes).
- **Words:** module, draft, attachment, image, conversion. The UI never says "ingest".

## Review Focus

1. **A big book.** A 300-page PDF converts chunk by chunk without running into a timeout or a context limit. Progress
   shows pages done out of pages. A reload during the conversion shows the same progress. Cancel stops it, and nothing
   half-made is left behind. (Task 4 tests.)
2. **Claude answers badly.** A chunk comes back empty, cut short, as prose about the text instead of the text, or with
   a fenced code block around it. A sketch doesn't parse twice. Entity JSON is invalid. Each becomes a warning, and the
   rest of the module still arrives. (Task 2 and Task 3 tests.)
3. **A scanned PDF on a machine without tesseract.** Every image-only page becomes a `page-not-read` warning, and the
   page image becomes an attachment, so nothing is silently lost. (Task 1 test.)
4. **A draft starts a campaign.** It is refused with 409 "This module is a draft: mark it ready first.", and the
   campaign form doesn't offer drafts. (Task 5 test.)
5. **A hostile or broken PDF:** encrypted, corrupt, zero pages, or not a PDF behind an `application/pdf` header. It is
   refused or fails with a clear message, and no module is created. (Task 1 and Task 5 tests.)

---

## File structure

```
src/delve/modules/books/__init__.py
src/delve/modules/books/pdf.py            read_pdf: pages in reading order, OCR fallback, page images
src/delve/modules/books/convert.py        chunks → Markdown texts, entity drafts, attachments, warnings
src/delve/modules/books/sketch.py         a map in the DSL from a room key, parsed and retried
src/delve/modules/books/generate.py       a module from a request
src/delve/modules/books/prompts/{convert,entities,sketch,generate}.md
src/delve/conversions/{__init__,runner}.py
src/delve/storage/migrations/versions/0009_conversions.py
src/delve/web/routes/conversions.py
web/src/routes/NewModule.tsx, web/src/module/ConversionProgress.tsx, web/src/routes/ModulePrint.tsx
tests/fixtures/pdfs.py
```

---

### Task 1: Reading a PDF

**Files:**
- Create: `src/delve/modules/books/__init__.py`, `src/delve/modules/books/pdf.py`, `tests/fixtures/pdfs.py`,
  `tests/modules/books/test_pdf.py`
- Modify: `pyproject.toml` (the two dependencies), `uv.lock`

**Interfaces:**
- Produces:
  - `PdfPage(number: int, text: str, ocr: bool, pictures: list[Picture])`.
  - `Picture(page: int, png: bytes, area: float)`: a rendered region; `area` is its share of the page (0–1).
  - `PdfBook(pages: list[PdfPage], warnings: list[Warning])`, using plateau 3's `Warning`.
  - `read_pdf(path: Path, *, ocr: Callable[[bytes], str] | None) -> PdfBook`.
  - `tesseract_ocr() -> Callable[[bytes], str] | None`: None when the binary or `pytesseract` is missing.
  - `PdfError(ValueError)`: for an encrypted, corrupt or empty PDF.
- **Reading order:** words grouped into lines, then into blocks. Columns are found by clustering the blocks' left
  edges, with a gap over 15% of the page width as a boundary (ttrpg3). Blocks are sorted by column, then top, then
  left. Full-width blocks come first.
- **OCR:** a page with fewer than 40 characters of text is rendered at 300 dpi and passed to `ocr`. Without `ocr`, it
  gets a `page-not-read` warning (`ref: "page:<n>"`).
- **Pictures:** an embedded image covering at least 15% of the page is rendered as PNG at 150 dpi. A page whose
  pictures cover 50% or more of it is a picture page, and the whole page is rendered.

- [ ] **Step 1: Write the failing tests:**
  - `test_two_columns_read_in_order`: the left column's sentences come before the right one's.
  - `test_a_scanned_page_uses_ocr` (a fake `ocr` returning a known string).
  - `test_without_tesseract_a_scanned_page_is_a_warning_and_a_picture` (Review Focus 3).
  - `test_pictures_and_picture_pages`.
  - `test_broken_pdfs_raise` (encrypted, truncated, zero pages; Review Focus 5).
  - `test_tesseract_ocr_reads_a_rendered_word`, skipped when `tesseract_ocr()` is None.
- [ ] **Step 2: Run them and see them fail.** `uv run pytest tests/modules/books/test_pdf.py -v`
- [ ] **Step 3: Implement.** `tests/fixtures/pdfs.py` writes minimal PDFs by hand (text with fonts at given
  positions, an image XObject, an encrypted trailer), so tests need no PDF-writing library.
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Read a PDF: pages in reading order, OCR for scanned pages, its pictures"`

---

### Task 2: Converting a book

**Files:**
- Create: `src/delve/modules/books/convert.py`, `src/delve/modules/books/prompts/convert.md`,
  `src/delve/modules/books/prompts/entities.md`, `tests/modules/books/test_convert.py`

**Interfaces:**
- Consumes: Task 1's `PdfBook`; plateau 3's `ModuleSource`, `TextDoc`, `Attachment`, `Warning`; `dscn.add_anchors`;
  `scenario.schema.json` `$defs`.
- Produces:
  - `Complete = Callable[[str], Awaitable[str]]`.
  - `Progress = Callable[[str, int, int], None]`: the step name (`reading`, `converting`, `entities`, `pictures`,
    `maps`), done and total.
  - `chunk_pages(pages: list[PdfPage], budget: int = 12_000) -> list[list[PdfPage]]`: whole pages only. A page over
    the budget is a chunk of its own.
  - `async convert_book(book: PdfBook, title: str, complete: Complete, progress: Progress, *, concurrency: int = 3)
    -> Converted(source: ModuleSource, pictures: list[tuple[Attachment, bytes]], warnings: list[Warning])`.

**How it converts:**
- **Chunks:** each chunk is sent with `convert.md`, the previous chunk's last heading as context, and its page numbers.
  The prompt asks for the chunk's words as Markdown:
  - chapters as `#` headings;
  - keyed areas as `## <key>. <name>` (the key as printed: `12`, `C3`, `W101`);
  - boxed read-aloud text as blockquotes;
  - tables as Markdown tables;
  - NPC and monster stat lines as they are;
  - no commentary.
- **Answers:** a fenced code block around the answer is unwrapped.
- **Bad chunks:** an empty answer, or one under 70% of the source's words, keeps the source text as a plain paragraph
  block with a `conversion-short` warning (`ref: "pages:<a>-<b>"`).
- **Texts:** the Markdown is split into one `TextDoc` per `#` chapter, with ids slugged from the chapter titles and made
  unique. `add_anchors` gives every heading an anchor; duplicate anchors get `-2`, `-3` and so on.
- **Entities:** one call per text with `entities.md` asks for JSON `{npcs, encounters, factions, quests}` drafts in
  the schema's shape. Each record is validated against its `$defs`. An invalid one is dropped with an
  `entity-dropped` warning, and invalid JSON gives one `entities-not-read` warning for the text.
- **Pictures:** each becomes an attachment, `gm`, with the description "Page <n>, near “<the nearest heading>”" and an
  `image-to-describe` warning. A picture page is described as "Page <n>: a map or full-page picture".

- [ ] **Step 1: Write the failing tests:**
  - `test_chunks_never_split_a_page`;
  - `test_a_book_becomes_texts_by_chapter` (a fake `complete` that turns pages into known Markdown);
  - `test_keyed_headings_get_anchors_and_duplicates_are_unique`;
  - `test_bad_answers_become_warnings` (empty, short, prose about the text, fenced; Review Focus 2);
  - `test_entity_drafts_are_validated`;
  - `test_pictures_become_described_attachments`;
  - `test_progress_counts_chunks`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement**, and write the two prompts.
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Convert a book to a module: faithful Markdown by chunks, entity drafts, pictures"`

---

### Task 3: Map sketches and generated modules

**Files:**
- Create: `src/delve/modules/books/sketch.py`, `src/delve/modules/books/generate.py`,
  `src/delve/modules/books/prompts/sketch.md`, `src/delve/modules/books/prompts/generate.md`,
  `tests/modules/books/test_sketch.py`, `tests/modules/books/test_generate.py`

**Interfaces:**
- Consumes: `delve.maps.dsl` (parse, errors), Task 2's `Complete`.
- Produces:
  - `async sketch_map(name: str, keyed: list[tuple[str, str]], complete: Complete) -> tuple[str | None,
    list[Warning]]`. `keyed` is `(key, heading text)` pairs, each with its paragraph.
  - `async generate_module(request: str, complete: Complete, progress: Progress) -> Converted`.
- **The language reference** in both prompts is built from `docs/maps/` at build time into
  `prompts/dsl-reference.md`, with a test that it is current.

**The sketch:**
- Claude writes one `map <name> { … }` in the map language: a room per key, named `r<key>` and labelled
  `<key>. <name>`, connected as the text describes, on a grid.
- Delve parses it. On a parse error, it asks once more with the error and its line.
- A sketch that still doesn't parse gives no map and a `map-not-drawn` warning.
- A sketch that parses gives a map and a `map-sketched` warning: "Drawn from the room key; compare it with page
  <n>."
- **Rooms link by themselves** (plateau 3), because the labels match the headings.
- **When a text gets a sketch:** a converted text with three or more keyed headings, with the picture page nearest to
  its first key named in the warning.

**Generation:**
- One call asks for a JSON plan `{title, summary, rooms: [{key, name, read_aloud, dm_text, monsters, treasure}],
  npcs, encounters}` with as much story as the request asks for.
- Then the sketch makes its map, and the plan becomes one keyed text plus its entities.
- Treasure follows the request; the ruleset's treasure tables are not called (the DM rolls in play).
- An unreadable plan is retried once, then the generation fails with "The module couldn't be generated: <reason>".

- [ ] **Step 1: Write the failing tests:**
  - `test_a_sketch_that_parses_is_kept_with_its_warning`;
  - `test_a_sketch_is_retried_once_with_the_parse_error` (the second prompt holds the error; Review Focus 2);
  - `test_a_sketch_that_never_parses_is_a_warning`;
  - `test_a_generated_module_links_its_rooms` (derive gives one link per room, no `key-without-room`);
  - `test_an_unreadable_plan_fails_after_one_retry`;
  - `test_the_dsl_reference_is_current`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Sketch a map from a room key, and generate a module from a request"`

---

### Task 4: Conversions in the background

**Files:**
- Create: `src/delve/conversions/__init__.py`, `src/delve/conversions/runner.py`,
  `src/delve/storage/migrations/versions/0009_conversions.py`, `tests/conversions/test_runner.py`
- Modify:
  - `src/delve/dm/provider.py` (`side_call` gains `timeout`);
  - `src/delve/dm/claude_cli/provider.py`;
  - `src/delve/dm/fake.py`;
  - `src/delve/domain/settings.py` (the `conversion` job's default);
  - storage (a `conversions` repository; `modules.draft`);
  - `pyproject.toml` (the import-linter contracts).

**Interfaces:**
- Consumes: Tasks 1–3; plateau 3's `save_source`, blob store.
- Produces:
  - **The provider:** `DMProvider.side_call(prompt, choice, *, timeout: float | None = None) -> str`. The claude CLI
    uses `timeout` when it's given, and `SIDE_TIMEOUT` (90 s) otherwise.
  - **The fake:** `FakeDM(..., side_handler: Callable[[str], str] | None = None)`; `FakeDM.side_prompts:
    list[str]` records every side prompt.
  - **The `conversion` job's default:** `claude-cli` with model `sonnet`, effort `medium`; `CONVERSION_TIMEOUT = 600`
    s per call.
  - **Migration 0009:**
    - `conversions(id, kind 'pdf'|'generate', title, mode 'ready'|'draft', status
      'running'|'done'|'failed'|'cancelled', step, done, total, module_id NULL, warnings JSON, error NULL, created_at,
      updated_at)`;
    - `modules.draft BOOLEAN NOT NULL DEFAULT 0`.
  - **The runner API:**
    - `start_pdf(services, path: Path, title: str, mode) -> Conversion`;
    - `start_generate(services, request: str, mode) -> Conversion`;
    - `cancel(services, id) -> Conversion`;
    - `close_orphans(storage)`: at start, a running job becomes failed with "Delve stopped during the conversion."
  - **Events:** `conversion` with `{id, status, step, done, total}`, at each progress call and at the end.
- **The background:** a job runs in an `asyncio` task that outlives the request, as `run_beat` does.
- **The module is created only at the end,** in one transaction: the source, the attachments' blobs, the original PDF
  as an attachment with `role: source` (`gm`, "The original PDF"), the sketched maps, and `draft` from the mode. A
  cancelled or failed job leaves no module.
- **One job at a time:** a second start while one runs answers 409 "A conversion is running.".

- [ ] **Step 1: Write the failing tests:**
  - `test_a_conversion_reports_progress_and_makes_a_module`;
  - `test_cancel_leaves_no_module` (Review Focus 1);
  - `test_a_failed_call_fails_the_job_with_its_reason`;
  - `test_orphans_are_closed_at_start`;
  - `test_one_conversion_at_a_time`;
  - `test_a_300_page_book_is_called_in_chunks_with_the_conversion_timeout` (a fake book of 300 short pages; the fake
    records the prompts and their timeouts);
  - `test_a_draft_module_is_marked_draft`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Conversions run in the background with progress, and make a module at the end"`

---

### Task 5: The conversion API and drafts

**Files:**
- Create: `src/delve/web/routes/conversions.py`, `tests/web/test_conversions_api.py`
- Modify: `src/delve/web/guard.py`, `src/delve/web/app.py` (closes orphans at startup), `src/delve/web/routes/modules.py`
  (`draft` in the module JSON; PATCH `{draft: false}`), `src/delve/web/routes/campaigns.py`, `GUILD.md`

**Interfaces:**
- Produces (organiser routes):

| Method | Path | Body | Answer |
|---|---|---|---|
| POST | `/api/conversions/pdf?title=…&mode=ready\|draft` | the PDF | 202 the conversion; 415, 413, 400 (not a PDF), 409 (one is running) |
| POST | `/api/conversions/generate` | `{request, mode?}` | 202 the conversion; 422 for an empty request |
| GET | `/api/conversions` | | the last 20, newest first |
| GET | `/api/conversions/{id}` | | the conversion |
| POST | `/api/conversions/{id}/cancel` | `{}` | the conversion |

- `POST /api/campaigns` with a draft module answers 409 "This module is a draft: mark it ready first."
- `GET /api/modules` and `GET /api/modules/{id}` carry `draft`. `PATCH /api/modules/{id}` takes `{draft: false}`; a
  module can't become a draft again (422).

- [ ] **Step 1: Write the failing tests:** the table's answers; Review Focus 4 (a draft can't start a campaign) and 5
  (a corrupt and an encrypted PDF fail their conversion with the reader's message and make no module).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The conversion API, and drafts that can't start a campaign"`

---

### Task 6: New module

**Files:**
- Create: `web/src/routes/NewModule.tsx`, `web/src/module/ConversionProgress.tsx`, and tests for each
- Modify: `web/src/App.tsx` (`/modules/new`), `web/src/routes/Modules.tsx` ("New module" opens it),
  `web/src/routes/ModuleDetail.tsx` (a Draft badge and "Mark as ready"), `web/src/routes/Campaigns.tsx` (no drafts),
  `web/src/api.ts`, `en.json`, `nl.json`

**What the screen does (spec §8.3, "all reached from New module"):**
- **Four choices:**
  - an empty module (today's form);
  - import a `.dscn` (today's picker);
  - a PDF, with "Ready to play" or "A draft to work on";
  - "Describe the module you want", a text area with Generate.
- **Progress:** `ConversionProgress` follows the `conversion` events, through the app's one event stream. It shows the
  step and pages done out of pages, a Cancel button, and the reason when a job fails. A reload shows the running job
  (`GET /api/conversions`).
- **The result:** the module page opens with the conversion's warnings in its warning list. A draft shows its badge and
  "Mark as ready".

- [ ] **Step 1: Write the failing tests:** a PDF upload starts a conversion and shows its progress from events; Cancel
  posts; a finished one links to its module; the campaign form lists no drafts; Mark as ready sends the PATCH.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "New module: a PDF, a draft or a request, with the conversion's progress"`

---

### Task 7: The whole module in print

**Files:**
- Create: `web/src/routes/ModulePrint.tsx`, `web/src/routes/ModulePrint.test.tsx`
- Modify: `web/src/App.tsx` (`/modules/:moduleId/print`), `web/src/routes/ModuleDetail.tsx` (a Print button),
  `web/src/routes/MapPrint.tsx` (share its map page and key components, without changing its own page)

**What it prints, in this order (spec §8.3; DM-only material included):**
1. A title page from the metadata: title, authors, levels, party size, setting, and the cover.
2. Each text, rendered as the editor shows it, with read-aloud boxed.
3. Each played map, as MapPrint prints it: the DM view and its key.
4. NPC and encounter blocks.
5. The image attachments, with their descriptions.

- Page breaks come before each text, map and section, and the PDF comes from the browser's print dialog.

- [ ] **Step 1: Write the failing tests:** the order above; a DM-only text is included; an empty module prints its
  title page only.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Print a whole module"`

---

### Task 8: End to end, the live check, and the docs

**Files:**
- Create: `tests/e2e/test_books_and_quick_dungeons.py`, `web/e2e/new-module.spec.ts`, `scripts/convert_live.py`
- Modify: `Makefile` (`convert-live`), `README.md` (a "Getting a module" section), `GUILD.md`, `docs/progress.md`

- **The e2e test, through `delve serve` with the fake DM:**
  - A built PDF with a two-column chapter, three keyed rooms and a full-page picture converts as a draft. The module
    has the chapter's text, the three keyed headings linked to the sketched map, the picture as an attachment, and the
    `map-sketched` and `image-to-describe` warnings.
  - The draft can't start a campaign until it's marked ready. Then it can.
  - A request generates a module that starts a campaign at once.
  - The whole module's print page lists its parts.
- **`make convert-live PDF=<file> [TITLE=…]`** (opt-in, never in the quest):
  - converts a real PDF with the real `claude` into a temporary data dir;
  - prints the timings per chunk, the warnings and the word coverage;
  - leaves the `.dscn` in `evals/recordings/conversions/`.
- **The browser check (`make e2e-browser`):** the New module screen during a conversion and after it, and the print
  page. Screenshots: `web/e2e/screenshots/new-module-1280x800.png`, `module-print-1280x800.png`.
- [ ] **Step 1: Write the e2e test and see it fail where parts are missing.**
- [ ] **Step 2: Make it pass, run `make ci` and `make e2e-browser`.**
- [ ] **Step 3: Update the docs.** README: the three ways, drafts, the sketch warnings, `make convert-live`, and
  tesseract as optional. GUILD.md: the plateau's constraints. progress.md: plateau 5 and what to check by hand.
- [ ] **Step 4: Commit.** `git commit -m "Plateau 5 end to end: a PDF, a draft and a request become modules"`

---

## Done when

- `make ci` passes on a fresh clone, and `make e2e-browser` writes both screenshots.
- A built PDF converts to a draft that, once marked ready, starts a campaign, with its rooms linked to a sketched map.
- A request generates a module that starts a campaign at once.
- A whole module prints.
- No task's tests run the real `claude`.
