# Voice at the Table, the Initiative Timeline and Module Fix-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Players talk to each other through Delve's own port; the table sees a fight's initiative timeline with
ongoing actions that can be interrupted, per combatant or per side; a PC can leave the party and come back; a failed
beat can be retried; the combat fixes of Fixes 10 land; and a module can be fixed up by comments: on the PDF form, as
fix-it comments a background job acts on (kept or rejected as a new revision), and by closing the conversion's
questions box.

**Architecture:** One migration (`0022_table_voice_and_fixes`, Task 0, done) carries every schema change; the
workstreams build on its accessors in parallel, each in files only it owns. Voice is a WebSocket relay in
`delve.web` that forwards Opus frames between the seats of one campaign and stores nothing. The timeline is a per-round
record (`combat_rounds`) the combat services write, released to the table by the beat runner's hooks once the DM's
text arrives, and read per seat through one redacting route. Fix-it comments are a new conversion kind (`fixit`) whose
result is the proposed source, kept as a new revision.

**Tech Stack:** Python 3.12+, FastAPI/Starlette WebSockets (uvicorn[standard]), SQLAlchemy/Alembic on SQLite, React +
TanStack Query, WebCodecs `AudioEncoder`/`AudioDecoder` (Opus), `AudioWorklet`, Vitest, Playwright (Chromium with a fake
microphone).

**Spec:** `docs/superpowers/specs/2026-10-25-table-voice-and-fixes-design.md` (owner-approved 2026-10-25; read it
first). Words: `docs/glossary.md`. Values: `docs/data-dictionary.md`. Rules: `GUILD.md`.

## Decisions (the smith's, recorded for the chronicle)

The design's owner decisions are not reopened. These are the plan's own calls and the "my call"s it changes:

1. **Fixes 10's engine lines go to B1, not E.** Sleep in round 1 (`declare`), the natural 20 note (`_swing`), the
   Dagger choice (`_select_attack`), `adjudicate` outside a fight, `add_combatant`'s `hp_max` and the call that puts
   the module's stated stats into `setup_combat`'s notes all live in `rules/adnd2e/combat.py`, `play/combat.py` and
   `dm/tools/combat.py`, which B1 rewrites for ongoing actions. Two agents can't own one file, and Sleep in round 1 *is*
   the declaration-after-initiative rule B1 changes. E keeps what lives elsewhere: "rat, giant" (the reference's
   monster ranking), `say` for a handed-over PC, the module's stated stats (`delve.play.stated_stats`, a seam made in
   Task 0) and dm.md.
2. **A fight's rounds are stored per round** (`combat_rounds`), not in the `Combat` JSON: the timeline must show a
   round's order and outcomes after `run_round` has already moved the fight to the next round, and the release (after
   the DM's text) is play's business, not the pure rules'. The ongoing actions themselves live on the combatant, in
   the `Combat` JSON (`combats.state`), as every other combatant field does; an old fight's JSON has none and reads
   as none (B1 tests it).
3. **Retry re-runs the same beat row** (`failed` → `running`), with no schema change: its rolls keep their keys, so the
   no-re-roll rule returns the dice already rolled, and its story keeps the first attempt and the `dm_error`. The
   `dm_error` payload gains `retryable` and `resets_at`, and `retried` once it is retried.
4. **A character's leaving is `characters.departure`** (`died`, `retired`, `left`) **and `departed_at`**, not
   `left_*`: a seat already "leaves the table" (`seats.left_at`). It changes only through
   `CharacterRepository.set_departure`, never `save`, as `controller_id` changes only through the seats, so a stale
   character saved by any service can't bring a departed PC back.
5. **A conversion's closed questions are `conversions.closed`** (a JSON list of item keys), written only by
   `ConversionRepository.set_closed`; `save` never writes it, so a running job saving its progress can't reopen what an
   organiser closed. Keys: `question:<question id>` and `doubt:<index in doubts>`.
6. **The PDF form's comments travel in the upload's query string** (`comments=`, at most 2000 characters, 422 over),
   since the body must stay the raw `application/pdf` the guard streams. F1 takes `comments=` out of the access log.
7. **A fix-it job uses the conversions' one slot and queue.** Sending a comment starts its job when the slot is free;
   while another job runs (a thorough conversion may run for hours) it is `queued` like a PDF job, and starts by itself.
   Task 0 teaches `runner._restored` the `fixit` kind (`delve.conversions.fixit.restored`).
8. **Voice: the relay is a hub per campaign in the server process**, with the framing pinned below; speaking is a flag
   the sender sets from its own microphone level (*my call* in the design's "left to the builder"). A seat reconnecting
   replaces its older socket.
9. **The timeline's events carry no content:** `timeline` events say only what changed; each browser reads the timeline
   again through its own seat's route, which is where the fourth wall is kept (as the `characters` event does).
10. **A monster's ongoing action shows to the table only by its kind** ("casting a spell", "drinking a potion"), and
    only for a monster the party can see; never its spell's name (*my call* in the design: "what counts as noticed").
11. **The DM's guidance for the new tools is in their `ToolSpec` descriptions**, not dm.md, which E owns.
12. **Shared files get seams in Task 0** (empty routers registered in `app.py`, stub components mounted in `Play.tsx`,
    the beat runner's timeline hooks, the fake server's fix-it answer hook), so no workstream edits a file another owns.

Open questions for the archmage are at the end.

## Global Constraints

- Every Global Constraint of `GUILD.md` holds: ports (never 5000, 7777, 7790, 8000; default 7810), the CSP (every
  source `'self'`), JSON bodies, `Origin`/`Host` checks, `{"error": …}` errors, the import-linter contracts.
- Never touch the live Delve (port 7810, `delve.service`, `~/.local/share/delve`); every manual run uses a tmp
  `DELVE_DATA_DIR` and a free high port. Tests never run `claude` or a paid service.
- No new Python or npm dependency. Voice uses the browser's own WebCodecs; no bundled WebAssembly encoder.
- Nothing of voice is stored, logged as audio, transcribed, or sent to the DM, the story, Ask, a novel or a log.
  Joins, leaves and frame counts may be logged.
- No DM secret reaches a seat through any new route, event or WebSocket message (`delve.play.audience`,
  `redact.player_view`). Unseen monsters stay unnamed on the timeline.
- Every user-visible string is in `web/src/i18n/en.json` and `nl.json`, `nl` has every key `en` has, and each
  workstream adds keys only under its own prefix (table below), as one block in the prefix's alphabetical place.
- Desktop and phone (390 px) both work for every new screen.
- Existing campaigns, fights, beats, characters, conversions and modules keep working: the migration's defaults are
  `voice = 'allowed'`, `initiative = 'combatant'`, `departure = NULL`, `comments = ''`, `closed = NULL`.
- Commit messages end with `(table voice and fixes Task <id>)`; module docstrings cite "table voice and fixes Task <id>".
- `make ci` green before each workstream is finished; `make e2e-browser` green at the end.

## Review Focus

1. **A cross-site page opening the voice socket with the player's cookies** (CSWSH): browsers send cookies on a
   WebSocket handshake from any origin, and the guard today lets every non-HTTP scope through. A handshake whose
   `Origin` isn't the request's host, or whose `Host` isn't allowed, must be refused before `accept` →
   Task V1.1 `test_cross_origin_handshake_refused`, `test_unknown_host_handshake_refused`.
2. **A round resolved and narrated in one beat, then the page reloaded mid-narration:** the timeline must not show the
   outcomes before the `dm_text` after the `combat_round` result is stored, and must show them after a reload once it
   is → Task B2.2 `test_outcomes_hidden_until_dm_text`, `test_outcomes_after_reload`.
3. **Retry pressed twice, or by two seats at once:** one re-run, never two (the beat's one-current index answers the
   second with 409), and the DM is told what the first attempt applied → Task D1 `test_retry_twice_is_409`,
   `test_retry_prompt_lists_applied_tools`.
4. **A departed PC still covered by the host's act or the beat's fallback:** it must neither hold a beat up nor get a
   fallback line, and must not be in `play/state`'s party → Task C1 `test_departed_pc_holds_no_beat`,
   `test_departed_pc_gets_no_fallback`.
5. **Keep on a fix-it result after the module was edited in the editor:** Keep must refuse (409) and offer a re-run,
   never overwrite the editor's save → Task F2.3 `test_keep_after_edit_is_409`.

---

## Workstreams and file ownership

| Workstream | Needs | i18n prefix | Owns (besides its own new test files and its i18n keys) |
|---|---|---|---|
| **0 Foundation** (done, Jordan) | — | — | see Task 0 |
| **V1 Voice relay server** | 0 | — | `src/delve/web/voice.py` (new), `src/delve/web/routes/voice.py`, `src/delve/web/guard.py`, `src/delve/web/auth.py`, `src/delve/web/seats.py` |
| **V2 Voice client** | 0 (V1 for its browser spec) | `voice.` | `web/src/play/voice/*` (new), `web/src/play/VoiceControls.tsx`, `web/src/play/SeatIndicators.tsx` (+ test), `web/playwright.config.ts`, `web/e2e/voice.spec.ts` |
| **E Combat fixes (rest)** | 0 | — | `src/delve/storage/reference/sqlite_reference.py`, `src/delve/play/stated_stats.py`, `src/delve/dm/tools/say.py`, `src/delve/dm/prompt/dm.md`, `src/delve/play/talk.py` (if `say`'s refusal is there) |
| **B1 Initiative engine** | 0 | — | `src/delve/rules/adnd2e/combat.py`, `src/delve/rules/adnd2e/initiative.py` (new), `src/delve/play/combat.py`, `src/delve/dm/tools/combat.py`, `tests/rules/adnd2e/test_combat.py`, `tests/fixtures/scripts/first_session.golden.json` |
| **B2 The timeline** | 0, B1 (B1's `combat_rounds` rows) | `timeline.` | `src/delve/play/timeline.py`, `src/delve/web/routes/timeline.py`, `web/src/play/Timeline.tsx`, `web/src/play/timeline.ts` (new), `web/e2e/timeline.spec.ts`, `tests/e2e/fake_play_server.py` |
| **C A character leaves** | 0 | `departure.` | `src/delve/play/departures.py` (new), `src/delve/dm/tools/party.py`, `src/delve/web/routes/characters.py`, `src/delve/web/routes/play.py`, `src/delve/play/beats.py`, `src/delve/play/seats.py`, `web/src/play/PartySidebar.tsx`, `web/src/play/Composer.tsx`, `web/src/play/api.ts` |
| **D Retry** | 0 | `retry.` | `src/delve/play/table.py`, `src/delve/web/routes/retry.py`, `src/delve/dm/provider.py`, `src/delve/dm/claude_cli/*`, `web/src/play/Story.tsx`, `web/src/play/retry.ts` (new) |
| **F1+F3 PDF comments, closing the box** | 0 | `conversionNotes.` | `src/delve/conversions/runner.py`, `src/delve/conversions/thorough/*`, `src/delve/modules/books/*`, `src/delve/web/routes/conversions.py`, `src/delve/web/routes/modules.py`, `src/delve/web/app.py` (`AccessLogRedactor` only), `web/src/api.ts`, `web/src/routes/NewModule.tsx`, `web/src/module/MakingQuestions.tsx` |
| **F2 Fix-it comments** | 0 | `fixit.` | `src/delve/conversions/fixit.py`, `src/delve/web/routes/fixits.py`, `web/src/module/FixIts.tsx`, `web/src/module/FixItReview.tsx`, `web/src/module/fixits.ts` (new), `web/src/routes/ModuleDetail.tsx`, `web/src/module/ConversionsPanel.tsx`, `tests/e2e/fake_fixit.py`, `web/e2e/u-fixit.spec.ts` |
| **S Campaign page settings** | 0 (C's route for Leave/Return, V1's `disconnect_campaign`) | `tableSettings.` | `src/delve/web/routes/table_settings.py`, `web/src/routes/CampaignDetail.tsx` (+ test), `web/src/campaign/TableSettings.tsx`, `web/src/campaign/tableSettings.ts` (new) |
| **Z Wrap-up** (last, after every merge) | all | — | `GUILD.md`, `docs/backlog.md`, `docs/glossary.md`, `docs/data-dictionary.md`, `docs/identity.md` |

A file not in a workstream's list (or a new file it makes) is not that workstream's to edit; if it finds it must, it
asks the archmage. `web/src/i18n/en.json` and `nl.json` are shared, by prefix. Tests: each workstream adds new test
files of its own name; an existing test file belongs to the workstream that owns the code it tests (B1 owns
`tests/rules/adnd2e/test_combat.py`, `tests/play/test_combat*.py` and `tests/dm/tools/test_combat*.py`; C the party's;
D `tests/play/test_table*.py`; F1+F3 `tests/conversions/test_runner*.py` and `tests/web/test_conversions_api.py`).
Z writes GUILD.md's notes on the new specs and strikes the backlog items; the workstreams note what Z must write in
their report.

**Order of the browser specs** (one server, file order): `timeline.spec.ts` runs after `thorough-conversion.spec.ts`
and before `u-fixit.spec.ts`, `voice.spec.ts` after it, then `world.spec.ts`. Each makes what it needs (a campaign, a
module revision) through the API and deletes the campaigns it made, so the later specs find what they found before;
the timeline's plays the fake's fight beat, which B2 puts right after `TAVERN_REPLY` in `TURNS`.

---

## Task 0: The foundation (done)

**Owns (until merged; after it, the owners above):** `src/delve/storage/migrations/versions/0022_table_voice_and_fixes.py`,
`src/delve/storage/sqlite/tables.py`, `src/delve/storage/interfaces.py`, `src/delve/storage/sqlite/__init__.py`,
`src/delve/storage/sqlite/{campaigns,characters,conversions,combat_rounds,module_comments}_repo.py`,
`src/delve/domain/{campaigns,conversions,modules}.py`, the seams listed below, `tests/storage/contract.py`,
`tests/storage/test_migrations.py`, `tests/storage/test_migration_0022.py`, `tests/web/test_table_settings_shown.py`,
`docs/glossary.md`, `docs/data-dictionary.md`; and the new fields in the key sets of `tests/domain/test_world.py`,
`tests/web/test_campaigns_api.py` and `tests/web/test_conversions_api.py`.

### Schema: `0022_table_voice_and_fixes`, revises `0021_login_sessions`

Every `ALTER TABLE … ADD COLUMN` is plain (as `0020_accounts`), never a batch, which would copy and drop the table and
cascade the drop.

- `campaigns.voice TEXT NOT NULL DEFAULT 'allowed'` — `allowed` | `off`.
- `campaigns.initiative TEXT NOT NULL DEFAULT 'combatant'` — `combatant` | `side`.
- `characters.departure TEXT NULL` — `died` | `retired` | `left`; null while in the party.
- `characters.departed_at TEXT NULL` — when it left; null while in the party.
- `conversions.comments TEXT NOT NULL DEFAULT ''` — the PDF form's comments.
- `conversions.closed JSON NULL` — the closed item keys of its questions and doubts.
- `combat_rounds`: `combat_id TEXT NOT NULL REFERENCES combats(id) ON DELETE CASCADE`, `round INTEGER NOT NULL`,
  `campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE`, `beat_id TEXT NULL` (the tool call's beat,
  no foreign key: a call outside a beat has none), `mode TEXT NOT NULL`, `slots JSON NOT NULL`, `outcomes JSON NULL`,
  `rolled_at TEXT NOT NULL`, `resolved_at TEXT NULL`, `released_at TEXT NULL`; primary key `(combat_id, round)`; index
  `ix_combat_rounds_campaign (campaign_id, combat_id)`.
- `module_comments`: `id TEXT PK` (`mcm_…`), `module_id TEXT NOT NULL REFERENCES modules(id) ON DELETE CASCADE`,
  `text TEXT NOT NULL`, `anchor JSON NULL`, `status TEXT NOT NULL DEFAULT 'open'`, `conversion_id TEXT NULL REFERENCES
  conversions(id) ON DELETE SET NULL`, `revision INTEGER NULL`, `error TEXT NULL`, `author TEXT NOT NULL DEFAULT ''`,
  `created_at TEXT NOT NULL`, `updated_at TEXT NOT NULL`; index `ix_module_comments_module_status (module_id, status)`.
- Downgrade drops both tables and the six columns (`ALTER TABLE … DROP COLUMN`).

### Domain

- `delve.domain.campaigns`:
  - `VoiceSetting = Literal["allowed", "off"]`, `VOICE_SETTINGS = ("allowed", "off")`.
  - `InitiativeMode = Literal["combatant", "side"]`, `INITIATIVE_MODES = ("combatant", "side")`.
  - `Campaign` gains `voice: VoiceSetting = "allowed"` and `initiative: InitiativeMode = "combatant"` (last fields).
  - `Departure = Literal["died", "retired", "left"]`, `DEPARTURES = ("died", "retired", "left")`.
  - `Character` gains `departure: Departure | None = None` and `departed_at: str | None = None` (last fields).
  - `@dataclass(frozen=True) class CombatRound: combat_id: str; round: int; campaign_id: str; mode: InitiativeMode;
    slots: tuple[dict[str, Any], ...]; outcomes: dict[str, Any] | None = None; beat_id: str | None = None;
    rolled_at: str = ""; resolved_at: str | None = None; released_at: str | None = None`. The JSON shapes of `slots`
    and `outcomes` are pinned under B1.
- `delve.domain.conversions`: `ConversionKind` and `CONVERSION_KINDS` gain `"fixit"`; `Conversion` gains
  `comments: str = ""` and `closed: list[str] = field(default_factory=list)` (last fields).
- `delve.domain.modules`: `CommentStatus = Literal["open", "working", "review", "kept", "rejected", "failed",
  "closed"]`, `COMMENT_STATUSES` (that order), `COMMENT_ENDS = ("kept", "rejected", "closed")`;
  `@dataclass(frozen=True) class ModuleComment: id: str; module_id: str; text: str; anchor: dict[str, Any] | None =
  None; status: CommentStatus = "open"; conversion_id: str | None = None; revision: int | None = None; error: str |
  None = None; author: str = ""; created_at: str = ""; updated_at: str = ""`. An `anchor` is `{"kind": "map", "map"}`,
  `{"kind": "room", "map", "node"}`, `{"kind": "text", "text_id"}` or `{"kind": "entity", "entity_kind",
  "entity_id"}`.

### Accessors

- `CampaignRepository.set_voice(id: str, voice: VoiceSetting) -> Campaign` and `set_initiative(id: str, mode:
  InitiativeMode) -> Campaign`: `KeyError` for an unknown campaign, `ValueError` for a value not in the tuple.
- `CharacterRepository.set_departure(id: str, departure: Departure | None, at: str | None = None) -> Character`:
  sets both columns (`at` defaults to now when `departure` is given; both null when it is None); `KeyError`,
  `ValueError` as above. `save` keeps both as stored and answers them.
- `ConversionRepository.create(…, comments: str = "")`; `set_closed(id: str, closed: Sequence[str]) -> Conversion`
  (stored de-duplicated, in the order given; `KeyError`); `save` writes every field but `closed`, and answers the
  stored `closed`.
- `CombatRoundRepository` (`storage.combat_rounds`):
  - `put(row: CombatRound) -> CombatRound`: insert, or replace everything of `(combat_id, round)` but `released_at`,
    which only `release` sets; `KeyError` for an unknown combat.
  - `get(combat_id: str, round: int) -> CombatRound | None`; `latest(combat_id: str) -> CombatRound | None` (highest
    round); `list(combat_id: str) -> list[CombatRound]` (by round).
  - `release(combat_id: str, round: int, at: str) -> bool`: sets `released_at` once; False when already released or
    unknown.
  - `unreleased(campaign_id: str) -> list[CombatRound]`: resolved (`resolved_at` set) and not released, oldest first.
- `ModuleCommentRepository` (`storage.module_comments`):
  - `create(module_id: str, text: str, *, anchor: dict | None = None, author: str = "") -> ModuleComment` (`open`;
    `KeyError` for an unknown module).
  - `get(id: str) -> ModuleComment | None`; `list(module_id: str) -> list[ModuleComment]` (oldest first);
    `with_status(module_id: str, *statuses: CommentStatus) -> list[ModuleComment]` (oldest first);
    `for_conversion(conversion_id: str) -> list[ModuleComment]`.
  - `save(comment: ModuleComment) -> ModuleComment`: stores every field but `id`, `module_id`, `created_at`, sets
    `updated_at`; `KeyError`; `ValueError` for a status not in `COMMENT_STATUSES`.

### Exposed read-only (so no workstream edits these for them)

- `campaign_json` gains `voice` and `initiative`; `character_json` gains `departure` and `departed_at`;
  `GET …/play/state` gains `voice` and `initiative`.
- TypeScript: `Campaign` (`web/src/api.ts`) gains `voice?: "allowed" | "off"` and `initiative?: "combatant" |
  "side"`; `Character` gains `departure?: "died" | "retired" | "left" | null` and `departed_at?: string | null`;
  `PlayState` (`web/src/play/api.ts`) gains `voice?` and `initiative?`. Optional ("left out by an older server", as
  the file's other late fields), so the existing test fixtures stay valid.

### Seams (stubs a workstream fills, each owned by that workstream from Task 0's merge)

- Routers, registered in `delve.web.app`: `routes/voice.py` (V1; with `async def disconnect_campaign(app, campaign_id:
  str, reason: str = "off") -> int`, which closes every voice socket of the campaign and answers how many; 0 in the
  stub), `routes/timeline.py` (B2), `routes/retry.py` (D), `routes/fixits.py` (F2), `routes/table_settings.py` (S).
- `delve.play.timeline` (B2): `after_event(services, campaign_id: str, beat_id: str, event: DMEvent, stored:
  list[StoryEntry]) -> None`, called by `play.table._stream` after each DM event is fed; `after_beat(services, beat:
  Beat) -> None`, called when a beat closes (`_answer`'s `finally` and `_close_orphan`). Both are no-ops in the stub;
  D keeps the calls where they are.
- `delve.play.stated_stats` (E): `stated_differences(storage: Storage, campaign_id: str, monster: str, reference_row:
  Mapping[str, Any] | None) -> list[str]`, `[]` in the stub; B1's `setup_combat` puts its lines in the result's
  `notes`.
- `delve.conversions.fixit` (F2): `restored(services, conversion) -> runner._Start | None`, None in the stub;
  `runner._restored` calls it for a `fixit` job, and `runner.STEPS["fixit"] = (("fixing",),)`.
- Web: `web/src/play/voice/VoiceProvider.tsx` (V2; `{campaignId, allowed, role, children}`, rendering its children;
  wraps the play screen so voice outlives the phone's screens), `web/src/play/VoiceControls.tsx` (V2; null; mounted in the desktop play header and on the
  phone's Table screen), `web/src/play/Timeline.tsx` (B2; null; mounted above the story, both layouts).
- `tests/e2e/fake_fixit.py` (F2): `fixit_answer(prompt: str) -> str | None`, None in the stub, chained first in the
  fake server's side-call answers.

- [x] **Step 1:** Failing tests: `tests/storage/test_migration_0022.py` (`test_existing_campaign_gets_the_defaults`,
  `test_existing_fight_and_conversion_keep_working`, `test_downgrade_drops_what_0022_added`) and the contract's
  `test_campaign_voice_and_initiative`, `test_character_departure`, `test_conversion_comments_and_closed`,
  `test_combat_rounds`, `test_module_comments`; `HEAD = "0022_table_voice_and_fixes"`.
- [x] **Step 2:** `uv run pytest tests/storage -q` → FAIL.
- [x] **Step 3:** The migration, the tables, the domain, the repositories, the exposures and the seams.
- [x] **Step 4:** `make ci` → PASS. `tests/web/test_table_settings_shown.py` pins the exposures and that the beat
  runner calls `timeline.after_event`/`after_beat` (D keeps it passing).
- [x] **Step 5:** Commit `Foundation: migration 0022, its accessors and the workstreams' seams (table voice and fixes
  Task 0)`.

---

## V1. The voice relay server

**Owns:** see the table. **Interfaces consumed:** `Campaign.voice`, the identity chain (`app.state.identity`),
`storage.seats`.

### The voice protocol (pinned; V2 builds against it)

- **Route:** `WS /api/campaigns/{campaign_id}/voice`, on Delve's own port and process, `ws://` on the LAN and
  `wss://` through the tunnel (the browser picks by `location.protocol`).
- **Handshake checks, before `accept`** (a refusal closes the handshake, which the browser sees as a failed
  connection; the code is for tests and logs): `Host` not allowed → 4421; `Origin` present and not the request's host
  → 4403 (both in `RequestGuard`, which today passes every non-HTTP scope); nobody known (the same identity chain as
  HTTP: owner token cookie, account session, seat cookie, this machine) → 4401; no such campaign → 4404; not a live
  seat of the campaign (a seat that left, another table's seat) → 4403; `campaigns.voice = 'off'` → 4403.
- **After accept, close codes:** 1000 left; 4000 voice switched off (`disconnect_campaign`); 4001 the seat left the
  table; 4009 replaced by the same seat's newer socket; 4029 voice full (more than `VOICE_CAP = 8` sockets in the
  campaign); 4008 a protocol error (an unknown message type, bad JSON, a bad frame header).
- **Text frames (JSON, at most 1024 bytes, at most 10 a second per socket; over → dropped):**
  - server → client, first: `{"type": "welcome", "you": "<seat id>", "slot": <0-255>, "talk": <bool>, "peers":
    [<peer>], "limits": {"frame_bytes": 1024, "frames_per_s": 60, "bytes_per_s": 8000}}`. `talk` is false for an
    observer: the server drops its audio.
  - `<peer>` is `{"seat_id", "name", "slot", "talk", "muted", "listening_only"}`; `name` is the seat's name.
  - server → clients: `{"type": "peer", …<peer>}` on a join or a state change; `{"type": "left", "seat_id", "slot"}`;
    `{"type": "bye", "reason": "off" | "left-table" | "replaced" | "full"}` just before the server closes.
  - client → server: `{"type": "state", "muted": <bool>, "listening_only": <bool>}` (on join and on each change);
    `{"type": "ping"}` every 20 s, answered `{"type": "pong"}` (Cloudflare closes an idle socket after 100 s).
- **Binary frames, client → server:** an 8-byte header and one Opus packet: byte 0 version (`1`), byte 1 flags (bit 0
  speaking, the others 0), bytes 2–3 sequence number (uint16 big-endian, wrapping), bytes 4–7 timestamp in
  milliseconds (uint32 big-endian, wrapping), then the payload. At most `frame_bytes` (1024) in all. A frame from a
  socket that is muted, listening only or an observer's is dropped, as is one over the rate budget (a token bucket:
  60 frames a second and 8000 bytes a second, bursts of twice that). A bad header (version ≠ 1, under 9 bytes) closes
  with 4008.
- **Binary frames, server → client:** one byte, the sender's `slot`, then the sender's frame exactly as received.
  Never sent back to the sender.
- **The codec** (V2's side, pinned so V1's tests can carry real-shaped frames): Opus, mono, 48 kHz, 20 ms frames,
  24 kbit/s (`AudioEncoder.configure({codec: "opus", sampleRate: 48000, numberOfChannels: 1, bitrate: 24000, opus:
  {frameDuration: 20000}})`).
- **Nothing is recorded:** the hub holds no frame after forwarding it. It logs joins, leaves and, at leave, the
  socket's frame and byte counts (`voice: seat_… left cmp_… after 1234 frames`).

### Task V1.1: The guard for WebSockets

**Files:** Modify `src/delve/web/guard.py`. Test `tests/web/test_guard_websocket.py`.

**Interfaces:** Produces `RequestGuard` refusing a `websocket` scope's handshake by sending `{"type":
"websocket.close", "code": 4421 | 4403}` before the app sees it. The CSP and nosniff headers stay HTTP-only.

- [x] **Step 1: Failing tests** (Starlette `TestClient.websocket_connect`, an app with a `/ws` echo route behind the
  guard): `test_cross_origin_handshake_refused` (`Origin: http://evil.example` → `WebSocketDisconnect` with code
  4403), `test_unknown_host_handshake_refused` (`Host: evil.example` → 4421), `test_same_origin_handshake_accepted`,
  `test_no_origin_handshake_accepted` (as HTTP: a non-browser client sends none).
- [x] **Step 2:** `uv run pytest tests/web/test_guard_websocket.py -q` → FAIL.
- [x] **Step 3:** Implement `RequestGuard.__call__` for `scope["type"] == "websocket"` with the Host and Origin parts of
  `refusal` (factor them into `handshake_refusal(scope) -> int | None`).
- [x] **Step 4:** Run → PASS; `uv run pytest tests/web/test_guard.py -q` still PASS.
- [x] **Step 5:** Commit `Voice: the guard checks a WebSocket's Host and Origin (table voice and fixes Task V1.1)`.

### Task V1.2: The hub and the route

**Files:** Create `src/delve/web/voice.py`; modify `src/delve/web/routes/voice.py`, `src/delve/web/auth.py` (an
identify for an `HTTPConnection`, if the chain takes only a `Request`), `src/delve/web/seats.py` (a seat lookup for a
connection, if needed). Test `tests/web/test_voice_relay.py`.

**Interfaces:**
- `delve.web.voice`: `VOICE_CAP = 8`, `FRAME_BYTES = 1024`, `FRAMES_PER_S = 60`, `BYTES_PER_S = 8000`,
  `TEXT_BYTES = 1024`, `TEXT_PER_S = 10`; `def parse_frame(data: bytes) -> Frame` (`Frame(version, speaking: bool,
  seq: int, ts_ms: int, payload: bytes)`; `ValueError` for a bad header); `class VoiceHub` with `async def join(self,
  campaign_id, seat: Seat, socket) -> Member`, `async def leave(self, member) -> None`, `async def relay(self, member,
  data: bytes) -> int` (how many it was sent to), `async def set_state(self, member, muted: bool, listening_only:
  bool) -> None`, `async def close_campaign(self, campaign_id, code: int, reason: str) -> int`, `def members(self,
  campaign_id) -> list[Member]`; `def hub(app) -> VoiceHub` (made on first use, on `app.state.voice`).
- `routes.voice.disconnect_campaign(app, campaign_id, reason="off") -> int` → `hub(app).close_campaign(campaign_id,
  4000, reason)`.
- Every 20 s (on a `ping`, or a timer) the route checks the seat is still live (`seats.get(...).left_at is None`) and
  the campaign's voice still allowed; else closes with 4001 or 4000.

- [x] **Step 1: Failing tests:** `test_two_seats_hear_each_other` (host and player join; the player's frame reaches
  the host prefixed by the player's slot, byte for byte, and not the player), `test_observer_is_listen_only` (welcome
  `talk: false`; its frames reach nobody), `test_muted_frames_dropped`, `test_voice_off_refuses_join` (4403),
  `test_disconnect_campaign_closes_everyone` (both get `bye` `off` and close 4000), `test_left_seat_refused` (4403),
  `test_other_tables_seat_refused`, `test_ninth_socket_is_full` (4029), `test_same_seat_replaces_its_socket` (old gets
  4009), `test_oversized_frame_dropped` (1025 bytes → nobody gets it, the socket stays), `test_rate_limited_frames_dropped`
  (200 frames at once → at most the bucket's burst forwarded), `test_bad_header_closes_4008`,
  `test_peer_and_left_messages`, `test_nothing_of_audio_is_logged` (`caplog` holds no payload bytes, only counts).
- [x] **Step 2:** `uv run pytest tests/web/test_voice_relay.py -q` → FAIL.
- [x] **Step 3:** Implement `delve.web.voice` and the route (an `asyncio.Lock` per campaign around the member set;
  forwarding with `send_bytes` to each other member, a slow member's send not blocking the rest: one bounded
  `asyncio.Queue(maxsize=50)` per member, dropping the oldest when full).
- [x] **Step 4:** Run → PASS; `uv run lint-imports` → kept.
- [x] **Step 5:** Commit `Voice: the relay, a hub per campaign on Delve's own port (table voice and fixes Task V1.2)`.

### Task V1.3: Through `delve serve`

**Files:** Test `tests/e2e/test_voice_through_serve.py`.

- [x] **Step 1: Failing test** `test_voice_through_serve`: start `delve serve` on a free high port with a tmp data dir
  (as `tests/test_serve.py` does), join two seats over a real socket with the `websockets` client that
  `uvicorn[standard]` installs, relay one frame, and check a `Origin: http://evil.example` handshake fails.
- [x] **Step 2–4:** Run → FAIL, fix what the real server needs (none expected), → PASS.
- [x] **Step 5:** Commit `Voice: relayed through delve serve (table voice and fixes Task V1.3)`.

---

## V2. The voice client

**Owns:** see the table. **Consumes:** the protocol above; `PlayState.voice`; the seats list.

### Task V2.1: Framing, encoder and jitter buffer

**Files:** Create `web/src/play/voice/framing.ts`, `web/src/play/voice/encoder.ts`,
`web/src/play/voice/jitter.worklet.ts`, `web/src/play/voice/player.ts`, `web/src/play/voice/support.ts`, tests beside
them.

**Interfaces:**
- `framing.ts`: `encodeFrame(f: {speaking: boolean; seq: number; tsMs: number; payload: Uint8Array}): ArrayBuffer`;
  `decodeRelayed(data: ArrayBuffer): {slot: number; speaking: boolean; seq: number; tsMs: number; payload:
  Uint8Array}` (throws on version ≠ 1 or under 10 bytes).
- `support.ts`: `voiceSupport(): "talk" | "listen" | "none"` — `talk` when `AudioEncoder` and `isConfigSupported` of
  the Opus config are true and `navigator.mediaDevices?.getUserMedia` exists; `listen` when `AudioDecoder` supports
  Opus and `AudioWorkletNode` exists; else `none` (the button says why: `voice.unsupported`).
- `encoder.ts`: `startMicrophone(onFrame: (frame: ArrayBuffer) => void): Promise<Microphone>` with
  `getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}})`, a
  `MediaStreamTrackProcessor` (or an `AudioWorklet` tap where that is missing) into `AudioEncoder` with the pinned
  config, the speaking flag from the RMS level over the last 200 ms (speaking above −45 dBFS, with 300 ms hang);
  `Microphone` has `setMuted(m: boolean)` (disables the track) and `stop()`.
- `jitter.worklet.ts`: an `AudioWorkletProcessor` registered as `"delve-jitter"`, one input buffer per slot, target
  delay 60 ms, at most 200 ms (older samples dropped), mixing every slot into its output.
- `player.ts`: `startPlayer(): Promise<Player>`; `Player.push(relayed)` decodes with one `AudioDecoder` per slot and
  posts PCM to the worklet; `Player.stop()`.

- [x] **Step 1: Failing tests** (Vitest): `framing.test.ts` (`encodeFrame`/`decodeRelayed` round trip, big-endian
  bytes for seq 0x0102 and ts 0x01020304, refusing version 2), `support.test.ts` (each of the three answers with
  stubbed globals), `jitter.test.ts` (the processor's buffer logic as a plain class `JitterBuffer`, exported for the
  test: 60 ms target, drops past 200 ms, mixes two slots by sum with clipping).
- [x] **Step 2–4:** `npm --prefix web test -- voice` → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Voice: framing, the Opus encoder and a jitter buffer (table voice and fixes Task V2.1)`.

### Task V2.2: Join, leave, mute and who is speaking

**Files:** Modify `web/src/play/voice/VoiceProvider.tsx`, `web/src/play/VoiceControls.tsx`,
`web/src/play/SeatIndicators.tsx`; create `web/src/play/voice/useVoice.ts`; tests `VoiceControls.test.tsx`,
`SeatIndicators.test.tsx`.

**Interfaces:**
- `VoiceProvider({campaignId, allowed, role, children})` (`role` the seat's: an observer only listens) holds one `VoiceState`: `{status: "off" | "joining" | "in" |
  "error"; mode: "talk" | "listening-only"; muted: boolean; peers: Record<seatId, {slot, name, talk, muted,
  listening_only, speaking: boolean}>; join(): Promise<void>; leave(): void; setMuted(m): void}` through
  `useVoiceState()`. It asks for the microphone only inside `join()`. A refused or missing microphone joins
  listening only. Unmount (leaving the play screen, a reload) leaves. A dropped socket reconnects after 1 s, 2 s, 5 s,
  then shows `voice.lost` with a Join again button. `allowed` false (the campaign's voice off, or a `bye` `off`) leaves
  and hides the controls.
- `VoiceControls()`: Join voice (`voice.join`) / Leave voice (`voice.leave`), Mute / Unmute (`voice.mute`,
  `voice.unmute`), the "listening only" note (`voice.listeningOnly`), and why it can't (`voice.unsupported`).
- `SeatIndicators` marks each seat in voice (`voice.inVoice`), muted (`voice.muted`), listening only, and speaking
  (a ring that lights while `speaking`), with `aria-label`s from those keys.

- [x] **Step 1: Failing tests:** `test no microphone is asked before Join` (a spy on `getUserMedia` is not called on
  render), `test refused microphone joins listening only`, `test mute toggles the track`, `test voice off hides the
  button`, `test speaking ring follows the flag`, `test phone table screen shows the controls` (390 px).
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Voice: Join voice, mute, listening only and who is speaking (table voice and fixes Task V2.2)`.

### Task V2.3: The browser spec

**Files:** Modify `web/playwright.config.ts` (Chromium `launchOptions.args`: `--use-fake-device-for-media-stream`,
`--use-fake-ui-for-media-stream`); create `web/e2e/voice.spec.ts`.

- [x] **Step 1: Write** `voice.spec.ts`: the host makes a campaign of the crypt through the API and an invite; a player
  account (a username of its own) joins it in a second context whose `getUserMedia` an init script makes reject (the
  listen-only seat); both open the play screen and press Join voice; the host's seat lights as speaking on the
  player's screen; a `page.on("websocket")` listener on the player's page counts binary frames received (more than
  20 in 2 s); the player's indicator says listening only; the host switches voice off on the campaign page (S's
  control) and both lose the controls; screenshots `voice-desktop.png`, `voice-phone.png`; the campaign is deleted.
- [x] **Step 2:** `make e2e-browser` → the spec PASSES (after V1 and S are merged).
- [x] **Step 3:** Commit `Voice: the two-seat browser spec (table voice and fixes Task V2.3)`.

---

## E. The combat fixes that live outside the engine

**Owns:** see the table.

### Task E1: "rat, giant" finds the giant rat

**Files:** Modify `src/delve/storage/reference/sqlite_reference.py`. Test `tests/storage/test_reference_monsters.py`.

- [x] **Step 1: Failing tests** on `real_reference_db`: `test_rat_giant_is_the_giant_rat` (`monster("rat, giant")[0]
  ["name"]` is the giant rat's row), `test_giant_rat_too`, `test_exact_name_first`, `test_closer_name_first` (of two
  rows matching every word, the one whose name has fewer other words first).
- [x] **Step 2–4:** Run → FAIL → fix the ranking (the "every word" fallback ranks by the words left over, and an
  inverted name, "rat, giant", is tried as "giant rat" before any substring) → PASS.
- [x] **Step 5:** Commit `Combat: "rat, giant" finds the giant rat (table voice and fixes Task E1)`.

### Task E2: The module's stated stats

**Files:** Modify `src/delve/play/stated_stats.py`, `src/delve/dm/prompt/dm.md`. Test `tests/play/test_stated_stats.py`.

**Interfaces:** `stated_differences(storage, campaign_id, monster, reference_row) -> list[str]`: reads the campaign's
pinned revision's encounter entities and keyed texts for a stat line naming `monster` (`AC 5`, `HD 2`, `hp 12`,
`THAC0 19`, `MV 6`, `Dmg 1d8`), and answers one line per stat that differs from `reference_row`: `"The module gives
Zombie AC 5 (the reference says 8): pass ac=5 in setup_combat's monsters."`. `[]` when none differ or none is
stated. dm.md asks for the module's numbers when the module states them.

- [x] **Step 1: Failing tests:** `test_zombie_ac_differs` (a module with "Zombies (4): AC 5, HD 2" → the AC line),
  `test_same_stats_say_nothing`, `test_no_stat_line_says_nothing`, `test_dm_md_asks_for_the_modules_numbers`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Combat: the module's stated stats against the reference's (table voice and fixes Task E2)`.

### Task E3: `say` for a PC handed to the DM

**Files:** Modify `src/delve/dm/tools/say.py` (and `src/delve/play/talk.py` if the refusal is there). Test
`tests/dm/tools/test_say_handed.py`.

- [x] **Step 1: Failing test** `test_say_for_a_handed_pc`: a PC whose seat handed it to the DM (no controller, or the
  host's handing in the beat's submissions) speaks through `say` → a `say` entry, not a refusal.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Combat: say works for a PC the player handed over (table voice and fixes Task E3)`.

---

## B1. The initiative engine

**Owns:** see the table. **Consumes:** `Campaign.initiative`, `storage.combat_rounds`, `stated_differences`.

### What B1 records (pinned; B2 reads it)

`storage.combat_rounds.put(CombatRound(...))` once a round's initiative is rolled (by `setup_combat` for round 1, or
`combat_round`), and again with `outcomes` and `resolved_at` once the round is resolved (in the same call for
`combat_round`). `beat_id` is `ctx.beat`. `slots` is the DM's truth, in initiative order; B2 redacts it:

```json
{"id": "mon_1", "name": "Goblin 1", "side": "enemy", "character_id": null, "node": "n12", "count": 7,
 "group": "enemy" ,
 "ongoing": null}
```

`group` is the side's group in `side` mode (`"party"` for party and allies, `"enemy"`), else the combatant's id.
`count` is the initiative count it acts on (in `side` mode its side's roll plus its own modifiers, as PHB ch. 9's
group initiative counts them). `ongoing`, when the combatant is busy:

```json
{"kind": "spell", "what": "Sleep", "started_round": 2, "started_count": 1, "completes_round": 2,
 "completes_count": 7, "state": "ongoing", "reason": null}
```

`kind` is `spell`, `scroll`, `potion`, `item` or `other`; `state` is `ongoing`, `completed` or `interrupted`;
`reason` is why it broke ("Mirela was hit"). `outcomes`:

```json
{"acted": ["chr_x", "mon_1"], "downed": ["mon_2"], "dead": [], "fled": [],
 "completed": [{"id": "chr_x", "what": "Sleep"}],
 "interrupted": [{"id": "chr_y", "what": "Cure light wounds", "reason": "Tansy was hit"}]}
```

### Task B1.1: Ongoing actions and their interruption

**Files:** Create `src/delve/rules/adnd2e/initiative.py`; modify `src/delve/rules/adnd2e/combat.py`. Tests
`tests/rules/adnd2e/test_initiative.py`, `tests/rules/adnd2e/test_combat.py`.

**Interfaces:**
- `initiative.py`: `ITEM_MODIFIERS = {"potion": 4, "ring": 3, "rod": 1, "stave": 2, "wand": 3, "item": 3}` (PHB ch. 9,
  Table 56's magical items; a scroll takes its spell's casting time) — verify against the reference's PHB text
  (`rules_lookup`) and cite the table by name in the docstring; where the reference differs, the reference wins and
  the plan's note is corrected in the report. `@dataclass(frozen=True) class Ongoing` with the fields of the JSON
  above; `def duration(kind, what, reference) -> tuple[int, int]` (the rounds it spans after this one, and the count
  it completes on: a casting time of 1–9 segments completes this round at that count; "1 round" at count 10; "N
  rounds" N−1 rounds later at count 10; a potion at count +4 and works at the end of the round, per PHB ch. 9).
- `Combatant.ongoing: Ongoing | None = None` replaces the per-round `casting` (kept readable from old JSON: a
  `casting` string and the `casting` condition read as an ongoing spell completing this round).
- `declare` takes `{"caster", "spell"}`, `{"actor", "item": "potion of healing", "kind": "potion"}` and `{"actor",
  "action", "rounds": n}` (another long action); a declaration after the round's initiative is rolled (round 1 after
  `setup_combat`) is accepted and re-places the declarer at its new count (the Sleep in round 1 fix), with one hint
  that says so.
- `_end_round` keeps an ongoing action that runs past the round (`completes_round > round`) and clears completed and
  interrupted ones; damage (`_hurt`) or a failed saving throw before `completes_round`/`completes_count` interrupts a
  spell or scroll, across rounds; `def interrupt(combat, id, reason) -> tuple[Combat, dict]` breaks any ongoing action
  (`CombatError` when it has none).
- `status()` gives each combatant's `ongoing`. `RoundResult.to_dict()` gives `outcomes` in the shape above.
- `_swing`'s note says `"Natural 20 — an automatic hit."` (not a critical hit).
- `_select_attack`: in melee, a name that exactly or as a whole word matches a block whose name is not marked thrown
  or missile wins over a "(thrown)" one ("Dagger" → the melee dagger).

- [x] **Step 1: Failing tests:** `test_sleep_declared_in_round_one_after_setup`, `test_late_declaration_moves_the_count`,
  `test_two_round_spell_carries_over`, `test_damage_in_the_second_round_interrupts`, `test_potion_completes_at_plus_4`,
  `test_interrupt_names_why`, `test_interrupt_without_ongoing_refused`, `test_old_fight_json_reads`
  (a `Combat` JSON of 0021 with `casting: "Sleep"` reads as an ongoing spell), `test_natural_20_is_automatic_hit`,
  `test_dagger_in_melee_is_the_melee_dagger`, `test_status_shows_ongoing`.
- [x] **Step 2:** `uv run pytest tests/rules/adnd2e -q` → FAIL.
- [x] **Step 3:** Implement.
- [x] **Step 4:** Run → PASS.
- [x] **Step 5:** Commit `Combat: ongoing actions carry over rounds and can be interrupted (table voice and fixes Task B1.1)`.

### Task B1.2: Initiative per side

**Files:** Modify `src/delve/rules/adnd2e/initiative.py`, `src/delve/rules/adnd2e/combat.py`. Tests as B1.1.

**Interfaces:** `run_round(…, mode: InitiativeMode = "combatant")` and `roll_initiative(…, mode=…)`. `side`: one d10 per
side (`purpose="initiative"`, `actor="side:party"` / `"side:enemy"`), party and allies one side; the lower acts first;
ties act simultaneously (PHB ch. 9, the standard procedure). An individual's casting time, weapon speed or item
modifier is added to its side's roll (PHB ch. 9's group initiative), so a long spell still lands later; cite the
section names B1 implements in `initiative.py`'s docstring. `combatant`: as today. The round's mode is the campaign's
at the round's start; a change takes effect at the next round.

- [x] **Step 1: Failing tests:** `test_side_mode_rolls_two_dice`, `test_side_tie_is_simultaneous`,
  `test_side_mode_casting_time_adds_to_the_side_roll`, `test_mode_change_takes_effect_next_round`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Combat: initiative per side, the PHB's standard method (table voice and fixes Task B1.2)`.

### Task B1.3: The tools, the rounds' records and the rest of Fixes 10

**Files:** Modify `src/delve/play/combat.py`, `src/delve/dm/tools/combat.py`. Tests `tests/play/test_combat_rounds.py`,
`tests/dm/tools/test_interrupt.py`; regenerate `tests/fixtures/scripts/first_session.golden.json` if it moves
(`DELVE_REGOLDEN=1`, then review the diff).

**Interfaces:**
- `play.combat.interrupt(ctx, ref: str, reason: str) -> dict` and the tool `interrupt` (`combatant`, `reason`;
  mutates; player-visible; its result splits `perceived` "Mirela was hit; Sleep is lost" from `dm_only` nothing).
- `combat_round` and `setup_combat` read `ctx.storage.campaigns.get(ctx.campaign_id).initiative`, and write the
  round's `CombatRound` (shape above).
- `setup_combat`'s result `notes` holds `stated_differences(...)` for each group; its `ToolSpec` description says to
  pass the module's numbers in `monsters[].ac/hp/thac0` when the notes give them.
- `adjudicate` works outside a fight (a ruling with no combatants; its effects apply to characters by name).
- `add_combatant` takes `hp_max` (defaults to `hp`).
- `combat_status` shows each combatant's `ongoing`; the tool descriptions of `combat_round`, `combat_status` and
  `interrupt` tell the DM about ongoing actions and interruption (Decision 11).

- [x] **Step 1: Failing tests:** `test_combat_round_records_the_round` (the row's slots and outcomes as pinned),
  `test_setup_records_round_one_unresolved`, `test_interrupt_tool_perceived`, `test_interrupt_passes_fourth_wall`
  (added to `tests/dm/tools/test_fourth_wall.py`'s tool list), `test_adjudicate_outside_a_fight`,
  `test_add_combatant_hp_max`, `test_setup_notes_hold_stated_differences` (with `stated_differences` monkeypatched),
  `test_side_mode_from_the_campaign`.
- [x] **Step 2–4:** `uv run pytest tests/play tests/dm -q` → FAIL → implement → PASS; `uv run pytest
  tests/e2e/test_scripted_session.py tests/e2e/test_tool_timing.py -q` → PASS.
- [x] **Step 5:** Commit `Combat: interrupt, the rounds' records and the rest of Fixes 10 (table voice and fixes Task B1.3)`.

---

## B2. The timeline

**Owns:** see the table. **Consumes:** `storage.combat_rounds` (B1 writes), the `after_event`/`after_beat` hooks,
`storage.combats.live`, the map state.

### The read route and the events (pinned)

`GET /api/campaigns/{campaign_id}/timeline` (`TableSeat`) answers `{"fight": null}` when there is no live fight, for an
observer, and for a player none of whose characters fights (as `play/state`'s `combat`); else:

```json
{"fight": {"combat_id": "cbt_…", "round": 3, "mode": "combatant", "released": false, "max_count": 12,
  "slots": [
    {"key": "chr_x", "name": "Mirela", "side": "party", "character_id": "chr_x", "count": 7,
     "state": "waiting", "ongoing": {"kind": "spell", "what": "Sleep", "from": 1, "to": 7, "next_round": false,
                                     "state": "ongoing", "reason": null}},
    {"key": "unseen-1", "name": null, "side": "enemy", "character_id": null, "count": 4,
     "state": "waiting", "ongoing": null}]}}
```

- `state` is `waiting` or `acting` while `released` is false (`acting` only for the slots at the lowest count no
  outcome has passed: none, as a round resolves in one call, so `waiting`), and `acted`, `down`, `dead` or `fled` once
  released; a combatant down or dead from an earlier round is `down`/`dead` throughout.
- An enemy is named (and keyed by its id) only when the party can see it: the fight has no map, or its `node` is a
  node the party's characters have discovered on the fight's map (`delve.maps.state`, merged for the party); otherwise
  `name: null` and `key: "unseen-<n>"`, numbered by order of appearance.
- An enemy's `ongoing` shows only for a named enemy, and only `kind`, `from`, `to`, `next_round`, `state`: `what` and
  `reason` are null (Decision 10). A party member's shows whole.
- No hit points, armour class, THAC0 or declared action of an enemy in any shape.
- `max_count` is the highest count among the slots and their `to`, at least 10.

Events (`scope="table"`, `campaign_id`, no `audience`): `timeline` with `{"campaign_id", "combat_id", "round",
"change": "initiative" | "outcomes" | "ended"}`; the browser reads the route again.

### Task B2.1: The redacted timeline

**Files:** Modify `src/delve/play/timeline.py`, `src/delve/web/routes/timeline.py`. Tests `tests/play/test_timeline.py`,
`tests/web/test_timeline_api.py`.

**Interfaces:** `timeline_for(storage, campaign_id: str, seat: Seat) -> dict` (the answer above); the route calls it in a
worker thread.

- [x] **Step 1: Failing tests:** `test_no_fight_is_null`, `test_observer_gets_null`, `test_unseen_monster_unnamed`
  (`SECRET-XYZZY` as the monster's name and as its declared action never appear in the JSON), `test_seen_monster_named`,
  `test_monster_spell_shows_only_its_kind`, `test_party_spell_shows_whole`, `test_no_enemy_hp_anywhere`,
  `test_side_mode_groups_at_the_side_count`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Timeline: the fight's order and ongoing actions, per seat (table voice and fixes Task B2.1)`.

### Task B2.2: Released after the DM's text

**Files:** Modify `src/delve/play/timeline.py`. Test `tests/play/test_timeline_release.py`.

**Interfaces:** `after_event`: a `ToolResult` of `setup_combat` or `combat_round` publishes `initiative`; a stored
`dm_text` entry (in `stored`) after such a result releases every `unreleased(campaign_id)` round
(`combat_rounds.release`) and publishes `outcomes`; a `ToolResult` of `end_combat` publishes `ended`. `after_beat`
releases what is left (a beat that ended with no narration after its last round) and publishes `outcomes`.

- [x] **Step 1: Failing tests:** `test_outcomes_hidden_until_dm_text`, `test_outcomes_after_reload` (a fresh
  `timeline_for` after the release shows them), `test_beat_end_releases_the_rest`, `test_orphan_beat_releases`,
  `test_events_carry_no_names`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Timeline: a round's outcomes once the DM has told them (table voice and fixes Task B2.2)`.

### Task B2.3: The strip, desktop and phone

**Files:** Modify `web/src/play/Timeline.tsx`; create `web/src/play/timeline.ts`; test `web/src/play/Timeline.test.tsx`.

**Interfaces:** `Timeline({campaignId, phone})` reads the route (`["timeline", campaignId]`, refetched on `timeline`,
`story` and `beat` events), draws an axis of counts 1…`max_count`, each slot at its count (portrait or token, its name
or `timeline.unseen`, side by colour: the looks' party and enemy colours), slots on one count stacked together, an
ongoing span from `from` to `to` ("casting *Sleep*", `timeline.casting`), running off the end with
`timeline.nextRound`, completed (`timeline.completed`) and interrupted (`timeline.interrupted`) marks, the round
(`timeline.round`), and acted/down/dead/fled marks. On a phone: one thin row at the top of the story, scrolling
sideways. Nothing renders without a fight.

- [x] **Step 1: Failing tests:** `renders nothing without a fight`, `stacks two slots on one count`, `draws a span to its
  count`, `runs a long span off the end`, `marks interrupted`, `unseen enemy shows no name`, `phone row scrolls sideways`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Timeline: the strip above the story (table voice and fixes Task B2.3)`.

### Task B2.4: The fight in the browser

**Files:** Modify `tests/e2e/fake_play_server.py` (the fight turn after `TAVERN_REPLY`); create
`web/e2e/timeline.spec.ts`.

- [x] **Step 1: Write** the fight turn: `create_character` Mirela (a mage with Sleep) and Tansy, `setup_combat` against
  two goblins with Mirela casting Sleep, a `{"sleep": THINKING_S}` (the strip shows the span before any narration),
  `interrupt` Mirela with the reason "Mirela was hit" (the real dice can't be scripted through the bridge, so the
  interruption is the DM's ruling), a `combat_round`, then the narration. The spec makes its own campaign,
  acts once, sees the strip with Mirela's span before the narration, then the interrupted mark after it, on desktop
  and at 390 px (`timeline-desktop.png`, `timeline-phone.png`), and deletes its campaign.
- [x] **Step 2:** `make e2e-browser` → PASS (the later specs too: the turn is consumed only by this spec).
- [x] **Step 3:** Commit `Timeline: the fake DM's fight in the browser (table voice and fixes Task B2.4)`.

---

## C. A character leaves the party

**Owns:** see the table. **Consumes:** `CharacterRepository.set_departure`, `play.combat.remove_combatant`.

### Task C1: The service and the beats

**Files:** Create `src/delve/play/departures.py`; modify `src/delve/play/beats.py`, `src/delve/play/seats.py` (where
the host's covered PCs and the fallback's PCs are counted). Tests `tests/play/test_departures.py`.

**Interfaces:** `leave_party(ctx, ref: str, departure: Departure) -> dict` (in one transaction: `set_departure`, the
character leaves the live fight with `remove_combatant(ctx, id, "left the party")` when it fights, a `departure` event
in the campaign's log; `PlayError` for an NPC or one already departed) and `rejoin_party(ctx, ref: str) -> dict`
(`set_departure(id, None)`; `PlayError` when it hasn't left). Departed PCs count for neither the host's act, the
beat's waiting, nor the fallback.

- [x] **Step 1: Failing tests:** `test_leave_keeps_the_sheet_and_story`, `test_leave_during_a_fight_leaves_the_fight`,
  `test_rejoin_undoes`, `test_npc_cannot_leave`, `test_departed_pc_holds_no_beat`, `test_departed_pc_gets_no_fallback`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Party: a character leaves the party, and comes back (table voice and fixes Task C1)`.

### Task C2: The DM's tools and the routes

**Files:** Modify `src/delve/dm/tools/party.py`, `src/delve/web/routes/characters.py`, `src/delve/web/routes/play.py`.
Tests `tests/dm/tools/test_party_departure.py`, `tests/web/test_departure_api.py`.

**Interfaces:**
- Tools `leave_party` (`character`, `reason`: one of `died`, `retired`, `left`) and `rejoin_party` (`character`):
  mutate, player-visible; `party` lists departed PCs apart (`departed: [{id, name, departure}]`).
- `PUT /api/campaigns/{campaign_id}/characters/{character_id}/departure` (`Organiser`), body `{"departure": "died" |
  "retired" | "left" | null}` → 200 `character_json`; 422 for another value, 409 for an NPC; publishes `characters`.
- `play/state`'s `party` (and `marching_order`) leave departed PCs out; `departed: [{id, name, departure}]` beside it.

- [x] **Step 1: Failing tests:** `test_leave_party_tool`, `test_rejoin_party_tool`, `test_party_lists_departed_apart`,
  `test_departure_route_organiser_only` (a player seat → 403), `test_play_state_leaves_departed_out`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Party: leave_party, rejoin_party and the departure route (table voice and fixes Task C2)`.

### Task C3: The sidebar and Acting for

**Files:** Modify `web/src/play/PartySidebar.tsx`, `web/src/play/Composer.tsx`, `web/src/play/api.ts`; tests beside them.

**Interfaces:** `PlayState.departed?: {id, name, departure}[]`. The sidebar shows them folded under the party: one line
per reason, `departure.fallen` ("Fallen: Tansy"), `departure.retired`, `departure.left`, unfolding to the names (each
opens the sheet). Acting for never offers a departed PC.

- [x] **Step 1: Failing tests:** `folds the departed by reason`, `opens a departed PC's sheet`, `acting for leaves the
  departed out`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Party: the departed, folded under the party (table voice and fixes Task C3)`.

---

## D. Retry a failed beat

**Owns:** see the table. **Consumes:** the beat runner, the DM log.

### Task D1: Retryable beats and the retry route

**Files:** Modify `src/delve/play/table.py`, `src/delve/web/routes/retry.py`, `src/delve/dm/provider.py` and
`src/delve/dm/claude_cli/*` (only for the reset time). Tests `tests/play/test_retry.py`, `tests/web/test_retry_api.py`.

**Interfaces:**
- A `dm_error` entry's payload is `{"message", "retryable": bool, "resets_at": str | null}`: `retryable` from
  `DMError.retryable`, true for the provider's failure and for a beat closed by `_close_orphan` (a restart);
  `resets_at` the usage limit's reset time (ISO 8601) from the CLI's rate-limit event kept in `account.json`.
  Entries stored before this have no `retryable` and are not retryable.
- `retry_beat(services, campaign_id: str, beat_id: str, seat: Seat) -> Beat`: the beat must be the campaign's latest
  (highest `number`), `failed`, its last `dm_error` retryable, and no beat open or running (`BeatRunning`, 409); the
  seat is the host, a co-host, or a seat whose submission is in the beat (else `NotAllowed`, 403). It marks the
  `dm_error` entry `retried: true` (`story.put`), sets the beat `running` again with `closed_at` null, and starts it
  (`start_beat`) with the same submissions; the DM's message is the beat's message after `RETRY_NOTE`, which lists the
  mutating tool calls the first attempt made (from the beat's DM log: name and arguments) and says they are applied
  and not to be repeated.
- `GET /api/campaigns/{campaign_id}/retry` (`TableSeat`) → `{"beat_id": str | null, "may_retry": bool, "resets_at":
  str | null}` for the latest beat; `POST /api/campaigns/{campaign_id}/beats/{beat_id}/retry` (`TableSeat`, body
  `{}`) → 202 the beat's JSON.
- The `after_beat`/`after_event` hooks stay where Task 0 put them.

- [x] **Step 1: Failing tests:** `test_provider_failure_is_retryable`, `test_restart_leaves_it_retryable`,
  `test_retry_plays_the_same_acts`, `test_retry_prompt_lists_applied_tools`, `test_retry_keeps_the_dice` (a roll of
  the first attempt is returned again, not re-rolled), `test_only_the_latest_beat`, `test_newer_beat_hides_retry`,
  `test_retry_twice_is_409`, `test_other_players_seat_403`, `test_resets_at_from_account_json`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Play: retry a failed beat with the same acts (table voice and fixes Task D1)`.

### Task D2: The Retry button

**Files:** Modify `web/src/play/Story.tsx`; create `web/src/play/retry.ts`; test `web/src/play/Story.test.tsx`.

**Interfaces:** On the latest `dm_error` entry, while `may_retry`: Retry (`retry.button`), and with `resets_at` the
limit's end in the reader's time (`retry.resetsAt`); after a press, the button disables until the `beat` event.

- [x] **Step 1: Failing tests:** `shows Retry on the latest retryable error`, `hides it once retried`, `hides it for a
  newer beat`, `says when the limit ends`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Play: the Retry button (table voice and fixes Task D2)`.

---

## F1+F3. Comments on the PDF form, and closing the questions box

**Owns:** see the table. **Consumes:** `Conversion.comments`, `ConversionRepository.set_closed`.

### Task F1: Comments on the PDF form

**Files:** Modify `src/delve/web/routes/conversions.py`, `src/delve/conversions/runner.py`,
`src/delve/conversions/thorough/*`, `src/delve/modules/books/*` (the quick prompts), `src/delve/web/app.py`
(`AccessLogRedactor`), `web/src/api.ts`, `web/src/routes/NewModule.tsx`. Tests `tests/conversions/test_pdf_comments.py`,
`tests/web/test_pdf_comments_api.py`, `web/src/routes/NewModule.test.tsx`.

**Interfaces:**
- `POST /api/conversions/pdf?…&comments=<text>`: at most `COMMENTS_MAX = 2000` characters (422 over); stored on the
  job (`create(…, comments=)`), queued ones too.
- `start_pdf(…, comments: str = "")`, `start_thorough(…, comments: str = "")`: every prompt of the job that reads the
  book gets, when not empty, `"## The organiser's comments\n\n<comments>"` after its task, quick and thorough.
- The access log shows `comments=…` (the value dropped).
- NewModule: a "Comments for Claude" text area on the PDF form (`conversionNotes.comments`,
  `conversionNotes.commentsHint`); the generate box shows `conversionNotes.looksLikeImport` with a link to the PDF form
  when its text has a file name (`\.\w{2,4}\b`), "import" or "convert" (also `importeer`, `omzetten`).

- [x] **Step 1: Failing tests:** `test_comments_stored_on_the_job`, `test_comments_over_2000_is_422`,
  `test_quick_prompts_hold_the_comments`, `test_thorough_prompts_hold_the_comments`, `test_no_comments_no_section`,
  `test_access_log_drops_comments`; Vitest `sends the comments`, `points to the PDF form`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Conversions: comments on the PDF form, given to every prompt (table voice and fixes Task F1)`.

### Task F3: Closing the questions and doubts box

**Files:** Modify `src/delve/conversions/runner.py` (`_entry`), `src/delve/web/routes/conversions.py`,
`web/src/module/MakingQuestions.tsx`. Tests `tests/conversions/test_closing.py`, `web/src/module/MakingQuestions.test.tsx`.

**Interfaces:**
- `GET /api/modules/{id}/questions` entries gain `closed: string[]` (keys as Decision 5).
- `PUT /api/conversions/{conversion_id}/closed` (`Organiser`) body `{"closed": [keys]}` → the entry; 422 for a key
  that names no question or doubt of the job; publishes `modules` `{id}` so every organiser's page refreshes.
- The box: each question and doubt has Close / Reopen (`conversionNotes.close`, `conversionNotes.reopen`); when all
  are closed it folds to one line, `conversionNotes.allDealtWith` ("All 12 dealt with · Show"); Close all
  (`conversionNotes.closeAll`). Closing changes neither "Notes from making this module" nor what the DM is told.

- [x] **Step 1: Failing tests:** `test_closed_round_trip`, `test_unknown_key_is_422`, `test_closing_leaves_the_notes`,
  `test_running_job_save_keeps_closed`; Vitest `folds when all are closed`, `close all`, `reopen`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Conversions: close the questions and doubts, and fold the box (table voice and fixes Task F3)`.

---

## F2. Fix-it comments

**Owns:** see the table. **Consumes:** `storage.module_comments`, the conversions' runner (`start_job`/`_admit`/
`_begin`/`finish`, `STEPS["fixit"]`), `load_source`/`save_source`, `revisions.snapshot`, `modules.changed_since`.

### Task F2.1: The job

**Files:** Modify `src/delve/conversions/fixit.py`. Test `tests/conversions/test_fixit.py`.

**Interfaces:**
- `send_comment(services, module_id: str, text: str, *, anchor: dict | None, author: str) -> ModuleComment`: stores
  it `open` and, unless the module has a fix-it job running or waiting for review, starts one now (queued when the
  slot is busy).
- A job takes every `open` comment of the module (`working`), the module's latest revision number (`revision` on each
  comment), and runs Claude with the module's editing operations only (texts as Markdown, entities, keys, maps in the
  map language) and the comments; its `target` is `{"module_id", "revision", "comment_ids"}`; its `result` is
  `{"revision", "source": <ModuleSource.to_json>, "maps": [{name, role, source, is_default}], "summary"}`; the comments
  become `review`, or `failed` with `error`. Nothing is saved to the module.
- `keep(services, conversion_id: str) -> Revision`: 409 (`FixitStale`) when `modules.changed_since(module_id,
  revision)`; else saves the result's source and maps (`save_source`, `put_map`, `delete_map`) and snapshots a new
  revision; the comments become `kept`; then starts the next job if comments are `open`.
- `reject(services, conversion_id) -> None`: comments `rejected`; then the next job as above.
- `rerun(services, comment_id)`: a `failed`, `rejected` or stale `review` comment back to `open`, starting a job as
  `send_comment` does. `close_comment(storage, comment_id)`: an `open` one to `closed`.
- `restored(services, conversion)`: a queued `fixit` job's start after a restart.
- `STEPS["fixit"] = (("fixing",),)` (Task 0).

- [x] **Step 1: Failing tests** (the fake `complete`, no `claude`): `test_send_starts_a_job`,
  `test_second_comment_queues_behind`, `test_result_is_not_saved_before_keep`, `test_keep_makes_a_new_revision`
  (a campaign pinned to the old revision stays pinned), `test_keep_after_edit_is_409`, `test_reject_saves_nothing`,
  `test_failed_has_reason_and_rerun`, `test_close_without_running`, `test_only_asked_parts_change` (a result that
  changes a text the comment didn't name is refused as `failed` with "changed what the comment didn't ask",
  when the comment has an anchor), `test_queued_job_restored`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Modules: fix-it comments, a job that proposes the fix (table voice and fixes Task F2.1)`.

### Task F2.2: The routes

**Files:** Modify `src/delve/web/routes/fixits.py`. Test `tests/web/test_fixits_api.py`.

**Interfaces (all `Organiser`):** `GET /api/modules/{module_id}/fixits` → `[comment JSON]` (oldest first; each with
its job's `status` and progress); `POST /api/modules/{module_id}/fixits` `{text, anchor?}` → 201; `GET
/api/fixits/{conversion_id}/review` → `{"texts": [{id, title, before, after}], "maps": [{name, before, after}],
"entities": {"added": [], "changed": [], "removed": []}, "summary"}`; `POST /api/fixits/{conversion_id}/keep` → 200
`{revision}` or 409 `{"error", "code": "stale"}`; `POST /api/fixits/{conversion_id}/reject`; `POST
/api/fixit-comments/{comment_id}/rerun`; `POST /api/fixit-comments/{comment_id}/close`. Each publishes `modules`
`{id}`.

- [x] **Step 1–4:** Failing tests for each route and a player seat's 403 → implement → PASS.
- [x] **Step 5:** Commit `Modules: the fix-it routes (table voice and fixes Task F2.2)`.

### Task F2.3: The module page and the review

**Files:** Modify `web/src/routes/ModuleDetail.tsx`, `web/src/module/ConversionsPanel.tsx` (a `fixit` job's row);
create `web/src/module/FixIts.tsx`, `web/src/module/FixItReview.tsx`, `web/src/module/fixits.ts`; tests beside them.

**Interfaces:** a "Fix-it comments" section on the module's page: a text area and an optional anchor (a map, a room, a
text or an entity, picked from the module's own), the list with each comment's status (`fixit.status.open`,
`…working`, `…review` "Ready to review", `…kept`, `…rejected`, `…failed`, `…closed`), Close, Retry; Review opens
`FixItReview`: the text diff (before/after, line by line), the maps before and after (rendered SVGs side by side), the
entities added, changed and removed, Keep and Reject; a stale Keep says so (`fixit.stale`) and offers Run again.

- [x] **Step 1: Failing tests:** `lists comments with their status`, `review shows the diff`, `keep calls keep`,
  `stale keep offers run again`, `phone layout stacks before and after`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Modules: fix-it comments on the module's page, and their review (table voice and fixes Task F2.3)`.

### Task F2.4: The browser spec

**Files:** Modify `tests/e2e/fake_fixit.py` (`fixit_answer` recognises the fix-it prompt and answers a result that
adds the exit the comment names); create `web/e2e/u-fixit.spec.ts`.

- [x] **Step 1: Write** `u-fixit.spec.ts`: on New module's ready module (not the crypt, which the module editor's spec
  expects alone and unchanged), write "the exit from room 2 to room 3 is not yet in place, fix it", watch the job,
  open the review, Keep, and see the module's revision go up by one and the map hold the exit; screenshots
  `fixit-review.png`, `fixit-phone.png`.
- [x] **Step 2:** `make e2e-browser` → PASS.
- [x] **Step 3:** Commit `Modules: the fix-it browser spec (table voice and fixes Task F2.4)`.

---

## S. The campaign page's table settings

**Owns:** see the table. **Consumes:** `set_voice`, `set_initiative`, `disconnect_campaign` (V1), C's departure route.

### Task S1: The route

**Files:** Modify `src/delve/web/routes/table_settings.py`. Test `tests/web/test_table_settings_api.py`.

**Interfaces:** `PUT /api/campaigns/{campaign_id}/table-settings` (`HostSeat`), body `{"voice"?: "allowed" | "off",
"initiative"?: "combatant" | "side"}` → 200 `campaign_json`; 422 for another value; voice `off` awaits
`disconnect_campaign(app, campaign_id)`; publishes `campaigns` `{id}` and a table event `play_options`
`{campaign_id}` so every seat reads `play/state` again.

- [x] **Step 1: Failing tests:** `test_host_sets_voice_off`, `test_voice_off_disconnects` (a monkeypatched
  `disconnect_campaign` is awaited), `test_initiative_side`, `test_player_seat_403`, `test_bad_value_422`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Campaigns: voice and initiative mode, set by the host (table voice and fixes Task S1)`.

### Task S2: The campaign page

**Files:** Modify `web/src/routes/CampaignDetail.tsx`; create `web/src/campaign/TableSettings.tsx`,
`web/src/campaign/tableSettings.ts`; tests beside them.

**Interfaces:** On the campaign page: Voice: Allowed / Off (`tableSettings.voice`, `tableSettings.voiceAllowed`,
`tableSettings.voiceOff`, `tableSettings.voiceOffHint` "Switching it off disconnects everyone in voice"); Initiative:
Per combatant / Per side (`tableSettings.initiative`, `…perCombatant`, `…perSide`, `…nextRound` "From the next round");
in the character list, Leave the party (with the reason: died, retired, left) and Return (`tableSettings.leave`,
`tableSettings.return`, `tableSettings.reason.*`) beside Delete, calling C's route; a departed PC shows its reason.

- [x] **Step 1: Failing tests:** `sets voice off`, `sets per side`, `leave with a reason`, `return`, `390 px stacks`.
- [x] **Step 2–4:** Run → FAIL → implement → PASS.
- [x] **Step 5:** Commit `Campaigns: the table settings and Leave the party on the campaign page (table voice and fixes Task S2)`.

---

## Z. Wrap-up (after every workstream is merged)

- [x] GUILD.md: a "Voice, the timeline and fix-ups" section (the voice protocol's place and caps, the timeline's
  release rule, the fix-it job's kind and statuses) and the e2e paragraph's three new specs and their order.
- [x] `docs/backlog.md`: strike Features 17, 26, 27 (with "reduced to fix-it comments and closing the questions box",
  this quest), 33, Interface 9 and the combat lines of Fixes 10 (Sleep in round 1, natural 20, Dagger, rat giant,
  zombie AC, adjudicate/say/add_combatant), each with "Done in the table voice and fixes plan, Task <id>".
- [x] `docs/identity.md`: the voice socket's identity and refusals.
- [x] Glossary and data dictionary: any word or value a workstream reported beyond Task 0's.
- [x] `make ci` in a fresh clone and `make e2e-browser` → PASS. Commit `Docs: table voice and fixes wrap-up (table
  voice and fixes Task Z)`.

---

## Open questions (for the archmage)

1. **PHB ch. 9's numbers.** B1 pins Table 56's item modifiers (potion +4, ring +3, rod +1, stave +2, wand +3, other
   magic +3, a scroll its spell's casting time) and the group-initiative reading of per side from memory; B1 checks
   them against the reference's rules text and reports any difference.
2. **Retry and the scripted golden.** Re-running the same beat id keeps its dice; if the owner would rather a retry
   roll fresh, D re-keys the rolls by attempt (`<beat>#2`), which needs no schema change.
3. **The fix-it job's "only what was asked" check** refuses a result that changes a text or map outside an anchored
   comment's anchor; an unanchored comment can change anything the module holds, shown in the review before Keep.
