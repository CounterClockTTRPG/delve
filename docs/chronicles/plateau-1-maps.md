# Build Delve plateau 1 (maps) exactly as planned in docs/superpowers/plans/2026-10-17-plateau-1-maps.md.

# Delve plateau 1: maps

Plateau 1 is built as planned in `docs/superpowers/plans/2026-10-17-plateau-1-maps.md` and merged on `guild/20261017-c6b622fd/party`: maps, modules, the map editor, and campaigns with a map state per character.

`make install && make ci` passes on the merged branch:
- ruff is clean and import-linter keeps all 5 contracts;
- pytest: 937 passed, 1 skipped;
- the web typecheck, 59 vitest tests and the build all pass.

The skipped test is `test_wheel`: pytest runs before the web build, so the built SPA isn't there yet. Run after the build, it passes.

Nothing has been tried in a browser yet. The editor and the map-state panel were checked only by the vitest tests, against mocked calls.

## Test counts
| Area | Tests |
|---|---|
| Copied DSL tests (`tests/maps/dsl`) | 638 of dungml's 639. The one gone is `test_console_script_works`, deleted as the plan says. |
| Copied `.dscn` tests (`tests/modules/dscn`) | 71 collected: the plan's 51 test functions, with their parametrised cases. The new `test_requires_dungml_checked` comes on top. |
| Other Python tests (plateau 0 and the new plateau 1 tests) | 229, plus `test_wheel` |
| Frontend tests | 59: 14 ported editor tests, unchanged except for import paths, and 45 others |

## Per task
1. **The DSL as `delve.maps.dsl`** (Mateo, `31980d7`)
   - Copied from dungml at `a66a1bb` with its tests, its samples (now `tests/fixtures/samples`, reached through `SAMPLES`) and the dependencies lark and shapely.
   - `tests/test_wheel.py` was added, along with the import contract "delve.maps does not import delve.modules".
   - Hatch's wheel artifacts were already set in plateau 0.
2. **`.dscn` as `delve.modules.dscn`** (Mateo, `3bd4a8e`)
   - Copied with its schema and the dependencies pyyaml, jsonschema and markdown-it-py.
   - The version check now gets its version from `delve.maps.dsl.__version__`, without the `+a66a1bb` suffix. In dungml this check silently did nothing when dungml wasn't installed as a package.
3. **One party marker per group** (Kenji, `c464966`)
   - `render_fogged(..., party_locations=())` draws one `<g class="party" data-node>` disc per distinct node.
   - A node not yet discovered gets no disc.
   - With only `party_location`, the output is byte-identical to a reference SVG captured before the change.
4. **Map state per character** (Kenji, `3ce62eb`)
   - `delve.maps.state` is new and has no side effects: `CharacterView`, `MapState`, `place`, `move`, `reveal`, `start`, `merge`, `view`, `groups`, `render_view`, `render_dm`, `upgrade` and the JSON round-trip, with `UnknownNode` and `NoPosition`.
   - It has 17 tests, including the chute case and a planted `SECRET-XYZZY`.
5. **Storage** (Ravi, `87f58ea`)
   - Domain types, plus repositories for modules, revisions, campaigns, characters, map states and blobs.
   - Migration `0002_modules_campaigns`.
   - Blobs are content-addressed and written atomically to `<data dir>/blobs/<aa>/<sha>`.
   - A revision is reused when nothing has changed; a module that campaigns use can't be deleted (`ModuleInUse`).
   - 28 storage tests.
6. **Module, map and DSL routes, with `.dscn` import and export** (Omar, `706831c`)
   - The routes, `import_bundle` and `export_bundle` behind a small Protocol, and the guard's single upload exception (64 MB cap, 413 above it).
   - A parse error answers 400 `{error, line, column}`, never a 500.
   - A hostile upload is refused and stores nothing: a `../` path, a zip bomb, a missing manifest or a wrong content type.
   - 42 new tests.
7. **Campaign, character and map-state routes** (Jordan, `2a75865`)
   - Every map-state route works against the campaign's pinned revision.
   - The characters' view and the DM view are separate routes, and query parameters can't switch one into the other (tested byte-identical).
   - 409 "map offline" for a pinned map that doesn't parse, or a view with no positioned character; 404 `{error, candidates}` for an unknown node.
   - Upgrading keeps the discovery of nodes that still exist; deleting a character removes it from every map state.
   - 25 tests.
8. **The map editor and module pages** (Lars, `90e8c96`)
   - dungml's editor is ported into `web/src/editor`. Monaco is bundled and configured with `loader.config({ monaco })`, so nothing loads from a CDN.
   - The app switched to `createBrowserRouter` and keeps the plateau 0 routes and the TokenGate.
   - New pages: Modules, ModuleDetail, MapEditor and MapPrint, with every string in EN and NL.
   - New dependencies, exactly the plan's: `@monaco-editor/react`, `monaco-editor` and `lucide-react`.
9. **Campaign pages and the map-state panel** (Lars, `3bb0f77`)
   - Campaigns and CampaignDetail.
   - `MapStatePanel`, with tabs for the characters' view and the DM view; the DM view has its own label and a dashed `--dm-view` border.
   - It shows "Map offline" on a 409 and offers a node picker from the 404 candidates.
   - It re-fetches when the server sends a `map_state` event.
10. **Integration, CSP and docs** (Jordan, `3071ab3`)
    - The CSP gains `worker-src 'self' blob:` and names no external host.
    - The smoke test runs `delve serve` through import, campaign, split, views, the DM view's discs, and the SPA answering on `/maps/...`.
    - 7 dungml docs are copied to `docs/maps/`, each with a "Ported from dungml (commit a66a1bb)" line on top.
    - `GUILD.md` and `README.md` are updated.

## Deviations and decisions you approved
- **Plan correction (Task 2):** the plan said `requires: {dungml: ">=99"}` gives an *error*. The copied code gives a *warning*, and you kept the warning. The new test asserts code `requires`, severity warning, and a message naming `0.1.0`.
- **Task 6, six points the plan left open:**
  1. The import answers the module detail plus `warnings[]`.
  2. 201 for creating things; 204 with no body for DELETE.
  3. Export is `application/vnd.dscn+zip`, sent as an attachment.
  4. **Security fix:** includes come only from the module's library maps, then the built-ins, never from the filesystem. dungml could read server files. `include "/etc/passwd"` and relative paths answer 400 "include not found".
  5. The import keeps the manifest, minus its structural keys, as the module's metadata.
  6. A parse error answers exactly `{error, line, column}`, and renaming a map to a taken name answers 409.
- **Task 8:**
  - dungml's "Play" button is removed (play is the campaign map state now, and plateau 2's screen later).
  - The project breadcrumb is replaced by a link "‹module title› / ‹map name›" back to the module.
  - "DM only" replaces "GM only", and "module" replaces "project".
  - The editor's browser settings are stored under `delve.editor.*`.
  - A parse error on save shows in the diagnostics.
- **Task 7:**
  - The 404 `candidates` are `[{id, label}]`, as dungml gives them, and the SPA was adapted to pick by id.
  - A campaign lists only `map`-role maps; library or unknown maps answer 404 "No such map.".
  - `groups` is `[{location, characters}]`, sorted by location.

## Choices the engineers made where the plan was silent
- **Linting:** ruff doesn't check the copied packages and tests (`extend-exclude`). Its defaults flag 234 issues in dungml's code, and fixing them would mean editing copied code. Kenji's edits to `play.py` and `classic_bw.py` are therefore not linted either.
- **Storage:**
  - `SqliteStorage(engine, blobs_dir)` takes a new argument.
  - Missing ids raise `KeyError`.
  - "Changed since the last revision" compares content, so an edit that is undone reuses the old revision.
- **Map state:**
  - `place` doesn't discover the node.
  - `start` does nothing on a map without `party_start`, and none of the samples has one. The smoke test and the manual walk position the characters with `move`.
- **Export:** it leaves out an `asset:` cover, because assets aren't carried yet. With the cover in, the re-import would fail its check.
- **Unknown doors and secrets:** a door or secret key the map doesn't have answers 404, and a character that isn't the campaign's answers 400.
- **New colours:**
  - the party disc is `#2c7be5` with a `#123a6b` stroke, radius 0.42;
  - `--dm-view` is `#8a3fa0` in light mode and `#d39ae6` in dark mode.

## Checked by hand
Jordan ran `delve serve` on port 32869 and walked the "Done when" flow with curl:
- **Import:** the Crypt of Saint Vellis arrives as the map `crypt` plus the library `core.dmap`, with the warning that only the maps were imported.
- **Split:** two characters, one sent down the chute, get different views, and the DM view shows two discs.
- **Meeting:** when they meet, both know all 5 rooms and corridors.
- **Edit and upgrade:** adding a room to the module leaves both views byte-identical until "upgrade". After it the campaign is on revision 2 with its discovery kept, and the new room shows only in the DM view.
- **Wheel:** it contains the grammar, the 7 include libraries, the schema, the built SPA and both migrations.

After merging, I re-ran `make install && make ci` and `test_wheel` (after the build) in the integration worktree, and they pass.

## What plateau 2 should know
- **Leftover CDN address:** the 3.4 MB editor chunk still contains the jsdelivr address as `@monaco-editor/loader`'s default. It's never used and the CSP would block it, but a scan of the bundle would flag it.
- **No player routes yet:** every route is organiser-only. Player views must build on `render_view`, never on `dm-view`.
- **Not atomic:** an upgrade saves the campaign's revision and its map states one after another, not in one transaction.
- **Broken maps:** an upgrade leaves the map state of a map that doesn't parse untouched.
- **No caching:** every request parses the map and builds its graph again. Measure this for the play screen.
- **`party_start`:** none of the samples declares one, so `start` places nobody on them. The play screen will want maps that declare it, or a fallback.
- **Character lookup:** storage has no `characters.get`; routes check membership through `list(campaign_id)`.
- **Events:** the SPA has one event-stream subscription, in `App`; plateau 2 may want a shared one.
- **Ported docs:** the links inside `docs/maps/*` still point to dungml's routes and paths.

