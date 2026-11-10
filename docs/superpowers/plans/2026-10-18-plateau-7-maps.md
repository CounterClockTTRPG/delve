# Delve plateau 7: maps, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** World maps become real maps. The organiser imports them from GIS files (GeoJSON, Azgaar) or reads them from a
picture and its scale ("1 hex = 30 miles"), reviews what Delve read, and edits them in the browser. The party travels
them by a mode the DM picks (on foot, horse, cart, river boat, ship), along routes worked out from the map. Each seat
sees only what the party knows. Dungeon maps can be generated from a description or drawn from the book's own map.
The small backlog items come along.

**Architecture:**
- **One pure package for the new world maps: `delve.maps.geo`.**
  - A `GeoMap` is a frame in km, a grid of terrain cells, layers of features and an optional base picture.
  - It is stored as a Delve GeoJSON document (coordinates in km from the top left, plus a `delve` member).
  - Beside the model, the package holds routing, the party's knowledge with the seat's view, the tiles and the fog,
    and the reading of a picture (`delve.maps.geo.reading`).
  - Like `delve.maps.world`, it imports nothing of storage, play, dm or web. Claude and OCR are injected callables.
- **The two homes stay plateau 6's.** A world map lives in a module's source (`ModuleSource.worldmaps`) or in a
  campaign (`world_maps`), and a campaign copies its module's maps when it is created. The `.map` text maps are
  converted once into the new form, on first read, by plateau 6's parser. A pointer table names the setting's map on
  this install.
- **The fourth wall is decided on the server.**
  - The seat's view, its fogged tiles and its journey line are cut from the party's knowledge.
  - A tile with nothing known in it is never sent.
- **Claude sees pictures through a vision side call:** a new provider method, run as a `conversion` job. It reads the
  world-map picture (the terrain colours and the labels) and draws a dungeon map from a book's map page.
- **Leaflet draws the maps in the browser** (`CRS.Simple`, in km), with Leaflet-Geoman for editing. Both are bundled.

**Tech Stack:**
- **New Python dependencies, as direct dependencies** (both are already in `uv.lock` as transitive ones, at these
  versions):
  - `pillow==13.0.0` (MIT-CMU);
  - `numpy==2.5.4` (BSD-3-Clause).
  - No scipy or opencv. `shapely` 2.2 (already direct) clips the seat's lines and areas. `pytesseract==0.3.13`
    (plateau 5) reads labels when `tesseract` is installed.
- **New web dependencies, exact versions:**
  - `leaflet` 1.9.4 (BSD-2-Clause);
  - `@geoman-io/leaflet-geoman-free` 2.20.2 (MIT; its own types, `dist/leaflet-geoman.d.ts`);
  - `@types/leaflet` 1.9.22 as a dev dependency (MIT).
  - No `react-leaflet`: a thin hook wraps Leaflet.
- (Versions as `uv pip compile` and `npm view` resolve them on 2026-10-18.)

**Spec:**
- `docs/superpowers/specs/2026-10-18-plateau-7-maps-design.md`, all of it. This plan's "Decisions taken in this plan"
  settle what its §7 and its "call"s leave open.
- `docs/superpowers/plans/2026-10-18-plateau-6-the-rest-of-the-world.md`: what plateau 6 built, whose names and shapes
  stay where the design doesn't replace them.
- `docs/backlog.md` items 1–9; `docs/glossary.md`; `docs/data-dictionary.md`; `docs/maps/world-maps.md`.
- The owner's survey of the small items (`~/claude/refactoring-assets/plateau7-survey-small-items.md`, read-only,
  never copied into the repository). Its line numbers were checked against this branch; the task Files below cite
  functions, not lines.

## Global Constraints

- **Earlier plateaus still apply:** `GUILD.md`, and the Global Constraints of plateaus 0–6 and of the walkthrough
  fixes.
- **Every task leaves `make ci` green on its own once its prerequisites are merged.**
  - A task that removes or changes a name changes every caller, test, prompt line and doc that uses it in the same
    task.
  - If those callers belong to a later task, it keeps the old name beside the new one. The task that removes it is
    named, and it greps for the old name before it commits.
  - The removals below were checked against their callers on this branch. A builder who finds another caller fixes it
    in the same task.
- **The fourth wall, per seat.**
  - Nothing a seat may not see reaches its browser: an unknown area's tile, a hidden place, `dm_notes`, an unknown
    map's name, a feature outside the known area, or the part of a journey line in unknown land.
  - That holds for routes, events, the replay buffer and tool rows alike. When in doubt, a seat sees less.
  - `tests/web/test_world_fourth_wall.py` and `tests/web/test_fourth_wall_per_seat.py` keep their planted
    `SECRET-XYZZY` discipline: a new route or event a seat can reach gets a planted secret in that test.
- **Single-player play stays as fast as it is.**
  - No new tool runs a side pass or a vision call inside a beat.
  - Routing runs on a graph built once per map and mode, and kept until the map changes.
  - A route across a Flanaess-sized map takes under a second.
- **Tests never run the real `claude`, `tesseract`, Replicate or the network.**
  - Use `FakeDM` (`vision_handler`), the fake `claude` (its vision mode) and a fake OCR callable.
  - An autouse fixture in `tests/conftest.py` sets `DELVE_OCR=off` for every test (Task 1).
  - Both OCR factories, `pdf.tesseract_ocr()` and `reading.ocr.tesseract_words()`, answer None under it. In-process
    `TestClient` tests are covered too, and so is anything that starts `delve serve`.
- **Pictures in tests are synthetic,** drawn with Pillow by `tests/maps/geo/pictures.py`.
  - The owner's `greyhawk.jpg` is never committed and never read by `make ci` or `make e2e-browser`.
  - It may be used by hand for a trial run, from `~/claude/refactoring-assets/greyhawk.jpg`, outside the repository.
  - `.gitignore` refuses `greyhawk*.jpg`. `tests/test_repository.py` fails on a tracked picture (`.jpg`, `.jpeg`,
    `.png`, `.webp`, `.tif`) named `greyhawk*` or over 2 MB (Task 1). The largest tracked picture today is a 136 KB
    screenshot. The 5 MB `reference/snapshots/*.sql.gz` aren't pictures.
- **No randomness outside `Dice`.**
  - The reading is deterministic: no `random`, and no `numpy.random` either (`tests/test_no_random.py`'s spirit).
  - Clustering is Pillow's median cut, and the hex/square detection is a fixed computation.
- **The dependency rules hold.**
  - `delve.maps.geo` imports none of `delve.web`, `delve.dm`, `delve.storage`, `delve.play` or `delve.modules`.
  - `delve.conversions` imports none of `delve.web` or `delve.play`.
  - Pillow and numpy are imported only by `delve.maps.geo`, `delve.modules.books` (already) and `delve.maps.vision`.
- **Migration:** Task 1 adds `0014_maps`, with every column and table of the plateau, small items included. If master
  already has a 0014 when the quest starts, use the next free number and keep the name.
- **The tool surface:** every new or removed tool updates `dm/tools/host.py` `all_specs()`, `test_fourth_wall.py`
  (`DM_ONLY_TOOLS` and the `SESSION` list), and the ttrpg2 mapping in `tests/dm/tools/test_tools.py`. Tasks 9 and 10
  add their own lines there, and Task 11 removes `edit_world_map`'s, in that order (waves 3, 4, 5).
- **CSP:** Leaflet's and Geoman's CSS and images are bundled by Vite: no CDN, no external host. Tiles come from
  `'self'`; a fog tile may be a `data:` URI.
- **UI strings** come from `en.json` and `nl.json`, and `nl` has every key.
- **The rule for parallel builders:** each web task adds its i18n keys as **one block, right after its named anchor**,
  in both files. It never moves, reorders or reformats another key, so blocks from parallel tasks merge without a
  conflict.

  | Task | Anchor (the key its block follows) |
  |---|---|
  | 6 | `conversion.dismiss` |
  | 13 | `modules.conversionFailed` |
  | 14 | `worldMaps.source.campaign` |
  | 15 | `editor.preview.textTitle` |
  | 16 | `world.deleteConfirm` |
  | 17 | `play.paidImagesHint` |
  | 18 | `join.failed` |
  | 19 | `campaigns.playing` |
  | 20 | `sheet.disposition` |

  These anchors are distinct, and no two sit on neighbouring lines.
- **`src/delve/maps/geo/__init__.py`** is Task 2's: a docstring and nothing to export. Tasks 3, 4, 5 and 7 add their
  own modules and never edit it.
- **Words** (glossary): world map, terrain, place, route, river, region, picture, scale, key, review, known, journey,
  leg, mode (on foot, on horseback, by cart, by river boat, by ship), fog. Never "hex" for a place (the picture's grid
  may be hexes: "hex" is said only of the grid, as in "1 hex = 30 miles"), "tile" in the UI, "GM", "turn" or "round".

## Review Focus

1. **The seat's view leaks at the edges of what is known.** Planted cases:
   - a partly known tile whose unknown half has a distinctive colour;
   - a road that runs from known land into unknown land;
   - the stopped journey's line ahead of the party;
   - a hidden place inside a known area;
   - `dm_notes` on a known place;
   - the name of a map the party knows nothing of, in the list and in a `world` event (a table-scoped `world` event
     carries no map name at all);
   - a `world` event replayed with `since=0`, after the organiser saved and deleted a map named `SECRET-XYZZY`.

   None of them reaches a second seat. The tile shows only fog where nothing is known, the road and the line are cut at
   the known edge, and the map isn't listed. (Task 11 test, with Task 4 and Task 5 unit tests.)
2. **The owner's full-size picture.** A 13,706 × 10,678 px JPEG (146 million pixels) is over Pillow's own
   decompression-bomb guard and would fill memory if it were read naively. It must import within
   `MAX_PICTURE_PIXELS` (200 million) with no array over `ANALYSIS_MAX_PIXELS`.
   - A picture of more pixels is refused with 422 and a message, before any tile is cut.
   - A body over 64 MB is 413.
   - A body that isn't the image it claims to be is 400.

   `PictureRefused` and every test use these three statuses. (Task 5 and Task 12 tests, with the caps patched down to
   keep the tests small.)
3. **Routes at the edges:**
   - a land journey to a place on an island is refused, naming the mode;
   - a ship's leg from an inland town is refused, and one from a port snaps to its water;
   - a river boat's leg from a town one cell from the river snaps to it;
   - an impassable ridge is crossed only at its pass;
   - a journey continued after the organiser edited the map plans again from where the party is.

   (Task 3 and Task 10 tests.)
4. **Old maps and old campaigns.**
   - A plateau 6 campaign with a `.map` world map, a party position and a revealed hidden place converts on its first
     read: the party stays on the same place, the revealed place stays visible, and its seats still see the whole map.
   - A new campaign's copy of the setting's map starts with nothing known.
   - A `.dscn` with a `ttrpg2-worldmap` still imports and exports unchanged.

   (Task 2 and Task 9 tests.)
5. **The review never keeps a doubtful reading silently.** A map in review isn't copied into a campaign, travelled
   on, listed to a seat or exported. Accept is refused while a colour has no terrain ("outside the map" counts as
   one). A picture without a grid and
   without two marked points is refused before the job starts. Every doubt kind appears in the review list before the
   readings that are sure. (Task 8 and Task 12 tests.)

---

## File structure

```
src/delve/storage/migrations/versions/0014_maps.py      every new column and table (Task 1)
src/delve/domain/world.py, campaigns.py, conversions.py world-map, journey, knowledge, picture, status fields (Task 1)
src/delve/maps/geo/{model,terrain,grid,geojson,from_dsl}.py   the GeoMap and its documents (Task 2)
src/delve/maps/geo/routing.py, src/delve/rules/adnd2e/overland.py   routes by mode, the 2e speeds (Task 3)
src/delve/maps/geo/knowledge.py                         what the party knows; the seat's and the DM's view (Task 4)
src/delve/maps/geo/{tiles,pictures}.py, src/delve/modules/worldmaps.py   tiles, fog, pictures, .dscn (Task 5)
src/delve/maps/vision.py, src/delve/dm/{provider,fake}.py, src/delve/dm/claude_cli/   the vision call (Task 6)
src/delve/maps/geo/reading/                             reading a picture (Tasks 7, 8)
src/delve/play/world_maps.py, src/delve/dm/tools/world.py   campaign world maps on the new model (Task 9)
src/delve/play/travel.py, src/delve/dm/tools/travel.py  travel by mode, journeys (Task 10)
src/delve/web/routes/{world,module_world_maps,world_pictures,world_import,map_drafts}.py   routes (5, 11, 12, 13)
src/delve/conversions/{worldmap,dungeon_maps}.py        the reading job, the dungeon-map drafts (Tasks 12, 13)
web/src/worldmap/                                       Leaflet: the seat's map, the editor, import, review (14–16)
```

---

### Task 1: Foundations: dependencies, migration 0014, domain and storage

**Files:**
- Create: `src/delve/storage/migrations/versions/0014_maps.py`
- Modify: `pyproject.toml`, `uv.lock`, `web/package.json`, `web/package-lock.json`; `src/delve/domain/world.py`,
  `src/delve/domain/campaigns.py`, `src/delve/domain/conversions.py`; `src/delve/storage/interfaces.py`,
  `src/delve/storage/sqlite/{tables.py,world_repos.py,campaigns_repo.py,conversions_repo.py,table_repos.py,__init__.py}`
  (`SqliteTranslationRepository` is in `table_repos.py`); `tests/storage/contract.py`,
  `tests/storage/test_migrations.py`
- **OCR off in tests:** `tests/conftest.py` (the autouse `DELVE_OCR=off` fixture), `src/delve/modules/books/pdf.py`
  (`tesseract_ocr` honours it), and `tests/modules/books/test_pdf.py`. Its `test_tesseract_ocr_reads_a_rendered_word`
  ran the real `tesseract` when it was installed. It becomes a test that `tesseract_ocr()` is None under
  `DELVE_OCR=off`.
- **The owner's map stays out:** `.gitignore` (`greyhawk*.jpg`), `tests/test_repository.py` (new)

**Interfaces:**
- Produces:
  - **Dependencies:** `pillow==13.0.0`, `numpy==2.5.4` in `[project] dependencies`; `leaflet` `1.9.4` and
    `@geoman-io/leaflet-geoman-free` `2.20.2` in `dependencies`, `@types/leaflet` `1.9.22` in `devDependencies`,
    exact. `uv lock` and `npm install` update the lock files; nothing else changes in them.
  - **Migration `0014_maps`:**

| Table | Change |
|---|---|
| `world_maps` | + `geo JSON NULL` (the Delve GeoJSON document), `picture TEXT NULL` (a `world_pictures.id`), `status TEXT NOT NULL DEFAULT 'ready'` (`ready` \| `review`), `knowledge JSON NULL`, `reading JSON NULL` |
| `campaign_state` | + `journey JSON NULL` |
| `campaigns` | + `status TEXT NOT NULL DEFAULT 'in_progress'` |
| `conversions` | + `target JSON NULL`, `result JSON NULL`, `questions JSON NULL` |
| `translations` | + `answer TEXT NULL` |
| `world_pictures` (new) | `id TEXT PK` (the original's sha256), `mime`, `width_px INT`, `height_px INT`, `max_zoom INT`, `tiles JSON` (`{"z/x/y": sha}`), `created_at` |
| `setting_world_maps` (new) | `setting TEXT PK`, `module_id TEXT` (FK modules CASCADE), `name TEXT`, `updated_at` |

  - **Domain, `domain/world.py`** (frozen dataclasses, `from_dict`/`to_dict` as the others; new fields are appended
    with defaults, so plateau 6's positional constructions still work):
    - `WorldMapSource(name, title, dsl, geo: dict | None = None, picture: str | None = None, status: WorldMapStatus =
      "ready", reading: dict | None = None)`;
    - `CampaignWorldMap` gains the same `geo`, `picture`, `status` and `reading`, and `knowledge: WorldKnowledge |
      None = None` (None: not yet converted from `dsl`);
    - `WorldMapStatus = Literal["ready", "review"]`;
    - `WorldKnowledge(everything: bool = False, cells: tuple[int, ...] = (), features: tuple[str, ...] = (),
      forgotten: tuple[str, ...] = ())`. Its `to_dict` writes `cells` as sorted runs `[[start, stop), …]` and
      `from_dict` reads them back.
    - `Journey(map: str, mode: str, to: str, to_label: str | None, points: tuple[tuple[float, float], ...], km: float,
      done_km: float = 0.0, by: tuple[str, ...] = (), planned_on: str = "", miles_per_day: float = 0.0)`:
      - `planned_on` is the map's `updated_at` when the route was planned, and Task 10 plans again when it differs;
      - `miles_per_day` is the DM's house-rule pace, 0 for the table's;
    - `WorldPosition` gains `km: bool = False`. True means `x, y` are km on the map's geo document. False means a
      plateau 6 point in the `.map`'s own units, which Task 9 reads through the conversion and Task 10 stops writing;
    - `WorldPicture(id, mime, width_px, height_px, max_zoom, tiles: dict[str, str], created_at: str = "")`, with
      `TILE_SIZE = 256`.
  - **`CampaignState.journey: Journey | None = None`.**
  - **`Campaign.status: CampaignStatus = "in_progress"`,** `CampaignStatus = str` (an open enum),
    `CAMPAIGN_STATUSES = ("in_progress", "paused", "complete")`.
  - **`Conversion`** gains `target: dict | None = None`, `result: dict | None = None` and `questions: dict | None =
    None`. `ConversionKind` adds `"worldmap"`, `"dungeon-map"` and `"book-map"` (and so does `CONVERSION_KINDS`).
  - **`Translation.answer: str | None = None`.** `TranslationRepository.put(entry_id, language, text, status, *,
    answer: str | None = None)`.
  - **Storage areas:**
    - `world_pictures`: `get(id) -> WorldPicture | None`, `put(picture) -> WorldPicture`;
    - `setting_world_maps`: `get(setting) -> tuple[str, str] | None` (module id, map name), `list() -> dict[str,
      tuple[str, str]]`, `put(setting, module_id, name)`, `delete(setting)`;
    - `campaigns.set_status(id, status) -> Campaign`;
    - `conversions.create(kind, title, mode, *, target: dict | None = None)`.
    - `conversions.save` stores `result` and `questions` too.
    - `conversions.for_module(module_id) -> list[Conversion]`, newest first and uncapped: the conversions whose
      `module_id` is that module or whose `target.module_id` names it (SQLite `json_extract`). The drafts (Task 13)
      and the questions (Task 20) are found through it, never through `list(limit=20)`.
- [ ] **Step 1: Write the failing contract and migration tests:**
  - each new field round-trips;
  - `WorldKnowledge` cells round-trip as runs (`(1, 2, 3, 7)` ↔ `[[1, 4], [7, 8]]`);
  - deleting a module removes its `setting_world_maps` row;
  - the migration keeps an existing campaign's world map, its `revealed` and its position, with `status` `ready` and
    `geo` null, and an existing campaign gets `status` `in_progress`;
  - a stored position without `km` reads as `km=False`;
  - `for_module` finds a draft job with only a `target`, and a 21st conversion is still found;
  - `tesseract_ocr()` is None under the autouse `DELVE_OCR=off`;
  - `tests/test_repository.py`: `git ls-files` holds no picture named `greyhawk*` and none over 2 MB.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Check the resolved versions with `uv lock` and `npm install` (they must be exactly the
  ones above).
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Plateau 7 foundations: Pillow, numpy and Leaflet, migration 0014, and the new fields and tables"`

---

### Task 2: The geo map: model, GeoJSON, and plateau 6's maps converted

**Files:**
- Create: `src/delve/maps/geo/{__init__.py,model.py,terrain.py,grid.py,geojson.py,from_dsl.py}`, `tests/maps/geo/`
  (`test_model.py`, `test_grid.py`, `test_geojson.py`, `test_from_dsl.py`, `fixtures/hand.geojson`,
  `fixtures/azgaar-cut.geojson`)
  - `azgaar-cut.geojson` is **synthetic**: a few features per Azgaar layer, written by hand in the shape of Azgaar's
    export, with `biome` as a number (and one cell with a biome name, for the fallback).
  - It isn't cut from a real export, and its first line says so. The owner checks a real export by hand
    (`docs/progress.md`, Task 22).
- Modify: `src/delve/setting/data/greyhawk-region.map` (its view's `scale`). The import-linter contracts on
  `delve.maps` already cover `delve.maps.geo`.
  - The new scale shortens every distance on the setting's map from Task 2 on. `tests/e2e/test_a_journey.py` (in
    `make ci`; it reads that file), `tests/play/test_travel.py`, `tests/setting/test_greyhawk.py` and
    `tests/web/test_world_api.py` must stay green.
  - Task 2 updates any assertion there that holds the old distance, such as the journey's day count. The copy in
    `tests/maps/world/data/` keeps plateau 6's text.

**Interfaces:**
- Produces:
  - **`terrain.py`:**
    - `TERRAIN_CLASSES = ("plains", "forest", "hills", "mountain", "swamp", "desert", "arctic", "jungle", "urban",
      "sea", "lake", "impassable")`;
    - `TERRAIN_LETTERS`: plains `p`, forest `f`, hills `h`, mountain `m`, swamp `s`, desert `d`, arctic `a`, jungle `j`,
      urban `u`, sea `w`, lake `l`, impassable `x`. `.` is no terrain (unknown or unread).
    - `TERRAIN_COLOURS`: Delve's own colour per class.
    - `PLACE_KINDS = ("city", "town", "village", "castle", "ruin", "dungeon", "port", "other")`;
    - `ROUTE_KINDS = ("road", "track", "trail")`;
    - `WATER_KINDS = ("river", "lake", "sea")`;
    - `LAYERS = ("places", "routes", "water", "regions")`.
  - **`model.py`:**
    - `Frame(width_km: float, height_km: float, units: Literal["km", "miles"] = "km")`;
    - `Grid(kind: Literal["hex", "square"], size_km: float, cols: int, rows: int, origin: tuple[float, float] =
      (0.0, 0.0), orientation: Literal["pointy", "flat"] = "pointy")`. `size_km` is the distance between the centres
      of two neighbouring cells in a row. Hexes are odd-row offset when pointy, odd-column offset when flat.
    - `GeoFeature(id, layer, kind, name, geometry: dict, description: str = "", dm_notes: str = "", tags: tuple[str,
      ...] = (), hidden: bool = False, props: Mapping[str, Any] = {})`. Its `props` are:
      - a river's `navigable_km` (from its mouth) and `barrier`;
      - a route's `surface`;
      - a reading's `doubt`.
    - **A river's coordinates run from its source to its mouth:** downstream is the line's direction.
    - `GeoMap(frame, grid, terrain: str, features: tuple[GeoFeature, ...], picture: PictureRef | None = None)`.
      - `terrain` holds one letter per cell, row-major.
      - Its methods: `feature(ref) -> GeoFeature | None` (by id, else by exact name, case-insensitive);
        `features_named(ref) -> list[GeoFeature]` (the candidates for an ambiguous ref); `terrain_of(cell: int) ->
        str | None`.
    - `PictureRef(id: str, width_px: int, height_px: int, km_per_px: float, asset: str | None = None)`.
    - `GeoMapError(message, problems: list[str])` for a document that doesn't hold together.
  - **`grid.py`:**
    - `cell_at(grid, x, y) -> int | None`, `cell_centre(grid, i) -> Point`, `cell_polygon(grid, i) -> list[Point]`;
    - `neighbours(grid, i) -> list[int]`, `cells_within(grid, point, radius_km) -> list[int]`,
      `cells_in_polygon(grid, ring) -> list[int]` (a cell whose centre is inside);
    - `default_grid(frame) -> Grid`: squares, `DEFAULT_CELLS = 200` along the longer side.
  - **`geojson.py`:**
    - `to_geojson(geo, *, terrain_cells: bool = False) -> dict`, the Delve document:
      - `{"type": "FeatureCollection", "delve": {"version": 1, "frame", "grid", "terrain", "picture"}, "features":
        [{"type": "Feature", "id", "geometry", "properties": {layer, kind, name, description, dm_notes, tags, hidden,
        …props}}]}`;
      - with `terrain_cells`, the export for QGIS: one `Polygon` feature per cell, `{layer: "terrain", terrain}`.
    - `from_geojson(doc, *, mapping: PropertyMapping | None = None, scale: Scale | None = None) -> Imported(geo:
      GeoMap | None, warnings: list[str], needs_scale: bool, properties: list[str], kinds: list[str])`.
      - A Delve document (it has `delve`) reads exactly back. Its `terrain` polygons, if any, are ignored in favour of
        the `terrain` string.
      - A foreign one takes x east and y north. It is scaled by `Scale(width_km: float | None = None, known: tuple[str,
        str, float] | None = None)`: the map's width, or two places and the km between them. y is flipped to grow
        down. Without a scale, it answers `needs_scale=True` and no map.
      - `PropertyMapping(kind: str = "kind", name: str = "name", values: Mapping[str, str] = {})` names the properties
        to read and maps raw kind values onto Delve's. A feature whose kind maps to nothing is dropped, with a warning
        naming its kind.
      - A polygon with a `terrain` (or mapped) class becomes the cells it covers.
      - Its water cells are then derived from its water areas (`water_from_areas`, below).
  - **`model.py`'s `water_from_areas(geo, previous: GeoMap | None = None) -> GeoMap`:** keeps the coasts and the
    cells in agreement.
    - A cell whose centre lies in a `sea` or `lake` area (`cells_in_polygon`) gets `w` or `l`.
    - With `previous` (the stored map, on a save), a `w`/`l` cell that lay in a previous water area and lies in none
      now becomes `p`.
    - Water painted with the brush outside any area stays as painted.
    - `from_geojson` calls it, and so does Task 9's `save_geo`, with the stored map as `previous`. Reshaping a lake
      or a sea in the editor therefore moves the cells that routing uses.
    - `is_azgaar(doc) -> bool`, recognised by its properties:
      - cells: `biome` and `height`;
      - burgs: `population` and `capital`;
      - rivers: `discharge`;
      - routes: `group`;
      - markers: `icon`.
    - `AZGAAR_BIOMES` maps Azgaar's default biome **ids**:
      - 0 Marine: sea;
      - 1 Hot desert and 2 Cold desert: desert;
      - 3 Savanna and 4 Grassland: plains;
      - 5 Tropical seasonal forest and 7 Tropical rainforest: jungle;
      - 6 Temperate deciduous forest, 8 Temperate rainforest and 9 Taiga: forest;
      - 10 Tundra and 11 Glacier: arctic;
      - 12 Wetland: swamp.

      A cell's `biome` is read as that number. A string falls back to `AZGAAR_BIOME_NAMES` (the same table by name,
      case-insensitive). An id or name not in the table is plains, with a warning naming it.
      - A land cell of `height` ≥ 67 is mountain, and ≥ 50 hills.
      - A burg is a city at ≥ 5 (thousand), a town at ≥ 1, else a village, and a port when it says so.
      - Markers are places of kind `other` (`ruin` or `dungeon` when their type says so).
      - Sea routes are dropped.
  - **`from_dsl.py`:** `from_view(view: WorldView, *, revealed: Collection[str] = ()) -> FromDsl(geo, warnings,
    names: dict[str, str])` converts a plateau 6 view.
    - Miles × 1.609344 make km, and the frame keeps `units` `miles` for display. y is flipped (the DSL's grows north).
      The frame is the features' bounding box plus 5%. The grid is `default_grid`.
    - **Kinds:**
      - `city` → a `town` place (`city` when `pop` ≥ 10,000, `village` under 1,000);
      - `poi` → its `kind` when it is a place kind, else `dungeon` or `ruin` by its tags, else `other`;
      - `road` → a route (surface `track` → `track`, `trail` → `trail`, else `road`, keeping `surface`);
      - `river` → a river;
      - `lake` → a lake area, and its cells `lake`;
      - `kingdom` → a region;
      - `terrain` → its cells, by biome (marsh swamp, tundra arctic, an unknown biome plains with a warning);
      - `building` and `room` → `other` places at their centre;
      - `street` and `passage` → `trail` routes;
      - `dungeon` → dropped. Each simplification is a warning.
    - A cell under no terrain is plains.
    - `hidden` comes from the tag. `description` and `doc` go to `dm_notes` (plateau 6 made them the DM's).
    - `names` maps each DSL name to its feature id (the same name).
  - **The setting's region map:** its `world` view gets `scale 0.44`, so that Greyhawk to Hardby is about 80 miles,
    as its text says (plateau 6 chronicle).
- [ ] **Step 1: Write the failing tests:**
  - a Delve document round-trips exactly, a hidden place and `dm_notes` included;
  - `hand.geojson` with a mapping and `width_km` gives the right places, routes and km;
  - without a scale, `needs_scale` comes back with the properties and kinds found;
  - `azgaar-cut.geojson` maps itself (a burg, a river, a road, a cell's biome id and height, and a biome given by
    name);
  - `water_from_areas`: a lake area's cells become `l`; shrinking it gives its old cells back as `p`; a cell painted
    `w` outside any area stays;
  - hex and square `cell_at` / `cell_centre` / `neighbours` agree on both orientations;
  - the four plateau 6 fixtures convert (`tests/maps/world/` data), and Greyhawk is a place on the converted region
    map;
  - a converted `doc` is in `dm_notes`, never in `description`;
  - Greyhawk to Hardby is 70–90 miles in a straight line on the converted region map. The test reads
    `src/delve/setting/data/greyhawk-region.map` (through `GreyhawkSetting().world_maps()`), never the copy in
    `tests/maps/world/data/`, which keeps the old scale.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The geo map: frame, terrain cells and features, GeoJSON in and out, and plateau 6's maps converted"`

---

### Task 3: Routing by mode

**Files:**
- Create: `src/delve/maps/geo/routing.py`, `src/delve/rules/adnd2e/overland.py`, `tests/maps/geo/test_routing.py`,
  `tests/rules/adnd2e/test_overland.py`

**Interfaces:**
- Consumes: Task 2 (`GeoMap`, `grid`).
- Produces:
  - **`routing.py`:**
    - `Mode = Literal["foot", "horse", "cart", "river", "ship"]`, `MODES`.
    - `ModeRules(mode, land: Mapping[str, float], routes: Mapping[str, float], water: Literal["none", "river",
      "sea"], downstream: float = 1.0, upstream: float = 1.0, lake: float = 1.0, flies: bool = False)`.
      - The rates are shares of the mode's base pace; 0 can't be crossed.
      - `land` is per terrain class, `routes` per route kind.
    - `build_graph(geo, rules) -> RouteGraph`. The nodes are the cells' centres and the vertices of the lines the mode
      uses. The callers cache the graph.
      - **On land:**
        - a step between neighbouring cells costs half its km at each cell's rate;
        - a route segment costs its km at its kind's rate, whatever the cells under it (so a road crosses a river or a
          ridge: a bridge, a pass);
        - a route vertex joins the cell it is in.
        - Rivers don't block, except one with `barrier`. That one is crossed only by a route, or in a cell holding a
          place tagged `ford` or `bridge`.
      - **`river`:**
        - river segments, downstream at `downstream`, upstream at `upstream`;
        - lake cells at `lake`;
        - a river's mouth joins the lake or sea cell it reaches, and two rivers join where a vertex is within half a
          cell of the other.
      - **`ship`:**
        - sea cells;
        - lake cells in a connected lake of at least `LARGE_LAKE_CELLS = 3` cells;
        - a river from its mouth up to its `navigable_km`.
      - `flies`: every cell at rate 1.
    - `plan(graph, start: Point, goal: Point) -> GeoRoute`.
      - Dijkstra with a heap (A* with the straight line at the fastest rate is allowed).
      - The ends snap to the graph within one cell: the cell they are in, or for water modes the nearest river vertex
        or sailable cell.
      - **A land mode's end in a cell it can't cross** snaps to the nearest crossable cell or route vertex within one
        cell. Water, impassable and `.` (outside the map) all count. This covers a port whose point lies inside its
        bay's polygon: Hardby, at (640, 385), lies inside the region map's `wooly-bay`, so its cell is `l`.
      - `.` cells (unread, or "outside the map" after the review) are crossed by no mode.
      - Ties go to routes: off-route steps cost × 1.0001.
      - `NoRoute(reason: str)` when an end doesn't snap ("Greyhawk isn't on a river or a lake") or nothing joins them.
    - `GeoRoute(points: tuple[Point, ...], km: float, cost_km: float, stretches: tuple[Stretch, ...])`.
      - `cost_km` is the km at the base pace.
      - `Stretch(km, rate, what: str, start_km: float)`: `what` is a terrain class, a route kind, `"downstream"`,
        `"upstream"`, `"lake"` or `"sea"`.
    - `point_along(route, km) -> Point`, `stretch_at(route, km) -> Stretch`, `slowest(route, n=3) -> list[Stretch]`.
  - **`overland.py`** (the 2e numbers; the data dictionary lists them):
    - `LAND_RATES = {plains: 1, urban: 1, forest: 1/2, hills: 1/2, desert: 1/2, arctic: 1/2, swamp: 1/3, jungle: 1/3,
      mountain: 1/3, impassable: 0, sea: 0, lake: 0}` (plateau 6's `TERRAIN_RATES`);
    - `ROUTE_RATES = {road: 1, track: 1/1.2, trail: 1/1.5}` (plateau 6's surface multipliers);
    - `CART_LAND`: `LAND_RATES` halved, mountain, swamp, jungle and impassable 0;
    - `HORSE_MV = 24` (a riding horse, when `horse` has no mount in `by`);
    - `CART_MILES_PER_DAY = 12` (DMG, Vehicles: a draft horse halved when hitched);
    - `RIVER_BOAT_MPH = 2` (DMG Table 76), `RIVER_CURRENT_MPH = 1`, `RIVER_HOURS = 10`: 30 miles a day downstream, 10
      upstream, 20 on a lake;
    - `SHIP_MPH = 3` (DMG Table 77, a cog or coaster), `SHIP_HOURS = 12`: 36 miles a day.
    - `mode_rules(mode, *, flies=False) -> ModeRules` builds the rules from these.
    - `MILES_TO_KM = 1.609344`.
- [ ] **Step 1: Write the failing tests** on small hand-built `GeoMap`s:
  - the road is faster than across the hills;
  - a ship goes around a peninsula, not across it;
  - a river boat is faster downstream than up;
  - an impassable ridge is crossed only at its pass;
  - a `barrier` river is crossed at the ford and nowhere else;
  - Review Focus 3's snapping and refusals;
  - a flyer goes straight over the ridge;
  - a foot leg to a port whose point lies inside a lake area snaps to the shore cell and arrives;
  - **the speed goal** (`time.perf_counter`), on two maps:
    - a 200 × 200 square grid with 500 road segments;
    - a flat-topped **155 × 105 hex grid** (about 16,000 cells, the owner's Flanaess, whose hexes are about 88 px
      apart in a row and 104 px tall on 13,706 × 10,678 px) with 500 road and river segments.

    On each, `build_graph` takes under 2 s, since a map edit rebuilds it. A route corner to corner then plans in
    under 1 s.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Routes by mode over the terrain cells, the roads and the rivers, at 2e speeds"`

---

### Task 4: What the party knows, and the seat's view

**Files:**
- Create: `src/delve/maps/geo/knowledge.py`, `tests/maps/geo/test_knowledge.py`

**Interfaces:**
- Consumes: Task 1 (`WorldKnowledge`, `Journey`), Task 2.
- Produces:
  - **`SIGHT_KM = 10.0`, `SIGHT_FACTOR = {"hills": 2.0, "mountain": 3.0}`** (of the cell the party stands in).
  - **`known_cells(geo, known) -> frozenset[int]`:** every cell when `everything`.
  - **`visible_features(geo, known) -> list[GeoFeature]`:**
    - never one in `forgotten`;
    - one in `features` whole;
    - a `hidden` one only when in `features`;
    - otherwise every feature when `everything`;
    - else a point in a known cell, and a line or an area clipped (shapely) to the known cells' union, dropped when
      nothing is left.
  - **`seat_view(geo, known, *, name, title, party: Point | None, journey: Journey | None, picture: dict | None,
    tiles_version: str) -> dict`:**
    - `{name, title, units, frame, grid, picture, tiles_version, known: {all, cells: runs}, terrain, features: [{id,
      layer, kind, name, description, geometry, tags}], party, journey: {mode, to_label, points, done_km, km} | null}`;
    - `terrain` has `.` in every unknown cell;
    - the tags leave out `hidden`;
    - the journey's points are clipped to the known cells, and `to_label` is null unless that place is visible.
    - Never `dm_notes`, `hidden`, `props` or a picture id.
  - **`dm_view(geo, known, *, name, title, party, journey, picture) -> dict`:** every feature with `dm_notes`, `hidden`
    and `known: bool`, the known cells as runs, the journey whole, and `picture.id`.
  - **`start(geo, how: Literal["everything", "nothing", "regions", "area"], *, regions: Sequence[str] = (), ring:
    Sequence[Point] = ()) -> WorldKnowledge`.** A region gives its cells; its roads come with the area, clipped.
  - **`reveal_along(geo, known, points, *, sight_km=SIGHT_KM) -> Revealed(knowledge, places: list[str])`:** the cells
    within sight of the line, sampled every half cell, and the names of the places that became visible.
  - **`reveal_feature(known, id)`, `forget_feature(known, id)`, `reveal_area(geo, known, centre, radius_km)`,
    `forget_area(geo, known, centre, radius_km)`.**
    - `forget_area` takes the area's cells out.
    - On an `everything` knowledge, it first turns it into every cell, listed, and then takes them out.
    - A feature then shows only as far as it lies in the cells still known, so a road through the area is cut there.
- [ ] **Step 1: Write the failing tests:**
  - `SECRET-XYZZY` planted in a hidden place's name, a known place's `dm_notes` and a place in an unknown area never
    appears in `json.dumps(seat_view(…))`;
  - a road from a known cell into unknown ones is cut at the edge;
  - a journey line is clipped, and the destination's name hidden while unknown;
  - `everything` shows all but hidden; `forgotten` hides a place in a known area;
  - starting from a region knows its cells and the part of its road inside;
  - sight from a hill cell reaches twice as far;
  - `reveal_along` names the places it uncovered, never a hidden one;
  - `forget_area` on an `everything` knowledge hides the area's place and cuts the road through it.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "What the party knows of a world map, and the seat's and the DM's view of it"`

---

### Task 5: Pictures, tiles, the fog, and world maps in a `.dscn`

**Files:**
- Create: `src/delve/maps/geo/tiles.py`, `src/delve/maps/geo/pictures.py`, `src/delve/modules/worldmaps.py`,
  `src/delve/web/routes/world_pictures.py`, `tests/maps/geo/test_tiles.py`, `tests/maps/geo/test_pictures.py`
  (their pictures are drawn in the test with Pillow, not with Task 7's `pictures.py`)
- Modify: `tests/modules/test_worldmaps.py` (plateau 6's; it already exists, so add to it),
  `src/delve/modules/source.py` (`_unreadable_worldmaps` skips `geojson` maps; a `worldmap-in-review` warning),
  `src/delve/modules/importer.py`, `src/delve/modules/exporter.py`, `src/delve/web/routes/modules.py` (the import cuts
  the pictures), `src/delve/web/app.py` (the router)

**Interfaces:**
- Consumes: Task 1 (`WorldPicture`, `world_pictures`), Task 2.
- Produces:
  - **`tiles.py`** (Pillow; pure):
    - `MAX_PICTURE_PIXELS = 200_000_000`, `PICTURE_TYPES = ("image/png", "image/jpeg", "image/webp")`, `FOG =
      "#d8cfbd"`;
    - `open_picture(source: bytes | Path, mime: str) -> Image`. It sets Pillow's `MAX_IMAGE_PIXELS` to the cap while
      it opens, and checks the magic bytes against `mime`. It raises `PictureRefused(status: 400 | 422, message)`:
      400 for bytes that aren't the type, 422 for more than `MAX_PICTURE_PIXELS`. A body over 64 MB is the routes'
      413, before Pillow sees it.
    - `max_zoom(width_px, height_px) -> int` = ⌈log2(max side / 256)⌉, at least 0.
    - `cut_tiles(image) -> Iterator[tuple[int, int, int, bytes]]` yields `(z, x, y, JPEG bytes at quality 85)`.
      - At `max_zoom`, a tile pixel is a picture pixel. Each lower level halves the one above, so only two levels are
        in memory at once.
      - Edge tiles are padded with `FOG`.
    - `tile_mask(geo, cells: frozenset[int], z, x, y, max_zoom) -> Literal["all", "none"] | Image` (an `L` mask of the
      known cells' polygons);
    - `fog_tile(tile: bytes, mask: Image) -> bytes`: opaque `FOG` where the mask is 0.
  - **`pictures.py`** (storage injected, as `modules.source` takes a `SourceStorage`):
    - `PictureStore` (a Protocol with `blobs` and `world_pictures`);
    - `store_blob(store, sha: str, mime: str) -> WorldPicture` cuts the tiles of an original already in the blob store
      and is idempotent;
    - `store(store, data: bytes, mime: str) -> WorldPicture` puts the original first;
    - `tile(store, picture_id, z, x, y) -> bytes | None`;
    - `original(store, picture_id) -> tuple[bytes, str] | None`: the original's bytes and mime, for Task 11's
      organiser download;
    - `seat_tile(store, picture_id, geo, cells: frozenset[int], z, x, y) -> bytes | None`, given the known cells (the
      callers take them from Task 4's `known_cells`). None means not sent: nothing known, or
      outside the picture. A partly known tile is fogged. An LRU of 512 fogged tiles is keyed by `(picture, z, x, y,
      digest of the known cells)`.
  - **Route:** `GET /api/world-pictures/{picture_id}/tiles/{z}/{x}/{y}` (`Organiser`). It answers the raw tile,
    `image/jpeg`, with `X-Content-Type-Options: nosniff` and `Cache-Control: private, max-age=86400`, and 404 `{"error":
    "no such tile"}`. The editors and the DM view use it.
  - **`modules/worldmaps.py`:**
    - `get_world_map(source, name) -> WorldMapSource | None`. A DSL include fragment (a map whose `dsl` isn't a
      workspace, `delve.maps.world.is_workspace`) is never a world map of its own: it is left out of lists and
      converted only as an include;
    - `put_world_map(source, world_map) -> ModuleSource`;
    - `remove_world_map(source, name) -> ModuleSource`;
    - `geo_of(world_map, includes) -> dict` (the stored `geo`, else converted from `dsl` by `from_dsl`, compiled
      with the module's `world_includes`).
  - **The `.dscn` format, a new `worldmaps[]` type `geojson`:**
    - `file` is `worldmaps/<name>.geojson`, the Delve document;
    - its picture is an asset `worldmap-<name>` (the original bytes, `role` `attachment`, `audience` `gm`, described
      "The picture of the world map <title>"), named in the document's `delve.picture.asset`;
    - the importer keeps such an asset out of `ModuleSource.attachments`, so `show_image` can never offer it;
    - `ttrpg2-worldmap` entries read and write as before;
    - a map in `review` isn't exported (warning `worldmap-in-review`, `ref` `worldmap:<name>`).
    - The copied `dscn` package doesn't change: `container.add_worldmap(name, text, type="geojson",
      file=…)` already takes a type.
  - **The module import route** calls `store_blob` for each imported map's picture, in the threadpool.
- [ ] **Step 1: Write the failing tests:**
  - a synthetic 1,000 × 700 picture cuts into the right pyramid (levels 0–2, edge tiles padded);
  - a tile half in known cells is fog where unknown: a planted magenta stays out of its fogged half;
  - a fully unknown tile is None;
  - a PNG declared as JPEG is 400;
  - Review Focus 2 with `MAX_PICTURE_PIXELS` patched down: 422 for a picture of more pixels, before any tile is
    put;
  - `.dscn` round trip: a `geojson` map with its picture exports and imports to the same document and the same picture
    id, with no attachment added;
  - a map in review isn't exported;
  - the organiser tile route refuses a seat (403).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "World-map pictures cut into tiles, the seat's fog, and geojson world maps in a .dscn"`

---

### Task 6: The vision side call, and the conversion jobs' plumbing

**Files:**
- Create: `src/delve/maps/vision.py`, `tests/dm/claude_cli/test_vision.py`, `tests/conversions/test_jobs.py`
- Modify: `src/delve/dm/provider.py`, `src/delve/dm/fake.py`, `src/delve/dm/claude_cli/{argv.py,provider.py}`,
  `tests/fixtures/fake_claude.py`, `tests/e2e/fake_play_server.py` (its `claude()` hands vision calls to the fake),
  `src/delve/conversions/runner.py`, `src/delve/web/routes/conversions.py` (`conversion_json` shows `target`, `result`
  and `questions`), `web/src/api.ts` (only `ConversionStep` and the conversion kind), `web/src/module/
  ConversionProgress.tsx`, `web/src/components/Nav.tsx` (the end notice), `web/src/module/conversions.ts`,
  `web/src/routes/NewModule.tsx` (its list), the tests beside them, `en.json`/`nl.json` (anchor `conversion.dismiss`)

**Interfaces:**
- Consumes: Task 1 (the `Conversion` fields and kinds).
- Produces:
  - **`DMProvider.vision_call(prompt: str, image: bytes, media_type: str, choice: BackendChoice, *, timeout: float |
    None = None) -> str`.** It is stateless with no tools, like `side_call`.
  - **`argv.vision_argv(*, model, effort) -> list[str]`:** `[CLAUDE, "-p", "--input-format", "stream-json",
    "--output-format", "stream-json", "--verbose", "--model", <as side_argv chooses>, *AUX_ARGS]`, plus `--effort` as
    in `side_argv`. Never `--mcp-config`.
  - **`ClaudeCliProvider.vision_call`:**
    - it writes one line on stdin, `{"type": "user", "message": {"role": "user", "content": [{"type": "image",
      "source": {"type": "base64", "media_type", "data"}}, {"type": "text", "text": prompt}]}}`, and closes stdin;
    - the answer is the `result` line's `result`, else the assistant text;
    - its errors are `side_call`'s (`ClaudeCliError`, the timeout kills the process group);
    - `MAX_VISION_BYTES = 5_000_000`.
  - **`FakeDM(…, vision_answers: dict[str, str] | None = None, vision_handler: Callable[[str, bytes, str], str] |
    None = None)`.** It records `vision_prompts` and `vision_images: list[tuple[str, int]]` (the media type and the
    size), and otherwise echoes `(fake vision answer to: …)`.
  - **The fake `claude`:** `--input-format stream-json` without `--mcp-config` is the vision mode.
    - It reads the one line and asserts an image block.
    - It logs `{prompt, media_type, size}` to `FAKE_CLAUDE_VISION_LOG` (JSON lines), when that is set.
    - It answers the script's next `"vision"` item, else `(fake vision answer)`, as an `assistant` line and a
      `result` line.
  - **`delve/maps/vision.py`:**
    - `Look = Callable[[str, bytes, str], Awaitable[str]]`;
    - `VISION_MAX_SIDE = 1568`;
    - `fit_for_vision(image) -> tuple[bytes, str]`: a PNG no longer than that on either side.
  - **The runner's jobs** (`conversions/runner.py`):
    - `STEPS` gains `"worldmap": (("tiles",), ("grid",), ("terrain",), ("water",), ("places",), ("routes",))`,
      `"dungeon-map": (("drawing",),)` and `"book-map": (("drawing",),)`.
    - `start_job(services, kind, title, work: Callable[[_Live], Coroutine[Any, Any, None]], *, target: dict | None =
      None, cleanup=lambda: None) -> Conversion` is public, with plateau 5's one-at-a-time rule and its cancel and
      orphan handling. It takes no `mode`: it opens the row with `_open(…, mode="ready")`, since
      `conversions.mode` is NOT NULL and `_open` checks it. A job that makes no module ignores it.
    - `finish(services, live, *, result: dict | None = None, warnings: list[Warning] = ()) -> Conversion` ends a job
      that makes no module.
    - `look_for(services) -> Look` (Settings' `conversion` job, `CONVERSION_TIMEOUT` per call), beside `_complete`.
    - `progress_for(services, live) -> Progress` is `_progress`, made public.
  - **Web:**
    - `ConversionStep` gains `"tiles" | "grid" | "terrain" | "water" | "places" | "routes" | "drawing"`, and the kind
      union gains the three new kinds;
    - `ConversionProgress` names each step (`conversion.step.<name>`) and counts it (`conversion.count.<name>`, a
      key for each new step).
    - **The jobs that make no module** (`worldmap`, `dungeon-map`, `book-map`), in `conversions.ts`'
      `conversionLink(conversion) -> string | null`:
      - Nav's end notice links a `worldmap` job to its map's review (`/world-maps/<owner>/<id>/<name>/review`, from
        `target`), and a draft job to the module's Maps tab (`/modules/<target.module_id>?tab=maps`, where Task 13's
        drafts show). A module job links to its module, as before.
      - `NewModule`'s list of conversions leaves the three kinds out, and so does its "follow the running one".
- [ ] **Step 1: Write the failing tests:**
  - `vision_argv` (no MCP, no tools, stream-json both ways, the model rule);
  - the provider against the fake `claude` on `PATH` (the image reaches it, the answer comes back, a timeout fails);
  - `FakeDM`'s vision answers;
  - `start_job`/`finish` (a second job is 409, cancel ends `cancelled`, `result` is stored, a job left running fails
    at start);
  - `ConversionProgress` labels and counts a `grid` step;
  - Nav's notice for a done `worldmap` job links to its review, and for a `dungeon-map` job to the module's maps;
    `NewModule` doesn't list either.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "A vision side call for Claude, faked in tests, and conversion jobs that make no module"`

---

### Task 7: Reading a picture, part 1: the scale, the grid, the terrain and the water

**Files:**
- Create: `src/delve/maps/geo/reading/{__init__.py,scale.py,grid_detect.py,colours.py,water.py}`,
  `tests/maps/geo/pictures.py` (the synthetic pictures), `tests/maps/geo/reading/test_{scale,grid,colours,water}.py`

**Interfaces:**
- Consumes: Task 1 (Pillow, numpy), Task 2.
- Produces:
  - **`tests/maps/geo/pictures.py`:**
    - `hex_map(*, size_px=40, cols=16, rows=12, orientation="pointy") -> Synthetic(image, truth)`;
    - `square_map(*, size_px=32, cols=20, rows=14) -> Synthetic`;
    - `truth` holds the grid in pixels and each cell's terrain, in four flat colours (plains, forest, hills,
      mountain). It also holds:
      - a cream margin frame with cell numbers in it, as the owner's map has, so no water touches the picture's
        edge;
      - a sea along the grid's left edge, inside the frame, and a lake;
      - a river from the lake to the sea, so both its ends reach water;
      - three towns with a symbol and a label drawn in Pillow's default font. One of them is on the river, halfway,
        and a port with a symbol and a label sits at the river's mouth;
      - a road between two towns, a label with no symbol beside the river (its name), and one cell of mixed colour.
    - The river town and the port give the river-boat leg of Task 21 a start and a destination.
    - `fake_ocr(truth) -> PictureOcr` answers the drawn labels' boxes.
  - **`scale.py`:** `ScaleKey(cell: Literal["hex", "square"] | None, distance: float, units: Literal["km", "miles"],
    points: tuple[Point, Point] | None = None)` (no free-text parsing: the form asks for each part), with
    `km(self) -> float` and `check(self)` (`ValueError`: no grid and no points, a distance ≤ 0, two equal points).
  - **`grid_detect.py`:** `find_grid(image, cell: Literal["hex", "square"]) -> GridGuess | None`, `GridGuess(kind,
    size_px: float, origin_px: Point, orientation, confidence: float)`. The method is the builder's, within
    deterministic and numpy only (for example, the periodicity of the dark-line mask along the grid's directions).
  - **`colours.py`:**
    - `MAX_CLUSTERS = 16`, `MIXED_SHARE = 0.6`;
    - `cluster_cells(image, grid_px: GridGuess) -> Clusters(palette: list[tuple[int, int, int]], cell_cluster:
      list[int], mixed: list[int])`. It samples each cell's interior (lines and labels excluded by the cell's middle
      70%) and quantises with Pillow's `Image.quantize(method=Image.Quantize.MEDIANCUT)`.
  - **`water.py`:**
    - blue is hue 180–250°, saturation ≥ 0.25 and value ≥ 0.25;
    - `find_water(image, grid_px) -> Water(bodies: list[WaterBody], rivers: list[RiverTrace])`, with `sea` and
      `lake` properties listing the cells of each kind;
    - a cell at least half blue is water;
    - **sea or lake:**
      - a connected water body touching the **grid's** bounds (the detected grid's extent, never the picture's edge,
        which a margin frame keeps dry) is sea;
      - when no body touches them, the largest body is sea;
      - every other body is a lake;
      - a body classed by size, not by touching the bounds, carries the guess (`WaterBody(cells, kind, guessed:
        bool)`), and Task 8 makes it a `water-kind-guessed` doubt;
    - thin blue lines are skeletonised (numpy thinning) into polylines. `RiverTrace(points_px, mouth: Literal["start",
      "end"] | None, flow_guessed: bool = False)`. The mouth is:
      - the one end that reaches sea or lake;
      - when both ends reach water, the end at the sea, else the end at the larger body, with `flow_guessed`;
      - None when neither end reaches water, which is a doubt.
  - **Analysis size:** `ANALYSIS_MAX_PIXELS = 40_000_000`. A bigger picture is read through a downscaled copy for the
    grid, the colours and the water, and the pixel results are scaled back.
- [ ] **Step 1: Write the failing tests:**
  - the grid of `hex_map` (both orientations) and `square_map` is found within 2% of its size and half a cell of its
    origin;
  - a picture with no grid gives None;
  - every cell's cluster matches the truth's four terrains, and the mixed cell is in `mixed`;
  - the sea cells and the river are found, and the river's mouth is the end at the sea, not the lake;
  - with the frame, the sea is still sea (it touches the grid's bounds), and the lake is a lake;
  - a picture whose water touches neither the picture's edge nor the grid's bounds makes the largest body sea,
    `guessed`;
  - a river between two lakes takes the larger as its mouth, `flow_guessed`;
  - the same picture read twice gives the same clusters;
  - `ScaleKey.check` refuses no grid without points.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Reading a map picture: its grid and scale, the terrain colours, the sea, lakes and rivers"`

---

### Task 8: Reading a picture, part 2: places, routes, the review and the whole reading

**Files:**
- Create: `src/delve/maps/geo/reading/{ocr.py,places.py,routes.py,review.py,read.py}`,
  `src/delve/maps/geo/reading/prompts/{clusters.md,labels.md}`, `tests/maps/geo/reading/test_{places,routes,review,
  read}.py`

**Interfaces:**
- Consumes: Task 6 (`Look`, `fit_for_vision`), Task 7.
- Produces:
  - **`ocr.py`:** `OcrWord(text, box: tuple[int, int, int, int], confidence: float)`, `PictureOcr = Callable[[Image],
    list[OcrWord]]`, and `tesseract_words() -> PictureOcr | None` (pytesseract `image_to_data`; None without the
    binary, or when `DELVE_OCR=off`, which every test has).
    - **Labels that are only digits** (the grid's cell numbers in the frame, "0712") are dropped before pairing,
      never reported.
  - **`places.py`:**
    - `read_places(image, grid_px, *, ocr: PictureOcr | None, look: Look) -> PlacesReading(places: list[ReadPlace],
      doubts: list[Doubt])`;
    - symbols are small dark blobs of a symbol's size, outside the words' boxes;
    - OCR runs on 2,048 px tiles with 128 px overlap, at full resolution, and words on a line join into labels;
    - a label is paired with its nearest symbol within three label heights. Two kinds of label are never paired with
      a symbol:
      - a label along a river line (most of its box within one label height of the trace, and longer than it is
        tall) is offered as that river's name, "SELINTAN";
      - a label spanning several cells (wider than two cells, or letter-spaced) is offered as a region's name, "CAIRN
        HILLS";
      - both are `label-unpaired` doubts whose `alternatives` start with `river-name` or `region-name`;
    - a label under confidence 60, or a symbol without a label, goes to `look` on a crop (`labels.md` asks for JSON
      `[{"n": 1, "label": "…"}]` for the numbered crops of one sheet);
    - a place's kind is `town` unless the symbol says otherwise (a doubt `kind-guessed`).
  - **`routes.py`:** `find_routes(image, grid_px, clusters, water) -> list[RouteTrace]`. Thin lines of a colour that
    is neither blue nor near any cell's cluster become routes, when they run at least 3 cells. Their kind is `road`
    unless they are dashed (`trail`).
  - **`review.py`:**
    - `Doubt(id, kind, ref, message, reading: str, alternatives: list[str], resolved: bool = False)`. The kinds:
      `cluster-unmapped`, `water-kind-guessed`, `river-flow-guessed`, `label-unpaired`, `symbol-unlabelled`,
      `label-uncertain`, `kind-guessed`, `cell-mixed` and `river-no-mouth`.
      - A `label-unpaired` doubt's alternatives are `place` (a place at the nearest symbol or at the label),
        `river-name`, `region-name` and `drop`, the likely one first.
      - `water-kind-guessed` offers `sea` and `lake`, and `river-flow-guessed` offers `keep` and `reverse`.
    - `OUTSIDE = "outside"`: a cluster mapped to it (the frame, the legend, the margin) has no terrain. Its cells stay
      `.`, which no mode crosses and no seat sees as land. It counts as mapped.
    - `Reading(geo, clusters: list[ClusterReading(id, colour, cells, suggestion: str | None, terrain: str | None)],
      doubts: list[Doubt])`, with `to_dict`/`from_dict`. The doubts are ordered by kind as listed, then by position.
    - `apply_review(reading, *, clusters: Mapping[int, str] = {}, decisions: Mapping[str, str] = {}, kinds:
      Mapping[str, str] = {}) -> Reading`.
      - Mapping a cluster (to a terrain class or `OUTSIDE`) re-derives its cells' terrain.
      - A decision is one of the doubt's `alternatives`, `"keep"` or `"drop"`, and marks it resolved.
      - `kinds` decides all of a kind at once: `{"label-unpaired": "drop"}` applies the choice to every unresolved
        doubt of that kind that offers it, and leaves the others for one-by-one.
    - `unmapped(reading) -> list[int]`: the clusters with neither a terrain nor `OUTSIDE`.
  - **`read.py`:** `async def read_picture(image, key: ScaleKey, *, ocr: PictureOcr | None, look: Look, progress:
    Callable[[str, int, int], None], should_stop: Callable[[], bool] = lambda: False) -> Reading`.
    - The steps are `grid`, `terrain`, `water`, `places` and `routes`; the CPU work runs in `asyncio.to_thread`.
    - The terrain step asks `look` once, with a contact sheet of each cluster's sample cells (`clusters.md`: JSON
      `{"<cluster>": "<terrain class>"}`), for `suggestion`.
    - Water clusters are mapped `sea` or `lake` by the water step, and cells that are certain use their class.
    - Every other cluster starts unmapped (terrain `.`), with a `cluster-unmapped` doubt.
    - With no grid it uses square cells of `key.points`' scale, `DEFAULT_CELLS` along the longer side.
    - The grid's `size_km` is `key.km()` (or the points' km per pixel × cell px).
    - `should_stop` is asked between steps (it raises `ReadStopped`, as the books do).
- [ ] **Step 1: Write the failing tests**, with `fake_ocr` and a `look` that answers from the truth:
  - the three towns are found with their names, at their symbols;
  - a label moved away from its symbol is `label-unpaired`;
  - the road is a route between its two towns;
  - `read_picture` on `hex_map` with "1 hex = 30 miles" gives a 48.28 km grid;
  - each step's progress is reported in order;
  - Review Focus 5: the doubts come first in kind order, every cluster is a `cluster-unmapped` doubt until mapped,
    `apply_review` with every cluster mapped leaves no terrain `.`, and `drop` removes a place;
  - with `ocr=None`, the labels come from `look`;
  - the frame's digit labels make no doubt;
  - the river's name label is offered as `river-name` and isn't paired with the river town;
  - `kinds={"label-unpaired": "drop"}` resolves every such doubt at once;
  - the frame's colour mapped to `outside` lets accept's `unmapped` be empty, with its cells `.`;
  - a guessed water kind and a guessed river flow are doubts, and `reverse` reverses the river's line.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Reading a map picture: places and their labels, routes, and the review list"`

---

### Task 9: Campaign world maps on the new model

**Files:**
- Modify: `src/delve/play/world_maps.py`, `src/delve/dm/tools/world.py`, `src/delve/dm/tools/host.py`,
  `tests/play/test_world_maps.py` (new), `tests/dm/tools/test_fourth_wall.py`, `tests/dm/tools/test_tools.py`.
- **The hint and the prompt** stop naming `edit_world_map`: `src/delve/dm/prompt/dm.md` (its lines on world maps,
  504–506), `NO_MAP_HINT`, and `tests/play/test_travel.py`'s
  `test_without_a_world_map_the_refusal_names_edit_world_map` (lines 195–203, that test only; the rest of the file is
  Task 10's). `tests/dm/test_prompt.py` requires every tool `dm.md` names to exist.
- Not `src/delve/web/routes/campaigns.py`: `seed_world` calls `world_maps.seed`, which reads the setting pointer
  itself.

**Interfaces:**
- Consumes: Tasks 1–5.
- **Task 9 adds; it removes nothing.** Plateau 6's `view`, `save`, `locate`, `edit`, `seat_svg`, `dm_svg`, `hidden`,
  `describe` and the `edit_world_map` tool stay, working, for their callers:
  - `play/travel.py` (until Task 10);
  - `dm/tools/world.py`'s `distance`, `nearest` and `world_map` (Tasks 10 and 11);
  - `web/routes/world.py` (Task 11);
  - their tests.

  Task 11 removes them once nothing calls them.
- Produces (names kept from plateau 6 where they still fit):
  - **Kept as they are:** `seed`'s and `ensure_seeded`'s names, `maps`, `get`, `current_map`, `position`, `move_to`,
    `place_party`, `delete`, `reveal`.
  - **Beside plateau 6's, under new names** (these are the final names; plateau 6's go in Task 11):
    - `geo(ctx, name) -> GeoMap`, cached in `_GEO` by `(campaign, name, updated_at)`;
    - `save_geo(ctx, name, geo: dict, title="", *, status="ready") -> CampaignWorldMap`. It checks the document with
      `from_geojson`, derives the water cells (`water_from_areas`, with the stored map as `previous`), and raises
      `GeoMapError` with its problems;
    - `locate_geo(geo, ref) -> tuple[str | None, Point]`, plateau 6's `locate` on a `GeoMap`;
    - `party_point(ctx, name) -> Point | None`, the party's point in km. A stored position with `km=False` is
      converted: by its `at` place on the geo map, else its point through the conversion.
  - **New:**
    - `ensure_geo(ctx, world_map) -> CampaignWorldMap`. A row with `dsl` and no `geo` is converted on first read
      (`from_dsl`, compiled with the campaign's includes). Its `knowledge` becomes everything plus its `revealed`, but
      only when it has none yet, so a seeded copy keeps knowing nothing.
      - It writes only `geo` and `knowledge`. `dsl`, `revealed` and the stored position stay, so plateau 6's readers
        keep working until Tasks 10 and 11.
      - A row whose `dsl` isn't a workspace (a DSL include fragment, `is_workspace`) is skipped: it isn't a map of
        its own and is never listed.
      - Until Task 11, plateau 6's `save` (the DSL PUT) clears `geo`, so the next read converts the new text.
    - `knowledge(ctx, name) -> WorldKnowledge`.
    - `set_start(ctx, name, how, *, regions=(), ring=()) -> WorldKnowledge`.
    - `seat_maps(ctx) -> list[CampaignWorldMap]`: the `ready` workspace maps that the party knows something of, or is
      on.
    - `seat_view(ctx, name) -> dict`, `dm_view(ctx, name) -> dict` (Task 4 with `party_point` and the journey).
    - `graph(ctx, name, rules: ModeRules) -> RouteGraph`, cached beside the map, by mode and `flies`.
    - `hide(ctx, feature, map="")`: any feature, a place or a road.
    - `reveal_area(ctx, at, radius_km=SIGHT_KM, map="", *, forget=False)`. With `forget`, it calls Task 4's
      `forget_area`, so the DM can hide an area.
    - `add_place(ctx, name, kind, at, *, description="", notes="", hidden=False, map="") -> dict`. It adds a point
      feature with a new id (its name, made unique) and `dm_notes` `notes`.
    - `reveal_around(ctx, name, point) -> list[str]`: the cells in sight of a point; `place_party` calls it.
    - `accept(ctx, name)`: review → ready (Task 12 calls it).
  - **`reveal(ctx, feature, map="")`** takes any feature now: a region reveals its cells, anything else the feature
    itself. Until Task 11, it also keeps adding to `revealed`, which plateau 6's SVG reads.
  - **`place_party`** writes the position as before (`km=False`) on a map that has `dsl`, so plateau 6's travel still
    reads it. On a geo-only map it writes `km=True`. Either way it calls `reveal_around`. Task 10 makes every write
    `km=True`.
  - **`seed`:**
    - module maps whose `status` is `ready` are copied: a DSL one keeps its `dsl` and gets its `geo` with nothing
      known;
    - then the setting's: the module world map that `storage.setting_world_maps.get(setting)` names, from that
      module's working source, else the setting's built-in maps converted;
    - every copy starts with `knowledge` nothing;
    - the module's map still wins a name clash.
  - **A map in `review`** is refused by `current_map`, `place_party` and travel ("The world map … is still in
    review.").
  - **`NO_MAP_HINT`** becomes "The organiser adds world maps on the campaign's page; until then, narrate the journey
    with advance_days." `dm.md`'s lines 504–506 name `add_place`, `reveal_place`, `reveal_area` and `hide_place`
    instead of `edit_world_map`.
  - **DM tools** (`dm/tools/world.py`):
    - `place_party`, `distance`, `nearest`, `world_map` and `edit_world_map` are kept (Task 11 removes
      `edit_world_map`);
    - `reveal_place(feature, map="")` takes any feature;
    - `hide_place(feature, map="")` (mutates, not player-visible) is new: a place or a road;
    - `reveal_area(at, radius_km=10, map="", forget=False)` (mutates, not player-visible) is new. With `forget` it
      hides the area: the party forgets it, or it was never theirs to know;
    - `add_place(name, kind, at, description="", notes="", hidden=False, map="")` (mutates, not player-visible; `kind`
      an enum of `PLACE_KINDS`) is new.
    - In `test_tools.py`'s ttrpg2 mapping, `add_world_map_feature` → `add_place`. The other `edit_world_map` rows are
      Task 11's.
  - **The fourth-wall test's `planted` fixture** plants its hidden place with `add_place(…, hidden=True)` instead of
    `edit_world_map`.
- [ ] **Step 1: Write the failing tests:**
  - Review Focus 4: a plateau 6 campaign (the DSL map, a position at Greyhawk, a revealed hidden place) converts on
    its first `maps()`, keeps the party at Greyhawk (`party_point` is Greyhawk's point in km), keeps the revealed place
    visible and knows everything; a new campaign's setting copy knows nothing;
  - the converted campaign still travels with plateau 6's `travel` (its tests pass unchanged);
  - a DSL include fragment isn't converted on its own, nor listed by `seat_maps`, and a map that includes it converts
    with the included features;
  - the install's setting map replaces the built-in one for a new campaign of that setting;
  - a map in review isn't copied, and isn't listed by `seat_maps`;
  - `place_party` reveals 10 km around;
  - `add_place` with `hidden` stays out of `seat_view`;
  - `hide_place` takes a known place out, and a road;
  - `reveal_area(…, forget=True)` hides an area;
  - `reveal_place` on a region knows its cells;
  - `save_geo` of a reshaped lake moves its cells;
  - the no-map refusal's hint names `advance_days` and no missing tool;
  - the fourth-wall `SESSION` runs the new tools.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Campaign world maps on the geo model: converted once, known by the party, seeded from the install's setting map"`

---

### Task 10: Travel by mode, and journeys

**Files:**
- Modify: `src/delve/play/travel.py`, `src/delve/dm/tools/travel.py`, `src/delve/dm/tools/world.py` (the `distance`
  and `nearest` specs and functions), `src/delve/dm/tools/host.py`, `src/delve/play/world_maps.py` (`move_to` writes
  `km=True`), `src/delve/play/possessions.py` (`mph`), `tests/dm/tools/test_fourth_wall.py`,
  `tests/dm/tools/test_tools.py`.
- `tests/play/test_travel.py`, except its SVG cases (lines 133–147) and its `world_map` and `edit_world_map` cases
  (lines 360–374), which are Task 11's.
- `tests/e2e/test_a_journey.py`: its travel assertions only, such as `travel.TERRAIN_RATES` and the legs' miles
  (lines 175–187). The SVG assertions are Task 11's.
- After this task, nothing but `web/routes/world.py` and the tests of Task 11 calls plateau 6's `view`, `save` or
  `locate`. Check it with `grep -rnE "world_maps\.(view|save|locate)\(" src tests`.

**Interfaces:**
- Consumes: Task 3 (`plan`, `mode_rules`, `overland`), Task 9.
- Produces:
  - **`travel(ctx, to: str = "", *, mode: str = "foot", terrain: str = "", by: Iterable[str] = (), forced_march: bool
    = False, miles_per_day: float = 0, map: str = "") -> dict`:**
    - **The leg:**
      - an empty `to` carries on the party's `Journey` (refused "No journey under way." without one);
      - a new `to` replaces it;
      - the leg is planned from the party's place, in the journey's mode when it carries one on.
      - When the map's `updated_at` differs from the journey's `planned_on`, the leg is planned again from the
        party's place.
      - The party's start is `world_maps.party_point`, so a plateau 6 position (`km=False`) works too.
      - Every position it writes has `km=True`, through `move_to`.
    - **The base pace,** in miles a day:
      - `foot`: 2 × the slowest PC's movement rate;
      - `horse`: 2 × the mount's `mv` (its `fly` when it flies, and the rules' `flies`), else 2 × `HORSE_MV`;
      - `cart`: `CART_MILES_PER_DAY`, or a vehicle's 2 × `mv`;
      - `river`: (`RIVER_BOAT_MPH`, or a boat possession's `mph`) ± `RIVER_CURRENT_MPH` (added downstream, taken
        off upstream), × `RIVER_HOURS`;
      - `ship`: (`SHIP_MPH`, or a ship possession's `mph`) × `SHIP_HOURS`. A ship possession with no `mph` goes at 2 ×
        its `mv` a day.
      - **`mph` is a new possession stats key** (a number, miles an hour on water). `possessions.mph(possession) ->
        float | None` reads it beside plateau 6's `movement` (`mv`, `fly`), which stays as it is. The data
        dictionary lists it (Task 22).
      - **A house rule's speed:** `miles_per_day` (0 for the table's) replaces the base pace for the leg, and the
        journey keeps it.
        - The terrain, route and weather rates still apply.
        - A campaign's house rule on speeds is an `always` rule, which the DM already has in its system prompt.
        - The tool descriptions tell the DM to pass `miles_per_day` when a house rule changes a speed.
      - `by` is plateau 6's `_rides`. A ship possession is needed for `ship` only when the DM names one; the mode
        alone hires passage.
      - Forced march × 1.5, on land.
    - **Each day,** as plateau 6:
      1. `pass_days(ctx, 1)`;
      2. the day's weather for its terrain: the cell's class under the day's start, with sea and lake as `ocean` and
         impassable as `mountain`; `road` on a route stretch; or `terrain` when given;
      3. km = miles a day × 1.609344 × the stretch's rate × the weather's pace, walking the stretches;
      4. the encounter check (`<beat>/travel day <n>`);
      5. `reveal_along` the day's line.
    - An encounter stops the leg there, and the journey keeps the rest.
    - Arrival clears the journey and sets `at`.
    - `MAX_DAYS` 60 stays: a leg estimated over it is refused, "travel in legs".
    - **The answer:** plateau 6's keys, with `km` and `km_left` beside `miles` and `miles_left`, and `mode`,
      `came_into_sight` (the labels of places newly visible) and `journey` (`{to, km_left}` or null). `via_roads`
      becomes true when a route stretch was used.
  - **`route_preview(ctx, to, *, mode="foot", by=(), miles_per_day=0, map="") -> dict`:** `{map, mode, units, km,
    miles, days, points, slowest: [{what, km, days}], to}`.
  - **`distance(ctx, a, b, map="", mode="") -> dict`:** with a mode, `{from, to, mode, km, miles, units}` by its route;
    without one, the straight line.
  - **`nearest(ctx, kind="city", n=3, map="")`** is kept; `kind` takes place kinds.
  - **DM tools:**
    - `travel(to="", mode="foot", terrain="", by=[], forced_march=False, miles_per_day=0)`, mutating, player-visible,
      `dm_only_keys` `CLOCKS`; `mode` is an enum of `MODES`;
    - `route(to, mode="foot", by=[], miles_per_day=0)`, not mutating, not player-visible;
    - `distance(a, b, map="", mode="")`.
    - The descriptions say: one leg per call; chain legs ("ride to the port, then sail"); a stopped leg goes on with
      `travel()`.
- [ ] **Step 1: Write the failing tests:**
  - plateau 6's cases, kept: unknown destination candidates, a blizzard day, an encounter stop partway, over 60 days;
  - Greyhawk to Hardby on foot by the road on the converted region map arrives in about 4 days (80 miles at 24 a
    day). Hardby's point lies inside the `wooly-bay` lake area, and the leg's end snaps to its shore (Task 3);
  - a party placed by plateau 6 (`km=False`) travels from the right place, and is stored with `km=True` after;
  - a river-boat leg downstream takes fewer days than the same leg upstream;
  - a ship crosses a lake that a foot leg walks around;
  - a stopped leg goes on with `travel()` and arrives;
  - the cells along the way become known and `came_into_sight` names the places;
  - a griffon flies over the ridge;
  - Review Focus 3's refusals, and a re-plan after a map edit;
  - `route` answers its slowest stretches;
  - a boat's `mph` 3 gives 40 miles a day downstream ((3 + 1) × 10), and a ship's `mph` 4 gives 48;
  - `miles_per_day=30` on foot covers 30 road miles a clear day, and a carried-on journey keeps it.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Travel by the mode the DM picks, leg by leg, with the journey kept and the land revealed on the way"`

---

### Task 11: The world-map routes

**Files:**
- Create: `src/delve/web/routes/module_world_maps.py`
- Modify: `src/delve/web/routes/world.py` (the world-map routes, `world_changed` and `_at_label`; the factions,
  clocks, quests and possessions are unchanged), `src/delve/web/app.py` (the router), `tests/web/test_world_api.py`,
  `tests/web/test_world_fourth_wall.py`, `tests/web/test_module_world_maps_api.py` (new)
- **The removals** (Task 9 kept them for this task):
  - `src/delve/play/world_maps.py`: plateau 6's `view`, `_VIEWS`, `save`, `locate`, `edit`, `seat_svg`, `dm_svg`,
    `hidden` and `_party_point` go. `describe` moves to the geo model: a feature's `dm_notes` replaces its `doc`.
    `reveal` stops writing `revealed`.
  - `src/delve/dm/tools/world.py`, `src/delve/dm/tools/host.py`: the `edit_world_map` tool goes.
  - `tests/dm/tools/test_fourth_wall.py`: `edit_world_map` leaves `DM_ONLY_TOOLS`.
  - `tests/dm/tools/test_tools.py`: `create_world_map`, `update_world_map` and `remove_world_map_feature` →
    `IN_THE_APP` (the organiser edits the map).
  - `tests/play/test_travel.py`: its `world_map` and `edit_world_map` cases (lines 360–374); its SVG cases (lines
    133–147), which become `seat_view` cases.
  - `tests/e2e/test_a_journey.py`: its SVG assertions (lines 200–209) become the seat view's JSON, with `Greyhawk`
    and `Hardby` among its features and no `SECRET` in it.
  - `tests/web/test_world_fourth_wall.py:111`: the `world_map` row expects `dm_notes`.
  - Before committing, `grep -rnE "edit_world_map|seat_svg|dm_svg|world_maps\.(view|save|locate|hidden)\(" src
    tests web/src` finds nothing.

**Interfaces:**
- Consumes: Tasks 4, 5, 9 (`world_maps.seat_view`, which reads the journey from `CampaignState.journey`) and 10 (the
  last plateau 6 caller of `view` and `locate`, `travel`, moved in Task 10).
- **The `world` event carries no map name.** `world_changed(request, campaign_id)` publishes `{"campaign_id"}`,
  table scope, for every change: a save, a delete, the knowledge or the setting pointer.
  - Each browser reads the list and the open map's view again through its own routes, which apply the fourth wall.
  - Nothing in this plateau needs the name, so no `organisers` event is added. If a later screen needs it, it gets an
    `organisers`-scoped event, never the table's.
  - `test_world_fourth_wall.py` checks a second seat's stream and its `since=0` replay after the organiser PUTs and
    DELETEs a map named `secret-xyzzy-…` with the title `SECRET-XYZZY`.
- Produces:

| Method | Path | Who | Answer |
|---|---|---|---|
| GET | `/api/campaigns/{id}/world-maps` | seat | `[{name, title}]` of `seat_maps` |
| GET | `…/world-maps/{name}/view` | seat | the seat view (Task 4); 404 for a map not in `seat_maps`; 409 `{"error": "map offline"}` when it can't be read |
| GET | `…/world-maps/{name}/tiles/{z}/{x}/{y}` | seat | the fogged tile, `image/jpeg`, `nosniff`, `Cache-Control: private, max-age=3600`; 404 `{"error": "unknown"}` when nothing is known there |
| GET | `…/world-maps/{name}/dm-view` | organiser | the DM view |
| GET | `…/world-maps/{name}` | organiser | `{name, title, source, status, geo, picture, knowledge, reading}` |
| PUT | `…/world-maps/{name}` | organiser | `{title, geo}`; 422 `{error, problems}` for a document that doesn't hold together |
| DELETE | `…/world-maps/{name}` | organiser | 204 |
| PUT | `…/world-maps/{name}/knowledge` | organiser | `{how, regions?, ring?}` → the knowledge |
| POST | `…/world-maps/geojson` | organiser | `{name, title, document, mapping?, width_km?, known?}` → 201 the map, or 422 `{error: "The map needs its size.", needs: "scale", properties, kinds}` |
| GET | `…/world-maps/{name}/export.geojson` | organiser | the Delve document with terrain cells, as an attachment |
| GET | `…/world-maps/{name}/picture` | organiser | the original picture (`pictures.original`), its own mime, `nosniff`, `Content-Disposition: attachment; filename="<name>.<ext>"`; 404 `{"error": "no picture"}` for a map without one. With the export, it is design §3.2's "a GeoJSON file, plus its picture". |
| GET, PUT, DELETE, POST | `/api/modules/{module_id}/world-maps…` | organiser | the same shapes, on the module's source: list (workspaces only), one (a `.map` one converted on read), put, delete, geojson, export, picture |
| GET | `/api/settings/world-maps` | organiser | `{setting: {module_id, name}}` |
| PUT, DELETE | `/api/settings/world-maps/{setting}` | organiser | `{module_id, name}`; 422 for an unknown setting, a map that isn't there or one in review |

  - The `view` answer's `tiles_version` is a digest of the known cells and the picture. The browser puts it in the
    tile URLs, so new knowledge loads new tiles.
- [ ] **Step 1: Write the failing tests:**
  - Review Focus 1, in `test_world_fourth_wall.py`, through two seats and the event stream with `since=0`: the
    planted `SECRET-XYZZY` cases, and a planted magenta in an unknown area of the picture never in a seat's tile
    bytes;
  - the seat routes 404 for an unknown map;
  - each organiser route refuses a seat (403), the picture download included;
  - the picture download answers the original's bytes and mime;
  - a `world` event holds no `map` key, live or replayed;
  - a GeoJSON import without a size answers `needs: "scale"`;
  - a module's `.map` world map reads converted;
  - the setting pointer refuses a map in review.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "World-map routes: the seat's view and fogged tiles, the organisers' maps, GeoJSON import and export"`

---

### Task 12: The reading job and the review

**Files:**
- Create: `src/delve/conversions/worldmap.py`, `src/delve/web/routes/world_import.py`,
  `tests/conversions/test_worldmap_job.py`, `tests/web/test_world_import_api.py`
- Modify: `src/delve/web/routes/conversions.py` (`ConversionServices` gets the picture OCR: `tesseract_words()`,
  none with `DELVE_OCR=off`), `src/delve/web/app.py` (the router; leftover `uploads/worldmap-*` removed at start)

**Interfaces:**
- Consumes: Task 5 (`pictures.store_blob`, `open_picture`), Task 6 (`start_job`, `finish`, `look_for`), Task 8
  (`read_picture`, `apply_review`, `unmapped`), Task 9 (`world_maps.accept`), Task 11 (merged first: its map JSON
  and its `world_changed`).
- Produces:
  - **`start_worldmap(services, path: Path, mime: str, key: ScaleKey, target: dict) -> Conversion`:**
    - the kind is `worldmap`; `target` is `{"module_id" | "campaign_id", "name", "title"}`;
    - its steps: `tiles` (the original into the blob store with `put_file`, then `store_blob`), then
      `read_picture`'s;
    - at the end, in one transaction, it puts the map with `status` `review`, `geo`, `picture` and `reading`: into the
      module's source (`put_world_map`, `save_source`) or the campaign's `world_maps` (through `storage`, since
      conversions don't import play);
    - a cancelled or failed job leaves no map, and its upload is removed.
  - **Routes:**

| Method | Path | Who | Answer |
|---|---|---|---|
| POST | `/api/conversions/worldmap?module_id=…\|campaign_id=…&name=&title=&cell=hex\|square\|none&distance=&units=km\|miles&points=x1,y1,x2,y2` | organiser | 202 the conversion. The body is the raw picture: `image/png`, `image/jpeg` or `image/webp` (else 415), at most 64 MB (413), streamed to `<data dir>/uploads/worldmap-*`. Bytes that aren't the type are 400, and a picture over `MAX_PICTURE_PIXELS` is 422, before any tile is cut. A key, name, title or target that doesn't check is 422 before the body is read. 409 while a conversion runs. |
| POST | `/api/campaigns/{id}/world-maps/{name}/review`, `/api/modules/{id}/world-maps/{name}/review` | organiser | `{clusters?: {id: class \| "outside"}, decisions?: {doubt_id: choice}, kinds?: {doubt_kind: choice}}` → the map, after `apply_review` |
| POST | `…/world-maps/{name}/accept` (both owners) | organiser | the map, `ready`; 422 "Give every colour a terrain first." while `unmapped` isn't empty, and nothing changes |

  - This is the fourth raw-body exception to the JSON rule, after the `.dscn`, the attachments and the PDF (GUILD.md
    gets it in Task 22).
- [ ] **Step 1: Write the failing tests:**
  - a job on `hex_map` with `FakeDM(vision_handler=…)` and `fake_ocr` ends with a module map in review, its doubts
    listed and its tiles stored;
  - the same into a campaign;
  - cancel leaves no map;
  - Review Focus 5 (accept refused while a colour is unmapped; a map in review isn't in `seat_maps`; `cell=none`
    without `points` is 422 before the body);
  - Review Focus 2: 413 for a body over 64 MB (the cap patched down), 422 for a picture over `MAX_PICTURE_PIXELS`
    (patched down), 400 for bytes that aren't the type;
  - 415 for `image/gif`;
  - a review decision `drop` removes the place, and `kinds` decides a whole kind;
  - accept passes once the frame's colour is `outside`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Reading a world-map picture in the background, then reviewing and accepting it"`

---

### Task 13: Dungeon maps from a description and from the book's map

**Files:**
- Create: `src/delve/modules/books/prompts/{describe-map.md,book-map.md}`, `src/delve/conversions/dungeon_maps.py`,
  `src/delve/web/routes/map_drafts.py`, `web/src/module/GenerateMap.tsx`, `web/src/module/MapDrafts.tsx` (with
  tests), `tests/modules/books/test_describe_map.py`, `tests/conversions/test_dungeon_maps.py`,
  `tests/web/test_map_drafts_api.py`
- Create too: `web/src/module/mapDrafts.ts`, the drafts' client functions (`startMapDraft`, `startBookMap`,
  `listMapDrafts`, `keepMapDraft`, `discardMapDraft`). They live there, not in `web/src/api.ts`.
- Modify: `src/delve/modules/books/sketch.py`, `src/delve/web/app.py` (the router), `web/src/routes/ModuleDetail.tsx`
  (the Maps tab's "Generate a map" only), `web/src/module/SketchNotice.tsx` ("Draw it from the book's map"),
  `en.json`/`nl.json` (anchor `modules.conversionFailed`)
- The campaign page's "Generate a map" link is Task 19's, since Task 19 already edits `CampaignDetail.tsx`. It is a
  plain link to the module's Maps tab, and needs nothing of this task.

**Interfaces:**
- Consumes: Task 1 (`conversions.for_module`), Task 6.
- Produces:
  - **`sketch.py`:**
    - `DESCRIBED = "# Drawn from a description."` and `FROM_BOOK = "# Drawn from the book's map"` (+ `
      asset:map-page-<n>.`);
    - `async def describe_map(name, description, keyed: list[tuple[str, str]], complete) -> tuple[str | None,
      list[Warning]]`. A module's keyed text, when it has some, goes in the prompt, so the rooms link. The answer is
      parsed and asked for once more on an error, as `sketch_map` does. The warnings are `map-described` or
      `map-not-drawn`.
    - `async def sketch_from_page(name, page: bytes, media_type, keyed, look) -> tuple[str | None, list[Warning]]`.
      Rooms are `r<key>` where the book puts them, with the levels drawn apart, and the retry is once. The warnings
      are `map-from-book` or `map-not-drawn`.
  - **`conversions/dungeon_maps.py`:**
    - `start_dungeon_map(services, module_id, name, description) -> Conversion` (kind `dungeon-map`);
    - `start_book_map(services, module_id, map_name, page_asset) -> Conversion` (kind `book-map`; `map_name` is the
      sketch it may replace).
    - Both `finish` with `result = {module_id, name, source, warnings, kept: false, discarded: false}`. Nothing is saved
      in the module until it is kept.
  - **Routes:**

| Method | Path | Who | Answer |
|---|---|---|---|
| POST | `/api/modules/{id}/map-drafts` | organiser | `{description, name?}` → 202 the conversion |
| POST | `/api/modules/{id}/map-drafts/from-book` | organiser | `{map, page}` (`page` a `map-page-<n>` attachment) → 202; 422 for a page that isn't one |
| GET | `/api/modules/{id}/map-drafts` | organiser | `[{id, kind, name, source, warnings, created_at}]`: the done, not kept, not discarded ones, from `conversions.for_module` (uncapped, never the list of 20) |
| POST | `/api/modules/{id}/map-drafts/{conversion_id}/keep` | organiser | `{name?}` → 201 the module map. A description draft makes a new map (a name taken gets `-2`); a book draft replaces its sketch. |
| DELETE | `/api/modules/{id}/map-drafts/{conversion_id}` | organiser | 204, discarded |

  - **Web:**
    - `GenerateMap` is a dialog: a description, then progress, then the drafts side by side, each drawn by
      `POST /api/dsl/render`, with Keep and Discard. Several drafts can be compared.
    - `SketchNotice` offers "Draw it from the book's map" when the sketch names a `map-page-<n>`.
- [ ] **Step 1: Write the failing tests:**
  - `describe_map` retries once on a parse error and gives `map-not-drawn` after a second;
  - the keyed rooms appear as `r<key>`;
  - `sketch_from_page` sends the page through `look` (`FakeDM.vision_images` holds one PNG);
  - a kept description draft is a new map; a kept book draft replaces the sketch and drops its `SKETCHED` line;
  - a discarded draft isn't listed;
  - a draft is still listed after 20 later conversions;
  - the dialog shows two drafts side by side, and Keep calls the route.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Dungeon maps drawn by Claude from a description or from the book's own map, kept only when chosen"`

---

### Task 14: The seat's world map in the browser

**Files:**
- Create: `web/src/worldmap/{crs.ts,api.ts,useLeaflet.ts,WorldMapView.tsx,KnownPlaces.tsx,fog.ts}` with tests
  (`crs.test.ts`, `fog.test.ts`, `WorldMapView.test.tsx`, `KnownPlaces.test.tsx`)
- Modify: `web/src/play/WorldPanel.tsx`, `web/src/play/WorldPanel.test.tsx`, `web/src/styles.css`,
  `web/src/play/api.ts` (plateau 6's `listWorldMaps` and the SVG view URL go: `WorldPanel` was their only user),
  `en.json`/`nl.json` (anchor `worldMaps.source.campaign`)

**Interfaces:**
- Consumes: Task 1 (`leaflet`); Task 11's `view` shape (the tests stub it).
- Produces:
  - **`crs.ts`:**
    - `kmCrs(maxZoom: number, kmPerPx: number): L.CRS` extends `L.CRS.Simple` with `new L.Transformation(s, 0, s,
      0)`, `s = 2 ** -maxZoom / kmPerPx`, so lat is y in km, growing down;
    - `toLatLng([x, y]): L.LatLngTuple` = `[y, x]`, and `fromLatLng`;
    - a map without a picture uses `kmPerPx = max(width_km, height_km) / 1024` and `maxZoom` 2.
  - **`api.ts`:** the types `SeatView`, `DmView`, `GeoFeatureView`, `JourneyView`; `getSeatView(campaignId, name)`,
    `getDmView(campaignId, name)`, `seatTileUrl(campaignId, name, version)` (`…/tiles/{z}/{x}/{y}?v=<version>`), and
    `pictureTileUrl(pictureId)`.
  - **`fog.ts`:** `knownCells(runs): Set<number>`, `cellPolygon(grid, i): [number, number][]` (the server's
    geometry).
  - **`WorldMapView`:** `{view: SeatView | DmView, tileUrl: string | null, onSelect?: (id: string) => void,
    children?}`:
    - the tile layer, whose `errorTileUrl` is a fog `data:` PNG;
    - for a map with no picture, the known cells drawn in `TERRAIN_COLOURS` on a canvas renderer;
    - the features: places as labelled markers, routes, rivers, regions;
    - the party's marker;
    - the journey: done solid, ahead dashed;
    - a scale bar in the map's units.
    - `useLeaflet` makes and disposes the map; no react-leaflet.
  - **`KnownPlaces`:** the visible places as a list beside the map (and the map's accessible name), with "You are
    here".
  - **`WorldPanel`:** the plateau 6 `<img>` of the SVG goes. It keeps the map picker, the quests, factions and
    possessions; it refetches the view on `world`. On the phone the World screen is the map full screen with
    KnownPlaces in a sheet.
- [ ] **Step 1: Write the failing tests:**
  - `kmCrs` puts the picture's corner pixels at the frame's corners;
  - `knownCells` decodes runs;
  - `WorldMapView` mounts in jsdom with a stubbed view and shows the party marker and the places' labels;
  - `KnownPlaces` lists only what the view holds;
  - the panel's picker switches maps;
  - the phone layout (`usePhone`) fills the screen.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests, `npm run build` (the CSP: no external URL in the bundle) and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The seat's world map in Leaflet: the picture under its fog, known places, the party and its journey"`

---

### Task 15: The world-map editor

**Files:**
- Create: `web/src/worldmap/{editorApi.ts,history.ts,brush.ts,FeatureForm.tsx,WorldMapEditor.tsx}` with tests, and
  `web/src/worldmap/WorldMapEditor.module.css`
- Create too: `web/src/worldmap/WorldMapRoutes.tsx`, the lazy module's own `<Routes>`: `""` is the editor, and Task
  16 adds `review` in this file, so only this task touches `App.tsx` for world maps.
- Modify: `web/src/App.tsx` (one lazy route), `en.json`/`nl.json` (anchor `editor.preview.textTitle`)

**Interfaces:**
- Consumes: Task 1 (`@geoman-io/leaflet-geoman-free`), Task 14 (`useLeaflet`, `crs`, `fog`); Task 11's map JSON
  (stubbed).
- Produces:
  - **The route** `/world-maps/:owner/:ownerId/:name/*` (`owner` is `module` or `campaign`), lazy-loaded like the map
    editor, so Leaflet stays out of the main bundle. It renders `WorldMapRoutes`.
  - **`editorApi.ts`:** `WorldMapOwner = {kind: "module"; moduleId: string} | {kind: "campaign"; campaignId: string}`;
    `WorldMapDoc`; `getWorldMap(owner, name)`, `putWorldMap(owner, name, {title, geo})`,
    `deleteWorldMap(owner, name)`, `exportUrl(owner, name)`, `pictureUrl(owner, name)` (Task 11's original
    picture).
  - **`history.ts`:** `History<T>`: `push(state)`, `undo()`, `redo()`, `canUndo`, `canRedo`, at most 100 states; pure.
  - **`brush.ts`:** `cellsUnder(grid, centre, radiusKm): number[]`, `paint(terrain: string, cells, letter): string`;
    pure.
  - **`FeatureForm`:** name, kind (by layer: `PLACE_KINDS`, `ROUTE_KINDS`, `WATER_KINDS`), description ("Players
    read it once they know the place"), DM notes ("DM only"), hidden; for a river, navigable km, barrier and
    **Reverse the flow** (it reverses the line, since downstream is the line's direction).
  - **`WorldMapEditor`:**
    - Geoman's marker, polyline, polygon, edit, drag and remove controls: a marker is a place, a line a route or a
      river (asked), a polygon a region, a lake or a sea;
    - the terrain brush with a class picker and a radius;
    - undo and redo (also Ctrl+Z / Ctrl+Shift+Z);
    - Save (PUT), then the server's answer replaces the document held, so the water cells it derived from a reshaped
      lake or sea (`water_from_areas`) show at once;
    - Export, and Download the picture when the map has one;
    - plateau 4's unsaved-changes guard (`useBlocker` and `useConfirm`, as `MapEditor.tsx`);
    - the base picture through `pictureTileUrl`.
- [ ] **Step 1: Write the failing tests:**
  - `History` undoes and redoes, and a push after an undo drops the redo;
  - `paint` changes only the brushed cells;
  - `FeatureForm` offers the kinds of its layer and edits a place's hidden flag; Reverse the flow reverses a river's
    coordinates;
  - after Save, the editor holds the server's document (a stubbed answer with other terrain shows it);
  - the editor blocks navigation with unsaved changes and saves the document it holds (stubbed fetch).
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests, `npm run build` and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "The world-map editor: places, roads, rivers, coasts and regions, a terrain brush, undo and redo"`

---

### Task 16: Import, review and the start of what the party knows

**Files:**
- Create: `web/src/worldmap/{importApi.ts,ImportWorldMap.tsx,ReviewPanel.tsx,ReviewPage.tsx,StartKnowledge.tsx}` with
  tests, `web/src/module/WorldMapsPanel.tsx` with a test
- Modify: `web/src/campaign/WorldMaps.tsx` (and its test), `web/src/routes/ModuleDetail.tsx` (mount the panel only),
  `web/src/worldmap/WorldMapRoutes.tsx` (the `review` route; not `App.tsx`), `en.json`/`nl.json` (anchor
  `world.deleteConfirm`)
- `campaign/WorldMaps.tsx` stops calling plateau 6's world-map functions in `web/src/api.ts`. Task 21 deletes them,
  because `web/src/api.ts` is Task 18's in this wave.

**Interfaces:**
- Consumes: Tasks 14 and 15; Task 11's and Task 12's routes (stubbed).
- Produces:
  - **`importApi.ts`:** `importGeojson(owner, {name, title, document, mapping?, width_km?, known?})`,
    `readPicture(owner, file, {name, title, cell, distance, units, points?})` (the raw-body POST), `review(owner,
    name, {clusters?, decisions?, kinds?})`, `accept(owner, name)`, `setKnowledge(campaignId, name, {how, regions?,
    ring?})`, `settingMaps()`, `setSettingMap(setting, {module_id, name})`, `clearSettingMap(setting)`.
  - **`ImportWorldMap`:** a dialog with two ways.
    - A GeoJSON file: when the answer is `needs: "scale"`, a mapping step shows the properties and kinds found, with
      the width in km or a known distance between two named places.
    - A picture with its key: the grid (hex, square or none), "1 cell = [n] [km | miles]", or with none, two points
      marked on the picture and their distance.
    - It starts the job and shows `ConversionProgress`.
  - **`ReviewPage`** (`/world-maps/:owner/:ownerId/:name/review`): `WorldMapView` with the reading on top, and
    `ReviewPanel` beside it.
    - The doubts come first, in the server's order, with one decision per item: its alternatives (place, river
      name, region name; sea or lake; keep or reverse the flow), Keep or Drop.
    - Each kind's heading has **Decide all of this kind**, with the choices its doubts share. It sends `kinds`, so the
      frame's hundreds of labels, if any are left, take one click.
    - Selecting a doubt flies the map to it.
    - The colours come with a terrain picker, showing Claude's suggestion. Its last choice is **Outside the map**
      (the frame, the legend), which counts as mapped.
    - Accept is disabled, with the reason, while a colour has no terrain.
  - **`StartKnowledge`** (campaign maps): Everything, Nothing, a regions picker, or an area drawn with Geoman.
  - **`campaign/WorldMaps.tsx`:** the list with status ("In review"), Import, Edit (the editor route), Review, Start
    knowledge, Download the picture and Delete. The DSL text area goes.
  - **`module/WorldMapsPanel.tsx`:** the same for a module's world maps, with Export, and "Use as <setting>'s map on
    this install" / "Stop using it".
- [ ] **Step 1: Write the failing tests:**
  - the GeoJSON import shows the mapping step on `needs: "scale"` and sends the width;
  - the picture import refuses "none" without two points;
  - the review lists doubts before the colours and sends one decision;
  - Accept stays disabled while a colour is unmapped, and is enabled once the last one is Outside the map;
  - Decide all of this kind sends `kinds` with the chosen alternative;
  - StartKnowledge sends the picked regions;
  - the module panel's setting toggle calls its route.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Importing world maps from GeoJSON or a picture, the review, and what the party knows at the start"`

---

### Task 17: Acts: pending acts shown to the table, and private acts

**Files:**
- Create: `web/src/play/PendingActs.tsx` with a test
- Modify: `src/delve/play/beats.py` (`submit`, `_closed`), `src/delve/play/table.py` (`dm_message`),
  `src/delve/web/routes/play.py` (`ActIn`, the pending route), `src/delve/dm/prompt/dm.md` (one line under the beat's
  procedure: answer a private act with `tell`, and never in the reply's text), `web/src/play/Composer.tsx`,
  `web/src/play/api.ts`, `web/src/routes/Play.tsx` (mount PendingActs), `tests/play/test_beats.py`,
  `tests/web/test_beats_api.py`, `tests/web/test_fourth_wall_per_seat.py`, `en.json`/`nl.json` (anchor
  `play.paidImagesHint`)

**Interfaces:**
- Produces:
  - **`submit(…, private: bool = False)`;** the submission gains `private`. `ActIn` gains `private: bool = False`.
    A pass can't be private (422).
  - **`pending(storage, campaign_id, seat: Seat) -> list[dict]`:** `[{seat_id, name, kind, text, characters, at}]`,
    the open beat's other submissions that aren't private, and the seat's own. `text` is the `original` for a seat of
    the act's language, else the English.
    - **An observer gets `[]`:** it sees no pending act, not even a public one, since an observer sees only what the
      whole table sees once it is in the story. The fourth wall wins.
  - **`GET /api/campaigns/{id}/beat/pending`** (`TableSeat`): `pending`. The browser refetches it on `beat`; no new
    event.
  - **`dm_message`** writes a private act as `<name>, privately (only the DM knows; tell them the outcome with tell,
    and keep it out of your reply): <text>`.
    - Both branches do: the many-submissions one, and the solo branch (`len(beat.submissions) == 1`, `table.py`
      around line 485), which today sends the act's text alone.
  - **At closing,** a private act's `player_act` entry gets the audience `{"seats": [its seat]}`.
  - **The Composer** gets an "Only the DM" toggle beside Act. `PendingActs` shows the others' acts so far, marked
    "draft", while the beat is open.
  - **A seat can change its own pending act** while the beat is open. Acting again already replaces its submission
    (`beats.submit`).
    - `PendingActs` lists the seat's own act first, with **Change**. Change puts its text and its private flag back
      in the Composer.
    - The Composer's Act then says **Replace my act**, and the toggle keeps the act's flag.
    - Nothing is sent until Act. A beat that closed meanwhile refuses the change as it refuses any late act.
- [ ] **Step 1: Write the failing tests:**
  - two seats: the first seat's act shows in the second's `pending`, its private act doesn't, and the first still
    sees its own;
  - the private act's story entry reaches only its seat;
  - `dm_message` marks it;
  - `test_fourth_wall_per_seat.py` plants `SECRET-XYZZY` in a private act and checks the other seat's routes, stream
    and replay;
  - one seat alone: a private act closes the beat at once, and `dm_message`'s solo branch carries the private marker;
  - an observer's `pending` is `[]`, with a public act and a private `SECRET-XYZZY` act open;
  - acting again replaces the seat's pending act, and the other seat's `pending` shows only the new text;
  - the toggle sends `private: true`, and Change refills the Composer with the act's text and flag.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Pending acts shown to the table, and private acts only the DM gets"`

---

### Task 18: Ask in the story, the shared answer translated, the tool count, and a lost event stream

**Files:**
- Modify: `web/src/play/Story.tsx`, `web/src/play/Composer.tsx` (an Ask mode), `web/src/play/TablePanel.tsx` (the Ask
  panel goes), delete `web/src/play/AskPanel.tsx` and its test, `web/src/play/TalkPanel.tsx`,
  `web/src/play/ThinkingIndicator.tsx`, `src/delve/play/translate.py`, `src/delve/play/talk.py`,
  `src/delve/play/table.py` (`beat_json`, `beat_changed`), `src/delve/web/routes/play.py` (`play/state`'s beat),
  `web/src/api.ts` (`sharedEvents` only), `web/src/App.tsx` (`Events()` only), the tests beside each,
  `tests/web/test_fourth_wall_per_seat.py`, `en.json`/`nl.json` (anchor `join.failed`)

**Interfaces:**
- Consumes: Task 1 (`translations.answer`), Task 17 (the Composer and the story after it).
- Produces:
  - **Ask in the story:**
    - `PRIVATE_KINDS` keeps only `talk`;
    - `ask` and `answer` entries show inline, marked "Only you", folded (`<details>`), the answer with Share
      (`POST …/ask/{answer_id}/share`);
    - the Composer has Act and Ask; Ask posts to the existing ask route. The side panel's Ask goes.
  - **The shared answer translated:** `translate_entry` translates a shared `talk`'s `answer` too, into
    `Translation.answer`, and the `translation` event carries it. `TalkPanel` shows it.
  - **The tool count:**
    - the table's `beat` event and `play/state` carry no `tool_count`;
    - a `beat_tools` event `{campaign_id, beat_id, tool_count}` goes with the audience `{"seats": [the host and
      co-hosts]}`;
    - `ThinkingIndicator` shows it to them only.
  - **A lost event stream:** `sharedEvents` watches `error` with `readyState === EventSource.CLOSED`. It then probes
    `GET /api/me`, and on 401 calls its new `onLost` listeners. `Events()` shows a notice: "Delve no longer knows this
    browser. Open the table's link again." (`events.lost`), with Reload.
- [ ] **Step 1: Write the failing tests:**
  - an ask and its answer show folded in the asker's story and nobody else's;
  - Share makes the table talk;
  - a Dutch seat gets the shared answer in Dutch (`NL: …` from the fake);
  - a player seat's stream has no `tool_count` and no `beat_tools`, while the host's has both (the fourth-wall test
    gets a planted case);
  - a closed stream with a 401 probe shows the notice.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Ask the DM in the story, shared answers translated, the tool count for the host, and a notice for a lost stream"`

---

### Task 19: Campaign status, a richer campaigns list, and the modules list's actions

**Files:**
- Modify: `src/delve/web/routes/campaigns.py` (`list_campaigns`, `campaign_json`, a PATCH route),
  `src/delve/storage/interfaces.py` + `src/delve/storage/sqlite/campaigns_repo.py` (`activity`),
  `web/src/routes/Campaigns.tsx`, `web/src/routes/CampaignDetail.tsx` (the status picker, and the "Generate a map"
  link to the module's Maps tab, `/modules/<id>?tab=maps`, when the campaign's module has no map: moved here from
  Task 13), `web/src/routes/Modules.tsx`, `web/src/api.ts` (the `Campaign` type and `patchCampaign` only), tests beside
  each, `tests/web/test_campaigns_api.py`, `en.json`/`nl.json` (one block, anchor `campaigns.playing`)

**Interfaces:**
- Consumes: Task 1 (`campaigns.status`, `set_status`).
- Produces:
  - **`PATCH /api/campaigns/{id}`** `{status}` (`HostSeat`): one of `CAMPAIGN_STATUSES`, else 422. It publishes
    `campaigns` to organisers.
  - **`campaigns.activity(campaign_id) -> CampaignActivity(last_played: str | None, sessions: int, playtime_s: int)`:**
    one query over `sessions` and `beats`. An open session counts up to its last closed beat.
  - **`GET /api/campaigns`** items gain `status`, `module_title`, `players` (the names of seats that haven't left,
    observers excepted), `last_played`, `sessions` and `playtime_s`.
  - **The Campaigns page:**
    - each row has the module, players, last played ("3 days ago"), sessions and playtime;
    - the rows are grouped In progress, Paused and Complete, Complete folded.
  - **The Modules page:** each row gets Export .dscn and Delete (plateau 4's `useConfirm`; a 409 shows its message),
    and the list gets Import a .dscn (`importModule`, then its warnings).
- [ ] **Step 1: Write the failing tests:**
  - PATCH by a host seat works, by a player 403, and an unknown status 422;
  - `activity` over two sessions;
  - the list's new fields;
  - the grouping;
  - Delete asks first and shows a 409;
  - the campaign page shows "Generate a map" only when its module has no map;
  - Import posts the file.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "Campaign status and a richer campaigns list; delete, export and import on the modules list"`

---

### Task 20: THAC0 per attack, questions while making a module, and two key fixes

**Files:**
- Create: `src/delve/rules/adnd2e/thac0.py`, `tests/rules/adnd2e/test_thac0.py`, `web/src/module/MakingQuestions.tsx`
  with a test
- Modify:
  - **THAC0:** `src/delve/web/routes/characters.py` (the sheet JSON), `web/src/campaign/CharacterSheet.tsx`, and the
    fight: `src/delve/rules/adnd2e/combat.py` (`start`, where a PC's attacks are built at line 724 through
    `_normalize_attacks`) and its caller `src/delve/play/combat.py`, with `tests/rules/adnd2e/test_combat.py`;
  - **the questions:** `src/delve/modules/books/{convert.py,generate.py}` and their prompts,
    `src/delve/conversions/runner.py` (`_make_module` stores `questions`), `src/delve/web/routes/conversions.py`,
    `src/delve/web/routes/modules.py` (`GET /api/modules/{id}/questions`), `web/src/routes/ModuleDetail.tsx` (mount
    MakingQuestions only);
  - **the keys:** `src/delve/modules/books/convert.py` (`key_entities`), `src/delve/dm/tools/module.py` (`room`),
    `src/delve/modules/dscn/text.py` (`_KEY_RX`), `web/src/module/MarkdownRoundTrip.ts` (`KEY`),
    `web/src/module/fixtures/everything.md` (a "## 31." heading);
  - the tests beside each; `en.json`/`nl.json` (one block, anchor `sheet.disposition`).

**Interfaces:**
- Consumes: Task 1 (`conversions.questions`), Task 6 (the runner).
- Produces:
  - **`attack_thac0(sheet, attack, reference) -> Thac0(value: int, parts: list[tuple[str, int]])`:**
    - from `sheet.thac0`: the non-proficiency penalty when no `weapon_profs` entry names the attack's weapon (PHB:
      warrior +2, priest +3, rogue +3, wizard +5 to THAC0; a multi-class character takes the smallest);
    - −1 when the matching entry says it is specialised ("special" in it);
    - minus Strength's hit adjustment (`reference.ability("str", score)`, through `encumbrance.parse_strength`);
    - minus the weapon's magic bonus (`+N` in its name).
    - An attack's stored `thac0` stays the DM's override.
    - **The fight uses the same number.** `combat.start(…, reference: Reference | None = None)`: with a reference, a
      PC's attack without a stored `thac0` gets `attack_thac0(sheet, attack, reference).value` as its
      `AttackBlock.thac0`. `_thac0` then rolls against what the sheet shows. `play/combat.py` passes
      `ctx.reference`. Without a reference (old callers, tests), it is plateau 6's sheet THAC0.
    - The sheet JSON's attacks gain `thac0_worked: {value, parts}`, and the sheet shows `a.thac0 ?? a.thac0_worked.value`
      with the parts as its title.
  - **The questions:**
    - the convert and generate prompts ask for at most 5 questions, each with the assumption made, in a final fenced
      `questions` JSON block, which the parsing strips from the text;
    - `Converted.questions: list[Question(id, text, default)]`;
    - the job stores `{"questions": [{id, text, default, answer: null}], "remarks": []}`;
    - `GET /api/modules/{id}/questions` (organiser) answers `[{conversion_id, questions, remarks}]` for the module's
      jobs that hold questions, from `conversions.for_module` (uncapped). `MakingQuestions` reads it, never
      `GET /api/conversions`, which shows the last 20.
    - `PUT /api/conversions/{id}/questions` `{answers: {id: text}, remarks: [text]}` (organiser) writes them into the
      module's `gm` text `making-notes`, "Notes from making this module" (a question, then the answer or "Assumed:
      <default>"; then the remarks), which the DM reads with the module. The job is not run again.
    - `MakingQuestions` on the module page lists them with the defaults filled in, and a remark field.
  - **The keys:**
    - `room` answers `encounters`: every encounter whose record's `key` names the room, the `keys[]` one first.
      `encounter` stays as the first.
    - `_KEY_RX` and `KEY` become `^([^\s.:]{1,12})[.:](?:\s+(.*))?$`, so "## 31." is keyed with an empty title.
      The digit check beside each stays (`text.py:94`, `any(c.isdigit() …)`; `MarkdownRoundTrip.ts`' `headingKey`,
      `/\d/.test`), so "## Treasure:" and "## Epilogue." stay unkeyed.
      This is a deliberate change to the copied `dscn` package (GUILD.md says so in Task 22).
- [ ] **Step 1: Write the failing tests:**
  - a fighter with a long sword proficiency, 18/50 Strength and a long sword +1 gets THAC0 − 3 − 1 (and −1 more when
    specialised);
  - a wizard with an unknown weapon gets +5;
  - a stored `thac0` wins;
  - in a fight started with the reference, the fighter's to-hit roll needs what the sheet's `thac0_worked` shows;
  - questions parsed from a fake answer and stripped from the text;
  - answers written into `making-notes`;
  - a room with two encounters lists both;
  - "## 31." is keyed, "## Treasure:" isn't, and the round-trip test stays byte-exact;
  - the module's questions are found after 20 later conversions.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests and `make ci`.**
- [ ] **Step 5: Commit.** `git commit -m "THAC0 worked out per attack, questions and remarks after making a module, and two key fixes"`

---

### Task 21: End to end, and the browser check

**Files:**
- Create: `tests/e2e/test_read_a_world_map.py`, `web/e2e/worldmap.spec.ts`
- Modify: `tests/e2e/test_a_journey.py`, `tests/e2e/fake_play_server.py` (a synthetic picture map in review on the
  crypt module, the region map known around Greyhawk, `DELVE_OCR=off`, vision answers by prompt), `Makefile` only if
  `e2e-browser` needs the new spec named (it runs `web/e2e/*.spec.ts`)
- `web/e2e/world.spec.ts`, plateau 6's browser spec. Its lines 66–68 and 79 expect the SVG `<img>` named "Greyhawk
  region", which Task 14 removed, and it drives the DSL editor that Task 16 removed. It now expects the Leaflet map
  (its accessible name, the party's marker and the known places' list) and the new world-maps list, keeping its
  quest, faction, possession and `SECRET` checks.
- `web/src/api.ts`: plateau 6's world-map client functions and types (`CampaignWorldMap`, `listCampaignWorldMaps`,
  `getCampaignWorldMap`, `putCampaignWorldMap`, `deleteCampaignWorldMap`, `worldMapDmViewUrl`) go. Nothing calls
  them after Tasks 14 and 16 (`grep` first). `WorldMapSource`, the module source's type, stays.

**What it covers:**
- **`test_read_a_world_map.py`,** through `delve serve` with the fake `claude` (vision mode) and `DELVE_OCR=off`:
  1. upload `hex_map`'s PNG with "1 hex = 30 miles" to a module;
  2. the job ends with the map in review and its doubts;
  3. map the colours, decide the doubts, accept;
  4. make a campaign that copies it, set the start to a region, `place_party` at a town;
  5. travel on foot by the road to the river town (`hex_map`'s town on the river), then by river boat down the river
     to the port at its mouth;
  6. a second seat's view, tiles and stream never show a planted `SECRET-XYZZY` place in the unknown part.
- **`test_a_journey.py`:** Greyhawk to Hardby on foot, then a `river` leg, on the converted region map, with
  `came_into_sight` and the seat's known places growing.
- **`web/e2e/worldmap.spec.ts`** (it runs after `world.spec.ts`, by file order) writes:
  - `web/e2e/screenshots/worldmap-seat-1280x800.png`;
  - `worldmap-seat-phone-390x844.png`;
  - `worldmap-review-1280x800.png`;
  - `worldmap-editor-1280x800.png`;
  - `map-drafts-1280x800.png`.
  - plateau 6's `world-panel-1280x800.png` and `world-phone-390x844.png` are taken again from the new panel.
- [ ] **Step 1: Write the tests and the spec, and see them fail where parts are missing.**
- [ ] **Step 2: Make them pass: `make ci` and `make e2e-browser`.**
- [ ] **Step 3: Commit.** `git commit -m "Plateau 7 end to end: a world map read from a picture and travelled, and the browser's screenshots"`

---

### Task 22: The DM's guidance and the docs

**Files:**
- Modify: `src/delve/dm/prompt/dm.md`, `GUILD.md`, `README.md` (world maps), `docs/glossary.md`,
  `docs/data-dictionary.md`, `docs/progress.md`, `docs/backlog.md`, `docs/maps/world-maps.md`,
  `docs/superpowers/specs/2026-10-18-plateau-7-maps-design.md` (a closing "Decided in the plan" section listing this
  plan's decisions)

**What it covers:**
- **`dm.md`'s "Travel"** names the modes, one leg per call, `route` before a long leg, `travel()` to go on, and the
  places that came into sight to narrate.
  - New lines cover `add_place` for a place it invents (hidden when the party shouldn't know it), `reveal_place` /
    `reveal_area` for a map bought or a rumour, and `hide_place` / `reveal_area(…, forget=True)` to hide a place, a
    road or an area. `edit_world_map` is gone.
  - A house rule that changes a speed: pass its `miles_per_day` to `travel` and `route`.
- **`GUILD.md`** gets a "Maps (plateau 7)" section:
  - `delve.maps.geo` is pure;
  - the fourth wall of the seat's view and its tiles;
  - knowledge is per campaign;
  - routing's cache;
  - the picture reading is deterministic, and its tests use synthetic pictures (never `greyhawk.jpg`);
  - the vision call and its fake;
  - the fourth raw-body exception (`POST /api/conversions/worldmap`);
  - `DELVE_OCR=off`;
  - the `_KEY_RX` change in the copied `dscn`;
  - the e2e spec and screenshots.
- **The glossary:**
  - world map (rewritten: GeoJSON, a picture, terrain, known), terrain, region, route, mode, leg, review, known, fog,
    setting's map;
  - private act, pending act;
  - campaign status (In progress, Paused, Complete).
  - The "hex" row says: only of a picture's grid.
- **The data dictionary:**
  - `world_maps.status`, `world_maps.knowledge`, `world_pictures`, `setting_world_maps`;
  - the terrain classes and letters, the place, route and water kinds;
  - the modes and their speeds (Task 3's table), the terrain rates, `travel`'s `miles_per_day`, and the possession
    stats key `mph`;
  - `conversions.kind` and `step`'s new values, the doubt kinds and their alternatives (`river-name`,
    `region-name`), the cluster value `outside`;
  - `WorldPosition.km`, `Journey.planned_on`;
  - the warnings `map-described`, `map-from-book` and `worldmap-in-review`;
  - `campaigns.status`, the submission's `private`, the `beat_tools` event, `translations.answer`;
  - the `.dscn` `geojson` world-map type.
- **`docs/maps/world-maps.md`:** the new world maps first (the document, the grid, the layers, import, reading,
  review, routing, knowledge), and the `.map` language kept as "plateau 6's maps, and how they convert".
- **`docs/backlog.md`:** items 1–9 struck as done in plateau 7. Add the ones this plan defers:
  - ships' weather modifiers (DMG Table 78);
  - a seat's own map notes;
  - Azgaar's sea routes.
- **`docs/progress.md`:** the plateau 7 row, and "to check by hand":
  - importing `greyhawk.jpg` with 1 hex = 30 miles and reviewing it;
  - Greyhawk to Hardby on foot and by river boat down the Selintan, and Greyhawk to Dyvers by ship across the Nyr
    Dyv;
  - a seat's fog on a phone;
  - generating a dungeon map from a description and drawing one from a book's map page, with the real `claude`;
  - importing a real Azgaar export (the test fixture is synthetic), to check the biome ids;
  - the small items.
- [ ] **Step 1: Write them.**
- [ ] **Step 2: Run `make ci`** (the prompt tests read `dm.md`).
- [ ] **Step 3: Commit.** `git commit -m "Plateau 7's docs: the DM's travel guidance, GUILD.md, the glossary, the data dictionary and world maps"`

---

## Order and parallelism

Every task leaves `make ci` green once the tasks of the earlier waves are merged (Global Constraints). Within a wave,
no two tasks edit the same file, except `en.json` and `nl.json`, where each adds one block after its own anchor. So the
tasks of a wave can be built and merged in any order.

| Wave | Tasks | Waits for |
|---|---|---|
| 1 | **1**, **2**, **17** | nothing |
| 2 | **3**, **4**, **5**, **6**, **7**, **14** | 3: 2. 4, 5, 7: 1 and 2. 6, 14: 1 |
| 3 | **8**, **9**, **13**, **15**, **19** | 8: 6 and 7. 9: 1–5. 13: 1 and 6. 15: 14. 19: 1 |
| 4 | **10**, **16**, **18** | 10: 3 and 9. 16: 14 and 15. 18: 17 |
| 5 | **11**, **20** | 11: 4, 5, 9 and 10. 20: 1 and 6 (and 13 and 16, for `ModuleDetail.tsx`) |
| 6 | **12** | 5, 6, 8, 9 and 11 |
| 7 | **21**, **22** | everything. Task 22 can be drafted from this plan during wave 6 |

- **Why these waves:**
  - Task 2 is pure `delve.maps.geo` and needs only shapely. Task 17 needs no new column, since `private` lives in
    the submission's JSON.
  - Task 19 waits for wave 3 so that `web/src/api.ts` isn't edited by it and Task 6 in one wave.
  - Task 18 waits for wave 4: `web/src/api.ts` is Task 6's in wave 2 and Task 19's in wave 3, and `App.tsx` is
    Task 15's in wave 3.
  - Task 20 waits for wave 5 because `ModuleDetail.tsx` is Task 13's in wave 3 and Task 16's in wave 4, and because
    `runner.py` and `routes/conversions.py` are Task 6's.
  - Task 11 comes after Task 10, because it removes plateau 6's world-map functions and `travel` is their last
    caller outside the routes.
  - Task 12 comes after Task 11: it uses Task 11's map JSON and `world_changed`, and both add a router to `app.py`.
- **Shared files, and who touches them, in wave order:**
  - `pyproject.toml`, `uv.lock`, `web/package.json`, `web/package-lock.json`, the migration, `.gitignore` and
    `tests/conftest.py`: Task 1 only.
  - `src/delve/maps/geo/__init__.py`: Task 2 only.
  - `web/src/api.ts`: Task 6 (wave 2: the conversion unions), Task 19 (wave 3: `Campaign`), Task 18 (wave 4:
    `sharedEvents`), Task 21 (wave 7: plateau 6's world-map functions go). The world-map tasks use
    `web/src/worldmap/*api.ts`, and Task 13 uses `web/src/module/mapDrafts.ts`.
  - `web/src/play/api.ts`: Task 17 (wave 1), Task 14 (wave 2).
  - `src/delve/web/app.py`: Task 5 (2), Task 13 (3), Task 11 (5), Task 12 (6), one router line each.
  - `src/delve/web/routes/modules.py`: Task 5 (2: the import cuts the pictures), Task 20 (5: the questions route).
  - `tests/modules/test_worldmaps.py`: Task 5 only.
  - `web/src/App.tsx`: Task 15 (3: the one lazy world-map route), Task 18 (4: `Events()`). Task 16 adds its review
    route in `web/src/worldmap/WorldMapRoutes.tsx`, after Task 15.
  - `web/src/routes/ModuleDetail.tsx`: Task 13 (3), Task 16 (4), Task 20 (5), one mount point each.
  - `web/src/routes/CampaignDetail.tsx`: Task 19 only (the status picker and the "Generate a map" link).
  - `src/delve/play/table.py`, `web/src/play/Composer.tsx` and `web/src/play/Story.tsx`: Task 17 (1), then Task 18
    (4).
  - `src/delve/conversions/runner.py`: Task 6 (2), then Task 20 (5). Tasks 12 and 13 use its public functions from
    their own modules.
  - `src/delve/web/routes/conversions.py`: Task 6 (2), Task 20 (5: the questions), Task 12 (6: the OCR).
  - `src/delve/play/world_maps.py`: Task 9 (3: adds), Task 10 (4: `move_to`), Task 11 (5: removes).
  - `src/delve/dm/tools/world.py`, `dm/tools/host.py`, `tests/dm/tools/test_fourth_wall.py` and
    `tests/dm/tools/test_tools.py`: Task 9 (3), Task 10 (4), Task 11 (5), their own lines.
  - `tests/play/test_travel.py`: Task 9 (3: the no-map hint test only), Task 10 (4: the travel cases), Task 11 (5:
    the SVG and `world_map` cases).
  - `tests/e2e/test_a_journey.py`: Task 2 (1: only if the new scale moves an assertion), Task 10 (4: travel), Task 11
    (5: the SVG), Task 21 (7).
  - `tests/web/test_world_fourth_wall.py`: Task 11 only.
  - `tests/web/test_fourth_wall_per_seat.py`: Task 17 (1), then Task 18 (4), their own planted cases.
  - `src/delve/dm/prompt/dm.md`: Task 17 (1: one line), Task 9 (3: the world-map lines), Task 22 (7).
  - `web/src/components/Nav.tsx`, `web/src/module/conversions.ts`, `web/src/routes/NewModule.tsx`: Task 6 only.
  - `tests/e2e/fake_play_server.py`: Task 6 (2: vision passes through), then Task 21 (7).
  - `en.json` and `nl.json`: every web task, one block after its anchor (Global Constraints).

## Done when

- `make ci` passed after every task's merge, and passes on a fresh clone at the end. `make e2e-browser` passes and
  writes the world map for a seat on the desktop and the phone, the review, the editor and the map drafts.
- A world map read from a synthetic picture, reviewed and accepted, is travelled on foot along its road and by river
  boat down its river. A seat sees only what the party knows, with no planted secret in a tile, a feature, a journey
  line or an event.
- Plateau 6's campaigns keep their world maps, positions and revealed places after the conversion.
- A dungeon map is generated from a description and drawn from a book map page with the fakes, and is kept only on
  Keep.
- The small items work: pending and private acts, Ask in the story, campaign status and the richer list, the modules
  list's actions, THAC0 per attack, the questions, the key fixes, the hidden tool count and the lost-stream notice.
- No test runs `claude`, `tesseract`, Replicate or the network, and `greyhawk.jpg` is nowhere in the repository.

## Decisions taken in this plan

Taken by the rules the quest set: the design's owner and call decisions stand; the fourth wall wins; single-player play
stays as fast; plateau 6's names and shapes stay where the design doesn't replace them; the smallest change.

| # | Question | Answer | Why |
|---|---|---|---|
| 1 | Where does an imported world map live? | In a module's source or in a campaign, plateau 6's two homes. There is no install-wide library. | Smallest change; the design's §3.3 names those two. |
| 2 | How is "the setting's map on this install" kept? | A pointer table `setting_world_maps` (setting → a module and its world map). New campaigns of that setting copy it instead of the built-in maps. | The design's call; one small table, and nothing printed ships with Delve. |
| 3 | What is stored? | A Delve GeoJSON document (km from the top left; a `delve` member with the frame, grid, terrain letters and picture) in `world_maps.geo` and `WorldMapSource.geo`. | The design's "stored as GeoJSON", and an export that QGIS opens. |
| 4 | When are the `.map` maps converted? | On first read (a campaign's map) or on GET (a module's), never in the migration. The migration only adds columns. | The migration can't import `delve.maps`. This follows plateau 3's "from its bundle on first read". |
| 5 | What does a converted old campaign know? | Everything, plus what was revealed. A new campaign's copies know nothing. | Its seats already saw the whole map; the fourth wall wins for new ones. |
| 6 | Where does a `.map` feature's `description` go? | Into `dm_notes`. | Plateau 6 made it the DM's; in the new model `description` is the players'. |
| 7 | The grid when the source has none? | Squares, 200 along the longer side (`DEFAULT_CELLS`). | Within the speed goal (40,000 cells). |
| 8 | The routing method? | Dijkstra (or A*) with a heap over the terrain cells, joined to the route and river lines, in pure Python with numpy. No scipy. | The design's call; no new dependency; under a second on the Flanaess. |
| 9 | Do rivers block walking? | Only a river marked `barrier`, crossed at a route or a place tagged `ford` or `bridge`. Routes cross rivers and ridges (bridges, passes). | A cell is tens of km; most streams are forded. This keeps "crossed only at its pass". |
| 10 | Where can a ship go? | Sea cells, lakes of 3 cells or more, and rivers up to their `navigable_km` from the mouth. | "Sea and large lakes", and "as far as the DM marks it navigable". |
| 11 | The speeds? | On foot 2 × MV a day; horse 2 × the mount's MV (24 without one); cart 12 miles a day; river boat 2 mph (or the boat's `mph`) ± a 1 mph current for 10 hours; ship 3 mph (or the ship's `mph`) for 12 hours. `mph` is a new possession stats key. The terrain and route rates are plateau 6's. | PHB/DMG (Tables 76, 77, Vehicles); plateau 6's names and rates kept. |
| 12 | The weather's terrain on water and ridges? | Sea and lake are `ocean`, impassable is `mountain`. | The weather tables' 13 terrains stay as they are. |
| 13 | Whose knowledge? | The campaign's (the party's), shared by its seats, with cells stored as runs. | The design's §3.5. |
| 14 | What of a road or a journey line that runs into unknown land? | It is cut at the known edge, and an unknown destination's name is left out. | The fourth wall. |
| 15 | Which world maps does a seat see listed? | Only those the party knows something of, or is on. | The plateau 6 chronicle's note that every seat saw every map's name; the fourth wall. |
| 16 | Does `place_party` reveal anything? | Yes: the land within sight. | Otherwise a new campaign's map starts all fog under the party. |
| 17 | `edit_world_map`? | Removed, in Task 11, after its last caller has moved. The DM gets `add_place`, `hide_place` and `reveal_area`, and `reveal_place` takes any feature. | The design gives editing to the organiser and adding a place to Claude. |
| 18 | A tile with nothing known? | 404 `{"error": "unknown"}`, drawn in the browser as a fog `data:` tile. A partly known tile is fogged on the server, opaque. Tiles are JPEG at quality 85. | "A fully unknown tile is never sent"; JPEG keeps 3,000 tiles small. |
| 19 | How big a picture? | 200 million pixels at most. The analysis runs on a copy of at most 40 million. | The owner's 146-million-pixel map fits, and memory stays bounded. |
| 20 | How is the picture carried in a `.dscn`, and can the DM show it? | As an asset with audience `gm`, named in the document's `delve.picture.asset`, kept out of the attachments. `show_image` can't show it. | The worldmaps entry allows no extra property but `x-`; showing the whole picture would break the fog. |
| 21 | How is the scale given? | As separate fields (grid kind, number, unit, or two points), never parsed from free text. | No Dutch/English parsing; one decision per field. |
| 22 | The colour clustering? | Pillow's median cut on each cell's middle 70%, up to 16 colours. A cell under 60% one colour is a doubt. | Deterministic, no random, no new dependency. |
| 23 | The vision call? | `claude -p --input-format stream-json --output-format stream-json`, one user message with a base64 image, the side calls' model rule, pictures fitted to 1,568 px. | The survey's lead; the CLI takes images only that way. |
| 24 | Dungeon-map drafts? | Conversion jobs `dungeon-map` and `book-map` whose `result` holds the draft. Keep makes (or, from the book, replaces) the map; several can be compared. | The design's "saved only when kept", with no new table. |
| 25 | "Generate a map" for a campaign? | A link to its module's Maps tab, and the host's existing upgrade. | A campaign is pinned to a revision; maps belong to modules. |
| 26 | A map in review? | Not copied, travelled, listed to a seat or exported. Accept needs every colour mapped, to a terrain or to "outside the map". | "Nothing is used in play until the owner accepts the map." |
| 27 | Greyhawk's region map's scale? | `scale 0.44`, so Greyhawk to Hardby is about 80 miles. | The plateau 6 chronicle's mismatch with the text. |
| 28 | Pending acts in another language? | The act's own words for seats of its language, else the English. No translation pass. | Single-player speed, no side pass in a beat. |
| 29 | Private acts? | An "Only the DM" toggle. The entry's audience is the act's seat, `dm_message` marks it, and the DM answers through `tell`. A pass can't be private. | Backlog 4 as the design words it. |
| 30 | The tool count? | Out of the table's `beat` event and `play/state`; a `beat_tools` event for the host and co-hosts only. | The fourth wall, decided on the server. |
| 31 | Campaign status? | `in_progress` (default), `paused`, `complete`, stored as open text. The host may set it. | Owner: "set by the host", "ready for Pending". |
| 32 | Questions while making a module? | A review list after the job. Answers and remarks go into the `gm` text `making-notes`, which the DM reads; the job doesn't run again. | The design's "a review list with defaults, not a pause". |
| 33 | THAC0 per attack? | Worked out whenever an attack has no stored `thac0`; a stored one is the DM's override. The parts are shown. | Keeps the DM's word; fills the common case. |
| 34 | "## 31."? | The key pattern allows an empty title, in the copied `dscn/text.py` and the editor's `KEY`. GUILD.md records it. | The walkthrough finding; the round-trip test guards the editor. |
| 35 | A second encounter on a room? | `room` answers `encounters` (all), keeping `encounter`. `keys[]` is unchanged. | The format holds one `encounter` per key. |
| 36 | The shared answer's translation? | A nullable `translations.answer` beside `text`. | One slot per entry and language, as plateau 4 has it. |
| 37 | Detecting a 401 on the stream? | On a closed EventSource, probe `GET /api/me`; a 401 shows the notice. | EventSource exposes no status. |
| 38 | react-leaflet? | Not used; a small `useLeaflet` hook. | One fewer dependency. |
| 39 | OCR in tests? (review 10) | An autouse fixture sets `DELVE_OCR=off` for every test, and both OCR factories answer None under it. In-process tests are covered too, not only `delve serve`. Labels then come from the vision call. | Tests never run tesseract; `ConversionServices.ocr` defaulted to the real one in `TestClient` tests. |
| 40 | Must each task leave `make ci` green on its own? (review 1, owner) | Yes, once its prerequisites are merged. A task that removes or changes a name changes every caller in the same task, or keeps the old name beside the new one until a named later task removes it. Task 9 adds the new world-map functions under new names (`geo`, `save_geo`, `locate_geo`, `party_point`) and removes nothing. Task 10 moves `travel`, and Task 11 moves the routes and removes plateau 6's functions and `edit_world_map`. | The owner's ruling. Every removal was checked against its callers on this branch, not only Task 9's. |
| 41 | How does a plateau 6 position live beside the km ones until travel moves? | `WorldPosition.km` (False by default). Task 9's `party_point` converts a `km=False` point. `place_party` keeps writing `km=False` on a DSL map until Task 10, which writes `km=True` everywhere. | Plateau 6's `travel` keeps reading its own positions until Task 10 replaces it, so `make ci` stays green. |
| 42 | Does a table-scoped `world` event name the map? (review 2, owner) | No. It carries `{campaign_id}` only, and each browser reads again through its own routes. Nothing in plateau 7 needs the name, so no `organisers` event is added. A later need gets one in `organisers` scope. A planted-secret test covers the live stream and the `since=0` replay. | The owner's ruling; the fourth wall. |
| 43 | How does the organiser get a world map's picture back? (review 14, owner) | `GET …/world-maps/{name}/picture`, organiser only, the original bytes as an attachment, beside `export.geojson`. No zip. | The owner's ruling; design §3.2's "a GeoJSON file, plus its picture". |
| 44 | How does the DM hide an area or a road? (review 21, owner: the smaller) | `hide_place` takes any feature, so a road too. `reveal_area` gains `forget=False`, whose inverse is Task 4's `forget_area`. No new tool. | Smaller than a new tool: no new spec, fourth-wall row or ttrpg2 mapping. |
| 45 | How do house rules change the speeds? (review 21, owner: the smallest) | `travel` and `route` take `miles_per_day` (0 for the table's), which replaces the base pace for the leg, and the journey keeps it. A speed house rule is an `always` rule, already in the DM's system prompt, and the tool descriptions say to pass its pace. No new phase, no new table. | The smallest change: one argument. House rules are prose the DM reads, as plateau 2a has them. |
| 46 | How are tasks ordered so that parallel ones share no file? (review 22, owner) | Seven waves: 1, 2, 17 / 3, 4, 5, 6, 7, 14 / 8, 9, 13, 15, 19 / 10, 16, 18 / 11, 20 / 12 / 21, 22. Tasks 19, 18 and 20 move later. Task 13's campaign-page link goes to Task 19. Task 16's review route goes into Task 15's `WorldMapRoutes.tsx`, not `App.tsx`. Task 13's client functions get their own file. | The owner's ruling: different waves, or one owner for the shared edit, rather than a merge order. |
| 47 | Task 12 and Task 11? (review 22, owner) | Task 12 comes after Task 11 (wave 6). | The owner's ruling; Task 12 uses Task 11's map JSON and `world_changed`. |
| 48 | i18n keys from parallel tasks? (owner) | Each web task adds its keys as one block right after its named anchor, in both files. The anchors are distinct and not on neighbouring lines. Tasks 19 and 20 have one anchor each now. | The owner's rule for parallel builders. |
| 49 | Can a seat change its pending act, and do observers see pending acts? (review 26, owner) | A seat changes its own act (Change refills the Composer; acting again replaces it). An observer's `pending` is `[]`. | The owner's ruling; the fourth wall wins. |
| 50 | Azgaar's biomes? (review 28, owner) | Mapped by numeric id (0–12, Azgaar's defaults), with the name as a fallback. The test fixture is synthetic and says so; the owner checks a real export by hand. | The owner's ruling. No real export is in the repository. |
| 51 | Which water is sea on a picture with a frame? (review 4) | Water touching the detected grid's bounds, not the picture's edge. When none does, the largest body is sea, as a `water-kind-guessed` doubt. | The owner's map has a cream frame (checked: no blue on any of its four edges), so the edge rule would find no sea. |
| 52 | Which way does a river flow when both its ends reach water? (review 4) | Toward the sea, else toward the larger body, with a `river-flow-guessed` doubt. The editor and the review can reverse it. | The Selintan runs between the Nyr Dyv and Woolly Bay; "down the Selintan" must be right or visibly doubtful. |
| 53 | Frame colours, cell numbers and region or river labels in the review? (review 5) | Digit-only labels are dropped. A label along a river or across several cells is offered as a river or region name. "Decide all of this kind" exists. A colour may be "outside the map", which counts as mapped. | Otherwise accept can't pass honestly on the owner's map, and the review is hundreds of clicks. |
| 54 | A place whose point lies in water? (review 12) | A land mode's end in a cell it can't cross snaps to the nearest crossable cell or route vertex within a cell. The terrain isn't changed. | Hardby lies inside `wooly-bay`; ports belong on their water for ships. |
| 55 | Water cells after editing a coast? (review 11) | `water_from_areas` derives them on import and on every `save_geo`, against the stored map. Brushed water outside any area stays. | Routing reads cells; the editor draws areas. |
| 56 | The fight's THAC0? (review 3) | `combat.start` takes the reference and gives an attack without a stored `thac0` the worked one. | The sheet and the fight show the same number. |
| 57 | How are drafts and questions found? (review 8) | `conversions.for_module`, uncapped; `GET /api/modules/{id}/questions`. | `GET /api/conversions` lists the last 20 only. |
| 58 | "## Treasure:" under the new key pattern? (review 9) | Unchanged plan: the digit check beside the pattern (`text.py:94`, `headingKey`) already leaves it unkeyed. A test says so. | The review's claim was checked and is wrong; nothing to fix. |
| 59 | Keeping `greyhawk.jpg` out? (review 27) | `.gitignore` and `tests/test_repository.py`: no tracked picture named `greyhawk*` or over 2 MB. Pictures only, because the reference snapshots are 5 MB. | A rule a test enforces. |
| 60 | A world-map or draft job's end notice? (review 7) | Nav links a world-map job to its review and a draft job to the module's Maps tab. `NewModule` lists module jobs only. | These jobs have no `module_id` to link to. |
| 61 | `start_job`'s mode? (review 19) | It opens the row with `"ready"`. | `conversions.mode` is NOT NULL and `_open` checks it. |
