# Build Delve plateau 5 (books and quick dungeons) exactly as planned in docs/superpowers/plans/2026-10-18-plateau-5-books

# Delve plateau 5: books and quick dungeons

Plateau 5 is built on `guild/20261018-0d2585ae/party`, following `docs/superpowers/plans/2026-10-18-plateau-5-books-and-quick-dungeons.md`. "New module" now offers four ways to get a module:
- an empty module;
- a `.dscn` import;
- a PDF, ready to play or as a draft;
- "Describe the module you want".

**From a PDF:**
- The pages are read in reading order. Scanned pages go through OCR, or become a warning and an image when OCR isn't available.
- The book is converted chunk by chunk into faithful Markdown, with entity drafts, described pictures and sketched maps of its keyed rooms.
- This runs as a background conversion: it shows progress, survives a reload, can be cancelled, and makes the module only at the end.
- A draft can't start a campaign until it is marked ready.

A request generates a small keyed module with its own sketched map. Every module prints whole at `/modules/{id}/print`.

**Checks on the merged HEAD, in the integration worktree:**
- `make install && make ci` passes: 1709 Python tests passed and 1 skipped, plus 158 web tests in 30 files.
- The plateau 5 e2e tests pass (3).
- `make e2e-browser` passes all 3 specs and writes all 9 screenshots.

Nothing was delivered to master.

## Per task

**Task 1, reading a PDF** (Priya, `56fd09a`; later fixes by Lars and Amara):
- **Interface:** `delve.modules.books.pdf` provides `read_pdf`, `PdfBook`, `PdfPage`, `Picture`, `PdfError`, `tesseract_ocr` and, added later, `ReadStopped`.
- **Reading order:** words become lines, and lines become blocks. Columns are split where the left edges have a gap over 15% of the page width. Full-width blocks come first.
- **OCR:** pages under 40 characters are rendered at 300 dpi and read with OCR. Without tesseract, such a page gets `page-not-read` and its image becomes an attachment.
- **Pictures:** each embedded picture covering at least 15% of the page is rendered at 150 dpi. A page whose pictures cover half of it or more is rendered whole.
- **Broken files:** an encrypted, truncated, zero-page or garbage file raises `PdfError` with a clear message.
- **Test PDFs:** `tests/fixtures/pdfs.py` writes PDFs by hand; there are no binary fixtures.
- **Dependencies:** exactly `pdfplumber==0.11.10` and `pytesseract==0.3.13`, and no PyMuPDF.

**Task 2, converting a book** (Alex, `95dd1a1`):
- **Interface:** `convert.py` provides `chunk_pages`, which cuts whole pages under a 12,000-character budget, and `convert_book`. The prompts are `convert.md` and `entities.md`.
- **Answers:** a fenced answer is unwrapped. An empty answer, or one with under 70% of the source's words, keeps the source text and gets a `conversion-short` warning (`pages:a-b`).
- **Texts:** one text per `#` chapter, with unique slug ids. Keyed headings get anchors through `add_anchors`.
- **Entities:** entity drafts are checked against the schema's `$defs`. A failure is an `entity-dropped` or `entities-not-read` warning.
- **Pictures:** each becomes a `gm` attachment with an `image-to-describe` warning.

**Task 3, sketches and generation** (Jonas, `027ba24`):
- **The sketch:** `sketch_map` asks for one `map` in the map language, with rooms named `r<key>` and labelled `<key>. <name>`.
  - The answer is parsed and validated. On an error, it is asked once more with the error and its line.
  - If the map parses, it is kept with a `map-sketched` warning: "Drawn from the room key; compare it with page n.".
  - If it still doesn't parse, there is no map and a `map-not-drawn` warning.
- **Generation:** `generate_module` turns a JSON plan into one keyed text, its NPCs and encounters, and a sketched map. An unreadable plan is retried once, then the generation fails with "The module couldn't be generated: …".
- **The map language reference:** `prompts/dsl-reference.md` is built from `docs/maps/` by `make dsl-reference`, and a test checks that it is current.

**Task 4, background conversions** (Elif, `05e5b37`):
- **Runner:** `delve.conversions.runner` provides `start_pdf`, `start_generate`, `cancel`, `wait` and `close_orphans`.
- **Migration:** `0009_conversions` follows `0008_audience_gm`. It adds the `conversions` table, `modules.draft`, and a partial unique index that allows one running conversion.
- **The DM layer:**
  - `side_call` takes a `timeout`: `CONVERSION_TIMEOUT = 600` s for conversions, with `SIDE_TIMEOUT = 90` s otherwise.
  - `FakeDM` gains `side_handler`, `side_prompts` and `side_timeouts`.
  - The `conversion` job's default is `claude-cli` with `sonnet` and effort `medium`.
- **Events:** `conversion` events carry `{id, status, step, done, total}`.
- **The module at the end,** made in one transaction:
  - the source, the picture blobs and the sketched maps;
  - the original PDF, as attachment `source-pdf` (role `source`, `gm`, "The original PDF");
  - `draft`, taken from the mode.
- **Failures:** a cancelled or failed job leaves no module. A second start answers 409 "A conversion is running.".

**Task 5, the API and drafts** (Femi, `f704f9c`):
- **Routes:** the plan's five routes are built, and the generate route takes `{request, mode?}`.
- **The PDF upload** is the third raw-body exception to the JSON rule: anything but `application/pdf` is 415, over 256 MB is 413 (the body streams to a temporary file), and bytes that don't start with `%PDF-` are 400.
- **Drafts:** modules carry `draft`. `PATCH {draft: false}` marks a module ready; trying to make it a draft again is 422.
- **Campaigns:** `POST /api/campaigns` with a draft is 409 "This module is a draft: mark it ready first.".
- **Startup:** orphaned conversions are closed.

**Task 6, the New module screen** (Aisha, `e1a97de`; Omar, `40710dc`):
- **The screen:** `NewModule.tsx` offers the four choices.
- **Progress:** `ConversionProgress.tsx` follows `conversion` events on the app's one event stream. It shows the step, the pages done out of the pages, a Cancel button, and the reason when a job fails. A reload shows the running job.
- **Drafts:** the module page has a Draft badge and "Mark as ready". The campaign form offers no drafts.
- **Warnings after a reload:** Omar made the module page fetch its conversion's warnings again.

**Task 7, the whole module in print** (Sam, `944a3b5`; Jordan):
- **The order:** `ModulePrint.tsx` prints:
  1. a title page;
  2. each text, as the editor renders it, with read-aloud boxed and DM-only texts included;
  3. the played maps, through components shared out of MapPrint (`useMapPrint`, `MapPage`, `MapKey`);
  4. NPC and encounter blocks;
  5. the images with their descriptions.
- **Page breaks** come before each part.
- **MapPrint's own page:** Sam compared the markup by eye only, and MapPrint has no tests of its own.
- **Jordan's fix:** the page no longer prints a converted text's title twice.

**Task 8, end to end, the live check and docs** (Lars, `a498ca4`; Lena, `aa55de6`):
- **`tests/e2e/test_books_and_quick_dungeons.py`,** through `delve serve` with the fake `claude`:
  - A built two-column PDF with three keyed rooms and a picture page becomes a draft.
  - Its keyed headings link to `room.r1`–`r3` on the sketched map, and it carries the `map-sketched` and `image-to-describe` warnings.
  - It gets 409 until it is marked ready, then starts a campaign.
  - A request generates a module that starts a campaign at once.
  - Both modules' print parts are listed.
- **The live check:** `scripts/convert_live.py` and `make convert-live PDF=… [TITLE=…]`, tested only with the fake `claude`.
- **The browser check:** `web/e2e/new-module.spec.ts`.
- **Docs:** README "Getting a module", GUILD.md, `docs/progress.md` and `docs/data-dictionary.md`.

### Follow-ups after Sofie's review
- **Jordan:** the e2e fakes now read the side prompt from stdin. Once Mateo's change was merged, they had broken `make ci` and `make e2e-browser`. He also fixed the doubled print title.
- **Kenji:**
  - A failed chunk stops the conversion.
  - The entity pass is chunked, and a failed entity call is only an `entities-not-read` warning.
  - A fenced answer with prose around it is unwrapped.
  - Text ids are safe.
  - What Claude marks for the players gets an `audience-player` warning.
- **Amara:**
  - `MAX_RENDER_PIXELS = 50_000_000`, with a `page-too-large` warning.
  - `read_pdf(…, should_stop=)` raises `ReadStopped`.
  - Vector-drawn pages with little text become picture pages.
- **Daniel:**
  - An ended job stays ended.
  - Cancel stops the reading thread.
  - The PDF and the pictures go into the blob store streamed (`put_file`), off the event loop.
  - A text whose keys repeat gets `map-not-drawn` instead of a sketch.
  - The title and mode get their 422 before the body is read.
  - Leftover uploads are removed at startup.
- **Mateo** (`110cb19`): side calls send their prompt on stdin. Linux's 128 KB limit on a single argument would break the entities and sketch prompts of a big book, and a test with a 200 KB prompt reproduced "Argument list too long".

## Test counts per area

On the merged HEAD, from Lena's JUnit run: 1709 passed, 1 skipped.

| Area | Tests |
|---|---|
| maps | 671 |
| web | 221 |
| rules | 209 |
| modules | 168, of which `modules/books` is 64 with parametrised cases (pdf 19, convert 23, generate 13, sketch 9) |
| play | 115 |
| dm | 106 |
| top-level `tests/*.py` | 82 |
| storage | 80 |
| domain | 24 |
| conversions | 15 |
| e2e | 10, of which plateau 5 is 3 |
| images | 5 |
| setting | 4 |

- **Web unit tests:** 158 in 30 files.
- **Browser specs:** 3 (module-editor, new-module, play).

## Deviations from the plan
1. **`Converted.maps`:** a fourth field, `maps: list[ModuleMap]` (decision 2).
2. **A chunk's context** is the previous chunk's pages and the last 300 characters of its source text, not its last heading (decision 3).
3. **Room links:** `derive` (`source.py` `_match`) also links a room whose label equals the whole heading (decision 4).
4. **The original PDF's role:** the plan's `role: source` is a new `Attachment.role` field, `Literal["attachment","source"]`. The export always leaves `source` attachments out, and there is no opt-in (decision 5). The API's attachment JSON gained `role`, and two exact-match tests changed with it.
5. **Progress:** the `converting` step counts pages, and the `entities` step counts texts (decision 6).
6. **Sketches and generation:**
   - `sketch_map` has an extra keyword, `page=None`.
   - Generation reports the steps `generating` and `maps`.
7. **PDF reading:**
   - OCR runs only on short pages that hold an image.
   - A page read by OCR keeps its picture only when OCR finds fewer than 20 characters (`MIN_OCR_CHARS`, Lars).
   - "Encrypted" means a PDF that needs a password.
   - The reading order drops ttrpg3's special case for a page with one block.
8. **Conversion:**
   - The players' marker `<!-- players -->` is Alex's own way to meet the audience rule.
   - Chunks without words are never sent to Claude.
   - A fenced answer with prose is unwrapped only when its fence is marked `markdown`, `md` or `json`, or holds more words than the prose around it (Kenji).
   - Text ids use a shared `text_id` instead of the guard the lead named, because `slugify("???")` gives `"x"` (Kenji).
   - `add_anchors` anchors keyed headings only.
9. **API:**
   - The 409 for a running conversion also carries that `conversion`.
   - The PDF route refuses with 409 or 422 before reading the body.
   - An unknown id is 404.
   - A broken PDF with a valid `%PDF-` header gets 202, then its conversion fails with the reader's message.
10. **Storage:** the attachment id is `source-pdf`, and uploads go to `<data dir>/uploads/`. To make `JOB_DEFAULTS` take effect, Elif also changed `web/defaults.py`, which was outside her files.
11. **Side calls** send their prompt on stdin (decision 7).
12. **Warnings and failures:** the follow-ups added three warnings the plan doesn't name: `audience-player`, `page-too-large`, and `map-not-drawn` for repeated keys. A failed entity call is a warning, not a failed job (decision 8).
13. **Generation mode:** the generate route accepts `mode`, but the New module screen sends `ready`, because plan Task 6 gives the request only a text area.
14. **Print:** a DM-only text whose part heading is left out still shows its "DM only" tag on its own (Jordan).
15. **Additions:** `make dsl-reference`, `ModulePrint.module.css`, and two extra screenshots (`new-module-done`, `module-converted`).

## Decisions taken without the human
1. **Where the shared types live.**
   - **Q (lead, at planning):** Tasks 2 and 3 run in parallel, and both need `Complete`, `Progress` and `Converted`.
   - **A:** both define them at the top of `convert.py`, with the exact same lines. Task 3 wrote a stub holding only those lines, and the lead kept Task 2's full file at merge.
   - **Why:** this keeps the plan's module layout and lets the two tasks run side by side.
2. **A place for sketched maps.**
   - **Q (Jonas):** `Converted` has no place for the sketched maps.
   - **A:** add `maps: list[ModuleMap] = field(default_factory=list)` as its last field. `generate_module` fills it for requests, and the runner fills it for books.
   - **Why:** it is the smallest change to the plan's shape.
3. **Chunk context.**
   - **Q (Alex):** "the previous chunk's last heading" forces the chunks to run in series, which conflicts with `concurrency=3`.
   - **A:** keep the concurrency, and give the previous chunk's pages and the last ~300 characters of its source text as context.
   - **Why:** this is deterministic, about 3× faster on a big book, and still tells Claude where the chunk starts.
4. **Room links.**
   - **Q (Jonas):** the heading `## C3. Guard Room` didn't link to room `rC3` labelled `C3. Guard Room`.
   - **A:** in `_match`, a label equal to the whole heading also matches, when it is unique and after the existing checks.
   - **Why:** the plan says rooms link by themselves. Existing links don't change.
5. **The original PDF's role.**
   - **Q (Elif):** the plan asks for `role: source`, but plateau 3's `Attachment` had no role field, and the exporter writes every attachment.
   - **A:** add `role: Literal["attachment","source"] = "attachment"`, carry it through `from_bundle` and the importer, and leave `source` attachments out of exports, with no opt-in yet.
   - **Why:** format rule R8 makes published sources opt-in on export. The alternative would export a published PDF by default.
6. **What progress counts.**
   - **Q (Alex):** the lead's first answer, to decision 3, let progress count chunks, as Alex built it. The plan says pages done out of pages.
   - **A:** the lead reversed this. The `converting` step counts the pages of the chunks that are done.
   - **Why:** plan Review Focus 1 and Task 6 ask for pages.
7. **Side prompts on stdin.**
   - **Q (lead, after Elif's note):** a side prompt passed as one argument can exceed Linux's 128 KB limit.
   - **A:** send it on stdin (Mateo).
   - **Why:** a big book would fail otherwise, and a test reproduced the error.
8. **Fixing the review's findings.**
   - **Q (lead, after Sofie's review):** fix her findings now, or leave them?
   - **A:** fix all of them now, in four engineers' separate files:
     - a failed chunk stops the job;
     - the entity pass is chunked, and a failed entity call is a warning;
     - a fenced answer with prose around it is unwrapped;
     - text ids are safe;
     - an `audience-player` warning;
     - a cap on the render size;
     - vector-drawn pages are kept;
     - Cancel stops the reading;
     - an ended job stays ended;
     - blobs stream;
     - repeated keys get a warning;
     - a 422 before the body is read;
     - leftover uploads are removed.
   - **Why:** the plan's Review Focus 1, 2, 3 and 5 ask for this robustness.
9. **Warnings after a reload.**
   - **Q (lead, after Aisha's report):** the conversion's warnings were lost when the module page was reloaded.
   - **A:** the page looks up the module's newest done conversion (Omar), with no new route.
   - **Why:** the plan wants the warnings in the module's list, and this was the smallest way.

## Screenshots
All are in `web/e2e/screenshots/`:
- `new-module-1280x800.png`, during a conversion;
- `new-module-done-1280x800.png`;
- `module-converted-1280x800.png`;
- `module-print-1280x800.png`;
- rewritten by the run: `module-text-1280x800.png`, `module-npc-1280x800.png`, `play-1280x800.png`, `play-820x1180.png` and `play-sheet-1280x800.png`.

I attached the four plateau 5 screenshots from the merged HEAD.

## What to check by hand
- `make convert-live PDF=<a real module PDF>` (it spends tokens): read the texts against the book, and look at the timings and the word coverage.
- Each sketched map against the page its `map-sketched` warning names.
- A generated dungeon ("a dungeon with kobolds, no plot") played for a few beats with the real `claude`.
- The print view in the browser's print dialog: the page breaks, the maps and their keys, and that MapPrint's own page still looks the same.
- That the real `claude -p` reads its prompt from stdin, for Ask the DM as well as for conversions.
- A large real PDF: the render cap, a vector-drawn map page, a Cancel during the reading, and a scanned PDF without tesseract.
- The original PDF in the module's attachments panel (see Open questions).

## Verified
- **`make install && make ci`** exits 0 on the merged HEAD `4adc79e`: ruff is clean, 8 import-linter contracts are kept, 1709 tests passed and 1 skipped, the web side passed 158 tests in 30 files, and the build is done. I ran it myself (`/tmp/archmage-ci.log`).
- **`DELVE_E2E_PORT=47957 make e2e-browser`** exits 0 with 3 passed and all 9 screenshots present, run myself with a temporary `DELVE_DATA_DIR`. I viewed two of them:
  - `new-module-1280x800.png`: "Converting the text", "0 of 2 pages", Cancel;
  - `module-print-1280x800.png`: a title page, then a DM-only text named once.
- **`uv run pytest tests/e2e/test_books_and_quick_dungeons.py`:** 3 passed, run myself.
- **In the code:**
  - the migration's `down_revision = "0008_audience_gm"` (`0009_conversions.py:13`);
  - the dependencies at `pyproject.toml:19-20`, with PyMuPDF only in a docstring;
  - `MAX_RENDER_PIXELS = 50_000_000`, `MIN_PAGE_CHARS = 40`, `MIN_OCR_CHARS = 20` and `MIN_DRAWING_OBJECTS = 10` (`pdf.py:23-37`);
  - `CONVERSION_TIMEOUT = 600.0` (`runner.py:53`) and `SIDE_TIMEOUT = 90.0` (`provider.py:50`);
  - the draft refusal (`campaigns.py:121`);
  - `Attachment.role` (`source.py:66`).
- **No test runs the real `claude`:** the web tests register FakeDM (`tests/web/test_conversions_api.py:52`), and the e2e tests put `fake_claude` first on `PATH` (`test_books_and_quick_dungeons.py:351-358`).

## Unverified
- How the prompts work with the real `claude`: faithful conversion, the players' marker, the entity JSON, the sketches and the generation plans. Only fakes were used.
- That `claude -p` reads its prompt from stdin when it gets no prompt argument. This rests on Mateo's report and the CLI's documented behaviour.
- The reading order, the speed of OCR, the render cap and the vector rule on real books; only built PDFs were used.
- The run without tesseract on this machine. It is covered only by unit tests with `ocr=None`.
- `make convert-live` on a real book.
- That MapPrint's own page is unchanged: Sam compared it by eye.

## Open questions
- **The original PDF in the attachments panel:** the web `Attachment` type has no `role` (`web/src/api.ts:311-318`), so `source-pdf` probably shows as an ordinary attachment there. The owner could delete it or switch it to the players. Nobody checked this.
- **Orphan blobs:** a blob written just before a failed or cancelled job stays in the store unlinked, and nothing collects these yet.
- **Exports:** there is no option to include `source` attachments in an export.
- **Conversion warnings on the module page** come only from the last 20 conversions.
- **Repeated keys:** a text whose keys repeat (two levels, each keyed 1…N) gets no sketch. Splitting it into one map per level is left for later.
- **Generation as a draft:** the New module screen offers no draft for a generated module, though the API accepts `mode`.

## Done when

All 7 verified.

| | Item | Status | Evidence |
|---|---|---|---|
| ✓ | make ci passes on a fresh clone (accepted here as `make install && make ci` in the integration worktree) | verified | Ran `make install && make ci` on merged HEAD 4adc79e in the integration worktree: exit 0, 1709 passed and 1 skipped, web 158 passed (/tmp/archmage-ci.log) |
| ✓ | make e2e-browser writes both screenshots (new-module-1280x800.png, module-print-1280x800.png) | verified | DELVE_E2E_PORT=47957 make e2e-browser: exit 0, 3 passed; both files present and viewed |
| ✓ | A built PDF converts to a draft that, once marked ready, starts a campaign, with its rooms linked to a sketched map | verified | tests/e2e/test_books_and_quick_dungeons.py::test_a_pdf_a_draft_and_a_request_become_modules passed (run myself) |
| ✓ | A request generates a module that starts a campaign at once | verified | the same e2e test, generate part, passed |
| ✓ | A whole module prints | verified | ModulePrint tests in make ci; the e2e test lists the print parts; module-print screenshot viewed |
| ✓ | No task's tests run the real claude | verified | tests/web/test_conversions_api.py:52 registers FakeDM; tests/e2e/test_books_and_quick_dungeons.py:351-358 puts fake_claude first on PATH; make convert-live never run |
| ✓ | The plateau 5 e2e test passes | verified | uv run pytest tests/e2e/test_books_and_quick_dungeons.py: 3 passed |
