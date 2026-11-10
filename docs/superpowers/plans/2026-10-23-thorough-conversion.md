# Thorough Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A PDF uploaded in Delve's GUI is converted, by default, the way the hand QA passes did it: agents with file
tools, working in a lasting job folder, clean every text against the page images, trace every map from its scan, join
the levels, describe the pictures, and leave a list of doubts and the cost; the job pauses and resumes instead of
failing.

**Architecture:** A new job variant of `pdf` conversions, `thorough`, run by `delve.conversions.thorough` (a package):
a `Workspace` (the job folder and its `state.json`, Delve's record of every finished piece), a stage pipeline that
runs today's read/classify/draft steps as code and the sort/clean/trace/describe stages as `claude -p` agent sessions
(`delve.dm.claude_cli.agent`), confined to the folder by CLI permission rules and a `./qa` wrapper around new
`delve qa` tool commands, and a maker that turns the folder into a `ModuleSource` in one transaction. Quick
conversion is unchanged.

**Tech Stack:** Python 3.13, asyncio, FastAPI, SQLAlchemy/SQLite, pdfplumber, Pillow, the `claude` CLI, React + TanStack
Query, Vitest, Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-10-23-thorough-conversion-design.md` (read it first; this plan argues from it).
Reference QA (read the briefs and tools before Tasks 3–6): `/home/raf/claude/qc/greyhawk-ruins/` (`gr/text/README.md`,
`gr/brief/README.md`, `notes/prompt-describe-greyhawk-illustrations.txt`, `gr/scripts/*`, `gr/text/textcheck.py`,
`gr/text/ocrkeys.py`, `gr/join_exits.py`, `gr/apply_texts.py`, `gr/apply_all.py`). Read only; never write there.

## Global Constraints

- Thorough is the PDF form's default; Quick is today's conversion, unchanged (same code path, same tests green).
- Preferences job `conversion.thorough` ("Thorough conversion"), default `BackendChoice("claude-cli", "opus", Effort.HIGH)`, Claude CLI only.
- No spending cap; `cost_usd` adds every agent session and side call across all runs of the job.
- No priority for play: no throttling when a campaign is played.
- Job folder: `<data_dir>/conversions/<conversion id>/`; never under /tmp; deleted on cancel and after a done job's module is made.
- A thorough job never ends `failed` with its folder deleted. Statuses: `running`, `paused`, `done`, `cancelled` (and `failed` only for Quick).
- Agents: tools Read, Write, Edit, Glob, Grep, Bash; Bash only `./qa …`; no MCP, no WebFetch/WebSearch, no slash commands, no user settings; Write/Edit only inside the folder; Read/Glob/Grep denied on the data directory (outside the folder), the repository and `$HOME`.
- Every new user-visible string has English and Dutch i18n keys.
- Delve's conventions: module docstrings cite this plan ("thorough conversion Task N"), `docs/` updated where behaviour is documented (`docs/conversions*.md` or the nearest existing doc), `make ci` green.
- No new system dependency. New Python dependency allowed: `resvg-py` (pinned exact version, a wheel with no system libs) for SVG→PNG; if no wheel installs on the host, fall back to drawing the PNG with Pillow from the map model and say so in the docs.

## Review Focus

1. **Keys that repeat across parts** (U1: the house and the Sea Ghost both have rooms 1, 2, 3…): keys are scoped per part; a map's room `r12` links only to its own part's `## 12.` → Task 7 test `test_repeated_keys_link_within_their_part`.
2. **A book with no map pages**: no trace pieces; a text with ≥3 keyed headings gets today's `SKETCHED` sketch, and each sketch is a doubt → Task 6 test `test_no_map_pages_sketches_and_doubts`.
3. **Delve stops while an agent is halfway**: on start the job is `paused`; resume reruns only that piece; finished pieces are not rerun and their cost is not added again → Task 4 test `test_restart_pauses_and_resume_skips_done_pieces`.
4. **A tool called with a path outside the folder** (`./qa textcheck /home/raf/x.md`, `../../delve.db`, a symlink out) is refused with exit code 2 → Task 3 test `test_qa_refuses_paths_outside_folder`.
5. **The usage limit mid-stage**: the session's limit notice pauses the job with the reset time, uses no retry, and the job resumes by itself after the reset → Task 4 test `test_usage_limit_pauses_without_spending_a_retry`.

---

## File Structure

- `src/delve/domain/settings.py`: `Job.CONVERSION_THOROUGH`, its default.
- `src/delve/domain/conversions.py`: `"paused"` status.
- `src/delve/dm/claude_cli/agent.py` (new): argv, permission settings and the run of one agent session.
- `src/delve/conversions/qa/` (new package): the general QA tools (`pages.py`, `textcheck.py`, `trace.py` for rotate/tile, `mapcheck.py`, `raster.py`, `join.py`, `paths.py`), behind `delve qa` in `src/delve/__main__.py`.
- `src/delve/conversions/thorough/` (new package): `workspace.py` (folder + `state.json`), `pieces.py` (retry/skip/pause rules), `pipeline.py` (stages), `make.py` (folder → module), `doubts.py`, `__init__.py` (`start_thorough`, `resume`).
- `src/delve/modules/books/prompts/thorough/` (new): `sort.md`, `clean.md`, `trace.md`, `describe.md`, `common.md`.
- `src/delve/conversions/runner.py`: `close_orphans` pauses thorough jobs; `STEPS["pdf-thorough"]`; cancel deletes the folder.
- `src/delve/web/routes/conversions.py`: `thorough` on the PDF route, `POST /api/conversions/{id}/resume`, availability.
- `src/delve/web/app.py`: auto-resume at start.
- `web/src/routes/NewModule.tsx`, `web/src/module/ConversionProgress.tsx`, `web/src/module/MakingQuestions.tsx`, `web/src/module/conversions.ts`, `web/src/i18n/*`: form, progress, paused/resume, doubts.
- `tests/fakes/fake_claude_agent.py` (new): a fake `claude` that plays the agents from canned outputs.

---

### Task 1: Preferences entry `conversion.thorough`

**Files:**
- Modify: `src/delve/domain/settings.py` (`Job`, `JOB_DEFAULTS`), the CLI capabilities that list which jobs `claude-cli` does (search `CLAUDE_CLI_CAPABILITIES`), web Preferences labels (`web/src/i18n/en.json`, `nl.json`, key pattern of the existing `conversion` job label)
- Test: `tests/domain/test_settings.py`, the Preferences web test that lists jobs

**Interfaces:**
- Produces: `Job.CONVERSION_THOROUGH = "conversion.thorough"`; `JOB_DEFAULTS[Job.CONVERSION_THOROUGH] == BackendChoice("claude-cli", "opus", Effort.HIGH)`; only `claude-cli` lists the job in its capabilities.

- [ ] **Step 1: Failing tests**: `test_thorough_conversion_defaults_to_opus_high` (the resolved settings with no stored choice give `("claude-cli", "opus", Effort.HIGH)`); `test_thorough_conversion_only_on_claude_cli` (a stored choice `{"conversion.thorough": {"provider": "codex"}}` is refused with `provider_wrong_job`); web: Preferences shows "Thorough conversion" / "Grondige conversie".
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_settings.py -q` and `cd web && npx vitest run src/routes/Preferences` → FAIL.
- [ ] **Step 3: Implement.** Check that `opus` is in the CLI's offered models; add it if not.
- [ ] **Step 4: Run** the same → PASS.
- [ ] **Step 5: Commit** `Preferences: a Thorough conversion job, Opus at high effort by default (thorough conversion Task 1)`.

### Task 2: One agent session (`claude_cli/agent.py`)

**Files:**
- Create: `src/delve/dm/claude_cli/agent.py`
- Test: `tests/dm/claude_cli/test_agent.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class AgentRun: text: str; usage: Usage | None; limited: bool; resets_at: str | None; session_id: str | None`
  - `def agent_settings(folder: Path, *, repo: Path, data_dir: Path, home: Path) -> dict` → the `--settings` JSON: `{"permissions": {"allow": ["Read(./**)", "Write(./**)", "Edit(./**)", "Glob", "Grep", "Bash(./qa:*)"], "deny": ["Read(<data_dir>/**)" except the folder, "Read(<repo>/**)", "Read(<home>/**)" except the folder, "WebFetch", "WebSearch", "Bash(*)" other than ./qa], "defaultMode": "dontAsk"}}`; the exact rule syntax is verified against `claude --help` / the CLI docs on the host, and the test pins what is produced.
  - `def agent_argv(*, model: str | None, effort: Effort | None, settings: Path) -> list[str]` → `claude -p --output-format stream-json --verbose --tools Read,Write,Edit,Glob,Grep,Bash --settings <path> --strict-mcp-config --setting-sources "" --disable-slash-commands --model <m> --effort <e>`; prompt on stdin (as `side_argv`).
  - `async def run_agent(prompt: str, folder: Path, choice: BackendChoice, *, timeout: float, repo: Path, data_dir: Path) -> AgentRun` — runs in `folder` (cwd), kills the process group on timeout (`ClaudeCliError`), reads the stream with `_stream_answer`'s rules, sets `limited`/`resets_at` from `stream.USAGE_LIMIT` (the DM's detection) instead of raising.
- Consumes: `Usage`, `_stream_answer`/`_usage`, `ClaudeCliError` from `provider.py`; `stream.USAGE_LIMIT`.

- [ ] **Step 1: Failing tests**: `test_agent_argv_confines_tools` (asserts `--tools` value, `--settings`, `--strict-mcp-config`, no `--mcp-config`, model/effort); `test_agent_settings_deny_outside_folder` (deny holds the data dir, repo and home; allow holds `Bash(./qa:*)` and no other Bash); `test_run_agent_reads_cost_and_text` (a fake `claude` script on PATH printing a stream-json `result` with `total_cost_usd: 1.25` → `AgentRun.usage.cost_usd == 1.25`, cwd is the folder); `test_run_agent_usage_limit_is_limited_not_error` (fake prints the limit notice → `limited is True`, `resets_at` parsed); `test_run_agent_timeout_kills` (fake sleeps → `ClaudeCliError`).
- [ ] **Step 2: Run** `uv run pytest tests/dm/claude_cli/test_agent.py -q` → FAIL.
- [ ] **Step 3: Implement.** Agent timeout constant `AGENT_TIMEOUT = 3 * 3600.0` (seconds; a trace of a big map runs long).
- [ ] **Step 4: Run** → PASS. Then one manual check on the host with the real CLI: an agent asked to `Read /home/raf/.bashrc` and to `Bash(ls /)` is refused; record the output in the task's commit message body.
- [ ] **Step 5: Commit** `Claude CLI: agent sessions confined to a job folder (thorough conversion Task 2)`.

### Task 3: The QA tools, general, behind `delve qa`

**Files:**
- Create: `src/delve/conversions/qa/{__init__,paths,pages,textcheck,trace,mapcheck,raster,join}.py`
- Modify: `src/delve/__main__.py` (subcommand `qa`), `pyproject.toml` (`resvg-py`), import-linter contracts if `delve.conversions` layering needs it
- Test: `tests/conversions/qa/test_*.py`

**Interfaces:**
- `paths.inside(folder: Path, given: str) -> Path` — resolves (following symlinks) and raises `OutsideFolder` unless under `folder`; every command resolves every path argument with it; the CLI exits 2 with "outside the job folder" on refusal. `folder` is the cwd.
- `delve qa pages <pdf> <out-dir> --dpi 150 [--first N --last M]` → `p-NNN.png` and `ocr-NNN.txt` (the text layer, OCR when empty, as `read_pdf`).
- `delve qa keys <ocr-dir> --pattern <regex>` → JSON `{key: {"page": n, "text": "..."}}`, the book's entries by key (generalises `ocrkeys.py`; the pattern is the part's key scheme, written by the sort agent into `parts.json`).
- `delve qa textcheck <parts.json> <file.md>…` → per file: keys missing, sections < 85 % coverage, sections > 25 % foreign words, bad headings (thresholds as `textcheck.py`). Heading form: `## <KEY>. <title> {#<key lower>}`, KEY matching the part's pattern.
- `delve qa rotate <in.png> <out.png> <deg>`, `delve qa tile <rot.png> <out.png> X0 Y0 X1 Y1 <px> OX OY <width>` (as `rot.py`, `tile.py`).
- `delve qa mapcheck <file.dmap> [--fix-doors]` → parse + validate + (fixdoors) + `<file>.svg` + `<file>.png`; prints errors/warnings; exit 1 on errors.
- `raster.svg_to_png(svg: str, out: Path, width: int = 1200) -> None` (resvg-py; Pillow fallback per Global Constraints).
- `join.join_exits(maps: dict[str, MapModel], exits: dict[str, list[Exit]]) -> tuple[dict[str, str], list[Doubt]]` where `Exit = {"label", "at": [x, y], "room", "to_map", "to_room"?, "text"}`: landing order = matching label on `to_map` pointing back; same label; centre of `to_room`; `to_map`'s party start (a doubt). Exits with no `to_map` are left and become doubts. Output: each map's source with `exit` statements added. (Generalises `join_exits.py`: the target is named explicitly, no level-code regex.)
- `delve qa join <maps-dir> <out-dir>` wraps it and writes `join-doubts.json`.

- [ ] **Step 1: Failing tests**: `test_qa_refuses_paths_outside_folder` (absolute path, `..`, a symlink out, each → exit 2); `test_pages_renders_and_reads_text` (fixture PDF from `tests/fixtures/pdfs.py`); `test_keys_by_pattern` (numbers `^\d+[a-z]?`, letter keys `^[WPZ][0-9B]\d\d[a-e]?`); `test_textcheck_flags_missing_and_foreign`; `test_mapcheck_renders_png_without_browser` (a reference `.dmap` → PNG exists, Pillow opens it); `test_join_matches_labels_and_guesses_with_doubt`.
- [ ] **Step 2: Run** `uv run pytest tests/conversions/qa -q` → FAIL.
- [ ] **Step 3: Implement**, porting the Greyhawk scripts' logic and removing every Greyhawk constant.
- [ ] **Step 4: Run** → PASS; `uv run delve qa --help` lists the commands.
- [ ] **Step 5: Commit** `delve qa: the hand QA's tools, made general (thorough conversion Task 3)`.

### Task 4: Workspace, pieces, paused and resume

**Files:**
- Create: `src/delve/conversions/thorough/{__init__,workspace,pieces}.py`
- Modify: `src/delve/domain/conversions.py` (`ConversionStatus` gains `"paused"`; `CONVERSION_ENDS` unchanged), `src/delve/conversions/runner.py` (`close_orphans`, cancel, `_open` treats `paused` as not holding the slot), storage `running()` unchanged (the unique index is on `running` only, so no migration)
- Test: `tests/conversions/thorough/test_workspace.py`, `test_pieces.py`, `tests/conversions/test_runner.py`

**Interfaces:**
- `Workspace(root: Path)`: `create(conversion_id, data_dir, pdf: Path) -> Workspace` (copies the PDF in as `book.pdf`, writes the `./qa` wrapper `#!/bin/sh\nexec <sys.executable> -m delve qa "$@"` mode 0755, copies the reference material: `docs/maps/dsl*.md` and 3 reference `.dmap`s to `ref/`); `state() -> State`; `done(piece: str, cost: float | None, outputs: list[str])`; `failed(piece: str, error: str)`; `is_done(piece) -> bool`; `remove()`.
- `State` (in `state.json`, written atomically): `{"stages": {stage: "done"|...}, "pieces": {piece: {"status": "done"|"skipped", "attempts": n, "cost_usd": x}}, "paused": {"reason", "resets_at"}|null, "options": {"mode", "title"}}`.
- `pieces.run_piece(ws, piece_id, attempt: Callable[[], Awaitable[AgentRun]], check: Callable[[], list[str]]) -> PieceOutcome` with `PieceOutcome = Literal["done", "skipped", "paused"]`: up to 3 attempts (1 + 2 retries); `AgentRun.limited` → raises `Paused(resets_at)` without counting an attempt; an attempt is a failure when `check()` (the piece's expected outputs) returns missing files; after 3 failures → `"skipped"` and a doubt. A piece whose status is done is never run. Cost of every attempt (including failed ones) is added to the job's `cost_usd` once, when the attempt ends.
- Conversion target for a thorough job: `{"thorough": true, "folder": "<path>"}`; `kind` stays `"pdf"`.
- `close_orphans`: a `running` job with `target.thorough` becomes `paused` with reason `"Delve stopped"`; others fail as today.
- `cancel` of a thorough job (running or paused) → `cancelled` and `Workspace.remove()`.
- `thorough.resume(services, id) -> Conversion` — refused (`ConversionRunning`) when another job runs; restarts the pipeline (Task 6) on the same workspace.

- [ ] **Step 1: Failing tests**: `test_restart_pauses_and_resume_skips_done_pieces` (state with 2 done pieces, 1 attempted; `close_orphans` → `paused`; resume runs only the third; cost unchanged for the two); `test_usage_limit_pauses_without_spending_a_retry`; `test_three_failures_skip_and_doubt`; `test_cancel_removes_folder`; `test_paused_job_does_not_block_a_new_job`; `test_qa_wrapper_runs_delve_qa`.
- [ ] **Step 2: Run** `uv run pytest tests/conversions -q` → FAIL.
- [ ] **Step 3: Implement.** Auto-resume after the usage limit: a `loop.call_later` to `resets_at` + 60 s (or 15 min when unknown), cancelled on cancel.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Thorough conversions: a lasting job folder, pieces, paused and resume (thorough conversion Task 4)`.

### Task 5: The briefs

**Files:**
- Create: `src/delve/modules/books/prompts/thorough/{common,sort,clean,trace,describe}.md`
- Test: `tests/conversions/thorough/test_briefs.py`

**Content** (generalise the Greyhawk briefs; keep their rules word for word where they are general):
- `common.md`: the folder layout (`book.pdf`, `pages/p-NNN.png`, `pages/ocr-NNN.txt`, `scan/` map pages at 200 dpi, `draft/`, `clean/`, `maps/`, `ref/`, `parts.json`), the `./qa` commands, "write only in this folder", and **the doubts file**: every agent writes `doubts/<piece>.json` = `[{"part": "<text or map id>", "pages": [n…], "kind": "<missing-text|missing-room|checker-flag|left-out|guessed-landing|picture-unsure|other>", "text": "…"}]` (empty list when none) and ends with a one-paragraph report.
- `sort.md` (lead): read the map pages and text layer; write `parts.json` = `[{"id", "title", "kind": "level"|"area"|"chapter"|"front"|"appendix", "audience", "pages": [first, last], "key_pattern": "<regex or null>", "map_pages": [n…], "maps": [{"name", "title", "page", "level"}], "order": n}]` and `"pictures": [page…]` at the top level for overland/world/region map pages, which are attached as pictures, never traced; re-sort every keyed section of `draft/*.md` into `draft/<part>.md` with normalised headings; write `keys/<part>.txt`; place orphans files' pieces after the clean stage (a second, short run of the sort agent: piece `sort-orphans`).
- `clean.md`: `gr/text/README.md` generalised (the key form uses the part's `key_pattern`; level titles from `parts.json`; orphans to `clean/<agent>-orphans.md`).
- `trace.md`: `gr/brief/README.md` generalised: read the scale and rotation from the page; renderer `classic-bw` unless the book's maps are colour plans (then `classic`); room names `<key lower>` scoped per map, labels as printed; `maps/<name>.dmap`, `maps/<name>.png`, `maps/<name>.exits.json` with `to_map`; ≥2 render-and-compare rounds.
- `describe.md`: the illustrations prompt generalised; output `art/descriptions.json`.
- [ ] **Step 1: Failing test** `test_briefs_name_only_folder_paths` (no `/home`, `/tmp`, `greyhawk`, `W539` in any brief; each names `doubts/`); `test_briefs_fill` (placeholders `{piece}`, `{parts}`, `{maps}` filled).
- [ ] **Step 2–4:** run → FAIL, write, run → PASS.
- [ ] **Step 5: Commit** `Thorough conversion briefs (thorough conversion Task 5)`.

### Task 6: The pipeline

**Files:**
- Create: `src/delve/conversions/thorough/pipeline.py`, `doubts.py`
- Modify: `src/delve/conversions/runner.py` (`STEPS["pdf-thorough"]` = `(("reading",), ("classifying",), ("drafting",), ("sorting",), ("cleaning",), ("tracing",), ("joining",), ("describing",), ("entities",), ("making",))`; progress for a thorough job is looked up by `target.thorough`)
- Test: `tests/conversions/thorough/test_pipeline.py`, `tests/fakes/fake_claude_agent.py`

**Interfaces:**
- `async def run_thorough(services: ConversionServices, live: _Live, ws: Workspace) -> None`, stages in order, each skipped when `state.stages[stage] == "done"`:
  1. `reading`: `read_pdf` → `ws/pages/` via `qa.pages` (150 dpi) and map/picture pages at 200 dpi to `ws/scan/`.
  2. `classifying`: `classify_pages` (side calls on the `conversion.thorough` choice), saved to `ws/classes.json`.
  3. `drafting`: `convert_book`'s chunk step only → `ws/draft/*.md` (reuse `_convert_chunks`/`_texts`; no entities, no sketches).
  4. `sorting`: piece `sort` (one agent, `sort.md`).
  5. `cleaning`: pieces `clean-<group>`; groups of parts with ≤ 25 pages of text each; then piece `sort-orphans`. Fallback for a skipped piece: copy `draft/<part>.md` to `clean/`, doubt `"not cleaned"`.
  6. `tracing`: one piece per map in `parts.json` (`trace-<map name>`). Skipped → `SKETCHED` sketch from the part's keys (`sketch_map`) + doubt.
  7. `joining`: code (`qa.join`), doubts from its output.
  8. `describing`: piece `describe` over pictures cut whole from picture pages (the classifier's boxes; text-strip crops are not offered).
  9. `entities`: `convert._entities` + `dedupe_entities` on `clean/*.md` texts.
  10. `making`: Task 7.
- While a thorough job runs it holds the one running slot, as every job does: other jobs are refused with today's 409 (my call; the spec left it to the builder).
- Concurrency: `THOROUGH_AGENTS = 4` agent sessions at once (a module constant).
- Parts with ≥ `SKETCHED_KEYS` keys and no map in `parts.json` get a sketch + doubt `"no map in the book"`.
- Progress: `progress(stage, done_pieces, total_pieces)`; cost after each attempt.
- `doubts.gather(ws) -> list[dict]` reads `doubts/*.json` (invalid file → one doubt "the agent's doubts file was unreadable").
- `tests/fakes/fake_claude_agent.py`: an executable fake `claude` that reads the prompt, recognises the piece from a `PIECE: <id>` first line every brief starts with, and writes canned outputs for the tiny fixture book (2 parts with repeating number keys, 1 map page) into its cwd, then prints a stream-json result with a cost.

- [ ] **Step 1: Failing tests**: `test_pipeline_end_to_end_with_fake_agents` (job `done`, every stage done, cost = sum of the fake's costs); `test_no_map_pages_sketches_and_doubts`; `test_skipped_trace_falls_back_to_sketch_with_doubt`; `test_skipped_clean_keeps_draft_with_doubt`; `test_stage_error_pauses_with_error` (a stage raising → `paused`, `error` set, folder kept).
- [ ] **Step 2: Run** `uv run pytest tests/conversions/thorough -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Thorough conversion: the stages (thorough conversion Task 6)`.

### Task 7: Make the module from the folder

**Files:**
- Create: `src/delve/conversions/thorough/make.py`
- Modify: `src/delve/conversions/runner.py` (`_make_module` reused; `questions` JSON gains `"doubts"`)
- Test: `tests/conversions/thorough/test_make.py`

**Interfaces:**
- `def build_source(ws: Workspace, title: str) -> tuple[ModuleSource, list[ModuleMap], list[tuple[Attachment, bytes]], list[dict]]` (generalise `apply_texts.py`/`apply_all.py`): texts from `clean/` in `parts.json` order, each level's text pointing at its map (`TextDoc.map`); maps from `maps/` after joining, the first map of the first dungeon part the module default; every room `<key>` of a map linked to its part's heading by an explicit key entry (`scoped_keys`, as `dungeon_maps._link_levels`); pictures from `art/` with `descriptions.json` (id, audience, description); entities from Task 6 step 9 keyed with `key_entities`; refs repaired with `repair_refs`; the original PDF as the `source` attachment; the doubts last.
- Junk crops are never attached (only `art/` pictures, the overland map pages as pictures, and the source PDF).
- After the transaction commits, the job folder is removed (`Workspace.remove()`); a failure before that leaves it.
- Thorough jobs' warnings stay in `warnings`; doubts in `questions["doubts"]`; `MAKING_NOTES` untouched unless the organiser chooses to pass doubts to the DM (Task 8's checkbox per doubt list: "Tell the DM").
- [ ] **Step 1: Failing tests**: `test_repeated_keys_link_within_their_part`; `test_texts_in_parts_order_with_maps`; `test_pictures_described_no_strips`; `test_doubts_stored_on_job`; `test_made_in_one_transaction` (a failure in `save_source` leaves no module, job `paused`).
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `Thorough conversion: the module from the job folder (thorough conversion Task 7)`.

### Task 8: API and web

**Files:**
- Modify: `src/delve/web/routes/conversions.py`, `src/delve/web/app.py`, `web/src/routes/NewModule.tsx`, `web/src/module/ConversionProgress.tsx`, `web/src/module/MakingQuestions.tsx`, `web/src/module/conversions.ts`, `web/src/i18n/{en,nl}.json`, `docs/` (conversion doc)
- Test: `tests/web/test_conversions_api.py`, `web/src/routes/NewModule.test.tsx`, `web/src/module/ConversionProgress.test.tsx`, `web/src/module/MakingQuestions.test.tsx`, one Playwright spec `web/e2e/thorough-conversion.spec.ts` against the fake agent

**Interfaces:**
- `POST /api/conversions/pdf?thorough=true` (default `true`): thorough when true and the `conversion.thorough` choice is the Claude CLI and `claude` is installed; 409 with code `thorough_unavailable` otherwise (the form never sends it then). `book_maps` ignored when thorough.
- `GET /api/conversions/options` → `{"thorough": {"available": bool, "reason": str | null}}`.
- `POST /api/conversions/{id}/resume` → 202 `conversion_json`; 409 when another job runs or it isn't paused.
- `conversion_json` adds `thorough: bool`, `paused: {reason, resets_at} | null`.
- App start: after `close_orphans`, every paused thorough job whose reason is "Delve stopped" resumes (one at a time: the first; the others stay paused).
- Form: radio "Thorough (default)" / "Quick" with hints (`newModule.thorough`, `newModule.thoroughHint` = "Checks every page, traces every map from the book. Takes hours for a big book and costs much more. Needs the Claude CLI."; `newModule.quick`, `newModule.quickHint`); Thorough disabled with the options' reason; book-maps checkbox shown only for Quick.
- Progress: "Step 5 of 10: cleaning texts, 12 of 34", "Cost so far: $x.xx"; paused: reason, reset time, **Resume** button; cancel asks for confirmation that the work is deleted.
- Doubts on the module page under the existing making-questions panel: a list, each with part, pages (links to the source PDF at that page: `#page=n`), kind, text; the cost of the job beside the heading; a "Tell the DM" button writes them into `MAKING_NOTES`.
- [ ] **Step 1: Failing tests** for each interface above (API: default thorough, unavailable 409, resume 409/202, options; web: form default, disabled reason, progress pieces + cost, paused + resume, doubts list + cost + Tell the DM; e2e: upload fixture PDF → fake agents → module with a traced map and a doubts list).
- [ ] **Step 2: Run** `uv run pytest tests/web -q`, `cd web && npx vitest run`, `make e2e-browser` (or the repo's e2e target) → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; `make ci` green.
- [ ] **Step 5: Commit** `Thorough conversion in the GUI: the default, its progress, resume and doubts (thorough conversion Task 8)`.

### Task 9: Real-Claude check on U1, and docs

**Files:**
- Modify: `docs/` conversion doc (how thorough works, its folder, resume, the tools, confinement), `docs/backlog.md`/`progress.md` as the repo does for delivered work
- Create: `docs/review/2026-10-23-thorough-conversion-u1.md`

- [ ] **Step 1:** On a fresh data dir (`DELVE_DATA_DIR` the quest's tmp), `make install`, start Delve, convert U1 Sinister Secret of Saltmarsh thoroughly with the real `claude` (the PDF: `/home/raf/claude/qc/saltmarsh/u1.pdf`; read only, copy it into the tmp dir). Stop Delve once during the cleaning stage and start it again: the job must resume and finish.
- [ ] **Step 2:** Check against the PDF and write the review: per text (complete, in order, linked), per map (traced, not invented, keys linked, joined), pictures, the doubts list, the cost, the time, the resume. Compare with the hand QA of the same module if `/home/raf/claude/qc/saltmarsh/REPORT.md` exists.
- [ ] **Step 3:** Fix what the check finds (each fix its own commit with a test), re-run the stages it affects.
- [ ] **Step 4:** `make ci` green.
- [ ] **Step 5: Commit** `Thorough conversion: U1 checked with the real Claude, docs (thorough conversion Task 9)`.
