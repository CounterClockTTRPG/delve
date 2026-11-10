# Delve plateau 0: foundation, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A runnable, installable Delve skeleton:
- one process on one port, serving a single-page app;
- an owner token and LAN-safe request checks;
- a storage layer with migrations;
- the four swappable layers, as interfaces with fake implementations;
- a Settings page that chooses backends, models and effort;
- one `make ci` command.

**Architecture:**
- **Packaging:** one Python package, `delve` (src layout, uv), with internal subpackages whose dependencies point inward,
  enforced by import-linter.
- **Server:** FastAPI serves the API, a server-sent-events stream and the built SPA.
- **Frontend:** React + Vite + TypeScript in `web/`, built into the package.
- **Storage:** only `delve.storage` knows SQL (SQLAlchemy Core on SQLite, Alembic migrations).

**Tech Stack:**
- **Python:** Python ≥ 3.12, uv, FastAPI, uvicorn, SQLAlchemy 2 Core, Alembic, pydantic 2, pytest, httpx, ruff, import-linter.
- **Frontend:** React 18.3, Vite 5, TypeScript 5.6, react-router-dom 6, @tanstack/react-query 5, Vitest 2,
  @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-10-17-unified-app-design.md` (§5 architecture, §5.2 swappable layers and
Settings, §11 security, §12 storage, §13 testing, §14 plateau 0). Terms: `docs/glossary.md`.

## Global Constraints

- **Names:**
  - Product name **Delve**. Python distribution and import package `delve`. CLI command `delve`.
  - Python `requires-python = ">=3.12"`.
- **Port:** default **7810**. Never use 5000, 7777, 7790 or 8000, which are in use on the owner's machine.
- **Data directory:** default `~/.local/share/delve`, overridden by the environment variable `DELVE_DATA_DIR`. The SQLite
  file is `<data dir>/delve.db`, and the owner token is `<data dir>/token` (mode 0600).
- **Dependency rules:**
  - Only `delve.storage` may import `sqlalchemy` or `alembic`.
  - Only `delve.web` may import `fastapi`, `starlette` or `uvicorn`.
  - `delve.domain` imports no other `delve` package.
  - `delve.rules`, `delve.setting`, `delve.maps` and `delve.modules` import none of `delve.web`, `delve.dm`,
    `delve.storage`, `delve.play`.
- **Words:** use the glossary in code, API and UI. Say DM (never GM), beat (never round or turn for a go of the table),
  map state (never session for it), organiser, host, player, observer.
- **UI strings:** every user-visible string comes from the i18n dictionaries. They exist in `en` and `nl`, and `nl` has
  every key `en` has.
- **Request rules:**
  - Every POST, PUT, PATCH and DELETE needs `Content-Type: application/json`, or the answer is 415.
  - Requests with an `Origin` header that doesn't match the request's host are refused with 403.
  - Requests whose `Host` isn't an allowed host are refused with 421.
- **Tests make no network calls** and never run `claude` or any paid service.
- One process, one port: the API, the SSE stream and the SPA are served together.

## Review Focus

1. **A browser on another LAN device opens Delve without the token.** API and SSE calls get 401 with a JSON
   `{"error": …}`. The page shows a "needs its token" prompt with an input, never a blank screen. (Task 7, Task 8 and Task 10 tests.)
2. **Stored settings name a model or provider that no longer exists.** Reading the settings falls back to that job's
   default, and the API reports a `warnings` list. It never fails with a 500. (Task 3 and Task 9 tests.)
3. **The database is from a newer Delve than the code.** `delve serve` refuses to start, with a message naming both
   schema revisions. A missing data directory is created. An older schema is migrated automatically. (Task 4 tests.)
4. **The browser reloads on a client route** (`/settings`, `/modules`). The SPA's `index.html` is served. An unknown
   `/api/...` path gets a JSON 404, never `index.html`. (Task 7 test.)
5. **The port is already in use.** `delve serve` exits with code 2 and a message naming the port and `--port`, not a
   traceback. (Task 11 test.)

---

## File structure

```
pyproject.toml                  package, deps, ruff, pytest, import-linter contracts
Makefile                        install, build, run, ci
README.md                       install and run
GUILD.md                        context for Guild agents working on this repo
src/delve/__init__.py           __version__
src/delve/__main__.py           CLI: delve serve | migrate | token
src/delve/config.py             Config: data dir, host, port
src/delve/domain/settings.py    Job, Effort, BackendChoice, Settings, defaults, resolve()
src/delve/domain/backends.py    ProviderCapabilities, Registry
src/delve/storage/__init__.py   open_storage(config) -> Storage
src/delve/storage/interfaces.py Storage, SettingsRepository protocols
src/delve/storage/sqlite/…      engine, tables, repositories
src/delve/storage/migrations/…  Alembic env and versions
src/delve/dm/provider.py        DMProvider, DMConversation, DMEvent types
src/delve/dm/fake.py            FakeDM (scripted)
src/delve/images/provider.py    ImageProvider, ImageRequest, ImageResult
src/delve/images/fake.py        FakeImages
src/delve/rules/ruleset.py      Ruleset protocol, ReferenceHit
src/delve/setting/setting.py    Setting protocol
src/delve/rules/fake.py, src/delve/setting/fake.py
src/delve/{maps,modules,play,i18n}/__init__.py   empty packages, boundaries only
src/delve/web/app.py            create_app(config, storage, registries)
src/delve/web/auth.py           Identity, Principal, owner-token resolution
src/delve/web/guard.py          JSON-only, Origin and Host checks, CSP
src/delve/web/events.py         EventBus, /api/events SSE
src/delve/web/routes/…          health, settings, backends
src/delve/web/spa.py            static files and SPA fallback
src/delve/web/static/           Vite build output (gitignored)
web/                            the React app
tests/…                         mirrors src/delve
```

---

### Task 1: Project skeleton, configuration and CLI

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `Makefile`, `README.md`, `src/delve/__init__.py`, `src/delve/__main__.py`,
  `src/delve/config.py`
- Test: `tests/test_config.py`, `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `delve.__version__: str = "0.0.1"`.
  - `delve.config.Config` is a frozen dataclass with:
    - `data_dir: Path`;
    - `host: str = "0.0.0.0"`;
    - `port: int = 7810`;
    - `db_path` (property, `data_dir / "delve.db"`);
    - `token_path` (property, `data_dir / "token"`).
  - `Config.from_env(env: Mapping[str, str] = os.environ, **overrides) -> Config`.
  - CLI entry point `delve = "delve.__main__:main"`, with `main(argv: list[str] | None = None) -> int` and the
    subcommands `serve`, `migrate` and `token`. Only `--version` works in this task; the others are wired in later tasks.

- [ ] **Step 1: Write failing tests**

```python
def test_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    c = Config.from_env({})
    assert c.port == 7810 and c.host == "0.0.0.0"
    assert c.data_dir == tmp_path / ".local/share/delve"
    assert c.db_path.name == "delve.db" and c.token_path.name == "token"

def test_env_and_overrides(tmp_path):
    c = Config.from_env({"DELVE_DATA_DIR": str(tmp_path)}, port=7811)
    assert c.data_dir == tmp_path and c.port == 7811

def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "delve 0.0.1"
```

- [ ] **Step 2: Run, expect failure.** `uv run pytest tests/test_config.py tests/test_cli.py` fails with an import error.
- [ ] **Step 3: Implement.**
  - `pyproject.toml`: hatchling backend, src layout, runtime deps `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2.0`,
    `alembic`, `pydantic>=2.7`. Dev group: `pytest`, `httpx`, `ruff`, `import-linter`.
  - `[tool.ruff]`: line length 120, target py312.
  - `.gitignore`: `.venv/`, `node_modules/`, `src/delve/web/static/`, `*.db`, `__pycache__/`.
  - CLI: argparse.
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Delve skeleton: package, config and CLI"`

### Task 2: Package boundaries

**Files:**
- Create: empty `__init__.py` with a one-line docstring naming what the package owns (copy the wording of spec §5.1
  table) for `domain`, `storage`, `rules`, `setting`, `maps`, `modules`, `play`, `dm`, `images`, `i18n`, `web`
- Modify: `pyproject.toml`, adding `[tool.importlinter]` contracts
- Test: `tests/test_boundaries.py`

**Interfaces:**
- Produces: import-linter contracts that later tasks must keep green, exactly the dependency rules in Global
  Constraints. `include_external_packages = true` is needed for the `sqlalchemy`, `fastapi` and `alembic` rules.

- [ ] **Step 1: Write the failing test.** `test_import_contracts_hold` runs `importlinter.cli.lint_imports()` (or
  `subprocess.run(["lint-imports"])`) and asserts exit code 0.
  `test_contract_catches_violation` writes a temporary module `delve/domain/_probe.py` containing `import delve.web`,
  asserts lint-imports fails, then deletes the module in a `finally`.
- [ ] **Step 2: Run, expect failure** (no contracts configured).
- [ ] **Step 3: Add the packages and contracts.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Package boundaries enforced by import-linter"`

### Task 3: Settings and backend choices (domain)

**Files:**
- Create: `src/delve/domain/settings.py`, `src/delve/domain/backends.py`
- Test: `tests/domain/test_settings.py`, `tests/domain/test_backends.py`

**Interfaces:**
- Produces:
  - `class Job(StrEnum)`: `DM = "dm"`, `SIDE = "side"`, `CONVERSION = "conversion"`, `IMAGE_PORTRAIT = "image.portrait"`,
    `IMAGE_SCENE = "image.scene"`, `IMAGE_POSSESSION = "image.possession"`. These are the jobs in spec §5.2.
  - `class Effort(StrEnum)`: `AUTO`, `LOW`, `MEDIUM`, `HIGH`, `MAX`.
  - `@dataclass(frozen=True) class BackendChoice`: `provider: str`, `model: str | None = None`,
    `effort: Effort | None = None`.
  - `@dataclass(frozen=True) class ProviderCapabilities`:
    - `id: str`, `title: str`;
    - `jobs: frozenset[Job]`;
    - `models: tuple[str, ...] = ()`;
    - `efforts: tuple[Effort, ...] = ()`;
    - `default_model: str | None = None`.
  - `class Registry(Generic[T])`:
    - `register(caps: ProviderCapabilities, factory: Callable[[], T]) -> None` (a duplicate id raises `ValueError`);
    - `capabilities() -> list[ProviderCapabilities]`;
    - `get(id: str) -> T`, which raises `KeyError` with the known ids in the message;
    - `for_job(job: Job) -> list[ProviderCapabilities]`.
  - `@dataclass(frozen=True) class Settings`: `choices: Mapping[Job, BackendChoice]`, `language: str = "en"`.
  - `resolve(stored: Mapping[str, Any], available: Sequence[ProviderCapabilities], defaults: Mapping[Job, BackendChoice]) -> tuple[Settings, list[str]]`.
    It returns the usable settings and human-readable warnings. For each job:
    - the stored choice is kept only if its provider exists, supports that job, and its model and effort are among the
      provider's (`None` is always allowed);
    - otherwise the default is used, with a warning such as `"dm: model 'x' is not offered by 'fake'; using default"`;
    - unknown jobs in `stored` are ignored with a warning.

    `language` must be `"en"` or `"nl"`; anything else becomes `"en"` with a warning.

- [ ] **Step 1: Write failing tests.**
  - `test_registry_rejects_duplicate_id`;
  - `test_registry_get_unknown_lists_known_ids`;
  - `test_for_job_filters`;
  - `test_resolve_keeps_valid_choice`;
  - `test_resolve_falls_back_on_unknown_provider`;
  - `test_resolve_falls_back_on_unoffered_model_and_effort`;
  - `test_resolve_falls_back_when_provider_lacks_job`;
  - `test_resolve_ignores_unknown_job_with_warning`;
  - `test_resolve_bad_language_becomes_en`.

  Each asserts the exact resulting `BackendChoice` and that exactly one warning names the job.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Settings: jobs, backend choices and their resolution"`

### Task 4: Storage layer, migrations and contract tests

**Files:**
- Create:
  - `src/delve/storage/__init__.py`, `interfaces.py`;
  - `src/delve/storage/sqlite/engine.py`, `tables.py`, `settings_repo.py`;
  - `src/delve/storage/migrations/env.py`, `script.py.mako`, `versions/0001_settings.py`.
- Test: `tests/storage/contract.py` (the reusable suite), `tests/storage/test_sqlite.py`, `tests/storage/test_migrations.py`

**Interfaces:**
- Consumes: `Config` (Task 1).
- Produces:
  - `class SettingsRepository(Protocol)`: `load() -> dict[str, Any]` (raw stored JSON, `{}` when nothing is stored) and
    `save(raw: dict[str, Any]) -> None`.
  - `class Storage(Protocol)`: `settings: SettingsRepository`, and `close() -> None`.
  - `open_storage(config: Config) -> Storage`:
    - creates `data_dir` if missing;
    - opens SQLite at `config.db_path` with WAL and `foreign_keys=ON`;
    - runs Alembic migrations up to head.
  - `class SchemaTooNewError(RuntimeError)`, carrying `db_revision` and `code_head`.
  - `migrate(config) -> str`, which returns the head revision. It backs `delve migrate`.
  - `run_contract_suite(make_storage: Callable[[], Storage])` in `tests/storage/contract.py`. The future Postgres backend
    reuses it.
  - Table `settings(key TEXT PRIMARY KEY, value JSON NOT NULL, updated_at TEXT NOT NULL)`. The whole settings dict is
    stored under `key = "app"`.
- **Rules:** Alembic runs programmatically (`alembic.command.upgrade` with a `Config` built in code). There's no
  `alembic.ini` in the repo root. Repositories use SQLAlchemy Core `Table` objects and never use the ORM.

- [ ] **Step 1: Write failing tests.**
  - Contract: `test_settings_empty_load` (`{}`), `test_settings_roundtrip` (a nested dict), `test_settings_overwrite`.
  - SQLite:
    - `test_open_creates_data_dir_and_db`;
    - `test_wal_enabled` (`PRAGMA journal_mode` → `wal`);
    - `test_contract_suite_sqlite`, which calls `run_contract_suite` against `open_storage` on `tmp_path`.
  - Migrations:
    - `test_fresh_db_is_at_head`;
    - `test_reopen_is_idempotent`;
    - `test_newer_schema_refused`: stamp the `alembic_version` table with `"9999_future"`, then
      `pytest.raises(SchemaTooNewError)`. The message contains both `"9999_future"` and the head revision id.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.** The newer-schema check compares the stored revision against the script directory's known
  revisions before upgrading.
- [ ] **Step 4: Run, expect them to pass.** Also run `uv run lint-imports`, which must pass.
- [ ] **Step 5: Commit.** `git commit -m "Storage: SQLite through SQLAlchemy Core, Alembic migrations, contract suite"`

### Task 5: DM provider interface and the fake DM

**Files:**
- Create: `src/delve/dm/provider.py`, `src/delve/dm/fake.py`
- Test: `tests/dm/test_fake.py`

**Interfaces:**
- Consumes: `ProviderCapabilities`, `Job`, `Effort`, `BackendChoice` (Task 3).
- Produces (spec §5.2, §6.1):
  - Event dataclasses, frozen. `DMEvent` is their union:
    - `TextDelta(text: str)`;
    - `ToolCall(id: str, name: str, args: dict)`;
    - `ToolResult(id: str, ok: bool, content: Any)`;
    - `Usage(input_tokens: int, output_tokens: int, cost_usd: float | None)`;
    - `TurnEnd(reason: Literal["done", "error", "cancelled"])`;
    - `DMError(message: str, retryable: bool)`.
  - `@dataclass(frozen=True) class ConversationSpec`:
    - `campaign_id: str`;
    - `system_prompt: str`;
    - `choice: BackendChoice`;
    - `resume_id: str | None = None`.
  - `class DMConversation(Protocol)`:
    - `id: str`;
    - `def send(self, text: str) -> AsyncIterator[DMEvent]` (implemented as an async generator), which always ends with exactly one `TurnEnd`;
    - `async def cancel(self) -> None`;
    - `async def close(self) -> None`.
  - `class DMProvider(Protocol)`:
    - `capabilities: ProviderCapabilities`;
    - `async def open(self, spec: ConversationSpec) -> DMConversation`;
    - `async def side_call(self, prompt: str, choice: BackendChoice) -> str`, a stateless call with no tools.
  - `FakeDM(script: list[list[DMEvent]], side_answers: dict[str, str] | None = None)`. Each `send` replays the next
    script entry and appends `TurnEnd("done")` if the entry has none. When the script runs out, it yields
    `DMError("script exhausted", False)` and then `TurnEnd("error")`. It records `sent: list[str]`. Its id is `"fake"`,
    with jobs DM, SIDE and CONVERSION, models `("fake-large", "fake-small")`, and all efforts.
  - `FakeDM.from_json(path: Path)` loads a script fixture, `[[{"type": "text", "text": "…"}, …], …]`, so later
    plateaus can record replays.

- [ ] **Step 1: Write failing tests.**
  - `test_send_replays_in_order_and_ends_once`;
  - `test_exhausted_script_errors`;
  - `test_cancel_ends_with_cancelled` (cancel during a send yields `TurnEnd("cancelled")` and nothing after it);
  - `test_side_call_returns_answer`;
  - `test_from_json_roundtrip`;
  - `test_sent_records_inputs`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "DM provider interface and a scripted fake DM"`

### Task 6: Image provider interface, rulesets and settings

**Files:**
- Create:
  - `src/delve/images/provider.py`, `src/delve/images/fake.py`;
  - `src/delve/rules/ruleset.py`, `src/delve/rules/fake.py`;
  - `src/delve/setting/setting.py`, `src/delve/setting/fake.py`.
- Test: `tests/images/test_fake.py`, `tests/rules/test_fake.py`, `tests/setting/test_fake.py`

**Interfaces:**
- Consumes: `ProviderCapabilities`, `Job`, `BackendChoice` (Task 3).
- Produces (spec §5.2, §10):
  - **Images:**
    - `@dataclass(frozen=True) class ImageRequest`: `job: Job` (one of the IMAGE_* jobs), `prompt: str`,
      `choice: BackendChoice`, `references: tuple[bytes, ...] = ()`.
    - `ImageResult = ImageFile | PortraitTraits`, with `ImageFile(data: bytes, mime: str)` and
      `PortraitTraits(describe: str, traits: dict | None)`. `PortraitTraits` is rendered in the browser by portraitgen
      (spec §5.2).
    - `class ImageProvider(Protocol)`: `capabilities`, and `async def generate(self, req: ImageRequest) -> ImageResult`.
    - `FakeImages` returns a fixed 1×1 PNG as `ImageFile` for scenes and possessions, and `PortraitTraits(prompt, None)`
      for portraits. Its id is `"fake-images"`.
  - **Rulesets:**
    - `@dataclass(frozen=True) class ReferenceHit`: `kind: str`, `key: str`, `title: str`, `text: str`.
    - `class Ruleset(Protocol)`: `id: str`, `title: str`, `kinds() -> tuple[str, ...]`,
      `lookup(kind: str, query: str, limit: int = 5) -> list[ReferenceHit]`.
    - `FakeRuleset` (id `"fake-rules"`) holds a dict of hits, and `lookup` matches case-insensitively on the title.
  - **Settings (the world, spec §10):**
    - `class Setting(Protocol)`: the same shape as `Ruleset`, with the kinds `place`, `deity` and `faction`.
    - `FakeSetting` (id `"fake-setting"`).
  - Unknown `kind` raises `ValueError` listing the kinds, for both `Ruleset` and `Setting`.

- [ ] **Step 1: Write failing tests.**
  - `test_fake_images_portrait_returns_traits`;
  - `test_fake_images_scene_returns_png` (the data starts with `b"\x89PNG"`);
  - `test_ruleset_lookup_case_insensitive`;
  - `test_ruleset_unknown_kind_lists_kinds`;
  - `test_setting_lookup`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.** Run `uv run lint-imports` too, because `rules` and `setting` must stay free of
  web, dm and storage.
- [ ] **Step 5: Commit.** `git commit -m "Image, ruleset and setting interfaces with fakes"`

### Task 7: The web app, identity and request guards

**Files:**
- Create:
  - `src/delve/web/app.py`, `auth.py`, `guard.py`, `spa.py`;
  - `src/delve/web/routes/__init__.py`, `routes/health.py`.
- Test: `tests/web/test_auth.py`, `tests/web/test_guard.py`, `tests/web/test_spa.py`, `tests/web/conftest.py`

**Interfaces:**
- Consumes: `Config`, `open_storage`, `Storage`, `Registry`.
- Produces:
  - `@dataclass class Registries`:
    - `dm: Registry[DMProvider]`;
    - `images: Registry[ImageProvider]`;
    - `rulesets: Registry[Ruleset]`;
    - `settings_: Registry[Setting]`, named so to avoid clashing with app settings. The builder may rename it to
      `worlds`, but must keep the glossary word "setting" in docs.
  - `create_app(config: Config, storage: Storage, registries: Registries, static_dir: Path | None = None) -> FastAPI`.
    `static_dir` defaults to `delve/web/static`.
  - `@dataclass(frozen=True) class Principal`: `id: str`, `roles: frozenset[str]`. Plateau 0 has only `"owner"`,
    whose roles are `{"organiser"}`.
  - `class Identity(Protocol)`: `resolve(request) -> Principal | None`. The plateau 0 implementation is
    `OwnerTokenIdentity(token: str)`:
    - a request from a loopback client address (`127.0.0.1`, `::1`) is the owner;
    - so is a request with header `Authorization: Bearer <token>` or cookie `delve_token=<token>`;
    - anything else resolves to `None`.
  - `load_or_create_token(config) -> str`: 24 random bytes as hex, written with mode 0600, reused on later starts.
  - A FastAPI dependency `require(role: str)` that raises 401 `{"error": "Open the link Delve printed at start."}` when
    there is no principal, and 403 when the principal lacks the role.
  - `guard.py` middleware, applied to every request:
    - **Host check:** the host must be `localhost`, `127.0.0.1`, `[::1]`, any address of the machine's interfaces, or
      one listed in `DELVE_ALLOWED_HOSTS` (comma-separated), with any port. Otherwise 421.
    - **Origin check:** if `Origin` is present, its host:port must equal the request's `Host`. Otherwise 403.
    - **Write methods** need `Content-Type: application/json`. Otherwise 415.
    - **Response headers:** `Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`,
      plus `X-Content-Type-Options: nosniff`.
  - `GET /api/health`, without auth: `{"ok": true, "name": "delve", "version": __version__}`.
  - SPA serving:
    - files under `static_dir`;
    - any non-`/api` GET with no matching file returns `index.html`;
    - `/api/*` with no route returns JSON 404 `{"error": "not found"}`;
    - when `static_dir` has no `index.html`, a plain page says to run `make build`.
- **TestClient note:** its client address is `testclient`, which is not loopback. Tests of loopback behaviour override the
  client via `TestClient(app, client=("127.0.0.1", 50000))` (httpx transport) or an equivalent fixture in `conftest.py`.

- [ ] **Step 1: Write failing tests.**
  - `test_health_open`;
  - `test_lan_without_token_401_json`;
  - `test_loopback_is_owner`;
  - `test_bearer_token_ok`;
  - `test_cookie_token_ok`;
  - `test_wrong_token_401`;
  - `test_token_file_created_0600_and_reused`;
  - `test_post_form_encoded_415`;
  - `test_cross_origin_403`;
  - `test_bad_host_421`;
  - `test_allowed_hosts_env`;
  - `test_csp_header_present`;
  - `test_spa_fallback_serves_index_for_client_route` (`/settings` returns index.html);
  - `test_unknown_api_path_json_404`;
  - `test_missing_build_message`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Web app: owner token identity, request guards, SPA serving"`

### Task 8: Event stream

**Files:**
- Create: `src/delve/web/events.py`
- Modify: `src/delve/web/app.py` (mount `/api/events`)
- Test: `tests/web/test_events.py`

**Interfaces:**
- Consumes: `create_app`, `require` (Task 7).
- Produces:
  - `class EventBus`:
    - `publish(type: str, data: dict) -> int`, which assigns an increasing `seq` and returns it;
    - `subscribe(since: int | None) -> AsyncIterator[Event]`, which first replays buffered events with `seq > since`
      and then streams live ones;
    - it keeps a ring buffer of 500 events;
    - a subscriber more than 1000 events behind is dropped.
  - `@dataclass(frozen=True) class Event`: `seq: int`, `type: str`, `data: dict`.
  - `GET /api/events` (needs a principal):
    - SSE frames `id: <seq>\nevent: <type>\ndata: <json>\n\n`;
    - honours the `Last-Event-ID` header or `?since=`;
    - sends a `: ping` comment every 20 s.
  - `app.state.events: EventBus`, which Task 9 publishes on.

- [ ] **Step 1: Write failing tests.**
  - `test_publish_assigns_increasing_seq`;
  - `test_subscribe_replays_since`;
  - `test_slow_subscriber_dropped`;
  - `test_sse_requires_principal` (401 from LAN);
  - `test_sse_frame_format`, which publishes one event and reads the first frame through an async httpx client with a
    timeout.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Event stream with replay"`

### Task 9: Settings API

**Files:**
- Create: `src/delve/web/routes/settings.py`, `src/delve/web/defaults.py`
- Modify: `src/delve/web/app.py`, `src/delve/__main__.py` (`delve token` prints the LAN URLs, `http://<ip>:<port>/#token=<token>`)
- Test: `tests/web/test_settings_api.py`, `tests/test_cli.py` (add `test_token_prints_links`)

**Interfaces:**
- Consumes: `resolve`, `Settings`, `Job`, `BackendChoice`, `Registries`, `Storage.settings`, `EventBus`.
- Produces:
  - `default_choices(registries) -> dict[Job, BackendChoice]`. For each job it picks the first registered provider that
    supports the job, with its `default_model` and `Effort.AUTO` when that is offered.
  - `GET /api/backends` (organiser): `{"jobs": [...], "providers": [ProviderCapabilities as JSON]}`.
  - `GET /api/settings` (organiser): `{"choices": {job: {provider, model, effort}}, "language": "en", "warnings": [...]}`.
  - `PUT /api/settings` (organiser). It takes the same shape without `warnings`. If the input would produce any warning,
    it is refused with 422 `{"error": …, "warnings": [...]}`, so only valid choices are saved. On success it stores the
    settings, publishes the event `settings` with the new settings, and returns them.
  - Registries at startup (`__main__.serve`): plateau 0 registers `FakeDM`, `FakeImages`, `FakeRuleset` and
    `FakeSetting`, each under its id with a title that has `(development)` appended. Real providers come in plateau 2 and
    later.

- [ ] **Step 1: Write failing tests.**
  - `test_backends_lists_providers_and_jobs`;
  - `test_settings_defaults_when_empty`;
  - `test_put_valid_settings_persists_and_publishes`;
  - `test_put_invalid_model_422_with_warning`;
  - `test_stored_stale_choice_falls_back_with_warning`: write raw settings that name provider `"gone"` directly through
    the storage repo, then GET. It returns 200 with the default and one warning, never a 500.
  - `test_settings_need_organiser` (401 from LAN without a token);
  - `test_token_prints_links`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect them to pass.**
- [ ] **Step 5: Commit.** `git commit -m "Settings API: backends, models and effort per job"`

### Task 10: The frontend shell

**Files:**
- Create:
  - `web/package.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/index.html`;
  - `web/src/main.tsx`, `web/src/App.tsx`, `web/src/api.ts`, `web/src/token.ts`;
  - `web/src/i18n/{index.ts,en.json,nl.json}`;
  - `web/src/routes/{Play,Campaigns,Modules,Maps,HouseRules,Settings}.tsx`, `web/src/components/{Nav,TokenGate}.tsx`;
  - `web/src/styles.css`.
- Test: `web/src/i18n/i18n.test.ts`, `web/src/token.test.ts`, `web/src/routes/Settings.test.tsx`, `web/src/App.test.tsx`

**Interfaces:**
- Consumes: `/api/health`, `/api/backends`, `/api/settings`, `/api/events`, and the 401 shape (Tasks 7–9).
- Produces:
  - Vite builds into `../src/delve/web/static` (`build.outDir`, `emptyOutDir: true`). The dev server proxies `/api` to
    `http://127.0.0.1:7810`.
  - `token.ts`, which:
    - reads `#token=…` from the URL;
    - stores it as the cookie `delve_token` (`Path=/; SameSite=Strict; Max-Age=31536000`);
    - removes it from the address bar with `history.replaceState`.
  - `api.ts` `apiFetch(path, init)`. It always sends JSON for writes and throws `NeedsToken` on 401.
  - Routes `/play`, `/campaigns`, `/modules`, `/maps`, `/house-rules` and `/settings`, with `/` redirecting to
    `/campaigns`. All but Settings are placeholders showing their name and "Coming in a later plateau" (translated).
  - Nav: a side bar at ≥ 900 px, and a bottom tab bar below 900 px (phone and narrow tablet).
  - Theme: CSS variables, with a light theme and a dark one under `prefers-color-scheme: dark`.
  - Settings page:
    - one row per job from `/api/backends`, with a provider select (filtered to providers supporting the job), a model
      select (that provider's models, plus "provider default") and an effort select (that provider's efforts);
    - a language select (English / Nederlands);
    - Save does the PUT, shows the 422 warnings inline, and shows a "Saved" status;
    - on load, it shows the server's `warnings` as a notice;
    - it re-fetches on the SSE `settings` event.
  - `TokenGate`: when any call throws `NeedsToken`, the app shows "Delve needs its token" with a token input that sets
    the cookie and reloads.
  - i18n: `t(key)` from a React context. The language comes from the settings, and falls back to `en`.

- [ ] **Step 1: Write failing tests.**
  - `test_nl_has_every_en_key` (and no extra keys);
  - `test_token_from_hash_sets_cookie_and_strips_url`;
  - `Settings` lists the jobs and filters providers per job;
  - changing the provider resets the model to "provider default";
  - a 422 shows its warning text;
  - `App` renders `TokenGate` when `/api/settings` returns 401.

  Mock `fetch` in the tests.
- [ ] **Step 2: Run, expect failure.** `cd web && npm test` fails.
- [ ] **Step 3: Implement.** Pin the dungml versions: react and react-dom ^18.3.1, vite ^5.4.10, typescript ^5.6.3,
  @vitejs/plugin-react ^4.3.3, react-router-dom ^6.27.0, @tanstack/react-query ^5.59.0, vitest ^2.1.9, plus
  @testing-library/react and jsdom. Add the scripts `dev`, `build` (`tsc -b && vite build`), `typecheck` and `test`
  (`vitest run`).
- [ ] **Step 4: Run, expect them to pass.** `npm test`, `npm run typecheck` and `npm run build` all succeed, and
  `src/delve/web/static/index.html` exists.
- [ ] **Step 5: Commit.** `git commit -m "Frontend shell: areas, EN/NL, token gate, Settings page"`

### Task 11: Run, CI and the repo's own docs

**Files:**
- Modify: `src/delve/__main__.py` (`serve`, `migrate`), `Makefile`, `README.md`
- Create: `GUILD.md`, `tests/test_serve.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `delve serve [--host H] [--port P]`. It:
    1. opens storage (migrating it);
    2. loads or creates the token;
    3. builds the registries;
    4. prints the localhost URL and the LAN `#token=` URLs;
    5. runs uvicorn with a single worker.
  - Exit codes for `delve serve`:
    - **2:** the port is in use. It prints `Port <P> is in use; start with --port <other>`. The check binds a socket
      before starting uvicorn.
    - **3:** `SchemaTooNewError`, printing its message.
  - `delve migrate`: prints the head revision and exits 0.
  - Makefile targets:
    - `install`: `uv sync` and `cd web && npm ci`;
    - `build`: the web build;
    - `run`: build, then `uv run delve serve`;
    - `ci`: `uv run ruff check src tests`, `uv run lint-imports`, `uv run pytest`, `cd web && npm run typecheck && npm test && npm run build`.
  - `README.md`: what Delve is (one paragraph, from spec §1), install, run, the token link, and where data lives.
  - `GUILD.md`, for agents:
    - the spec and glossary paths;
    - the Global Constraints of this plan;
    - "run `make ci` before finishing";
    - "never run `claude` or paid services in tests";
    - "don't use ports 5000, 7777, 7790 or 8000".

- [ ] **Step 1: Write failing tests.**
  - `test_serve_port_in_use_exits_2`: bind a socket on a free port, run `main(["serve", "--port", str(p)])`, and assert
    the return value 2 and the message.
  - `test_serve_schema_too_new_exits_3`;
  - `test_serve_smoke`: start `delve serve` as a subprocess on a free port with `DELVE_DATA_DIR=tmp`. Poll
    `/api/health` until it's ok (within 10 s), then GET `/` (200) and terminate the process.
  - `test_migrate_prints_head`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `make ci`.** It exits 0, and every step passes.
- [ ] **Step 5: Commit.** `git commit -m "delve serve, make ci, README and GUILD.md"`

---

## Done when

- `make install && make ci` passes on a fresh clone.
- `make run` starts Delve on port 7810. A browser on localhost shows the six areas with nav in English or Dutch, and the
  Settings page saves backend, model and effort choices per job.
- Another LAN device sees the token gate until it opens the printed `#token=` link.
- `uv run lint-imports` passes. Nothing outside `delve.storage` imports SQLAlchemy.
