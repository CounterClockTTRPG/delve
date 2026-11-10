# Delve plateau 1: maps, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maps in Delve:
- dungml's map language, renderer and fog of war as internal packages;
- modules that consist of maps, created in Delve or imported from `.dscn`;
- the map editor as its own screen;
- campaigns started from a module revision, with a **map state** that keeps a position and discovered rooms **per character**.

**Architecture:**
- **Copied code:** dungml's `dsl` package becomes `delve.maps.dsl` and its `scenario` package becomes
  `delve.modules.dscn`. Both are copied with their tests.
- **Map state** is new, pure code in `delve.maps.state`, built on the DSL's fog functions.
- **Storage** gets repositories for modules, revisions, campaigns, characters, map states and blobs.
- **API:** the web layer exposes module, map, DSL, campaign and map-state routes.
- **Frontend:** the SPA gets the ported editor, with Monaco bundled locally, plus module and campaign pages.

**Tech Stack:**
- **Python:** as plateau 0, plus `lark>=1.2.2`, `shapely>=2.0`, `pyyaml>=6.0`, `jsonschema>=4.21` and `markdown-it-py>=3.0`.
- **Frontend:** as plateau 0, plus `@monaco-editor/react ^4.6.0`, `monaco-editor ^0.52.0` and `lucide-react ^1.21.0`.

**Spec:** `docs/superpowers/specs/2026-10-17-unified-app-design.md`:
- §4: what is taken from dungml and how it is copied;
- §7.4: split party;
- §7.5: the fourth wall;
- §8.1: modules, revisions, maps-only modules;
- §14: plateau 1.

Terms: `docs/glossary.md`.

**Source to port:** `/home/raf/claude/dungml` at commit `a66a1bb`. It is read-only, so copy from it and never edit it.

## Global Constraints

- **Everything in plateau 0's Global Constraints still holds:** ports, data directory, import rules, glossary words,
  EN/NL strings, JSON-only writes except the one upload exception in Task 6, and no network or `claude` in tests.
- **Package paths:** the DSL lives at `src/delve/maps/dsl/` and the scenario package at `src/delve/modules/dscn/`. Each
  package's `__init__.py` docstring ends with `Ported from dungml (commit a66a1bb).`
- **Import rules:**
  - `delve.maps` must not import `delve.modules`; `delve.modules` may import `delve.maps`.
  - Neither may import `delve.web`, `delve.storage`, `delve.dm` or `delve.play`.
  - Add a contract for "maps does not import modules".
- **Ported behaviour is kept.** Copied code changes only where a task says so: imports, resource paths, and the new
  `party_locations` render argument. Every copied test keeps passing.
- **Fog invariants from dungml/CLAUDE.md:**
  - fog is computed by the pure `fog_of_war`, never in a renderer;
  - what is secret is decided only in `room_context` and `secrets`;
  - a marker shows to players only in a discovered node;
  - SVG ids stay namespaced per drawing.
- **The players' view and the DM view are separate routes.** No query parameter switches one into the other.
- **Ids are typed strings:** `mod_<12 hex>` for modules, `cmp_<12 hex>` for campaigns, `chr_<12 hex>` for characters.
  Map names are the module's map entry names (for example `crypt`).
- The frontend loads nothing from a CDN. The CSP keeps every source `'self'` (plus `data:` and `blob:` where already
  allowed, and `worker-src 'self' blob:` for Monaco).

## Review Focus

1. **A map whose source doesn't parse.**
   - Render and save routes answer 400 `{"error", "line", "column"}`, never a 500, and the editor shows the error at its
     line.
   - A campaign whose pinned map doesn't parse answers 409 `{"error": "map offline"}` on its view routes.

   Tests in Tasks 6 and 7.
2. **A hostile or malformed `.dscn` upload:** a zip with `../` paths, a zip bomb past `DEFAULT_LIMITS`, a missing
   `scenario.json`, or a wrong content type. It gets 400 or 415 with a reason, and nothing is stored: no module and no
   blob. (Task 6 test.)
3. **The fog view leaks nothing.** Plant a secret room and a marker labelled `SECRET-XYZZY`. The characters' view never
   contains it until it's revealed or discovered. A character with no position gets the "map offline" 409, never the full
   map. (Task 7 test.)
4. **A module edited after a campaign started.**
   - The campaign's map view is unchanged until the host upgrades the campaign.
   - Upgrading keeps the discovery of nodes that still exist and drops ids that are gone.

   (Tasks 4 and 7 tests.)
5. **Offline editing.** The editor makes no request to any CDN: Monaco is loaded from the bundle via `loader.config`.
   The CSP has no external host. (Task 8 and Task 10 tests.)

---

## File structure

```
src/delve/maps/dsl/…            copied from dungml packages/dsl/src/dungml (grammar.lark, includes/, render/ …)
src/delve/maps/state.py         MapState, CharacterView and the operations on them (new, pure)
src/delve/modules/dscn/…        copied from dungml packages/scenario/src/dungml_scenario (+ scenario.schema.json)
src/delve/domain/modules.py     Module, ModuleMap, Revision
src/delve/domain/campaigns.py   Campaign, Character
src/delve/storage/interfaces.py add ModuleRepository, CampaignRepository, CharacterRepository, MapStateRepository, BlobStore
src/delve/storage/sqlite/…      their SQLite implementations; blobs on disk under <data dir>/blobs/
src/delve/storage/migrations/versions/0002_modules_campaigns.py
src/delve/web/routes/modules.py, maps.py, dsl.py, campaigns.py, map_state.py
tests/maps/dsl/…                copied dsl tests;  tests/modules/dscn/… copied scenario tests
tests/fixtures/samples/…        copied from dungml samples/
web/src/editor/…                ported editor components;  web/src/routes/{Modules,ModuleDetail,MapEditor,MapPrint,Campaigns,CampaignDetail}.tsx
```

---

### Task 1: The DSL as `delve.maps.dsl`, and a package that carries its files

**Files:**
- Create: `src/delve/maps/dsl/` (copied), `tests/maps/dsl/` (copied), `tests/fixtures/samples/` (copied),
  `tests/test_wheel.py`
- Modify: `pyproject.toml` (add the deps lark and shapely, the import contract, and the hatch build settings)

**Interfaces:**
- Produces:
  - the DSL's public API as in dungml's `__init__.py`, imported as `from delve.maps.dsl import parse, render, build_graph, fog_of_war, render_fogged, room_context, SessionView, …`;
  - `delve.maps.dsl.__version__ = "0.1.0+a66a1bb"`;
  - the samples, in the test helper `tests/fixtures/__init__.py` as `SAMPLES: Path`.

- [ ] **Step 1: Copy.** Copy `dungml/packages/dsl/src/dungml/*` to `src/delve/maps/dsl/`, with `grammar.lark` and
  `includes/*.dmap`. Copy the tests to `tests/maps/dsl/`, `samples/` to `tests/fixtures/samples/`, and
  `tests/data/golden_builtin_glyphs.json` with them.
- [ ] **Step 2: Rewrite the test imports.** `import dungml` and `from dungml…` become `delve.maps.dsl`.
  - Repoint `parents[3]/"samples"` to `SAMPLES`.
  - Fix the CWD-relative `Path("samples/…")` in `test_overlap.py:148,152`.
  - Delete `test_cli.py::test_console_script_works`; Delve has no `dmap` console script. Keep the other CLI tests by
    calling `delve.maps.dsl.cli.main` directly.
- [ ] **Step 3: Write `tests/test_wheel.py::test_wheel_contains_data_files`.** Build the wheel with
  `uv build --wheel -o <tmp>` and list it with `zipfile`. Assert that these are present:
  - `delve/maps/dsl/grammar.lark`;
  - at least one `delve/maps/dsl/includes/*.dmap`;
  - `delve/web/static/index.html` (run `make build` first; skip with a clear reason if `src/delve/web/static` doesn't
    exist).
- [ ] **Step 4: Run, expect failures.** The test imports fail before the deps are in, and the wheel test fails because
  `static/` is gitignored and hatch drops it.
- [ ] **Step 5: Fix the build.**
  - Add `lark>=1.2.2` and `shapely>=2.0` to `pyproject.toml`.
  - Add `[tool.hatch.build.targets.wheel] artifacts = ["src/delve/web/static/**"]`.
  - Add the import-linter contract "delve.maps does not import delve.modules".
- [ ] **Step 6: Run.** `uv run pytest tests/maps tests/test_wheel.py` and `uv run lint-imports` pass. The copied test
  count matches dungml's: report it.
- [ ] **Step 7: Commit.** `git commit -m "Maps: the dungml DSL as delve.maps.dsl, with its tests"`

### Task 2: `.dscn` as `delve.modules.dscn`

**Files:**
- Create: `src/delve/modules/dscn/` (copied, with `scenario.schema.json`), `tests/modules/dscn/` (copied)
- Modify: `pyproject.toml` (pyyaml, jsonschema, markdown-it-py)

**Interfaces:**
- Consumes: `delve.maps.dsl` (Task 1).
- Produces: `from delve.modules.dscn import Bundle, check, validate, schema, keyed_texts, DEFAULT_LIMITS, …`, the same
  API as `dungml_scenario`.

- [ ] **Step 1: Copy** the sources and tests. In the sources, the lazy `import dungml` / `from dungml…` become
  `delve.maps.dsl`. In the tests, `dungml_scenario` becomes `delve.modules.dscn`, and `SAMPLE` points into
  `tests/fixtures/samples/scenarios/crypt-of-saint-vellis`.
- [ ] **Step 2: Fix the resource and version lookups.**
  - `validate.schema()` uses `importlib.resources.files("delve.modules.dscn")`.
  - `validate._dungml_version()` returns `delve.maps.dsl.__version__` without its local suffix (`"0.1.0"`), so the
    manifest's `requires.dungml` check keeps working.
  - `test_scn_validate.py:123` monkeypatches `sys.modules["delve.maps.dsl"]`.
- [ ] **Step 3: Write `test_requires_dungml_checked`:** a manifest with `requires: {dungml: ">=99"}` gives a warning
  diagnostic with code `requires` whose message names `0.1.0`, as the copied code does. This proves the version check
  still runs.
- [ ] **Step 4: Run.** `uv run pytest tests/modules` passes, with all 51 copied tests plus the new one.
  `lint-imports` passes. Extend `test_wheel_contains_data_files` with `delve/modules/dscn/scenario.schema.json`, and it
  passes.
- [ ] **Step 5: Commit.** `git commit -m "Modules: the .dscn package as delve.modules.dscn"`

### Task 3: One party marker per group in the fog render

**Files:**
- Modify: `src/delve/maps/dsl/play.py` (`render_fogged`), `src/delve/maps/dsl/render/classic_bw.py` only if the
  party disc is drawn there
- Test: `tests/maps/test_party_locations.py`

**Interfaces:**
- Produces:
  `render_fogged(dmap, discovered_nodes, discovered_doors, *, party_location=None, party_locations: Sequence[str] = (), renderer=None, full=False, revealed=()) -> str`.
  - It draws one party disc per distinct node in `party_locations`, in order. When both arguments are given,
    `party_location` is drawn first.
  - Every disc has `class="party"` and a `data-node="<node id>"` attribute.
  - With only `party_location`, the output is byte-identical to before.

- [ ] **Step 1: Write the failing tests.**
  - `test_two_groups_draw_two_discs` (two `class="party"` elements, with the right `data-node`);
  - `test_duplicate_locations_draw_once`;
  - `test_single_party_location_unchanged`, which compares against the SVG from the unmodified call on a sample map,
    captured before the change into `tests/maps/data/fogged_single.svg`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement** with the smallest change to `render_fogged`.
- [ ] **Step 4: Run.** `uv run pytest tests/maps` all pass.
- [ ] **Step 5: Commit.** `git commit -m "Fog render: a party marker per group"`

### Task 4: Map state per character (pure)

**Files:**
- Create: `src/delve/maps/state.py`
- Test: `tests/maps/test_state.py`

**Interfaces:**
- Consumes: `DungeonMap`, `build_graph`, `visible_doors`, `party_start_node`, `SessionView`, `render_fogged` and
  `resolve_node` from `delve.maps.dsl`.
- Produces, frozen dataclasses (operations return new values):
  - `CharacterView`: `location: str | None`, `nodes: frozenset[str]`, `doors: frozenset[str]`.
  - `MapState`:
    - `characters: Mapping[str, CharacterView]` (keyed by character id);
    - `door_states: Mapping[str, str]`;
    - `revealed: frozenset[str]` (secret keys).

    Door states and revealed secrets are facts of the world, shared by everyone. Discovery is what each character knows.
  - `MapState.empty() -> MapState`.
  - `place(state, dmap, character_ids, node) -> MapState`, which raises `UnknownNode(query, candidates)` for an unknown
    node.
  - `move(state, dmap, character_ids, to) -> MapState`: it sets the location, discovers `to` and its
    `visible_doors` for those characters, then merges.
  - `reveal(state, dmap, character_ids, node, reveal_doors=True) -> MapState`, which discovers without moving.
  - `set_door(state, door_key, door_state) -> MapState` and `reveal_secret(state, secret_key) -> MapState`.
  - `start(state, dmap, character_ids) -> MapState`, which places the characters at `party_start_node(dmap)` and
    discovers it.
  - `merge(state) -> MapState`: characters that share a location get the union of their `nodes` and `doors`.
  - `view(state, character_ids) -> SessionView`: the union of those characters' knowledge. `party_location` is set only
    if they all share one location.
  - `groups(state, character_ids) -> list[tuple[str, frozenset[str]]]`: (location, character ids) for each occupied
    location, sorted by location.
  - `render_view(state, dmap, character_ids) -> str`, the fog SVG with one disc per group. It raises `NoPosition` when no
    given character has a location.
  - `render_dm(state, dmap) -> str`, the full SVG with every group's disc.
  - `upgrade(state, new_dmap) -> MapState`, which drops node ids, door keys and secret keys that no longer exist and keeps
    everything else.
  - `to_json(state) -> dict` and `from_json(raw) -> MapState`, which round-trip, for storage.

- [ ] **Step 1: Write the failing tests** on a sample map from `SAMPLES`:
  - `test_move_discovers_node_and_visible_doors`;
  - `test_characters_apart_know_different_rooms`;
  - `test_meeting_merges_discovery` (the chute case: A falls into room X, B explores Y; when A comes back to B's room,
    both know X and Y);
  - `test_view_union_and_party_location_only_when_together`;
  - `test_groups_sorted`;
  - `test_render_view_two_groups_two_discs`;
  - `test_render_view_without_position_raises`;
  - `test_fog_view_hides_undiscovered_secret_and_marker`, which plants a label `SECRET-XYZZY` in an undiscovered room
    and asserts it's not in the SVG;
  - `test_upgrade_keeps_surviving_and_drops_missing`;
  - `test_json_roundtrip`;
  - `test_unknown_node_lists_candidates`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.** Build the graph once per call. There is no caching yet.
- [ ] **Step 4: Run, expect them to pass,** and `lint-imports` too.
- [ ] **Step 5: Commit.** `git commit -m "Map state: positions and discovery per character, merged when they meet"`

### Task 5: Storage for modules, revisions, campaigns, characters, map states and blobs

**Files:**
- Create: `src/delve/domain/modules.py`, `src/delve/domain/campaigns.py`,
  `src/delve/storage/sqlite/{modules_repo,campaigns_repo,characters_repo,map_states_repo,blobs}.py`,
  `src/delve/storage/migrations/versions/0002_modules_campaigns.py`
- Modify: `src/delve/storage/interfaces.py`, `src/delve/storage/sqlite/__init__.py`, `tables.py`, `tests/storage/contract.py`

**Interfaces:**
- Produces (domain, frozen dataclasses):
  - `ModuleMap(name: str, role: Literal["map", "library"], source: str, is_default: bool)`.
  - `Module(id: str, title: str, metadata: dict, maps: tuple[ModuleMap, ...], head_revision: int | None, updated_at: str)`.
  - `Revision(module_id: str, number: int, title: str, metadata: dict, maps: tuple[ModuleMap, ...], created_at: str)`.
  - `Campaign(id: str, name: str, module_id: str, revision: int, created_at: str)`.
  - `Character(id: str, campaign_id: str, name: str, created_at: str)`.
  - `new_id(prefix: str) -> str`, with prefixes `"mod"`, `"cmp"` and `"chr"`, giving `<prefix>_<12 hex>`.
- **Revisions (call, from spec §8.1):** the module's maps are its working copy and are edited in place. A revision is an
  immutable snapshot, created when a campaign is started or upgraded and the working copy has changed since the last
  revision. Otherwise the last revision is reused.
- Repositories (Protocols), added to `Storage` as `modules`, `revisions`, `campaigns`, `characters`, `map_states` and
  `blobs`:
  - `ModuleRepository`:
    - `create(title, metadata=None) -> Module`, `get(id) -> Module | None`, `list() -> list[Module]`, `delete(id) -> None`;
    - `rename(id, title)`, `set_metadata(id, metadata)`;
    - `put_map(id, ModuleMap) -> Module` (an upsert by name), `delete_map(id, name) -> Module`,
      `set_default_map(id, name) -> Module`;
    - `changed_since(id, revision: int | None) -> bool`.
  - `RevisionRepository`: `snapshot(module_id) -> Revision`, which applies the reuse rule above,
    `get(module_id, number) -> Revision | None`, and `latest(module_id) -> Revision | None`.
  - `CampaignRepository`: `create(name, module_id, revision) -> Campaign`, `get`, `list`,
    `set_revision(id, revision) -> Campaign`, `delete`.
  - `CharacterRepository`: `create(campaign_id, name) -> Character`, `list(campaign_id)`, `rename`, `delete`.
  - `MapStateRepository`: `get(campaign_id, map_name) -> dict | None` (raw JSON from `delve.maps.state.to_json`; storage
    doesn't import maps), `put(campaign_id, map_name, raw: dict) -> None`, and `list(campaign_id) -> dict[str, dict]`.
  - `BlobStore`:
    - `put(data: bytes, mime: str) -> str` returns the sha256 hex digest. Content-addressed, stored at
      `<data dir>/blobs/<aa>/<sha256>`, and written atomically;
    - `get(sha) -> bytes | None`, `exists(sha) -> bool`;
    - `link(module_id, role: str, sha)` and `links(module_id) -> list[tuple[str, str]]`. The `.dscn` import keeps its
      original bundle under role `"source-bundle"`.
- **Migration `0002_modules_campaigns`:** the tables `modules`, `module_maps`, `module_revisions` (maps stored as JSON),
  `campaigns`, `characters`, `map_states`, `blobs` and `module_blobs`. Foreign keys: deleting a campaign cascades to its
  characters and map states. A module with campaigns can't be deleted (`ModuleInUse`).

- [ ] **Step 1: Extend `tests/storage/contract.py`** with:
  - `test_module_crud`;
  - `test_put_map_upserts_by_name`;
  - `test_single_default_map`;
  - `test_snapshot_reuses_unchanged_revision`;
  - `test_snapshot_after_edit_creates_next`;
  - `test_revision_immutable_after_edit` (editing the working copy doesn't change revision 1);
  - `test_campaign_and_characters`;
  - `test_delete_campaign_cascades`;
  - `test_module_in_use_not_deleted`;
  - `test_map_state_roundtrip`;
  - `test_blob_content_addressed_and_deduplicated`;
  - `test_blob_written_atomically` (no partial file after a simulated failure).

  Add `test_migration_0001_to_0002_keeps_settings` in `test_migrations.py`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `uv run pytest tests/storage` and `lint-imports` pass.
- [ ] **Step 5: Commit.** `git commit -m "Storage: modules, revisions, campaigns, characters, map states and blobs"`

### Task 6: Module, map and DSL routes, with `.dscn` import

**Files:**
- Create: `src/delve/web/routes/modules.py`, `maps.py`, `dsl.py`, `src/delve/modules/importer.py`
- Modify: `src/delve/web/guard.py` (the upload exception), `src/delve/web/app.py`
- Test: `tests/web/test_modules_api.py`, `tests/web/test_dsl_api.py`, `tests/modules/test_importer.py`

**Interfaces:**
- Consumes: the Task 5 repositories, `delve.maps.dsl` and `delve.modules.dscn`.
- Produces (all organiser-only; error bodies are `{"error": …}`):
  - **Modules:**
    - `GET /api/modules` returns `[{id, title, maps: [{name, role, is_default}], head_revision, updated_at}]`.
    - `POST /api/modules {title}` returns the module, with one empty map named `map` that is the default.
    - `GET /api/modules/{id}` returns the module with its map sources. `PATCH {title?, metadata?}`. `DELETE` answers 409
      when campaigns use the module.
  - **Maps, in the shapes dungml's editor already uses:**
    - `GET /api/modules/{id}/maps/{name}` returns `MapDetail{module_id, name, role, is_default, updated_at, source}`.
    - `PUT /api/modules/{id}/maps/{name} {source?, role?, new_name?}` returns `MapDetail`. A parse error answers 400
      `{error, line, column}`, and nothing is saved for a map. Library sources are saved even if they don't parse on
      their own.
    - `POST /api/modules/{id}/maps {name, role}` creates a map. `DELETE /api/modules/{id}/maps/{name}`.
      `PUT /api/modules/{id}/maps/{name}/default`.
    - `POST /api/modules/{id}/maps/{name}/render {source?, renderer?}` returns `{svg, diagnostics[]}`.
    - `POST /api/modules/{id}/maps/{name}/feature-names {source?}` returns `{names[], groups[{source, names[]}]}`.
    - `POST /api/modules/{id}/maps/{name}/simplify {source, door_spurs}` returns the same shape as dungml's.
  - **DSL:**
    - `POST /api/dsl/connectivity {source, module_id?}`, `POST /api/dsl/render {source, renderer?, module_id?}`,
      `POST /api/dsl/parse {source, module_id?}`, `GET /api/dsl/renderers`, `GET /api/dsl/themes`.
    - **Include resolution:** a module's `library` maps first, then the built-in libraries. It replaces dungml's
      project includes.
  - **Import and export:**
    - `POST /api/modules/import` with the body being the `.dscn` zip, and `Content-Type: application/zip` or
      `application/vnd.dscn+zip`. It returns the new module.
    - `import_bundle(storage_like, data: bytes) -> ImportResult(module, warnings)` in `delve.modules.importer`. It
      depends on a small Protocol, not on `delve.storage`. It:
      1. loads the bundle with `Bundle.load(bytes, limits=DEFAULT_LIMITS)`;
      2. refuses it if `check()` reports errors;
      3. creates the module from the manifest's `title` and metadata;
      4. adds every map entry (role map or library, with the default);
      5. keeps the whole original bundle as a blob with role `source-bundle`, for plateau 3.

      Text, entities and assets are not unpacked yet; the result has one warning saying so.
    - `GET /api/modules/{id}/export.dscn` returns a `.dscn` zip with the manifest and maps. It uses the `dscn` container
      writer.
  - **Guard exception:** only `POST /api/modules/import` may use a non-JSON content type, and only the two types above.
    Neither is CORS-safelisted, so a cross-site form still can't send one. There's a body cap of 64 MB (413 above it).
- Publish events `modules` (`{id}`) on every module change.

- [ ] **Step 1: Write the failing tests.**
  - `test_create_module_has_default_map`;
  - `test_put_map_parse_error_400_with_line`;
  - `test_render_returns_svg_and_diagnostics`;
  - `test_include_resolves_module_library_then_builtin`;
  - `test_feature_names_shape`;
  - `test_import_sample_dscn`: zip the `crypt-of-saint-vellis` fixture; the maps arrive, and the blob is linked;
  - `test_import_refuses_traversal_and_bomb_and_missing_manifest`: each gives 400 with a reason, and afterwards the
    module and blob counts are unchanged;
  - `test_import_wrong_content_type_415`;
  - `test_import_too_large_413`;
  - `test_export_roundtrip` (export then import gives the same maps);
  - `test_delete_module_in_use_409`;
  - `test_modules_need_organiser`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `uv run pytest` and `lint-imports` pass.
- [ ] **Step 5: Commit.** `git commit -m "Module, map and DSL routes; .dscn import and export"`

### Task 7: Campaign, character and map-state routes

**Files:**
- Create: `src/delve/web/routes/campaigns.py`, `src/delve/web/routes/map_state.py`
- Modify: `src/delve/web/app.py`
- Test: `tests/web/test_campaigns_api.py`, `tests/web/test_map_state_api.py`

**Interfaces:**
- Consumes: the Task 5 repositories and `delve.maps.state` (Task 4).
- Produces (organiser-only in plateau 1; players come in plateau 4):
  - **Campaigns:**
    - `POST /api/campaigns {name, module_id}` snapshots a revision and returns the campaign.
    - `GET /api/campaigns` and `GET /api/campaigns/{id}`. The latter returns
      `{…campaign, module_title, maps: [names in the pinned revision], upgrade_available: bool}`.
    - `DELETE /api/campaigns/{id}`.
    - `POST /api/campaigns/{id}/upgrade`. It snapshots the module, runs `upgrade()` on every stored map state against
      the new revision's maps, saves them, and returns the campaign.
  - **Characters:** `POST /api/campaigns/{id}/characters {name}`, `GET`, `PATCH /…/{cid} {name}`, `DELETE`. Deleting a
    character removes it from every map state.
  - **Map state**, at `/api/campaigns/{id}/maps/{name}/…`, against the **pinned revision**:
    - `GET state` returns `{characters: {cid: {location, nodes, doors}}, door_states, revealed, groups}`. This is the DM
      side, for this plateau's map-state panel.
    - `POST start {characters}`, `POST move {characters, to}`, `POST reveal {characters, node, reveal_doors?}`,
      `POST door {door, state}` and `POST secret {key}`. Each returns the new state.
    - An unknown node answers 404 `{error, candidates}`.
    - `GET view?characters=a,b` returns `{svg}`: the characters' fog view.
    - `GET dm-view` returns `{svg}`: the full map with every group. It's a separate route; `view` has no parameter that
      turns it into the DM view.
    - A pinned map that doesn't parse answers 409 `{"error": "map offline"}`. So does `view` when none of the characters
      has a position.
  - Publish the event `map_state` (`{campaign_id, map}`) after every change.

- [ ] **Step 1: Write the failing tests.**
  - `test_campaign_pins_revision`;
  - `test_module_edit_does_not_change_campaign_view`;
  - `test_upgrade_moves_to_new_revision_and_keeps_discovery`;
  - `test_move_and_view`;
  - `test_split_party_views_differ_and_merge_on_meeting`;
  - `test_view_without_position_409_map_offline`;
  - `test_broken_pinned_map_409`;
  - `test_view_never_contains_planted_secret` (with `SECRET-XYZZY`);
  - `test_view_has_no_dm_switch` (adding `?scope=gm`, `?full=1` or `?view=dm` gives a response byte-identical to the
    plain view);
  - `test_unknown_node_404_candidates`;
  - `test_delete_character_cleans_map_states`;
  - `test_map_state_event_published`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `uv run pytest` and `lint-imports` pass.
- [ ] **Step 5: Commit.** `git commit -m "Campaigns, characters and per-character map state routes"`

### Task 8: The map editor and the module pages (frontend)

**Files:**
- Create:
  - `web/src/editor/` ported from `dungml/packages/web/src`: `SvgPreview`, `DrawToolbar`, `FeatureSelect`,
    `MonacoEditor`, `DiagnosticsPanel`, `SimplifyDialog`, `Primitives`, `icons`, `lib/draw.ts`,
    `lib/dmapLanguage.ts`, `lib/sourceAnchor.ts`, `useDebounce.ts`, `types.ts`, with their CSS modules;
  - `web/src/editor/monacoSetup.ts`;
  - `web/src/routes/{Modules,ModuleDetail,MapEditor,MapPrint}.tsx`.
- Modify: `web/src/App.tsx` (switch to `createBrowserRouter`, the data router that `useBlocker` needs), `web/src/api.ts`,
  `web/src/i18n/{en,nl}.json`, `web/package.json`
- Test: the ported editor tests (`SvgPreview.highlight`, `SimplifyDialog`, `sourceAnchor`), plus `web/src/editor/monacoSetup.test.ts`,
  `web/src/routes/Modules.test.tsx` and `web/src/routes/MapEditor.test.tsx`

**Interfaces:**
- Consumes: the Task 6 routes.
- Produces:
  - **Routes:**
    - `/modules`: the list, "New module" and "Import .dscn" (a file input that POSTs the bytes with
      `application/zip`).
    - `/modules/:moduleId`: the module's maps (add, rename, delete, default, role), and a link to each map's editor.
    - `/maps`: every map across modules, grouped by module.
    - `/maps/:moduleId/:mapName`: the editor.
    - `/maps/:moduleId/:mapName/print`: the print view.
  - **The editor is ported, not rewritten.** Replace dungml's `api.ts` calls with Delve's module-scoped routes (same
    shapes). The exit tool's sibling-map list is the module's other `map`-role maps. Remove `useAuth`, `AppHeader`,
    `ProtectedRoute` and project breadcrumbs. Keep `useBlocker` for unsaved changes.
  - **`monacoSetup.ts`** imports `monaco-editor` and its editor worker through Vite (`?worker`), and calls
    `loader.config({ monaco })`, so nothing loads from a CDN.
  - **Strings:** editor labels move to i18n keys in `en` and `nl` where they're user-visible.
- `useBlocker` with `createBrowserRouter` keeps the plateau 0 routes and the TokenGate.

- [ ] **Step 1: Copy the editor files and their tests.** Write `monacoSetup.test.ts`: it mocks `@monaco-editor/react`'s
  `loader` and asserts `loader.config` is called with a `monaco` object and no `paths.vs` CDN URL.
  `Modules.test.tsx` lists modules and posts an import with `content-type: application/zip`. `MapEditor.test.tsx`
  loads a map, shows a parse error from a 400 at its line, and blocks navigation while unsaved.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Adapt and wire.**
- [ ] **Step 4: Run.** `npm test`, `npm run typecheck` and `npm run build` pass. The ported tests pass unchanged except
  for import paths.
- [ ] **Step 5: Commit.** `git commit -m "Map editor and module pages, with Monaco bundled locally"`

### Task 9: Campaign pages and the map-state panel (frontend)

**Files:**
- Create: `web/src/routes/{Campaigns,CampaignDetail}.tsx`, `web/src/campaign/MapStatePanel.tsx`
- Modify: `web/src/App.tsx`, `web/src/i18n/{en,nl}.json`
- Test: `web/src/routes/Campaigns.test.tsx`, `web/src/campaign/MapStatePanel.test.tsx`

**Interfaces:**
- Consumes: the Task 7 routes and SSE `map_state`.
- Produces:
  - **`/campaigns`:** the list, plus "New campaign" (name plus a module picker).
  - **`/campaigns/:id`:** the module and revision, an "Upgrade to the latest revision" button when available, and the
    characters (add, rename, remove).
  - **The map-state panel**, per map of the pinned revision:
    - a character multi-select;
    - Start, Move to (a node picker with the candidates from a 404), Reveal, and door and secret controls;
    - two tabs, **Characters' view** (`view?characters=`) and **DM view** (`dm-view`), with distinct labels and a
      distinct border colour for the DM view;
    - a "Map offline" message on 409.

    The panel is a host tool for this plateau; the play screen arrives in plateau 2.
  - It re-fetches on the SSE event `map_state`.

- [ ] **Step 1: Write the failing tests.**
  - The campaign list renders and "New campaign" posts `{name, module_id}`.
  - The panel posts a move for the selected characters.
  - A 409 shows "Map offline" (translated).
  - The DM view tab calls `dm-view` and the characters' tab never does.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** `npm test`, `typecheck` and `build` pass.
- [ ] **Step 5: Commit.** `git commit -m "Campaign pages and the map-state panel"`

### Task 10: Integration, CSP and docs

**Files:**
- Modify: `src/delve/web/guard.py` (CSP), `README.md`, `GUILD.md`, `Makefile` only if needed
- Copy: `dungml/docs/scenario-format.md` and `dungml/docs/dsl*.md` into `docs/maps/`, with a first line saying they
  are ported from dungml `a66a1bb`
- Test: `tests/web/test_guard.py` (CSP), `tests/test_serve.py` (smoke)

**Interfaces:**
- Produces:
  - **CSP:** `worker-src 'self' blob:` is added; there are no external hosts.
  - The smoke test runs `delve serve`, then:
    1. imports the sample `.dscn`;
    2. creates a campaign and two characters;
    3. starts and moves them apart;
    4. checks that the two views differ, and that the DM view contains both discs;
    5. GETs `/maps/<module>/<map>`, which serves the SPA.

- [ ] **Step 1: Write the failing tests.**
  - `test_csp_has_worker_src_and_no_external_hosts` asserts that no `http` or `https` appears in the CSP.
  - Extend `test_serve_smoke` with the flow above.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.** Update `GUILD.md`:
  - the two copied packages and "never edit dungml";
  - the fog invariants;
  - the per-character map state;
  - the upload exception.
- [ ] **Step 4: Run `make ci`.** Everything passes. Report the test counts per area: copied dsl, copied dscn, new
  Python, frontend.
- [ ] **Step 5: Commit.** `git commit -m "Plateau 1 integration: CSP for the editor, smoke test, map docs"`

---

## Order and parallelism

- **Tasks 1 → 2 → 3** come first, in order. Task 4 needs Task 1 and Task 3.
- **Task 5** (storage) can run alongside Tasks 1–4, since it doesn't import maps.
- **Task 6** needs Tasks 1, 2 and 5. **Task 7** needs Tasks 4, 5 and 6.
- **Task 8** needs Task 6's shapes, which are given above, so it can start from this plan in parallel with Tasks 6 and 7.
  **Task 9** needs Task 7's shapes, and can likewise start early.
- **Task 10** is last.

## Done when

- `make install && make ci` passes on a fresh clone. The copied dungml tests pass in their new places.
- In a browser on localhost, you can:
  1. import the Crypt of Saint Vellis sample;
  2. open its map in the editor, edit it, see the live preview and parse errors, save, and print it;
  3. start a campaign with two characters, move them apart (one down a chute), and see two different characters'
     views and a DM view with two party discs;
  4. bring them together and see their discoveries merge.
- Editing the module afterwards doesn't change the campaign until you press "Upgrade to the latest revision". After the
  upgrade, discovery survives.
- The wheel contains the grammar, the include libraries, the schema and the built SPA.
