# Delve plateau 2b: solo play, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The first real session. Claude is the DM through `claude -p`, behind the DM layer, isolated and using only
Delve's tools. You play from the browser on the play screen, with **Act** and **Ask the DM**. The player's screen gets
only what passed the fourth-wall filter. A module's text is available to the DM. An offline eval harness, with an
opt-in live mode, keeps the DM's procedure honest.

**Architecture:**
- **The provider:** `delve.dm.claude_cli` is the `claude -p` DMProvider. It keeps one resident process per active
  campaign, fed over stream-json. It is isolated with `--strict-mcp-config` and has no file tools.
- **The tools:** the DM's tools reach Delve through `delve dm-bridge`, a small stdio MCP server (the `mcp` SDK). It
  forwards each call to the running Delve over localhost, with a per-process secret, to `ToolHost` from plateau 2a.
- **The table:** `delve.play.table` runs beats, stores the story and builds the players' feed through `player_view`.
- **The screen:** the play screen in the SPA.

**Tech Stack:**
- **New runtime dependency:** `mcp>=1.27,<2`. It's the official SDK, the same as ttrpg2's, and is used only by the
  bridge.
- **New dev dependency:** `@playwright/test`, for one browser smoke test outside `make ci`.

**Spec:**
- `docs/superpowers/specs/2026-10-17-unified-app-design.md` §5.2 (Settings choose backends), §6.1–6.5 (the DM), §7.1
  (beats), §7.3 (three ways to speak; only Act and Ask the DM here), §7.5 (the fourth wall), §7.6 (the play screen) and
  §14 (plateau 2b).
- `docs/progress.md`, especially "Carried into plateau 2b".
- `docs/notes/2026-10-17-ttrpg2-dm-driver-survey.md`: how ttrpg2 drives `claude -p`, its `/play` page and its evals.
  **Read it first.**
- `docs/glossary.md`.

**Source to port (read only):**
- `/home/raf/claude/ttrpg2`: `tools/dm_session.py`, `CLAUDE.md`, `evals/` and `dashboard.py` (the `/play` parts).
- Never open `campaigns/`.

## Global Constraints

- **Earlier plateaus still apply:** everything in the Global Constraints of plateaus 0, 1 and 2a holds.
- **Tests never run the real `claude`.** Provider tests use a fake `claude` executable (Task 5). The live eval mode
  and the live speed check are opt-in commands. They are not tests, and the quest doesn't run them.
- **DM isolation.** Every DM process is started with:
  - `--strict-mcp-config` and an `--mcp-config` naming only Delve's bridge;
  - no `Read`, `Write`, `Edit`, `Bash` or any other built-in tool (`--tools ""` plus
    `--allowedTools "mcp__delve__*"`);
  - `--setting-sources ""`;
  - `--disable-slash-commands`;
  - a working directory inside the data dir, `<data dir>/dm/<campaign id>/`, never the repo or the home directory.

  A test asserts the argv.
- **The players' feed is built only through `player_view`.** Nothing else reaches the player's screen from a tool:
  - no thinking blocks;
  - no partial tool input;
  - no tool input of DM-only tools;
  - errors show their message only, without `candidates`, because those can name hidden rooms.
- **The speed guideline (spec §6.4).** The DM's first words should appear within 30 s of a beat closing. The prompt asks
  for ttrpg2's one-line pacing opener before tool calls. The screen always shows progress: the thinking indicator with
  elapsed time and the tool count.
- **Settings choose the DM's provider, model and effort per job** (plateau 0). `auto` effort is ttrpg2's heuristic.
- **The internal tool endpoint** answers only loopback clients that send the per-process secret header. It is never
  reachable with the owner token alone.
- **Words:** DM, beat, map state, host. Never "GM", "turn" for a beat, or "session" for a map state. The DM prompt uses
  the glossary too.

## Review Focus

1. **The browser reloads in the middle of a beat.** The beat keeps running, and the reloaded page shows the story so
   far and picks up the stream. A second Act while a beat runs is refused with 409 "the DM is still answering". (Task 6
   and Task 7 tests.)
2. **`claude` crashes, hangs or isn't installed.**
   - A crash or a hang past the timeout ends the beat with a visible "The DM didn't answer: …" entry and the stderr
     tail in the DM log.
   - The next Act starts a fresh resident.
   - A missing `claude` binary gives Settings a clear error and `/api/health` a `dm: unavailable` field.

   Never a hung page. (Task 5 test with the fake executable.)
3. **A secret reaches the player through a tool result, an error or an Ask the DM answer.** A planted `SECRET-XYZZY`
   is put in:
   - module text;
   - an NPC's notes;
   - a DM secret;
   - a hidden room.

   It never appears in the feed, in the stored story the player sees, or in an Ask answer. Ask the DM is built without
   module canon. (Task 6 and Task 8 tests.)
4. **A long session.** The context passes the reset threshold. The next beat at a safe boundary (not during a fight)
   starts a fresh DM conversation rebuilt from `primer` plus a handover, and the player sees no break. (Task 5 test.)
5. **The internal tool endpoint is called from the LAN, or without the secret.** It answers 403. With the owner token
   but no secret it also answers 403. (Task 4 test.)

---

## File structure

```
src/delve/modules/text.py            unpack .dscn text, keys and entities; search
src/delve/dm/prompt/dm.md            the DM's procedure (from ttrpg2 CLAUDE.md, DM parts only, Delve names)
src/delve/dm/prompt/__init__.py      build_system_prompt(...), addenda
src/delve/dm/bridge.py               `delve dm-bridge`: stdio MCP server → Delve's internal endpoint
src/delve/dm/claude_cli/{__init__,argv,stream,resident,effort,provider}.py
src/delve/dm/tools/module.py         module_lookup, module_key
src/delve/play/table.py              beats, story, feed, the beat runner
src/delve/play/ask.py                Ask the DM
src/delve/web/routes/{play.py, internal_tools.py}
evals/ (top level)                   ported harness: trace, checks, cases, fixtures, runner
web/src/routes/Play.tsx, web/src/play/{Story,Composer,PartySidebar,MapPanel,SheetDrawer,ThinkingIndicator,AskPanel}.tsx
tests/fixtures/fake_claude.py        a fake `claude` executable that replays scripts and calls the bridge
web/e2e/play.spec.ts                 the Playwright smoke test (outside make ci)
```

---

### Task 1: Module text for the DM

**Files:**
- Create: `src/delve/modules/text.py`, `src/delve/dm/tools/module.py`, `src/delve/storage/migrations/versions/0004_module_text.py`
- Modify:
  - `src/delve/modules/importer.py` (unpack text, keys and entities on import);
  - storage (a `module_texts` repository; revisions also snapshot the text and entities);
  - `src/delve/dm/tools/host.py` (register the new tools);
  - the coverage test (move `module_lookup` and `module_key` from deferred into 2b).
- Test: `tests/modules/test_text.py`, `tests/dm/tools/test_module_tools.py`

**Interfaces:**
- `unpack(bundle) -> ModuleText(sections: list[TextSection], keys: list[Key], entities: dict[kind, list[dict]])`:
  - `TextSection(anchor, heading_path, markdown, audience, read_aloud: str | None)` comes from
    `dscn.parse_text` / `keyed_texts`;
  - `Key(node, text_anchor, npcs, encounter, assets)`.
- The importer stores this in the module's working copy. A revision snapshot includes it.
- `module_texts.search(module_id, revision, query, limit=5) -> [{anchor, heading_path, snippet}]`, through FTS5 over the
  revision's sections.
- **Tools** (both DM-only, `player_visible=False`):
  - `module_lookup(query, section="")` searches the campaign's pinned revision;
  - `module_key(room)` resolves the room like `move_party` does and returns its keyed text, read-aloud, NPCs and
    encounter.

  Without module text, both answer `{"error": "this module has no text"}`.

- [ ] **Step 1: Write failing tests:**
  - `test_import_unpacks_text_keys_entities` (on the crypt sample);
  - `test_revision_snapshots_text`;
  - `test_module_lookup_searches_pinned_revision`;
  - `test_module_key_by_room`;
  - `test_module_tools_are_dm_only`;
  - `test_map_only_module_answers_no_text`.
- [ ] **Step 2: Run, expect failure.** **Step 3: Implement.** **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Module text for the DM: module_lookup and module_key"`

### Task 2: Beats and the story

**Files:**
- Create: `src/delve/play/table.py` (storage parts and the feed builder), migration `0005_beats_story.py`, repositories
- Test: `tests/play/test_table.py`

**Interfaces:**
- **Beats:**
  - `Beat(id: beat_<12 hex>, campaign_id, number, status: open | running | done | failed | cancelled, submissions: [{player: "owner", character_ids, kind: "act", text}], opened_at, closed_at)`.
  - In this plateau there is one player, the owner, and submitting closes the beat at once. The shape already holds
    several players for plateau 4.
- **The story:** `StoryEntry(id, campaign_id, beat_id, seq, kind, payload, at)`.
  - `kind` is one of `player_act`, `dm_text`, `tool` (player-safe), `dm_error`, `recap`, `ask`, `answer`.
  - `payload` is already player-safe for every kind the player sees.
  - The raw DM stream is never stored in the story. It goes to `dm_log` (below).
- **The DM log:** `DmLogEntry(campaign_id, beat_id, raw_event_json)`, a DM-only record of the full stream for
  debugging. It's reachable only through `GET /api/campaigns/{id}/dm/log` (the DM view, host only).
- **Functions:**
  - `open_beat(storage, campaign_id, submission) -> Beat` refuses with `BeatRunning` if a beat is running.
  - `close_beat(...)`.
  - `story(storage, campaign_id, before_seq=None, limit=50) -> {entries, has_more}`.
  - `feed_entry_for(event: DMEvent, spec_lookup, pending_calls) -> StoryEntry | None`:
    - `TextDelta`s are merged into one `dm_text` per reply;
    - a `ToolCall` and its `ToolResult` together become one `tool` entry, `{name, summary, result: player_view(...)}`;
    - DM-only tools become `None`;
    - errors become `{name, error: message}`.

- [ ] **Step 1: Write failing tests:**
  - `test_one_beat_at_a_time`;
  - `test_story_paging`;
  - `test_feed_merges_text_and_pairs_tool_rows`;
  - `test_feed_drops_dm_only_tools_and_error_candidates`;
  - `test_planted_secret_not_in_story` (Review Focus 3);
  - `test_dm_log_keeps_raw_stream`.
- [ ] **Step 2: Run, expect failure.** **Step 3: Implement.** **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Beats, the story and the players' feed"`

### Task 3: The DM's prompt

**Files:**
- Create: `src/delve/dm/prompt/dm.md`, `src/delve/dm/prompt/__init__.py`
- Test: `tests/dm/test_prompt.py`

**Interfaces:**
- **`dm.md`** is the DM procedure, rewritten from ttrpg2 `CLAUDE.md`.
  - **Taken over, with the line ranges from the survey notes:**
    - Hard Procedural Constraints, with the worked anti-patterns;
    - Turn Pacing (the one-line opener);
    - Composite Tools and Batching;
    - Hidden State and the Fourth Wall;
    - Session Start;
    - the DM's Role through Lore;
    - Dice, Saves and XP;
    - Reference Lookups;
    - Narrative Detail;
    - Out-of-character.
  - **Left out:**
    - dev and test guidance, the dashboard, and running the system;
    - dungml, file paths and `Read`/`Bash` advice;
    - strongholds, rumors, hirelings and rations;
    - the "Harness Reminders" (Delve's DM has no built-in tools).
  - **Changed:**
    - tool names are Delve's (plateau 2a);
    - words follow the glossary (beat, map state, DM);
    - module lookup is `module_lookup` / `module_key`;
    - the character sheet comes from `session_primer`.
  - **Added:**
    - the rule that the DM moves the party only with `move_party`, which updates the map;
    - spell effects are ruled with `adjudicate` and conditions;
    - house rules come in `house_rules` results.
- **`build_system_prompt(ctx, *, tone, detail, rehydrate=None) -> list[str]`** returns the addenda in a fixed order, for
  the prompt cache:
  1. `dm.md`;
  2. the campaign's `always` and `behaviour` house rules;
  3. race and class house rules whose subject is in the party;
  4. tone (ttrpg2's presets and their texts);
  5. detail (ttrpg2's levels 0–3);
  6. rehydrate and handover, only after a reset.

  The output is identical for identical inputs.

- [ ] **Step 1: Write failing tests:**
  - `test_prompt_has_hard_constraints`;
  - `test_prompt_names_only_existing_tools` (every `tool_name(` or backticked tool name in `dm.md` is a `ToolHost`
    spec);
  - `test_prompt_has_no_dev_guidance` (no "pytest", "Bash", "Read(", "dashboard.py", "campaigns/");
  - `test_prompt_uses_glossary_words` (no "GM ", no "turn" meaning a beat, by phrase list);
  - `test_house_rule_addenda_and_order_are_stable`;
  - `test_identical_inputs_identical_output`.
- [ ] **Step 2: Run, expect failure.** **Step 3: Write `dm.md` and implement.** **Step 4: Run, expect them to pass.**
  Report the prompt's size in words and an estimated token count.
- [ ] **Step 5: Commit.** `git commit -m "The DM's prompt: ttrpg2's procedure with Delve's tools and words"`

### Task 4: The tool bridge

**Files:**
- Create: `src/delve/dm/bridge.py`, `src/delve/web/routes/internal_tools.py`
- Modify:
  - `src/delve/__main__.py` (`delve dm-bridge --url URL --campaign ID`, with the secret read from the environment
    variable `DELVE_BRIDGE_SECRET`);
  - `src/delve/web/app.py` (a per-process secret on `app.state`, and the routes);
  - the guard (the internal route is exempt from the owner-token check but enforces the secret and loopback);
  - `pyproject.toml` (`mcp>=1.27,<2`, plus an import-linter rule that only `delve.dm.bridge` imports `mcp`).
- Test: `tests/dm/test_bridge.py`, `tests/web/test_internal_tools.py`

**Interfaces:**
- **`GET /internal/dm/tools`** returns `[{name, description, inputSchema}]` from `ToolHost.specs()`.
- **`POST /internal/dm/{campaign_id}/call {name, args}`** runs `ToolHost.call(campaign_id, current_beat_id, …)`, where
  the current beat comes from Task 2. It needs the header `X-Delve-Bridge: <secret>` and a loopback client, and answers
  403 otherwise.
  - After a mutating tool it publishes events: `characters`, `map_state`, `combat` and `story`, so the play screen
    refreshes. This fixes the 2a gap.
  - Outside a beat it answers `{"error": "no beat is running"}`.
- **`delve dm-bridge`** is a stdio MCP server built on the `mcp` SDK's low-level `Server`, named `delve`.
  - `list_tools` fetches `/internal/dm/tools` once and caches it.
  - `call_tool` POSTs to the call endpoint and returns the result as one text content (JSON). An error result has
    `isError: true`.
  - It writes nothing to stdout except the MCP protocol.
- **Tool names** as `claude` sees them are `mcp__delve__<name>`.

- [ ] **Step 1: Write failing tests:**
  - `test_internal_requires_secret_and_loopback` (LAN, no secret, wrong secret, owner token only: each gives 403;
    Review Focus 5);
  - `test_call_runs_tool_in_current_beat`;
  - `test_mutating_call_publishes_events`;
  - `test_bridge_lists_and_calls_over_stdio`. Start `delve dm-bridge` as a subprocess against a test server and use the
    SDK's stdio client, so no `claude` is involved.
- [ ] **Step 2: Run, expect failure.** **Step 3: Implement.** **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "The DM tool bridge: stdio MCP to Delve's tool host, secret-guarded"`

### Task 5: The `claude -p` provider

**Files:**
- Create: `src/delve/dm/claude_cli/{argv,stream,resident,effort,provider}.py`, `tests/fixtures/fake_claude.py`
- Modify: the registries (register `ClaudeCliProvider` for the DM, side and conversion jobs when `claude` is on `PATH`;
  otherwise mark it unavailable), `src/delve/web/routes/health.py` (`dm` field)
- Test: `tests/dm/claude_cli/test_argv.py`, `test_stream.py`, `test_resident.py`, `test_effort.py`, `test_provider.py`

**Interfaces:**
- **Capabilities:** id `claude-cli`, models `("default", "opus", "sonnet", "haiku")`, efforts
  `(AUTO, LOW, MEDIUM, HIGH, MAX)`, default model `"default"`. The model and effort come from the Settings choice.
- **`build_argv(*, mcp_config: Path, model, effort, addenda: list[str], resume: str | None, resident: bool) -> list[str]`**:
  - it includes ttrpg2's flags from the survey notes, with `--system-prompt-snapshot off`;
  - plus the isolation flags from Global Constraints;
  - with `--append-system-prompt` set to the joined addenda.
  - The MCP config names one server, `delve`, that runs `delve dm-bridge` with `DELVE_BRIDGE_SECRET` in its env.
- **`parse_line(obj) -> list[DMEvent | SessionId]`** follows the mapping table in the survey notes:
  - the full assistant text block is dropped when deltas were seen;
  - thinking and `input_json_delta` are dropped;
  - the `mcp__delve__` prefix is stripped from tool names.
- **`Resident`** follows ttrpg2's `_Resident` behaviour:
  - it is spawned with `cwd=<data dir>/dm/<campaign>/`;
  - one turn is one stdin line, and the turn ends at the first `result`;
  - it keeps a stderr tail of 80 lines;
  - the timeout is `DELVE_DM_TURN_TIMEOUT`, default 900 s;
  - it respawns when the argv signature changes or the process dies;
  - after a cancel it drains to the `result`;
  - one turn runs at a time per campaign.
- **`auto_effort(message, ctx) -> Effort`** ports ttrpg2's heuristic: high during a fight, for long messages or marker
  words, and when two or more NPCs are named; low otherwise.
- **`ClaudeCliProvider.open(spec)`** returns a conversation that resumes the stored session id. The session id is kept
  per campaign in storage.
- **Auto-reset:**
  - It happens when the context, measured from the `result` usage, passes `DELVE_DM_RESET_TOKENS` (default 250000) at
    a safe boundary, meaning no live combat.
  - First a hidden handover turn runs, then the session is cleared.
  - The next turn's addenda get `rehydrate`, which says to call `session_primer` and continue seamlessly, plus the
    handover.
- **`side_call(prompt, choice)`** runs a one-shot `claude -p` with ttrpg2's `_AUX_ARGS`:
  - `--model haiku` by default, or the side job's model;
  - `--tools ""`, `--strict-mcp-config` and `--setting-sources ""`;
  - cwd is a temp directory, and the output is plain text.
- **`tests/fixtures/fake_claude.py`** is an executable that pretends to be `claude`:
  - it reads `FAKE_CLAUDE_SCRIPT` (a JSON list of turns);
  - it prints stream-json lines;
  - for scripted tool calls, it **really calls the MCP server from `--mcp-config`** through the SDK's stdio client, and
    prints the matching `tool_result`;
  - it can be told to crash, to hang, and to report large usage.

  Tests put it on `PATH` as `claude`.

- [ ] **Step 1: Write failing tests:**
  - `test_argv_is_isolated` (Global Constraints, exact flags);
  - `test_parse_line_mapping` (every row of the survey table, and the double text);
  - `test_resident_turn_and_respawn_on_signature_change`;
  - `test_crash_and_hang_end_beat_with_error` (Review Focus 2);
  - `test_cancel_drains`;
  - `test_auto_effort_cases`;
  - `test_reset_at_safe_boundary_rehydrates` (Review Focus 4);
  - `test_side_call_uses_aux_args`;
  - `test_missing_claude_marks_unavailable`.
- [ ] **Step 2: Run, expect failure.** **Step 3: Implement.** **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "The claude -p provider: a resident, isolated DM with auto effort and reset"`

### Task 6: The beat runner and Ask the DM

**Files:**
- Modify: `src/delve/play/table.py` (the runner), create `src/delve/play/ask.py`
- Test: `tests/play/test_runner.py`, `tests/play/test_ask.py`

**Interfaces:**
- **`run_beat(app_services, campaign_id, submission) -> Beat`** is async and runs in a background task, so it survives
  the browser going away. It:
  1. opens the beat;
  2. formats the submission for the DM. One player: the text, prefixed with the acting characters' names when not the
     whole party;
  3. opens or resumes the DM conversation through the Settings choice for the DM job, with the Task 3 addenda;
  4. streams the reply; for each event it writes to `dm_log`, turns it into a feed entry, appends that to the story and
     publishes `story`;
  5. closes the beat as `done`, or as `failed` with a `dm_error` story entry.

  `cancel_beat(campaign_id)` cancels the running beat.
- **First beat of a campaign:** the submission is preceded by a hidden "begin the session" instruction, which calls
  `session_primer` and `new_session` with a title.
- **"End the session":** the player asks for it, the DM calls `end_session(recap)`, and the recap becomes a `recap`
  story entry.
- **Ask the DM:** `ask(app_services, campaign_id, question) -> answer`.
  - It's a side call (the side job's model) with no tools. Its prompt holds:
    - the question;
    - the player-safe party summary (sheets as the characters know them);
    - up to 3 `rules_search` snippets for the question;
    - setting lookups when available (plateau 6);
    - the rule "answer from the rules, the setting and what the characters know; never from the module".
  - **No module text, no DM secrets and no NPC notes.**
  - The answer is stored as `ask` and `answer` story entries, visible only to the asker. With one player, that's the
    owner.

- [ ] **Step 1: Write failing tests**, using `FakeDM` or fake claude:
  - `test_beat_streams_story_and_closes`;
  - `test_second_act_while_running_409`;
  - `test_beat_survives_client_disconnect` (Review Focus 1);
  - `test_dm_failure_becomes_dm_error_entry`;
  - `test_first_beat_primes_session`;
  - `test_recap_entry`;
  - `test_ask_has_no_module_canon` (plant `SECRET-XYZZY` in module text, NPC notes and secrets, then assert the side
    call's prompt and the answer entry don't contain it; Review Focus 3);
  - `test_ask_includes_rules_snippets`.
- [ ] **Step 2: Run, expect failure.** **Step 3: Implement.** **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "The beat runner and Ask the DM"`

### Task 7: The play API

**Files:**
- Create: `src/delve/web/routes/play.py`
- Test: `tests/web/test_play_api.py`

**Interfaces:**
- **Routes** (organiser for now; player roles come in plateau 4):
  - **Playing:**
    - `POST /api/campaigns/{id}/act {text, characters?}` answers 202 with the beat, or 409 when a beat is running.
    - `POST /api/campaigns/{id}/ask {question}` answers with the answer.
    - `POST /api/campaigns/{id}/cancel`.
  - **Reading:**
    - `GET /api/campaigns/{id}/story?before=&limit=`.
    - `GET /api/campaigns/{id}/play/state` returns:
      - the running beat with its status, elapsed time and tool count;
      - the party digest from the player-safe `primer` subset (hp, ac, conditions, spells memorized and uncast,
        marching order);
      - the positions;
      - the combat summary without enemy hit points;
      - the session number;
      - the time of day.
  - **Settings:** `GET` and `PUT /api/campaigns/{id}/play/settings {tone, detail, effort?, model?}`. The campaign
    overrides the Settings choice (spec §5.2).
  - **The DM view:** `GET /api/campaigns/{id}/dm/log`, host only.
- **Events** go on the existing `/api/events` stream with a `campaign_id` field: `story`, `beat`, `characters`,
  `map_state` and `combat`.

- [ ] **Step 1: Write failing tests:**
  - `test_act_202_then_story_entries`;
  - `test_act_409_while_running`;
  - `test_story_paging_after_reload` (Review Focus 1);
  - `test_play_state_hides_enemy_hp`;
  - `test_settings_override`;
  - `test_dm_log_is_dm_view_only`.
- [ ] **Step 2: Run, expect failure.** **Step 3: Implement.** **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "The play API"`

### Task 8: The play screen

**Files:**
- Create: `web/src/routes/Play.tsx` (replacing the placeholder), `web/src/play/*.tsx`
- Modify: `web/src/i18n/{en,nl}.json`
- Test: `web/src/play/*.test.tsx`

**Interfaces:**
- **`/play/:campaignId`**, plus `/play` to pick a campaign. The layout is for laptop and tablet:
  - **Story**, in the centre:
    - Markdown rendered after escaping (ttrpg2's approach);
    - read-aloud blockquotes styled apart;
    - tool rows collapsed to a one-line summary;
    - `dm_error` entries in a distinct style;
    - "Load earlier" at the top.
  - **Composer**, at the bottom: a textarea, and two buttons, **Act** (Enter) and **Ask the DM** (Ctrl-Enter or the
    button). Act is disabled while a beat runs, with a Cancel button.
  - **Thinking indicator:** the time since the beat closed, and the tool count, plus a gentle "this is a big one…"
    after 30 s.
  - **Party sidebar:** portrait placeholders until plateau 6, HP bars, conditions, and the marching order with up and
    down arrows (`set_marching_order` through a host route).
  - **Map panel:** the party's fog view, through the characters' view route for the party's characters. It shows
    groups when split, and "Map offline" on a 409.
  - **Sheet drawer:** plateau 2a's `CharacterSheet`.
  - **Ask panel:** answers shown beside the story, marked "only you see this".
  - **Settings popover:** tone, detail and effort.
- **Below 900 px** the panels stack, with the story first. The full phone layout comes in plateau 4.
- **Live updates:** it uses SSE `story`, `beat`, `characters` and `map_state` filtered by campaign. After a reload it
  rebuilds from `GET story` plus `play/state`.
- **Strings:** every one is in EN and NL.

- [ ] **Step 1: Write failing tests:**
  - the story renders entries and escapes HTML;
  - Act posts and disables until `beat` is done;
  - Ask shows a private answer;
  - the thinking indicator counts tools and time;
  - a reload rebuilds from the story;
  - the map shows "Map offline" on 409;
  - marching order arrows post the new order.
- [ ] **Step 2: Run, expect failure.** **Step 3: Implement.** **Step 4: Run.** `npm test`, `typecheck` and `build`
  pass.
- [ ] **Step 5: Commit.** `git commit -m "The play screen: story, Act and Ask the DM, party, map, sheets"`

### Task 9: The eval harness, ported

**Files:**
- Create: `evals/` (top level, outside the package), ported from ttrpg2 `evals/`, and `evals/README.md`
- Modify: `Makefile` (`make evals` offline; `make evals-live` opt-in), `src/delve/__main__.py` (`delve eval [--live]`, optional)
- Test: `tests/test_evals_offline.py` (in `make ci`)

**Interfaces:**
- **Porting** follows the survey notes' "Porting to Delve" list:
  - the prefix is `mcp__delve__`;
  - the tool-name sets use Delve's names (`setup_combat`, `combat_round`, `resolve_attack`, the dice and check tools,
    `apply_damage`, …);
  - `no_state_bypass` becomes "no tool outside `mcp__delve__`" (Delve's DM has no file tools);
  - `batch` steps expand.
- **Cases:** `locked_door` and `goblin_ambush`, rewritten for Delve's tools, each with a `pass` fixture and one
  `violates-<check>` fixture per check. Two more cases, from today's riskiest areas:
  - `split_party_secret`, where a character alone in a room sees something the other mustn't;
  - `ask_the_dm_rules`.
- **Live mode (opt-in, never in tests):**
  - It runs a case through Delve's real `claude -p` provider against a temp data dir with an imported sample module.
  - It records a fixture.
  - It reports per beat: the time to first `TextDelta`, the total time, and the tool count.
  - `--compare-ttrpg2` also runs the same scripted player lines through ttrpg2's own live mode (its `evals` runner,
    read-only), so the timings and check results sit side by side. This is the eval gate of spec §6.2.

- [ ] **Step 1: Write the failing offline test.**
- [ ] **Step 2: Run, expect failure.** **Step 3: Port it.** **Step 4: `make evals` passes.** The live mode is **not**
  run by the quest.
- [ ] **Step 5: Commit.** `git commit -m "The eval harness for Delve's DM, offline in CI, live on request"`

### Task 10: End to end with a fake `claude`, plus a browser smoke test

**Files:**
- Create:
  - `tests/e2e/test_play_with_fake_claude.py`;
  - `web/e2e/play.spec.ts` and `web/playwright.config.ts`;
  - `Makefile` target `e2e-browser` (not in `ci`).
- Modify: `GUILD.md`, `README.md` (how to play, how to run the live evals), `docs/progress.md` (2b's line)

**Interfaces:**
- **The e2e test** starts `delve serve` with `tests/fixtures/fake_claude.py` as `claude` on `PATH`, imports the crypt
  sample, creates a campaign with the seeded house-rules bundle, and plays three beats:
  1. build a party, where the fake calls `create_character` through the real bridge;
  2. move into a room;
  3. a short fight.

  It asserts:
  - the story entries;
  - the player feed contains no `SECRET-XYZZY` planted in the module;
  - the map state moved;
  - every roll is logged;
  - and **the argv the fake received was isolated**.
- **`make e2e-browser`** runs Playwright (Chromium) against the same fake setup:
  1. open the play screen;
  2. Act;
  3. see the story and the thinking indicator;
  4. reload mid-beat and see the story rebuild;
  5. Ask the DM;
  6. open a sheet;
  7. take screenshots at 1280×800 and at 820×1180 (a tablet) into `web/e2e/screenshots/`.

  The quest runs it once and attaches the screenshots to its report.

- [ ] **Step 1: Write the e2e test and the Playwright spec.**
- [ ] **Step 2: Run, expect failures until everything is merged.** **Step 3: Fix the integration mismatches.**
- [ ] **Step 4: Run `make ci`, then `make e2e-browser` once.** Report the test counts and the screenshot paths.
- [ ] **Step 5: Commit.** `git commit -m "Plateau 2b: play end to end with a fake claude; browser smoke test"`

---

## Order and parallelism

- **Tasks 1, 2, 3 and 5** can start in parallel. Task 5 doesn't need the bridge, because the fake `claude` can run
  without tool calls at first.
- **Task 4** needs Task 2, for the current beat.
- **Task 6** needs Tasks 2, 3, 4 and 5. **Task 7** needs Task 6.
- **Task 8** can start from the Task 7 shapes, in parallel with Tasks 6 and 7.
- **Task 9** needs Tasks 1 and 4, for the tool names.
- **Task 10** is last.

## Done when

- `make install && make ci` passes on a fresh clone.
- The fake-`claude` e2e plays three beats through the real bridge and tool host. The feed is clean and the argv is
  isolated.
- `make e2e-browser` produces screenshots of the play screen on a laptop and on a tablet.
- **Left for the owner and Claude to do together**, not by the quest:
  - run `make evals-live` with `--compare-ttrpg2` on the owner's machine (the eval gate);
  - check the 30 s first-words guideline;
  - play the first real session.
