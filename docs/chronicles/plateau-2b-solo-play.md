# Build Delve plateau 2b (solo play) exactly as planned in docs/superpowers/plans/2026-10-17-plateau-2b-solo-play.md.

# Plateau 2b: solo play is built, but not delivered

All ten tasks of `docs/superpowers/plans/2026-10-17-plateau-2b-solo-play.md` are built on the quest branch `guild/20261017-0fd9e57d/party`, each with the plan's commit message. Nothing is delivered to master, as you asked.

In the integration worktree, after the last merge:
- **`make install && make ci`** passes: ruff, 6 of 6 import contracts, **1490 Python tests passed** (1 skipped), and **79 web tests** with typecheck and build.
- **The fake-claude e2e** (`tests/e2e/test_play_with_fake_claude.py`) passes.
- **`make e2e-browser`** passed (1 Playwright test, Chromium) and wrote the screenshots.

The real `claude` never ran as the DM. Every test and the browser run used the fake `claude`.

## What each task delivered

1. **Module text for the DM** (Lucas)
   - `delve.modules.text.unpack` gives sections, keys and entities. Migration `0004_module_text` adds `module_texts`, a `text` column on revisions, and an FTS5 index with one row per paragraph or key entry.
   - Revision snapshots include the text.
   - `module_lookup(query, section, limit)` and `module_key(room)` are DM-only. A map-only module answers `{"error": "this module has no text"}`.
   - A public `moves.locate` resolves rooms the way `move_party` does.
2. **Beats and the story** (Noor)
   - `delve.play.table` has `open_beat`, `close_beat`, `current_beat`, `story` paging, `add_entry`, `dm_log`, `feed_entry_for` and `feed`.
   - Migration `0005_beats_story` adds `beats`, `story`, `dm_log` and `dm_sessions`. A partial unique index allows one running beat per campaign.
   - A DM reply grows as one `dm_text` entry with one id. A tool call and its result become one `tool` row through `player_view`. DM-only tools are dropped. Errors keep only their message.
3. **The DM's prompt** (Lucas)
   - `src/delve/dm/prompt/dm.md` is ttrpg2's procedure with Delve's tools and words.
   - `build_system_prompt` returns the plan's six addenda, in its fixed order.
   - **Prompt size: 6473 words, about 8.7k tokens** (10.5k at 4 characters per token). ttrpg2's whole CLAUDE.md is about 16k.
4. **The tool bridge** (Noor)
   - `GET /internal/dm/tools` and `POST /internal/dm/{id}/call`, guarded by loopback plus `X-Delve-Bridge`. The owner token alone gets 403.
   - The secret is made per process, with `secrets.token_urlsafe(32)`.
   - Mutating calls publish `characters`, `map_state`, `combat` and `story`.
   - `delve dm-bridge` is a low-level MCP `Server("delve")`. An import-linter contract makes `delve.dm.bridge` the only importer of `mcp`.
5. **The `claude -p` provider** (Ravi)
   - `delve.dm.claude_cli` holds `argv`, `stream`, `resident`, `effort` and `provider`.
   - It has the isolation flags. The MCP config file is mode 0600, so the secret never appears in argv.
   - The resident runs in its own process group and keeps an 80-line stderr tail.
   - It has the turn timeout, auto effort, auto-reset with handover and rehydrate, and `side_call` with the aux args.
   - `tests/fixtures/fake_claude.py` makes real MCP calls, can crash, hang or report large usage, and logs its argv to `FAKE_CLAUDE_ARGV_LOG`.
   - `/api/health` gains `dm: available | unavailable`.
6. **The beat runner and Ask the DM** (Zoe)
   - `run_beat`, `cancel_beat` and `wait_beat` run in a background task, so a beat survives a reload.
   - The first beat is primed with `session_primer` and `new_session`. Recaps get their own entries.
   - A failure shows as "The DM didn't answer: …".
   - Ask the DM is a side pass, built without module text, DM secrets or NPC notes.
7. **The play API** (Zoe)
   - `routes/play.py` serves act (202, or 409 "the DM is still answering"), ask, cancel, story, play state, play settings and the DM log.
   - It also adds `PUT /api/campaigns/{id}/marching-order`, which goes beyond the plan.
8. **The play screen** (Priya)
   - `/play` and `/play/:campaignId`: Story (escaped, then Markdown, with read-aloud styled apart), Composer, ThinkingIndicator, PartySidebar, MapPanel (with "Map offline"), SheetDrawer, AskPanel and SettingsPopover.
   - Below 900 px the panels stack. Every string is in EN and NL.
9. **The eval harness** (Diego)
   - Top-level `evals/` with checks `die_first`, `pacing_line`, `no_meta`, `no_hidden_intel`, `combat_pipeline` and `no_state_bypass` ("no tool outside `mcp__delve__`"). Batch steps expand.
   - Cases `locked_door`, `goblin_ambush`, `split_party_secret` and `ask_the_dm_rules`: 19 fixtures, all as expected.
   - `make evals` runs offline. `make evals-live` (with `--compare-ttrpg2`) is opt-in and was never run with the real claude.
10. **End to end** (Zoe)
    - The fake-claude e2e plays three beats through the real bridge and tool host. It checks the story, the clean feed, that the map state moved, that every roll is logged, and that the argv was isolated.
    - The Playwright spec, `web/playwright.config.ts` (port 47811) and the `make e2e-browser` target.
    - Updates to GUILD.md, README.md and docs/progress.md.

## Test counts per area (collected in the integration worktree)
- `tests/modules` 85, `tests/dm` 90, `tests/play` 109, `tests/web` 145, `tests/storage` 63, `tests/e2e` 6.
- `tests/test_evals_offline.py` 65.
- The new 2b test files together (claude_cli, table, runner, ask, play API, evals): 114.
- Total: 1490 Python tests passed (1 skipped) and 79 web tests.

## Screenshots (attached)
- `web/e2e/screenshots/play-1280x800.png`
- `web/e2e/screenshots/play-820x1180.png`
- `web/e2e/screenshots/play-sheet-1280x800.png`

## Deviations from the plan
- **Migrations:** `0005_beats_story` follows `0004_module_text`. It also holds the `dm_sessions` table (for the provider's session id) and `play_settings` (the campaign's tone, detail, effort and model).
- **An extra commit**, "Integrate plateau 2b tasks 1-5 and 8", wires the provider to `storage.dm_sessions`, the bridge secret and the campaign's live fight and NPCs, and closes it on shutdown. I added two merge commits of my own:
  - the live eval's Ask services now carry the `side` and `publish` that `play.ask` needs;
  - the live eval's imports are sorted.
- **`Key`** gains `key` and `title`.
- **`module_lookup`** takes `limit` (1–20), and `module_texts.search` takes `section=`. Snippets are whole paragraphs, as in ttrpg2.
- **`build_system_prompt`** takes `custom_tone=""`, and `rehydrate` is the handover text.
- **`feed_entry_for`'s third argument** is a `PendingCalls` object.
- **More helpers** than the plan names: `current_beat`, `feed`, `add_entry`, `log_dm_event` and `summarize_args`.
- **`beat_id` is nullable** on story entries, for Ask entries outside a beat.
- **`DMError`** gains a DM-only `detail` (the stderr tail). It goes to the DM log only.
- **The provider appends rehydrate and handover itself** (position 6), with the texts from `delve.dm.prompt`.
- **Small fixes to ported behaviour:**
  - no `--fallback-model sonnet` when the model is sonnet, because the CLI refuses a fallback equal to the main model;
  - auto effort counts NPCs, not name matches;
  - `tick_world` is gone from the rehydrate note (Delve has no such tool yet).
- **The Settings "clear error"** for a missing claude is the existing provider warning. `claude-cli` isn't registered when claude isn't on PATH.
- **The bridge uses `urllib`**, so it adds no runtime dependency, and the SDK's input validation is off, so the tool host's hints reach the DM.
- **Evals:** they use the word beat (the fixture markers keep ttrpg2's `eval_turn`). There is no `delve eval` command, which the plan made optional; the entry point is `python -m evals`.
- **The play screen:**
  - Markdown without links or tables;
  - no "custom" tone in the popover;
  - Ask stays usable while a beat runs (spec §7.3);
  - a second `EventSource` (carried into plateau 3).

## Decisions taken without the human
1. **Q:** Tasks 1 and 2 both need the next migration number, and they run in parallel. **A:** Task 1 is 0004, and Task 2's 0005 is re-chained onto it at merge. **Why:** the plan's own numbers, with the smallest merge fix.
2. **Q:** Where does the provider keep its session id per campaign (the plan says "in storage" but names no table)? **A:** a `dm_sessions` table and repository (`get`, `set`, `clear`) in 0005, used by the provider through a small Protocol. **Why:** the smallest storage addition, and it keeps the parallel tasks independent.
3. **Q:** Task 3 (the prompt) must name only existing tools, including Task 1's. **A:** the same engineer did Task 1, then Task 3. **Why:** the tool-name test can pass honestly, without a temporary allow-list.
4. **Q:** The rehydrate, handover and `HANDOVER_PROMPT` texts were written twice (`delve.dm.prompt` and the provider). **A:** `delve.dm.prompt` is the one source, and the provider imports it. **Why:** Task 3 owns the prompt texts; this is the smallest change.
5. **Q:** Who writes "The DM didn't answer: …"? **A:** the runner, around the provider's cause message. The stderr tail (`DMError.detail`) goes only to the DM log. **Why:** Review Focus 2 and the fourth wall; it also avoids the phrase appearing twice.
6. **Q:** No host route existed for the marching-order arrows. **A:** add `PUT /api/campaigns/{id}/marching-order {order}` over `set_marching_order`. **Why:** the plan requires "through a host route"; this is the smallest one.
7. **Q:** The play screen opens a second event stream. **A:** leave it and record it, carried into plateau 3. **Why:** it works, and merging the streams is out of 2b's scope.
8. **Q:** Modules imported before 0004 have no text. **A:** no backfill; re-import them. This is noted in progress.md. **Why:** a migration can't import `delve.modules` (layering).
9. **Q:** From when does the thinking indicator time a beat? **A:** from `opened_at`. **Why:** with one player, opening the beat is the moment it closes for submissions; `closed_at` is set when the DM finishes.
10. **Q:** In live eval mode, which model does Ask the DM's side call use? **A:** `BackendChoice("claude-cli", None, None)`, which gives `--model haiku`, the ttrpg2 aux default. **Why:** that is the plan's side-call default.

## What the morning should check, with the human
- **The eval gate:** `make evals-live EVAL_ARGS="--compare-ttrpg2"`. Compare the check results and the timings with ttrpg2. Only `locked_door` and `goblin_ambush` exist on the ttrpg2 side.
- **The 30 s first-words guideline:** read the live report's per-beat time to the first `TextDelta`. Note that the session-start beat is a long message, so auto effort makes it high, and the next low-effort beat respawns the resident (with resume).
- **That the real CLI accepts the argv:** `--tools ""`, `--allowedTools "mcp__delve__*"`, `--setting-sources ""`, `--disable-slash-commands` and `--system-prompt-snapshot off` were only ever checked against the fake. Also check that the DM really has no built-in tools.
- **The first real session on the crypt sample:**
  - a party is created through `create_character`;
  - `move_party` updates the map panel;
  - a fight runs through `setup_combat` and `combat_round`;
  - Ask the DM gives no module canon;
  - a reload in the middle of a beat rebuilds the story;
  - a `claude` killed during a beat shows "The DM didn't answer: …", and the next Act recovers.
- **Re-import any module imported before 0004** so it has text. Look at the prompt's size (about 8.7k tokens) and the cost per beat.
- **Still open from earlier:** THAC0 for priests and thieves in the reference, and how saves work for monsters under 1 HD.
