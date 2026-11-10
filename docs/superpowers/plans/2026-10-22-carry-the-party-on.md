# Delve: Carry the party on, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A host takes a campaign's party into a new campaign on another module, with everything the party owns, and
Claude writes a **history** of the old campaign. The DM reads the history every session, and the table reads its own
version.

**Architecture:**
- **Carrying on is a copy.** A new route makes the campaign exactly as `POST /api/campaigns` does: snapshot,
  owner seat, `seed_world` and house rules. It then calls `delve.play.carry.carry_into` in the same transaction.
  That copies the chosen PCs, the possessions, the coin and loot, and the painted portraits, records the link, and
  sets the old campaign to `complete`. Nothing of the old campaign is moved or deleted.
- **A history is a row per campaign** (`campaign_histories`) with two texts: `dm_md` and `table_md`. It is written by
  a conversion-runner job of the new kind `history`, as novels are. Its material is `novels.material.campaign_material`
  with two new options: no module part, and a `table` audience that filters before Claude sees anything.
- **Readers:** `sessions.primer` adds `history` (the DM's text). `ask_prompt` adds the table's text. The campaign
  page gets a History section (host: both versions, editable), and the play screen gets a History side tab
  (the table's version) when there is one.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core over SQLite with Alembic, React 18 + TypeScript + React Query,
vitest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-22-carry-the-party-on-design.md`, all of it. Owner decisions 1–6 and the
"Calls made after the builder check" are fixed requirements. File references were checked on master 858e861.

## Global Constraints

- **Earlier plans still apply:** `GUILD.md`, and the Global Constraints of every earlier Delve plan (novelization's
  in particular).
- **Every task leaves `make ci` green on its own** once the earlier tasks are merged.
- **Never move or delete the old campaign's rows.** Carrying on only adds rows and sets the old status to `complete`.
- **The table's text never holds DM-only material.** That covers private acts, `told_to` lines, host notes, DM
  notes, NPC `notes_md`, unrevealed secrets, unknown factions and quests, and reputation numbers. This is enforced by
  filtering the material, not by the prompt.
- **The history cap:** `HISTORY_MAX_CHARS = 6000`, for each of the two texts.
- **Carrying on never fails because of the history.** A refused or failed job leaves the new campaign playable, with
  the history `failed` and Write again offered.
- **Strings:** every new UI string goes in both `web/src/i18n/en.json` and `nl.json`.
- **Imports:** `delve.histories` is a new package. Add it to the "no sqlalchemy/alembic" and "no fastapi" contracts
  in `pyproject.toml`. Only `delve.web` imports it, as for `delve.novels`. Extend
  `tests/test_boundaries.py::test_only_the_web_and_the_cli_import_the_novels` with a twin for `delve.histories`.

## Decisions taken in this plan

- **Storage shape:** a table `campaign_histories` keyed by `campaign_id`, and a table `campaign_carries`
  (`id`, `from_campaign_id` nullable and `ON DELETE SET NULL`, `to_campaign_id` unique and `ON DELETE CASCADE`,
  `character_ids` JSON, `carried_at`). Deleting the old campaign keeps the new one and its history, and only drops
  the back link's target.
- **The writer's backend is Preferences' `novel` choice** (`Job.NOVEL`). There's no new Preferences job.
- **Two Claude calls per history:** the DM's from the full material, and the table's from the filtered material.
  Neither call sees the other's input. Each answer over the cap gets one "shorten to N characters" call. If it's
  still over, it's cut at the last paragraph break under the cap.
- **No light sources exist in Delve**, so the spec's "lit light sources" needs no code. What's dropped from a copy:
  every `Effect` (they're all round-timed), and the conditions in `FIGHT_CONDITIONS = ("casting", "surprised",
  "prone", "stunned")`.
- **Sheet fields tied to the old world are cleared on the copy:** `sheet.faction` becomes `""`. The portrait is
  kept (see Task 2).
- **Players' seats aren't copied.** Carried PCs have no `controller_id` until the host assigns them.
- **"The module's starting coin"** in the spec: Delve's modules have no starting-coin field. The party's coin is
  added to whatever the new campaign state holds (zero today), so a later field just works.

## Review Focus

1. **A painted portrait in a carried character:** `ImagePortrait.image_id` names a `campaign_images` row of the
   *old* campaign. `/pictures/{id}` checks `image.campaign_id`, so a plain copy shows a broken image. Task 2 copies
   the image row (same blob) and rewrites the reference. Its test fetches the picture through the new campaign.
2. **A job already running** (a conversion or a novel) when the party is carried on: the campaign must still be
   made, with the history `failed`, the message "A conversion is running: write the history again when it ends.",
   and a working Write again. Task 5 tests it.
3. **A dead PC ticked on purpose,** or an unknown or NPC id in `character_ids`. A dead PC is allowed if ticked, and
   carried as it is. An NPC or a stranger's id gets 422. Task 3 tests both.
4. **Carrying on a campaign that was itself carried on:** the new history must include the old history, so nothing
   from the first module is lost. The table's version must stack the *table* history, never the DM's. Task 4 tests
   both audiences.
5. **The host edits the history, then presses Write again:** the edit isn't lost silently. The route needs
   `overwrite: true` once the history is `edited`, and answers 409 without it. Task 5 tests it, and Task 7 shows the
   confirm dialog.

---

### Task 1: Storage for histories and carries

**Files:**
- Create: `src/delve/domain/histories.py`, `src/delve/storage/migrations/versions/0018_histories.py`,
  `src/delve/storage/sqlite/histories_repo.py`
- Modify: `src/delve/storage/interfaces.py` (two protocols, two `Storage` fields), `src/delve/storage/sqlite/tables.py`,
  `src/delve/storage/sqlite/__init__.py`
- Test: `tests/storage/test_histories_repo.py`, and a case in `tests/novels/test_migrations.py`'s style for 0018
  (`tests/storage/test_migration_0018.py`)

**Interfaces:**
- Produces, in `delve.domain.histories`:
  - `HistoryStatus = Literal["writing", "done", "failed"]`
  - `@dataclass(frozen=True) class History(_Record)` with `campaign_id: str`, `dm_md: str = ""`,
    `table_md: str = ""`, `status: HistoryStatus = "writing"`, `error: str | None = None`, `edited: bool = False`,
    `conversion_id: str | None = None`, `cost_usd: float | None = None`, `created_at: str = ""`,
    `updated_at: str = ""`
  - `@dataclass(frozen=True) class Carry(_Record)` with `id: int`, `from_campaign_id: str | None`,
    `to_campaign_id: str`, `character_ids: tuple[str, ...]`, `carried_at: str = ""`
- Produces, in `delve.storage.interfaces`:
  - `HistoryRepository`: `get(campaign_id) -> History | None`; `put(history) -> History` (insert or replace, keeps
    `created_at`; `KeyError` for an unknown campaign); `writing() -> list[History]`.
  - `CarryRepository`: `add(from_campaign_id, to_campaign_id, character_ids) -> Carry`; `origin(to_campaign_id) ->
    Carry | None`; `onward(from_campaign_id) -> list[Carry]` (oldest first).
  - `Storage.histories: HistoryRepository`, `Storage.carries: CarryRepository`.

- [ ] **Step 1: Write the failing tests.**
  - `test_put_then_get_round_trips_a_history`
  - `test_put_replaces_and_keeps_created_at`
  - `test_put_for_unknown_campaign_raises_key_error`
  - `test_writing_lists_only_writing_histories`
  - `test_deleting_the_campaign_deletes_its_history`
  - `test_carry_add_origin_onward`: two carries from A, so `onward(A)` has 2 and `origin(B).from_campaign_id == A`
  - `test_deleting_the_old_campaign_keeps_the_carry_with_from_none`
  - `test_deleting_the_new_campaign_deletes_the_carry`
  - Migration: `test_0018_upgrade_and_downgrade` (the tables exist after upgrade and are gone after downgrade)
- [ ] **Step 2: Run them:** `uv run pytest tests/storage/test_histories_repo.py tests/storage/test_migration_0018.py -v`.
  Expected: FAIL (no module `delve.domain.histories`).
- [ ] **Step 3: Implement** the domain types, migration `0018_histories` (down_revision `0017_novels`), the tables
  in `tables.py`, and `SqliteHistoryRepository` and `SqliteCarryRepository` in `histories_repo.py`, following
  `novels_repo.py` (`_require_campaign`, `_now`). Wire them in `sqlite/__init__.py`.
- [ ] **Step 4: Run** the same tests, then `make ci`. Expected: PASS.
- [ ] **Step 5: Commit** "Storage for campaign histories and carries".

### Task 2: Copying a party into a campaign

**Files:**
- Create: `src/delve/play/carry.py`
- Test: `tests/play/test_carry.py`

**Interfaces:**
- Consumes: `Storage.carries.add` (Task 1).
- Produces, in `delve.play.carry`:
  - `FIGHT_CONDITIONS: tuple[str, ...] = ("casting", "surprised", "prone", "stunned")`
  - `class FightLive(PlayError)`, message `"End the fight first."`
  - `class NotCarried(PlayError)`, for an id that isn't a PC of the old campaign; its message names it
  - `def check_carry(storage: Storage, from_campaign_id: str, character_ids: Sequence[str]) -> None`. It raises
    `FightLive` when `storage.combats.live(from_campaign_id)` is set, and `NotCarried` for an unknown, foreign or
    NPC id, or an empty list.
  - `def carry_into(storage: Storage, from_campaign_id: str, to_campaign_id: str, character_ids: Sequence[str]) ->
    dict[str, str]`. It answers the map from old character id to new. It runs inside the caller's transaction
    (`storage.transaction()` joins).

- [ ] **Step 1: Write the failing tests** (old campaign A, new campaign B, both made with storage helpers as in
  `tests/play`):
  - `test_copies_sheet_and_state_with_a_new_id`: the levels, XP, hp, inventory and memorized spells are equal; the
    ids differ; `campaign_id == B`; the marching order is kept in A's order.
  - `test_drops_effects_and_fight_conditions_keeps_lasting_ones`: effects `()`; `"prone"` and `"casting"` are gone;
    `"diseased"` and `"downed"` stay.
  - `test_clears_faction_and_controller`
  - `test_old_characters_unchanged` (A's characters compare equal before and after)
  - `test_owned_and_unowned_possessions_copied`: the owned ones point at the new owner id, and the unowned stay
    unowned. The possessions of a PC left behind are not copied.
  - `test_coin_added_and_loot_appended`: B's state starts with `{"gp": 5}`, so after the copy it has A's coin plus 5,
    and the loot is B's followed by A's.
  - `test_painted_portrait_is_copied_and_served`: an `ImagePortrait` on a PC and on a possession becomes a new
    `campaign_images` row in B with the same blob and the new `subject_id`, and the copied sheet names it. Rows that
    aren't `done` aren't copied, and the portrait is reset to None.
  - `test_records_carry_and_completes_old_campaign`: `carries.origin(B)` names A and the ids; A's status is
    `complete`.
  - `test_check_refuses_a_live_fight`, `test_check_refuses_npc_unknown_and_empty`
  - `test_dead_pc_carried_when_asked` (hp ≤ −10 and carried as is)
- [ ] **Step 2: Run** `uv run pytest tests/play/test_carry.py -v`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** `check_carry` and `carry_into` in `src/delve/play/carry.py`, using `characters.create`
  (pass `order`), `possessions.put`, `campaign_states.get/put`, `campaign_images.put`, `carries.add` and
  `campaigns.set_status(from, "complete")`.
- [ ] **Step 4: Run** the tests, then `make ci`. Expected: PASS.
- [ ] **Step 5: Commit** "Copy a party into another campaign".

### Task 3: The Carry the party on route

**Files:**
- Modify: `src/delve/web/routes/campaigns.py`
- Test: `tests/web/test_carry_api.py`

**Interfaces:**
- Consumes: `check_carry`, `carry_into`, `FightLive`, `NotCarried` (Task 2); `carries.origin/onward` (Task 1).
- Produces:
  - `POST /api/campaigns/{campaign_id}/carry` (`Organiser`), status 201. The body is
    `CarryIn {name: str, module_id: str, character_ids: list[str], ruleset: str | None = None, setting: str | None
    = <unset>, bundle_ids: list[str] | None = None, rule_ids: list[str] | None = None}`. Left out, `ruleset`,
    `setting` and the house rules are the **old campaign's** (`campaign_house_rules.get(old)`), not the module's.
    It answers `campaign_json(new)`. A later task (Task 5) adds `"history"`.
  - `campaign_json` gains `carried_from: {"id", "name"} | None` (`None` when the old one was deleted) and
    `carried_to: [{"id", "name"}]`. The `GET /api/campaigns/{id}` answer carries both.
  - `def make_campaign(request, name, module, ruleset, setting, bundle_ids, rule_ids) -> Campaign`: what
    `create_campaign`'s transaction body does today, pulled out so both routes share it. It runs inside the caller's
    transaction.

- [ ] **Step 1: Write the failing tests:**
  - `test_carry_makes_a_campaign_on_the_module_with_the_party`: 201; the new campaign plays the new module, has the
    chosen PCs and an owner seat, and is seeded with the module's factions.
  - `test_defaults_to_old_campaigns_ruleset_setting_and_house_rules`
  - `test_given_ruleset_and_house_rules_win`
  - `test_draft_module_409`, `test_unknown_module_404`, `test_unknown_campaign_404`
  - `test_live_fight_409_with_end_the_fight_first`
  - `test_npc_or_foreign_id_422`, `test_empty_party_422`
  - `test_player_seat_403` (as `create_campaign`)
  - `test_campaign_json_links_both_ways`, `test_links_survive_deleting_the_old_campaign` (`carried_from` is None)
  - `test_refused_carry_makes_nothing`: a 409 or 422 leaves no new campaign and A not `complete`
- [ ] **Step 2: Run** `uv run pytest tests/web/test_carry_api.py -v`. Expected: FAIL (404 route).
- [ ] **Step 3: Implement:** pull out `make_campaign`, and add `CarryIn` and the route. Call `check_carry` before the
  transaction, then `make_campaign` and `carry_into` inside one. Map `FightLive` to 409 and `NotCarried` to 422.
  Then call `ask_for_banner`, as `create_campaign` does.
- [ ] **Step 4: Run** the tests, `tests/web/test_campaigns_api.py`, then `make ci`. Expected: PASS.
- [ ] **Step 5: Commit** "Carry the party on: the route".

### Task 4: History material

**Files:**
- Modify: `src/delve/novels/material.py`
- Create: `src/delve/histories/__init__.py`, `src/delve/histories/material.py`
- Modify: `pyproject.toml` (contracts), `tests/test_boundaries.py`
- Test: `tests/histories/test_material.py`

**Interfaces:**
- Produces, in `delve.novels.material`: `campaign_material(storage, campaign_id, sessions, *, audience:
  Literal["all", "table"] = "all", with_module: bool = True) -> Material`. Novels keep the defaults, so their
  behaviour doesn't change. `audience="table"` keeps only story entries with `audience is None`, and drops private
  acts, `told_to` lines, host notes, ask/answer and table talk. It also drops NPC `notes_md` (keeping their
  `background`) and the "DM's secrets and notes" part.
- Produces, in `delve.histories.material`:
  `history_material(storage: Storage, campaign_id: str, audience: Literal["dm", "table"]) -> Material`. It is
  `campaign_material(..., audience="all" | "table", with_module=False)` plus three parts:
  - **"Standing with the factions":** DM: every faction with its reputation number. Table: only `known` factions,
    with a word for the standing instead of the number: `hostile` ≤ −50 < `unfriendly` ≤ −10 < `neutral` < 10 ≤
    `friendly` < 50 ≤ `allied`.
  - **"Quests":** DM: all, with status and stakes. Table: `known` only, with no `notes_md`.
  - **"The party's earlier history":** the campaign's own `History`, if it has one that's `done`. DM: `dm_md`.
    Table: `table_md`.

- [ ] **Step 1: Write the failing tests:**
  - `test_novel_material_unchanged_by_default`: the existing `tests/novels` material tests still pass, plus one
    asserting the module part is present by default.
  - `test_without_module_has_no_module_part`
  - `test_table_material_leaks_nothing`: seed a private act, a `told_to` line, a host note, an unrevealed secret
    note, an NPC with `notes_md="SECRETWORD"`, an unknown faction, and a known one at reputation −37. Then assert
    that `render(table)` contains none of the secret strings or `"-37"`, and does contain `"unfriendly"` and the
    public lines.
  - `test_dm_material_has_secrets_and_numbers`
  - `test_earlier_history_stacks_by_audience`: with a done `History(dm_md="DMPAST", table_md="TABLEPAST")`, the DM
    material holds `DMPAST` and not `TABLEPAST`, and the table material the opposite.
  - `test_boundaries`: the new twin test, which says only web and cli import `delve.histories.material`.
- [ ] **Step 2: Run** `uv run pytest tests/histories tests/novels -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the two options and `history_material`, and add the contracts.
- [ ] **Step 4: Run** the tests, then `make ci`. Expected: PASS.
- [ ] **Step 5: Commit** "History material, with a table audience filtered at the source".

### Task 5: Writing the history as a job, and its routes

**Files:**
- Create: `src/delve/histories/writer.py`, `src/delve/histories/jobs.py`, `src/delve/histories/prompts/history.md`,
  `src/delve/web/routes/histories.py`
- Modify: `src/delve/domain/conversions.py` and `web/src/api.ts` (`ConversionKind` gains `"history"`),
  `src/delve/web/app.py` (router, and `close_orphan_histories` at startup beside `close_orphan_novels`),
  `src/delve/web/routes/campaigns.py` (the carry route starts the job)
- Test: `tests/histories/test_writer.py`, `tests/histories/test_jobs.py`, `tests/web/test_histories_api.py`

**Interfaces:**
- Consumes: `history_material` (Task 4); `Storage.histories` (Task 1); `start_job`, `complete_with`, `finish` and
  `progress_for` from `delve.conversions`, as `novels/jobs.py` uses them.
- Produces:
  - `delve.histories.writer`: `HISTORY_MAX_CHARS = 6000`;
    `async def write_history(complete: Complete, material_text: str, audience: Literal["dm", "table"]) -> str`.
    The prompt asks for Markdown with the spec's sections, in order: `## The party`, `## People met`, `## Deeds`,
    `## Grudges and debts`, `## Loot`, and for the DM only `## Loose ends`. It must be faithful to the record: no
    invented outcomes, no dice or game terms. It shortens once if over the cap, then cuts at the last `\n\n` under
    the cap.
  - `delve.histories.jobs`: `RUNNING_MSG = "A conversion is running: write the history again when it ends."`,
    `ORPHANED = "Delve stopped while writing."`, `class HistoryEdited(ValueError)`;
    `async def start_history(services: NovelServices, to_campaign_id: str, from_campaign_id: str, *, overwrite: bool
    = False) -> History`. It reads both materials when it starts, from the old campaign. If another job is running,
    it stores a `failed` history with `RUNNING_MSG` and returns it, never raising `ConversionRunning`. It raises
    `HistoryEdited` when the stored history is `edited` and `overwrite` is false. The job runs steps `condensing`
    (if needed), then `writing` with done/total 0..2 (DM first, then table), saving each text as it ends, and
    `cost_usd`, as `_write` in novels does. `close_orphan_histories(storage) -> list[History]`.
  - Routes in `histories.py`:
    - `GET /api/campaigns/{id}/history` (`TableSeat`): 404 when there's none. Host and co-host get the whole
      `History`. Other seats get `{status, table_md}` only.
    - `PUT /api/campaigns/{id}/history` (`HostSeat`), body `{dm_md: str, table_md: str}`: sets both, with
      `edited: true` and `status: "done"`. Each text is at most `HISTORY_MAX_CHARS`, else 422. 409 while `writing`.
    - `POST /api/campaigns/{id}/history/write` (`HostSeat`), body `{overwrite: bool = false}`: 202. It's 409
      `"The history was edited: confirm to replace it."` for `HistoryEdited`, 409 while `writing`, and 404 when the
      campaign wasn't carried on or its origin was deleted.
  - The carry route answers `{**campaign_json(new), "history": {"status": ...}}`.

- [ ] **Step 1: Write the failing tests** (a fake `complete` as in `tests/novels`):
  - writer: `test_dm_prompt_asks_for_loose_ends_table_prompt_does_not`; `test_over_cap_shortens_once_then_cuts`
    (the answer stays ≤ 6000 and ends at a paragraph break).
  - jobs: `test_writes_dm_then_table_and_ends_done` (two calls, the table call's prompt has none of the DM-only
    seed strings from Task 4's fixture); `test_running_job_gives_failed_history_with_message`;
    `test_failure_keeps_campaign_and_marks_failed`; `test_edited_needs_overwrite`;
    `test_orphan_closed_at_start`; `test_cost_recorded`.
  - api: `test_carry_starts_history`; `test_player_gets_table_text_only` (no `dm_md` key);
    `test_host_put_marks_edited`; `test_put_over_cap_422`; `test_write_again_409_when_edited_then_202_with_overwrite`;
    `test_write_again_404_without_origin`.
- [ ] **Step 2: Run** `uv run pytest tests/histories tests/web/test_histories_api.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the writer, the prompt, the jobs, the routes and the carry hook. In the services, reuse
  `routes/novels.py::novels(app)` so the backend is the `novel` choice.
- [ ] **Step 4: Run** the tests, then `make ci`. Expected: PASS.
- [ ] **Step 5: Commit** "Write a carried party's history as a job".

### Task 6: The DM and Ask read the history

**Files:**
- Modify: `src/delve/play/sessions.py` (`primer`), `src/delve/dm/tools/notes.py` (`session_primer` docstring),
  `src/delve/dm/prompt/dm.md` (Session Start), `src/delve/play/ask.py` (`ask_prompt`)
- Test: `tests/play/test_sessions.py`, `tests/play/test_ask.py` (add cases), and the dm.md prompt test, if
  `tests/dm` has one for its sections

**Interfaces:**
- Consumes: `Storage.histories.get` (Task 1).
- Produces:
  - `primer(...)["history"]`: the `dm_md` of a `done` history, else `None`.
  - In `ask_prompt`, a part `"THE PARTY'S EARLIER HISTORY (what the table knows):\n" + table_md`, placed after the
    last recap and only when the history is `done`.
  - dm.md gets a paragraph in Session Start: "**The primer's `history` is where this party has been.** …" Bring
    back people, grudges, debts and loot from it when they fit the scene, unprompted. Contradict nothing in it, and
    invent no past beyond it. Its Loose ends are DM-only.

- [ ] **Step 1: Write the failing tests:** `test_primer_has_history_when_done`, `test_primer_history_none_when_writing`,
  `test_ask_prompt_includes_table_history_never_dm`.
- [ ] **Step 2: Run** `uv run pytest tests/play -k "history" -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the three changes and the dm.md paragraph.
- [ ] **Step 4: Run** `make ci`. Expected: PASS.
- [ ] **Step 5: Commit** "The DM and Ask read the party's history".

### Task 7: The web: carry form, History section, play tab

**Files:**
- Create: `web/src/campaign/CarryForm.tsx`, `web/src/campaign/HistorySection.tsx`, `web/src/play/HistoryPanel.tsx`,
  and their `*.test.tsx`
- Modify: `web/src/api.ts` (`carryCampaign`, `getHistory`, `putHistory`, `writeHistoryAgain`, the `Campaign` type's
  `carried_from` and `carried_to`, and `History`), `web/src/routes/CampaignDetail.tsx`, `web/src/routes/Play.tsx`,
  `web/src/module/conversions.ts` (`conversionLink` for `"history"`: `/campaigns/<target.campaign_id>#history`),
  `web/src/i18n/en.json`, `web/src/i18n/nl.json`, `README.md` (one paragraph under campaigns), `docs/glossary.md`
  (**carry the party on**, **history**)

**Interfaces:**
- Consumes: the routes of Tasks 3 and 5.

- [ ] **Step 1: Write the failing tests:**
  - CarryForm: it lists the PCs, with the living ones ticked and the dead unticked (marked dead); it offers only
    non-draft modules; it pre-fills the name and the ruleset/setting from the old campaign; it navigates to the new
    campaign on success; it shows a 409 "End the fight first." as an error.
  - HistorySection: the host sees a toggle between the DM's and the table's text, and while `writing` it shows
    progress. Edit saves both. Write again on an edited history asks with `useConfirm` before sending
    `overwrite: true`. A `failed` history shows its error and Write again. It shows "Carried on from <name>" and
    "Carried on to <names>" as links.
  - HistoryPanel: it shows `table_md` rendered as Markdown. The tab is absent when `GET history` is 404.
- [ ] **Step 2: Run** `cd web && npm test -- CarryForm HistorySection HistoryPanel`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **CampaignDetail:** a **Carry the party on** button in the actions row opens `CarryForm`. The `HistorySection`
    (`id="history"`) goes right after the banner, shown when the campaign has an origin or a history.
  - **Play.tsx:** a `history` side tab and phone screen, after `setting`, shown when the history exists.
  - Reuse `renderMarkdown` from `web/src/play/markdown.ts`.
- [ ] **Step 4: Run** `make ci`, then check in Chromium on desktop and at phone width: carry a party of 2 into a
  second module, see the History fill in, edit it, and open the play screen as a player seat (History tab, no
  Loose ends).
- [ ] **Step 5: Commit** "Carry the party on and the History, on the web".
