# Cloud Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Daily backups of modules, campaigns and settings to a private cloud store, and a shared module library on a
second store that friends' Delve installs browse, download from and publish to, by right.

**Architecture:** A new package `delve.cloud` holds the provider seam (`ObjectStore`, with Azure Blob, S3-compatible
and local-folder implementations), the two stores' connection files, the bundle format, and the backup, restore and
library logic. Reading and writing database rows for a bundle lives in `delve.storage` (only it may import
SQLAlchemy) as a `snapshots` repository. Routes live in `delve.web.routes.storage` (owner) and
`delve.web.routes.library` (organisers); the web gets a Storage section in Preferences and a Library tab on Modules.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy Core + Alembic on SQLite, `httpx` (no cloud SDKs), React + TypeScript,
vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-10-26-cloud-storage-design.md` (approved 2026-10-26). Read it first; this plan
argues from it.

## Global Constraints

- No cloud SDK dependencies: Azure Blob REST and S3 SigV4 over `httpx`.
- Never a real cloud call in tests: `LocalStore` or `httpx.MockTransport`.
- A credential (SAS query string, secret access key) never appears in a route's answer, a log line, an error message,
  an uploaded file, or a `repr`. Errors are Delve's own words with the HTTP status, never the provider's body.
- Connection files in the data dir at mode 0600, written atomically, as `delve.images.connections` does:
  `backup-store.json`, `library-store.json`, `install-id`.
- Store and backup settings are the owner's alone (`Owner` dependency; organisers get 403). Library browse, download,
  update and publish are for organisers (`Organiser`).
- Backup store needs list, read, create, overwrite, delete; a credential that can't is refused for backups.
- Library rights: `read` < `publish` < `manage`, from the probe table in the spec; for S3 a write credential is capped
  by the owner's choice of `publish` or `manage` (stored in `library-store.json` as `"right": "publish"|"manage"`).
- Publishing never overwrites: each version is new objects `<entry key>/v<N>/module.dscn` and `entry.json`.
- Backups are latest copy only: `<install id>/<kind>s/<id>.<ext>` overwritten, plus `<install id>/index.json`.
- Bundle extensions: `.dmod` (module, all revisions), `.dcmp` (campaign), `.dset` (setting); library uses `.dscn`.
- Backup time default `04:00` local time; a run due while Delve was down runs at the next start.
- Migrations: plain `ALTER TABLE … ADD COLUMN` / `CREATE TABLE`, no batch mode. Next revision `0024_cloud_storage`,
  down_revision `0023_image_jobs`.
- UI copy in all five languages: en, nl, de, fr, lv. Follow `docs/style-guide.md`.
- Add `delve.cloud` to the import-linter contracts that forbid `sqlalchemy`/`alembic` and `fastapi`/`starlette`/
  `uvicorn` (`pyproject.toml`).
- `make ci` green at every commit. Never run `ruff format` over the tree (the repo isn't formatted by it); `ruff check`
  only.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A campaign restored into an empty install plays on its pinned revision** — the module's revisions come back with
   their numbers, and `campaigns.(module_id, revision)` resolves. Test in Task 6.
2. **A SAS or secret key echoed by the provider** (an error page quoting the request URL) never reaches an exception
   message, a log or a route answer. Tests in Tasks 2, 3 and 4.
3. **A backup run where one item fails** (a bundle too large, the store refusing one write) reports partial, lists the
   failure, uploads the rest, and records hashes only for what succeeded, so the failed one is retried next run. Test
   in Task 7.
4. **Two publishes of the same entry from two installs at once** — create-only writes mean the second gets "already
   exists" for `v<N>` and retries as `v<N+1>`, never overwriting. Test in Task 9.
5. **A library entry whose `entry.json` is malformed or from a newer format** is skipped in the listing with a warning,
   not a 500 for the whole tab. Test in Task 9.

---

### Task 1: The object store seam and the local store

**Files:**
- Create: `src/delve/cloud/__init__.py`, `src/delve/cloud/store.py`
- Modify: `pyproject.toml` (import-linter contracts: add `"delve.cloud"` to the two forbidden lists' `source_modules`)
- Test: `tests/cloud/__init__.py`, `tests/cloud/test_store.py`

**Interfaces:**
- Produces:
  - `class StoreError(Exception)` — Delve's own words, never a credential. Subclasses `Exists(StoreError)` (create
    over an existing object), `Missing(StoreError)` (get/delete of an absent one), `Refused(StoreError)` (401/403).
  - `Right = Literal["read", "publish", "manage"]`; `RIGHTS: tuple[Right, ...] = ("read", "publish", "manage")`.
  - `@dataclass(frozen=True) class Listed: name: str; size: int; modified: str`
  - `class ObjectStore(Protocol)`: `async def list(self, prefix: str = "") -> list[Listed]`;
    `async def get(self, name: str) -> bytes`; `async def create(self, name: str, data: bytes) -> None` (raises
    `Exists`); `async def put(self, name: str, data: bytes) -> None`; `async def delete(self, name: str) -> None`;
    `async def aclose(self) -> None`; attribute `label: str` (where it is, credential-free, for the UI).
  - `async def probe(store: ObjectStore) -> Right | None` — None when it can't even list. Lists; creates
    `.delve-probe/<random>`; overwrites it; deletes it. Probe objects are removed on every path it reached.
  - `class LocalStore` — a folder; `create` uses `os.open(..., O_CREAT | O_EXCL)`; names with `..` or a leading `/`
    raise `StoreError`. Constructor `LocalStore(root: Path, *, read_only: bool = False, create_only: bool = False)`
    so tests can play each right.

- [ ] **Step 1: Write the failing tests** in `tests/cloud/test_store.py`:
  `test_create_refuses_an_existing_object` (`Exists`), `test_put_overwrites`, `test_list_by_prefix_is_sorted_by_name`,
  `test_get_of_a_missing_object_raises_missing`, `test_a_name_escaping_the_root_is_refused` (`"../x"`, `"/x"`),
  and `test_probe_gives_each_right` parametrized: `LocalStore(read_only=True)` → `"read"`,
  `LocalStore(create_only=True)` → `"publish"`, `LocalStore()` → `"manage"`; after each, `list(".delve-probe/")`
  is `[]`.
- [ ] **Step 2: Run** `uv run pytest tests/cloud/test_store.py -q` — expect import errors.
- [ ] **Step 3: Implement** `src/delve/cloud/store.py` as above (async methods wrap the file calls directly; files are
  small enough here).
- [ ] **Step 4: Run** `uv run pytest tests/cloud -q && uv run lint-imports` — PASS, contracts kept.
- [ ] **Step 5: Commit** `Cloud: the object store seam and a local store (DEL-110)`.

### Task 2: Azure Blob store

**Files:**
- Create: `src/delve/cloud/azure.py`
- Test: `tests/cloud/test_azure.py`

**Interfaces:**
- Consumes: `ObjectStore`, `StoreError`, `Exists`, `Missing`, `Refused`, `Listed` (Task 1).
- Produces: `class AzureBlobStore(ObjectStore)`, `AzureBlobStore(sas_url: str, *, client: httpx.AsyncClient)`;
  `def parse_sas(sas_url: str) -> tuple[str, str]` → `(container_url, query)`, `ValueError` (credential-free message)
  unless https, a container path, and `sv`/`sig` in the query. `label` is the container URL without the query.

REST calls (API version header `x-ms-version: 2023-11-03`):
- list: `GET {container}?restype=container&comp=list&prefix=…&marker=…` + SAS query; parse the XML
  (`xml.etree.ElementTree`), follow `NextMarker`.
- get: `GET {container}/{name}?{sas}`; 404 → `Missing`.
- create: `PUT` with `x-ms-blob-type: BlockBlob` and `If-None-Match: *`; 409/412 → `Exists`.
- put: `PUT` with `x-ms-blob-type: BlockBlob`.
- Bodies over 64 MiB go as `Put Block` (4 MiB blocks) + `Put Block List`; the create precondition goes on the block
  list call.
- delete: `DELETE`; 404 → `Missing`.
- 401/403 → `Refused`; any other ≥400 → `StoreError(f"Azure answered {status}.")`; `httpx.HTTPError` →
  `StoreError("Azure isn't answering.")`.

- [ ] **Step 1: Write the failing tests** against an `httpx.MockTransport` fake Azure that keeps blobs in a dict and
  honours `If-None-Match: *`:
  - `test_round_trip_create_get_list_delete`
  - `test_create_over_an_existing_blob_raises_exists`
  - `test_list_follows_the_next_marker` (the fake pages at 2)
  - `test_a_large_body_goes_in_blocks` (monkeypatch the threshold to 10 bytes; assert `comp=block` calls, then
    `comp=blocklist`)
  - `test_parse_sas_refuses_http_and_a_missing_signature`
  - `test_an_error_page_echoing_the_sas_never_reaches_the_message`: the fake answers 500 with the request URL in the
    body; `str(error)` == `"Azure answered 500."`, and `"sig="` not in `caplog.text` or `repr(store)`.
  - `test_probe_on_a_read_list_sas_is_read` and `test_probe_on_a_create_sas_is_publish`: the fake refuses with 403
    what the SAS's `sp` doesn't allow.
- [ ] **Step 2: Run** `uv run pytest tests/cloud/test_azure.py -q` — FAIL.
- [ ] **Step 3: Implement** `src/delve/cloud/azure.py`.
- [ ] **Step 4: Run** `uv run pytest tests/cloud -q` — PASS.
- [ ] **Step 5: Commit** `Cloud: Azure Blob store over its REST API (DEL-110)`.

### Task 3: S3-compatible store (Cloudflare R2)

**Files:**
- Create: `src/delve/cloud/s3.py`
- Test: `tests/cloud/test_s3.py`

**Interfaces:**
- Produces: `class S3Store(ObjectStore)`, `S3Store(endpoint: str, bucket: str, access_key_id: str,
  secret_access_key: str, *, region: str = "auto", client: httpx.AsyncClient)`; `def r2_endpoint(account_id: str) ->
  str` → `f"https://{account_id}.r2.cloudflarestorage.com"`; `def sign(method, url, headers, payload_sha256,
  access_key_id, secret, region, now) -> dict[str, str]` (SigV4, service `s3`, path-style URLs
  `{endpoint}/{bucket}/{key}`, `x-amz-content-sha256` set). `label` is `f"{endpoint}/{bucket}"`.

Calls: list `GET ?list-type=2&prefix=…&continuation-token=…` (XML); get `GET`; create `PUT` with `If-None-Match: *`
(412 → `Exists`); put `PUT`; delete `DELETE` (S3 answers 204 for a missing key: `delete` checks with `HEAD` first and
raises `Missing`). Bodies over 64 MiB use multipart upload (8 MiB parts); for create, the precondition goes on
`CompleteMultipartUpload`. Error mapping as Task 2, with "S3" in the words: `StoreError(f"The S3 store answered
{status}.")`.

- [ ] **Step 1: Write the failing tests:**
  - `test_sign_matches_the_aws_example` (AWS's published "GET Object" SigV4 example: access key `AKIAIOSFODNN7EXAMPLE`,
    secret `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`, region `us-east-1`, `20130524T000000Z`, bucket `examplebucket`,
    key `test.txt`, `Range: bytes=0-9`; expected signature
    `f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41`)
  - `test_round_trip_against_a_fake_s3`
  - `test_create_over_an_existing_key_raises_exists`
  - `test_list_follows_the_continuation_token`
  - `test_the_secret_never_reaches_an_error_or_repr`
  - `test_r2_endpoint`
- [ ] **Step 2: Run** `uv run pytest tests/cloud/test_s3.py -q` — FAIL.
- [ ] **Step 3: Implement** `src/delve/cloud/s3.py`.
- [ ] **Step 4: Run** `uv run pytest tests/cloud -q` — PASS.
- [ ] **Step 5: Commit** `Cloud: S3-compatible store for Cloudflare R2 (DEL-110)`.

### Task 4: The two stores' connections, and the Storage routes

**Files:**
- Create: `src/delve/cloud/connections.py`, `src/delve/web/routes/storage.py`
- Modify: `src/delve/web/app.py` (include the router; build the stores at start; close them at stop)
- Test: `tests/cloud/test_connections.py`, `tests/web/test_storage_api.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces in `delve.cloud.connections`:
  - `StoreKind = Literal["backup", "library"]`
  - `@dataclass(frozen=True) class StoreConfig: provider: Literal["azure", "s3", "local"]; sas_url: str = "";
    endpoint: str = ""; bucket: str = ""; access_key_id: str = ""; secret_access_key: str = ""; root: str = "";
    right: Right | None = None` (`repr` leaves out `sas_url`'s query and `secret_access_key`).
  - `def load_store(data_dir: Path, kind: StoreKind) -> StoreConfig | None`;
    `def save_store(data_dir: Path, kind: StoreKind, config: StoreConfig | None, *, keep_secret: bool) -> None`
    (None removes the file; `keep_secret` keeps the stored SAS/secret when the form sends none, as `KEEP` does for
    assetgen).
  - `def open_store(config: StoreConfig, client: httpx.AsyncClient) -> ObjectStore`.
  - `def install_id(data_dir: Path) -> str` — made once (`ins_` + 12 hex), file `install-id`.
  - `async def library_right(store: ObjectStore, config: StoreConfig) -> Right | None` — `probe`, then for `s3`
    capped at `config.right` (default `publish`).
  - `class Stores` (on `app.state.stores`): `backup: ObjectStore | None`, `library: ObjectStore | None`,
    `library_right: Right | None`, `async def reload(kind)`, `async def aclose()`.
- Produces routes (all `Owner`):
  - `GET /api/storage` → `{backup: StoreView | null, library: StoreView | null, schedule: {time, last_run}, install_id}`.
    `StoreView` is `{provider, label, secret: "set", right, expires}`; `expires` is an Azure SAS's `se=` time (None
    otherwise), so the section can say when it stops working.
  - `PUT /api/storage/{kind}` with the config body (raw body read as in `routes/connections.py`, so a 422 never echoes
    it). It probes the store: a backup store without `manage` is 422 "This credential can't write and delete, so
    backups can't use it.", and a library store that can't list is 422.
  - `DELETE /api/storage/{kind}`.
  - `POST /api/storage/{kind}/test` → `{ok, right, message}`.
  - `PUT /api/storage/schedule` `{time: "HH:MM"}`, stored in `storage.settings` under key `"backup"`.
  - Each change publishes `preferences`.

- [ ] **Step 1: Write the failing tests**:
  - `tests/cloud/test_connections.py`: `test_a_store_file_is_0600_and_atomic`, `test_keep_secret_keeps_the_stored_sas`,
    `test_the_install_id_is_made_once`, `test_repr_holds_no_secret`, `test_an_s3_write_credential_is_capped_by_the_owners_choice`.
  - `tests/web/test_storage_api.py` (stores as `local` providers under `tmp_path`):
    - `test_an_organiser_gets_403`
    - `test_get_never_answers_a_secret` (assert neither the SAS query nor the secret key is in `response.text`)
    - `test_a_read_only_backup_store_is_refused_with_the_reason`
    - `test_a_library_store_answers_its_right`
    - `test_a_refused_body_is_never_echoed`
    - `test_the_schedule_is_saved_and_read_back`
    - `test_a_bad_time_is_422`
    - `test_an_azure_sas_answers_its_expiry`
- [ ] **Step 2: Run** `uv run pytest tests/cloud/test_connections.py tests/web/test_storage_api.py -q` — FAIL.
- [ ] **Step 3: Implement** both modules; wire `Stores` in `delve.web.app` lifespan (build after the existing start
  steps; `await app.state.stores.aclose()` at stop).
- [ ] **Step 4: Run** the two files, then `uv run lint-imports` — PASS.
- [ ] **Step 5: Commit** `Cloud: the backup and library stores, set in Storage (DEL-110)`.

### Task 5: Migration and the snapshots repository

**Files:**
- Create: `src/delve/storage/migrations/versions/0024_cloud_storage.py`, `src/delve/storage/sqlite/snapshots_repo.py`
- Modify: `src/delve/storage/sqlite/tables.py`, `src/delve/storage/interfaces.py` (`SnapshotRepository`,
  `BackupItemRepository`, `Storage.snapshots`, `Storage.backup_items`), `src/delve/storage/sqlite/__init__.py`,
  `src/delve/domain/modules.py` (`Module` gains the library fields), `tests/storage/test_migrations.py` (HEAD)
- Test: `tests/storage/test_snapshots.py`

**Interfaces:**
- Schema (migration 0024):
  - `CREATE TABLE backup_items (kind TEXT NOT NULL, item_id TEXT NOT NULL, hash TEXT NOT NULL, size INTEGER NOT NULL,
    backed_up_at TEXT NOT NULL, PRIMARY KEY (kind, item_id))`.
  - `modules` gains `library_key TEXT`, `library_version INTEGER`, `library_hash TEXT`, `library_origin TEXT`
    (`'published'` | `'downloaded'` | NULL), `library_author TEXT`.
- Produces:
  - `SnapshotKind = Literal["module", "campaign", "setting"]`
  - `@dataclass(frozen=True) class Snapshot: kind: SnapshotKind; item_id: str; head: str; rows: dict[str,
    list[dict[str, Any]]]; blobs: frozenset[str]` (blob shas, mime in the `blobs` rows).
  - `storage.snapshots.dump(kind, item_id) -> Snapshot` — rows as JSON-ready dicts, ordered by primary key, for:
    - **module:** `modules`, `module_maps`, `module_revisions`, `module_texts`, `module_sources`, `module_blobs`,
      `module_comments` (with `conversion_id` set to None).
    - **campaign:** every table with a `campaign_id` column, plus `translations` of its `story` rows, plus the
      `house_rules`, `house_rules_bundles` and `house_rules_bundle_rules` rows its campaign rule and bundle links
      reach. Leaves out `campaign_carries`.
    - **setting:** `setting_pages`, `setting_facts`, `setting_maps`, `setting_world_maps` where `setting = item_id`,
      plus `world_pictures` their rows reference.
    - **blobs:** the `blobs` rows of every 64-hex string found anywhere in the dumped values (walk dicts, lists and
      strings) that is a `blobs.sha256`.
  - `storage.snapshots.restore(snapshot, *, replace: bool) -> list[str]` (warnings), in one transaction, parents
    before children:
    - Refuses with `SnapshotRefused` when `snapshot.head` is newer than this database's head, or when the item exists
      and `replace` is False.
    - With `replace`, deletes the item's rows first.
    - Inserts only the columns this table has.
    - House rules already present by id are kept.
    - `seats.account_id` is set to None when the account doesn't exist, with a warning naming the seat.
    - A campaign whose `(module_id, revision)` is missing is refused: `SnapshotRefused("Restore its module first.")`.
  - `storage.snapshots.item_ids(kind) -> list[str]`, `storage.snapshots.title(kind, item_id) -> str`.
  - `storage.backup_items.get(kind, item_id) -> BackupItem | None`, `.put(BackupItem)`, `.list() -> list[BackupItem]`;
    `BackupItem(kind, item_id, hash, size, backed_up_at)`.

- [ ] **Step 1: Write the failing tests** in `tests/storage/test_snapshots.py`, using the existing fixtures that build a
  played campaign (`tests/play/conftest.py` `crypt_campaign`) and a module with two revisions:
  - `test_a_campaign_round_trips_into_an_empty_database`: dump module, then campaign; restore both into a fresh
    `SqliteStorage`; every dumped table's rows are equal, and `campaigns.get(id).revision` resolves via
    `revisions.get`.
  - `test_a_module_keeps_all_its_revisions`
  - `test_a_setting_round_trips_with_its_world_pictures`
  - `test_blobs_referenced_anywhere_are_found` (a painted image's `blob`, a module attachment, a world picture's tiles)
  - `test_restore_refuses_an_existing_item_without_replace`
  - `test_replace_removes_rows_the_snapshot_doesnt_have`
  - `test_a_newer_head_is_refused`
  - `test_an_unknown_account_is_unlinked_with_a_warning`
  - `test_house_rules_present_are_kept`
  - `test_a_campaign_without_its_module_is_refused`
  - `test_dump_is_deterministic` (two dumps → equal)
- [ ] **Step 2: Run** `uv run pytest tests/storage/test_snapshots.py -q` — FAIL.
- [ ] **Step 3: Implement** the migration, tables, repository and protocol entries. Find the campaign's tables from
  `metadata.sorted_tables` by column name rather than a hand list, so a future table is never missed; the module and
  setting lists are explicit. Restore inserts in `metadata.sorted_tables` order.
- [ ] **Step 4: Run** `uv run pytest tests/storage -q` — PASS.
- [ ] **Step 5: Commit** `Storage: snapshots of a module, campaign or setting, and backup records (DEL-110)`.

### Task 6: Bundles

**Files:**
- Create: `src/delve/cloud/bundles.py`
- Test: `tests/cloud/test_bundles.py`

**Interfaces:**
- Consumes: `Snapshot`, `storage.snapshots`, `storage.blobs` (Task 5).
- Produces:
  - `EXTENSIONS = {"module": "dmod", "campaign": "dcmp", "setting": "dset"}`; `FORMAT = 1`.
  - `def pack(storage, kind, item_id) -> Packed`, where `@dataclass(frozen=True) class Packed: data: bytes; hash: str;
    title: str`.
    - The zip holds `manifest.json` (`format`, `kind`, `item_id`, `title`, `head`, `delve_version`, `created_at`,
      and for a campaign `module_id`, `revision`, `setting`), `rows/<table>.json` and `blobs/<sha>`.
    - Entries are written in sorted order with fixed timestamps.
    - `hash` is the sha256 of the manifest without `created_at` plus every other entry, so an unchanged item hashes
      the same.
  - `def unpack(data: bytes) -> tuple[Manifest, Snapshot, dict[str, tuple[bytes, str]]]` — refuses
    `format > FORMAT`, a missing manifest, a blob whose bytes don't hash to its name.
  - `def unpack_into(storage, data: bytes, *, replace: bool) -> list[str]` — puts the blobs (`storage.blobs.put`),
    then `storage.snapshots.restore`.

- [ ] **Step 1: Write the failing tests:**
  - `test_pack_then_unpack_into_an_empty_install_restores_the_campaign_and_it_plays_on_its_revision` (Review Focus 1;
    after restore, `context_for(...)` reads the campaign's module at its pinned revision)
  - `test_an_unchanged_item_packs_to_the_same_hash`
  - `test_a_story_entry_changes_the_campaigns_hash`
  - `test_a_newer_format_is_refused`
  - `test_a_tampered_blob_is_refused`
- [ ] **Step 2: Run** `uv run pytest tests/cloud/test_bundles.py -q` — FAIL.
- [ ] **Step 3: Implement** `src/delve/cloud/bundles.py` with `zipfile` (stored, not deflated, for blobs that are
  already compressed images; deflated for `rows/*.json`).
- [ ] **Step 4: Run** `uv run pytest tests/cloud -q` — PASS.
- [ ] **Step 5: Commit** `Cloud: bundles of a module, campaign or setting (DEL-110)`.

### Task 7: The backup run and its schedule

**Files:**
- Create: `src/delve/cloud/backup.py`
- Modify: `src/delve/web/routes/storage.py` (`POST /api/storage/backup` → 202; `GET /api/storage` gains `last_run`),
  `src/delve/web/app.py` (start the schedule task; cancel at stop)
- Test: `tests/cloud/test_backup.py`, `tests/web/test_storage_api.py`

**Interfaces:**
- Consumes: Tasks 4–6.
- Produces:
  - `@dataclass class RunResult: started_at: str; finished_at: str; uploaded: list[str]; unchanged: int; failed:
    list[dict[str, str]]` (`{kind, item_id, title, error}`) with `status` property `"ok" | "partial" | "failed"`.
  - `async def run_backup(storage, store: ObjectStore, install_id: str, *, now) -> RunResult`:
    - For each kind and each `item_ids(kind)`, `pack` (in a worker thread); skip when the hash equals the
      `backup_items` row's.
    - Otherwise `put` to `f"{install_id}/{kind}s/{item_id}.{EXTENSIONS[kind]}"` and record the `BackupItem` only after
      the put succeeded.
    - Then `put` `f"{install_id}/index.json"`: `{install_id, name, updated_at, items: [{kind, item_id, title, hash,
      size, backed_up_at, on_install: true}]}`. Items already in the old index that are gone locally stay, with
      `on_install: false`.
    - The result is stored in `storage.settings` key `"backup"` as `last_run`.
  - `def due(schedule_time: str, last_run_at: str | None, now: datetime) -> bool` — True when today's scheduled time
    has passed and the last run started before it (covers a run missed while Delve was down).
  - `async def schedule_loop(app) -> None` — checks `due` every 60 s; one run at a time (an `asyncio.Lock` shared with
    Back up now; a second Back up now while one runs answers 409).

- [ ] **Step 1: Write the failing tests:**
  - `test_a_first_run_uploads_every_module_campaign_and_setting`
  - `test_a_second_run_uploads_only_what_changed`
  - `test_one_failing_item_makes_the_run_partial_and_is_retried_next_time` (Review Focus 3: a store wrapper that
    raises on one name; that item's `backup_items` row is unchanged; the index lists the rest)
  - `test_an_item_deleted_locally_stays_in_the_index_as_not_on_this_install`
  - `test_due` parametrized: before the time → False; after, not yet run today → True; after, already run → False;
    Delve down at 04:00, started at 09:00 → True
  - `test_backup_now_answers_202_then_409_while_running`
  - `test_backup_never_blocks_a_beat` (a beat closes while a slow store's put waits)
- [ ] **Step 2: Run** `uv run pytest tests/cloud/test_backup.py tests/web/test_storage_api.py -q` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them — PASS.
- [ ] **Step 5: Commit** `Cloud: a daily backup of what changed (DEL-110)`.

### Task 8: Restore

**Files:**
- Create: `src/delve/cloud/restore.py`
- Modify: `src/delve/web/routes/storage.py`
- Test: `tests/cloud/test_restore.py`, `tests/web/test_storage_api.py`

**Interfaces:**
- Consumes: Tasks 4–7.
- Produces:
  - `async def backed_up_installs(store) -> list[dict]` — each `<id>/index.json`'s `{install_id, name, updated_at}`.
  - `async def backup_index(store, install_id) -> list[dict]` — the index's items, each with `exists_here: bool`.
  - `async def restore_items(storage, store, install_id, items: list[tuple[kind, item_id]], *, replace: bool) ->
    list[dict]` — per item `{kind, item_id, ok, warnings, error}`.
    - Adds a campaign's missing module (and setting, when its id is in the index) ahead of it, marked
      `added: true`.
    - Restores modules, then settings, then campaigns.
    - An item that exists here without `replace` answers `error: "exists"` and is left alone.
- Routes (Owner): `GET /api/storage/backups` (installs); `GET /api/storage/backups/{install_id}` (items);
  `POST /api/storage/restore` `{install_id, items: [{kind, item_id}], replace: bool}` → the results. Each restored
  module publishes `modules`, campaign `campaigns`, setting `settings`.

- [ ] **Step 1: Write the failing tests:**
  - `test_restore_a_campaign_brings_its_module_along`
  - `test_an_existing_item_needs_replace`
  - `test_restore_from_another_installs_backups` (new install id)
  - `test_several_items_restore_in_dependency_order`
  - `test_restore_needs_the_owner` (organiser 403)
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `Cloud: restore modules, campaigns and settings from a backup (DEL-110)`.

### Task 9: The library: publish, list, download, delete

**Files:**
- Create: `src/delve/cloud/library.py`, `src/delve/web/routes/library.py`
- Modify: `src/delve/web/app.py` (router)
- Test: `tests/cloud/test_library.py`, `tests/web/test_library_api.py`

**Interfaces:**
- Consumes: `ObjectStore`, `Exists`, `Right` (Task 1); `Stores.library`, `Stores.library_right`, `install_id`
  (Task 4); `export_module` (`delve.modules.exporter`), `export_bundle`, `import_bundle` (`delve.modules.importer`);
  the `modules.library_*` columns (Task 5).
- Produces:
  - `ENTRY_FORMAT = 1`. `@dataclass(frozen=True) class Entry: key: str; version: int; title: str; summary: str;
    author: str; created_at: str; updated_at: str; size: int; hash: str; publisher: str; format: int`.
  - `async def list_entries(store) -> tuple[list[Entry], list[str]]` — the newest version of each key, newest
    `updated_at` first, plus warnings. An `entry.json` that doesn't parse, or has `format > ENTRY_FORMAT`, is skipped
    with a warning naming its key.
  - `async def publish(storage, store, right: Right, module_id: str, *, author: str, install: str, now) -> Entry`:
    - A module without a `library_key`, or one downloaded from another publisher's entry, gets a new key `lib_` + 12
      hex and version 1.
    - A module published from here gets `newest + 1`; that needs `publisher == install` or the `manage` right,
      otherwise `PermissionError`.
    - Creates `module.dscn` before `entry.json`; on `Exists` it rereads the newest version and retries once at the
      next number (Review Focus 4).
    - Refuses `read` (`PermissionError`). An unchanged hash raises `UpToDate`.
    - Sets `library_key`, `library_version`, `library_hash`, `library_origin="published"`, `library_author`.
  - `async def download(storage, store, key: str) -> Module` — `import_bundle` of the newest `module.dscn`; sets
    `library_origin="downloaded"`, key, version, and `library_hash` = the hash of `export_module` of the new local
    module (so later local edits show as a different hash).
  - `async def delete_entry(store, right, key, version: int | None)` — `manage` only; None deletes every version.
  - `def module_hash(storage, module_id) -> str` — sha256 over the `.dscn` export's entries, sorted.
- Routes (Organiser; 409 with "No library store is set up." when unset):
  - `GET /api/library` → `{right, entries: [Entry + {local: {module_id, origin, version} | null}], warnings}`.
  - `POST /api/library/download` `{key}` → the module.
  - `POST /api/modules/{id}/publish` `{author?}` → the entry (403 for `read`, 409 `UpToDate`).
  - `DELETE /api/library/{key}` `?version=N` (403 without `manage`).

- [ ] **Step 1: Write the failing tests** (`LocalStore` per right):
  - `test_publish_creates_v1_with_author_and_dates`
  - `test_publishing_again_after_an_edit_creates_v2_and_keeps_v1`
  - `test_an_unchanged_module_is_up_to_date`
  - `test_a_read_right_cannot_publish`
  - `test_publish_right_cannot_add_a_version_to_anothers_entry_but_creates_its_own`
  - `test_manage_can_add_a_version_to_any_entry_and_delete`
  - `test_two_publishes_at_once_take_the_next_number` (Review Focus 4: a store that raises `Exists` once)
  - `test_a_malformed_or_newer_entry_is_skipped_with_a_warning` (Review Focus 5)
  - `test_download_makes_a_local_module_remembering_its_entry`
  - web: `test_the_library_answers_409_without_a_store`, `test_a_seat_gets_403`, `test_delete_needs_manage`
- [ ] **Step 2: Run** `uv run pytest tests/cloud/test_library.py tests/web/test_library_api.py -q` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `Cloud: a shared module library to publish to and download from (DEL-110)`.

### Task 10: Updates from the library

**Files:**
- Modify: `src/delve/cloud/library.py`, `src/delve/web/routes/library.py`, `src/delve/web/routes/modules.py`
  (`module_json` gains `library: {key, version, origin, newer: int | null, edited: bool} | null`), `src/delve/web/app.py`
  (check at start and on the daily tick)
- Test: `tests/cloud/test_library.py`, `tests/web/test_library_api.py`

**Interfaces:**
- Consumes: Task 9.
- Produces:
  - `async def check_updates(storage, store) -> dict[str, int]` — `{module_id: newest version}` for downloaded
    modules whose entry has a newer version. Kept on `app.state.stores.updates`, refreshed at start, on the daily
    tick and on `GET /api/library`; publishes `modules` when it changes.
  - `def edited(storage, module) -> bool` — `module_hash(...) != module.library_hash`.
  - `async def update(storage, store, module_id, *, keep_copy: bool) -> Module`:
    - With `keep_copy`, first a copy of the local module (export, then import, titled `"<title> (my version)"`).
    - Then `import_bundle` the newest version into a scratch module, and in one transaction move its working copy
      (metadata, maps, texts, source, `module_blobs`) onto `module_id`.
    - Delete the scratch, then `storage.revisions.snapshot(module_id)`.
    - Set `library_version` and `library_hash`. Campaigns keep their pinned revision.
- Route: `POST /api/modules/{id}/library-update` `{keep_copy: bool}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_newer_version_shows_on_the_module`
  - `test_update_makes_a_new_revision_and_campaigns_stay_on_theirs`
  - `test_an_edited_copy_is_flagged_edited`
  - `test_keep_copy_keeps_the_local_version_as_its_own_module`
  - `test_a_module_not_from_the_library_has_library_null`
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/cloud tests/web/test_library_api.py tests/web/test_modules_api.py -q` — PASS.
- [ ] **Step 5: Commit** `Cloud: a newer library version shows on the module, and Update takes it (DEL-110)`.

### Task 11: Web — the Storage section and Restore

**Files:**
- Create: `web/src/cloud/api.ts`, `web/src/preferences/Storage.tsx`, `web/src/preferences/Storage.test.tsx`,
  `web/src/preferences/Restore.tsx`, `web/src/preferences/Restore.test.tsx`
- Modify: `web/src/routes/Preferences.tsx` (render `Storage` beside `Connections`, owner only),
  `web/src/i18n/{en,nl,de,fr,lv}.json`

**Interfaces:**
- Consumes: the Task 4, 7 and 8 routes.
- Produces: `getStorage()`, `putStore(kind, config)`, `removeStore(kind)`, `testStore(kind)`, `putSchedule(time)`,
  `backupNow()`, `getBackups()`, `getBackupIndex(installId)`, `restore(installId, items, replace)` in
  `web/src/cloud/api.ts`, with types matching the routes' answers.
- Behaviour:
  - Two cards, Backup store and Library store. Each has a provider select (Azure / Cloudflare R2 / S3-compatible),
    with fields per provider:
    - Azure: SAS URL.
    - R2: account id, bucket, access key id, secret.
    - S3: endpoint, bucket, keys.
    - R2/S3 library only: publish/manage choice, with the line "On R2 the storage can't tell publish from manage;
      Delve keeps to it, other tools need not."
  - Secret inputs are empty with "set" placeholders, and blank keeps the stored secret. Test and Remove per card. The
    right is shown after a test, and an Azure SAS's expiry is shown, amber within 14 days and red once past.
  - Schedule time input; Back up now; the last run's status, uploaded count and each failure.
  - Restore: an install picker (this install first) and the item list with checkboxes (kind, title, last backed up,
    size, "on this install" / "no longer on this install").
  - Restore selected: a confirmation listing items that exist here (replace). Added dependencies show as ticked and
    locked.

- [ ] **Step 1: Write the failing tests:**
  - `shows the right after a test`
  - `never shows a stored secret`
  - `a blank secret keeps the stored one` (the PUT body has no secret)
  - `back up now shows a partial run's failures`
  - `restore asks before replacing an existing campaign`
  - `a campaign's module is ticked with it`
  - `the section is hidden from an organiser`
- [ ] **Step 2: Run** `cd web && npx vitest run src/preferences` — FAIL.
- [ ] **Step 3: Implement**, with copy in all five languages.
- [ ] **Step 4: Run** `cd web && npm run typecheck && npx vitest run src/preferences` — PASS.
- [ ] **Step 5: Commit** `Web: the Storage section, backup and restore (DEL-110)`.

### Task 12: Web — the Library tab, Publish and Update

**Files:**
- Create: `web/src/modules/Library.tsx`, `web/src/modules/Library.test.tsx`
- Modify: `web/src/routes/Modules.tsx` (a Library tab when the library is set up; an "Update available" badge on a
  module row), `web/src/routes/ModuleDetail.tsx` (Publish to library / New version, Update, Delete from library),
  `web/src/cloud/api.ts`, `web/src/api.ts` (`Module.library`), `web/src/i18n/*.json`, `docs/glossary.md` (Library,
  Publish, Backup store, Library store, in its existing style)

**Interfaces:**
- Consumes: the Task 9 and 10 routes.
- Behaviour:
  - Library rows: title, summary, author, created, last updated (reader's date format), version, size, and a local
    state ("Downloaded", "Published from here", or a Download button).
  - Buttons by right: Publish and New version for publish and up (New version on others' entries only for manage);
    Delete for manage only; none of them for read, with one line "This library is read-only here."
  - Update on a module marked `edited`: a dialog "Your edits to this module will be replaced." with "Keep my version
    as a separate module" checked by default.
  - The first publish shows the entry (title, summary, author editable, version 1).

- [ ] **Step 1: Write the failing tests:**
  - `lists entries with author, created and last updated`
  - `a read right shows no publish or delete`
  - `publish shows the entry before it is made, author editable`
  - `an update available badge shows on the module list`
  - `update on an edited module warns and offers to keep a copy`
  - `a malformed entry's warning is shown above the list`
- [ ] **Step 2: Run** `cd web && npx vitest run src/modules src/routes/Modules.test.tsx src/routes/ModuleDetail.test.tsx`
  — FAIL.
- [ ] **Step 3: Implement**, with copy in all five languages.
- [ ] **Step 4: Run** `make ci` — PASS.
- [ ] **Step 5: Commit** `Web: the module library, publish and update (DEL-110)`.

### Task 13: End to end, and delivery notes

**Files:**
- Create: `tests/e2e/test_cloud_storage.py`
- Modify: `README.md` (a short Storage section: what each store is for; making an Azure SAS with read+list,
  +create, or +write+delete; making an R2 API token, Object Read only or Read & Write, scoped to the bucket)

- [ ] **Step 1: Write** `test_two_installs_share_a_module_and_one_restores_from_its_backup`: two apps on separate
  data dirs and DBs, both pointed at one `LocalStore` library, and the first at a `LocalStore` backup store.
  - Install A publishes a module. B downloads it.
  - A publishes v2. B sees an update and takes it, and B's campaign on v1 stays on its revision.
  - A backs up. A fresh install C restores A's campaign from A's install id, and the campaign plays a beat with the
    fake DM.
- [ ] **Step 2: Run** `uv run pytest tests/e2e/test_cloud_storage.py -q` — PASS (it exercises finished code; if it
  fails, the fix goes in the owning task's file with a test there).
- [ ] **Step 3: Write** the README section.
- [ ] **Step 4: Run** `make ci` — PASS.
- [ ] **Step 5: Commit** `Cloud: two installs share a library and restore from a backup, end to end (DEL-110)`.
