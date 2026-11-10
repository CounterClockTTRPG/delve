# Build Delve plateau 0 (the foundation) exactly as planned in docs/superpowers/plans/2026-10-17-plateau-0-foundation.md.

# Delve plateau 0: the foundation is built

All 11 tasks of `docs/superpowers/plans/2026-10-17-plateau-0-foundation.md` are built test-first and committed, each with the plan's commit message. Everything is merged on `guild/20261017-78263c6a/party`.

**Checked in the integration worktree after the last merge:** `make install && make ci` passes.
- ruff is clean, and import-linter keeps 4 contracts with 0 broken.
- **pytest: 119 passed**, with one harmless Starlette deprecation warning.
- **vitest: 20 passed**; the typecheck and the vite build also pass.
- `delve serve --port 7861` answered `/api/health` with `{"ok":true,"name":"delve","version":"0.0.1"}`. `/` returned the built SPA, and Delve printed the localhost URL and the LAN `#token=` links. The server was stopped afterwards.

## What each task delivered

1. **Skeleton, config and CLI** (Alex)
   - `pyproject.toml` (built with hatchling) and `uv.lock`.
   - A frozen `Config`: data dir from `DELVE_DATA_DIR`, host 0.0.0.0, port 7810.
   - An argparse CLI with `--version`, `serve`, `migrate` and `token`; the Makefile, `.gitignore` and README.
2. **Package boundaries** (Alex)
   - 11 subpackages, each with a docstring taken from spec §5.1.
   - Four import-linter contracts that forbid imports across the boundaries, one per Global Constraints rule.
   - Alex planted a violation for each contract to confirm it breaks; two of these checks are now tests.
3. **Settings and backend choices** (Alex)
   - `Job`, `Effort`, `BackendChoice`, `Settings` and `resolve()`. A malformed stored value never raises; it gives a warning and falls back to the default.
   - `ProviderCapabilities` and a generic `Registry`.
4. **Storage** (Bram)
   - The `Storage` and `SettingsRepository` protocols, and a SQLite implementation through SQLAlchemy Core, with WAL and foreign keys on.
   - Alembic `0001_settings`, run from code with no `alembic.ini`.
   - `open_storage` migrates on open. `SchemaTooNewError` refuses a database at a revision this Delve doesn't know and leaves it unchanged.
   - A reusable contract suite in `tests/storage/contract.py`.
5. **DM provider and the fake DM** (Kenji)
   - The DM event types, `ConversationSpec`, and the `DMConversation` and `DMProvider` protocols.
   - A scripted `FakeDM`: it plays a JSON script and supports cancelling, `side_call` and resume ids.
6. **Image, ruleset and setting interfaces** (Kenji)
   - `ImageRequest` and the image result types. `FakeImages` returns a valid 1×1 PNG for scenes and possessions, and the traits for portraits.
   - `FakeRuleset` and `FakeSetting`, with a little built-in AD&D 2e and Greyhawk data.
7. **Web app, identity and guards** (Daniel)
   - `create_app`. The owner token (48 hex characters, file mode 0600) is accepted from loopback, a Bearer header or the `delve_token` cookie.
   - `require(role)` answers 401 for an unknown caller and 403 for a missing role.
   - A plain ASGI `RequestGuard`. It refuses a bad host (421), a cross-origin request (403) and a write that isn't JSON (415). It adds the CSP and `nosniff` headers to every response.
   - The SPA is served as the 404 fallback, so `/api/*` paths always get JSON. `GET /api/health` needs no token.
8. **Event stream** (Daniel)
   - An `EventBus` with increasing sequence numbers. It keeps the last 500 events and drops a subscriber that falls more than 1000 behind.
   - `GET /api/events` sends server-sent events. It replays from `Last-Event-ID` or `?since=` and sends a ping every 20 s. These tests run against a real uvicorn server on a loopback port.
9. **Settings API** (Daniel)
   - `GET /api/backends`, and `GET`/`PUT /api/settings`.
   - A `PUT` with an unusable choice answers 422 with a warning per job, and nothing is saved.
   - A good save stores the fully resolved settings and publishes a `settings` event.
   - `delve token [--port]` prints the LAN links.
10. **Frontend shell** (Lars)
    - `web/`: Vite, React and TypeScript, pinned to the same version ranges as dungml. The build goes into `src/delve/web/static`.
    - `token.ts` moves `#token=` from the address into a cookie. A 401 anywhere shows the token gate.
    - EN and NL with 49 keys each; a key missing in NL falls back to EN.
    - Six areas: Play, Campaigns, Modules, Maps and House rules are placeholders, and Settings works.
    - The nav is a side bar on desktop and a bottom tab bar on phones, with a light and a dark theme.
    - The Settings page has one row per job (provider, model, effort), saves with JSON, and re-fetches when a `settings` event arrives.
11. **Run, CI and docs** (Jonas)
    - `delve serve` migrates first, and exits 3 when the schema is too new. It binds the socket before uvicorn starts and exits 2 with a clear message when the port is in use. It then prints the URLs and runs a single worker.
    - `delve migrate` prints the head revision.
    - The Makefile's web steps now always run.
    - `README.md`, `GUILD.md` and `tests/test_serve.py`, which includes a smoke test that starts Delve in a subprocess.

The frontend's assumptions about the API and the real endpoints were checked twice, by Daniel and by Jonas. They match exactly; nothing needed fixing.

## Deviations from the plan
- **Plan correction, approved by you at Kenji's check-in.** `DMConversation.send` is written in the Protocol as `def send(self, text) -> AsyncIterator[DMEvent]`, without `async`. `FakeDM` keeps `async def send` with `yield`. This rule applies to every async-iterator member of a Protocol. `EventBus.subscribe` is a method of a concrete class, so it stays `async def` with `yield`.
- **`run(app, sock)` in `delve/web/app.py`.** It is a new function in an existing file. It was needed because import-linter forbids `delve.__main__` from importing uvicorn, so the uvicorn call has to live in `delve.web`.
- **Small additions the plan doesn't name**, made where it left room:
  - helpers: `current_principal`, `job_providers`, `build_registries`, `token_links`, `lan_addresses` and `machine_addresses`;
  - `delve token --port`;
  - `event_to_dict`, so recorded DM scripts can be written as well as read;
  - `# noqa: UP046` on `Registry(Generic[T])`, to keep the plan's form under ruff 0.17.
- **Choices where the plan left room:**
  - The page shown when the frontend hasn't been built answers 200.
  - The LAN links are printed only when Delve listens on all addresses.
  - A `since` beyond the newest event replays the whole buffer, because it is read as coming from before a restart.

No names, signatures, file layout or exact values were changed otherwise, and no runtime dependency was added.

## What plateau 1 should know
- **Tests:** every test folder needs an `__init__.py`, because several fakes' test files are all named `test_fake.py`.
- **Events:**
  - A client that misses more than 500 events gets no "resync" signal yet.
  - The settings handlers call SQLite directly from async handlers. That is fine for now, but `publish` must stay on the event loop.
- **Guard:** it covers HTTP only. Websockets pass through unchecked, which will matter when a later plateau adds sockets.
- **Dev mode:** `delve serve` has no reload. For frontend work, run `npm run dev` (Vite proxies `/api` to 7810) next to `delve serve`.
- **`ReferenceHit`:** it lives in `delve.rules.ruleset`, and `delve.setting` imports it from there. If setting should stand apart from rules, move it to `domain`.
- **`TurnEnd`:** the name stays as the plan gives it and means the end of one DM reply. A go of the table is a *beat*, per the glossary.
- **Dependencies:** Starlette's test client warns that using httpx with it is deprecated; deal with it at the next upgrade.
- **Not tried by hand:** the token gate in a real browser on another device. It is covered only by the tests and a curl 401.
