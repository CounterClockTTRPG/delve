# Delve plateau 7: maps, design

Plateau 7 makes Delve's maps good enough to play on, and takes along the small backlog items.
- **World maps** become real maps, in Leaflet over GIS data. They can be imported from GIS tools, or read from a
  picture with its scale.
- **The party travels them** by a mode the DM picks, along routes worked out from the map.
- **Players see only what their characters know.**
- **Two dungeon-map items from the backlog:** a map generated from what the player says, and a map sketched from the
  book's own map image.

The owner agreed the world-map part on 2026-10-18 (below, "owner"). Everything marked "call" is the designer's, open
to correction.

## 1. Why

- **Plateau 6's world maps are ttrpg2's text language, drawn as an SVG.** They are low quality to look at, hard to make,
  and poor at route-finding: roads between named cities, or a straight line.
- **The owner wants tools that already exist.** GIS tools (QGIS, Azgaar's Fantasy Map Generator) can make and edit the
  maps, and Leaflet can show them, zoom them and edit them in the browser.
- **The owner's test:** the large Darlene map of the Flanaess (`/tmp/greyhawk.jpg`, 13,706 × 10,678 px, a hex grid,
  flat terrain colours, town symbols with labels, blue rivers). If Delve reads it into a usable map, the engine works.

## 2. Goals, non-goals, anti-goals

**Goals**
- **Two ways in** (owner):
  - GIS files;
  - a picture plus its scale ("1 square = 10 km"), which Delve reads into data the owner then corrects.
- **Every world map is editable** (owner): places, roads, rivers, coasts, terrain, regions, and what each is called.
- **Routes and days by the mode the DM picks** (owner): on foot, horse, cart, river boat, ship. A mixed journey is a
  chain of legs.
- **Players see only what their characters know** (owner). The DM sets the start (everything, a part, or nothing), and
  travel reveals more.
- **A dungeon map from a description**, and **a dungeon map from the book's map image** (backlog 1 and 2).

**Non-goals**
- **Real-world projections and geography.** World maps are flat, in kilometres (call).
- **Automatic choice of transport.** The DM picks the mode (owner).
- **A full GIS editor in Delve.** Delve edits what play needs. Heavy work goes to QGIS and comes back as a file.

**Anti-goals**
- **A reading that looks finished but is wrong.** Every imported picture ends in a review where uncertain readings are
  marked, never silently kept.
- **A route Delve can't explain.** Each route shows its line on the map, and per leg its km, days and what slowed it.
- **A seat that sees an unknown place:** not in a feature list, a route, an event, or a tile of an area it doesn't know.

## 3. The world map

### 3.1 What it is (call)

- **A world map has:**
  - a **frame**: its width and height in km, and the units it is shown in (km or miles);
  - an optional **base picture**, cut into tiles at import;
  - **layers of features**, stored as GeoJSON with coordinates in km from the top left.
- **The layers:**
  - **places:** points, with kind city, town, village, castle, ruin, dungeon, port or other;
  - **routes:** lines, with kind road, track or trail;
  - **water:** river lines (with their flow direction), and lake and sea areas;
  - **terrain:** a grid of cells, each with a terrain class. The grid follows the picture's own hexes or squares when it
    has them, otherwise squares of the map's resolution;
  - **regions:** named areas, such as kingdoms, used for labels and lookups.
- **Each feature carries:** `id`, `name`, `kind`, `description` (players may read it once the feature is known),
  `dm_notes` (DM only), `tags`, and `hidden` (the place is a secret even from a party that knows the area).
- **Terrain classes** are the encounter tables' terrains: plains, forest, hills, mountain, swamp, desert, arctic,
  jungle, urban, plus water (sea, lake) and impassable. Their colours on the page are Delve's own.

### 3.2 Getting a map in (owner)

**GIS files**
- **GeoJSON**, which QGIS and most tools export:
  - point, line and polygon features;
  - their `kind` and `name` come from properties, through a mapping step when the names differ;
  - polygons with a terrain class become terrain cells.
- **Azgaar's Fantasy Map Generator:** its GeoJSON exports (cells, rivers, routes, markers, burgs) are recognised by
  their properties, and mapped without the owner's help.
- **Coordinates:** when they aren't already km, the importer asks for the map's width in km (or a known distance
  between two places) and scales them.

**A picture with its scale.** The owner uploads a picture and its key: "1 hex = 30 miles", or "1 square = 10 km". The
reading is a background job with progress, like a book conversion:
1. **The grid:** find the picture's hex or square grid and its size in pixels, which gives the km per pixel. With no
   grid, the scale comes from two points the owner marks with their distance.
2. **The terrain:** each cell takes its terrain from the colours inside it. The colours are clustered, and the owner
   maps each cluster to a terrain class once, with Claude's suggestion from the map's legend or look ("dark green with
   trees: forest").
3. **The water:**
   - large blue areas become sea and lakes;
   - thin blue lines become rivers, followed to their mouth to find which way they flow.
4. **Places:** town symbols are found, their labels read (OCR, then Claude on picture tiles), and each label is paired
   with its nearest symbol.
5. **Routes:** lines in a road colour, when the picture has them.
6. **The review:**
   - the owner sees the picture with the reading on top;
   - doubtful items are listed first: an unpaired label, a cell of mixed colour, a river that ends nowhere;
   - each item has the reading and the alternatives.
   - Nothing is used in play until the owner accepts the map.

**Exports and modules**
- A world map exports as a GeoJSON file, plus its picture.
- A `.dscn` module carries world maps as a new `worldmaps` type, `geojson`, with the picture as an asset.
- The ttrpg2 text maps that plateau 6 brought in are converted once into the new form, by the parser plateau 6 already
  has.
- **The setting's map on this install** (call):
  - an imported world map can be marked as its setting's map on this install, and new campaigns of that setting then
    copy it;
  - nothing printed ships with Delve: the imported Flanaess stays in the owner's data folder;
  - Greyhawk's built-in map stays plateau 6's region map, converted.

### 3.3 Editing (owner)

- **In the browser,** on the same Leaflet map:
  - add, move and delete places;
  - draw and reshape roads, rivers, coasts and regions;
  - paint terrain cells with a brush;
  - edit a feature's name, kind, description, notes and `hidden`.
- **Undo and redo**, and the same unsaved-changes guard as the dungeon map editor.
- **The organiser edits** a module's world maps and a campaign's own copies (as in plateau 6, a campaign copies its
  module's maps at creation, then owns them).

### 3.4 Routes and days (owner: the DM picks the mode)

- **Modes:** `foot`, `horse`, `cart`, `river` (a river boat), `ship`. A possession (plateau 6) can stand for the mode's
  speed, as when the party's own ship or a griffon gives its movement.
- **The route is the cheapest path for that mode over the map** (call: a weighted shortest path over the terrain cells,
  joined to the road and river lines):
  - **On land:** a road costs its surface, and off-road each terrain costs its 2e factor. Mountain and swamp are slow;
    impassable and water can't be crossed without a ford or a bridge.
  - **A river boat** keeps to rivers and lakes, faster downstream than up.
  - **A ship** keeps to sea and large lakes, and goes into a river only as far as the DM marks it navigable.
- **Speeds are the 2e rules** (PHB overland movement, the DMG's vessels), and house rules can change them (call).
  Plateau 6's weather and encounter checks apply day by day, as in its `travel`.
- **What the DM gets:**
  - `route(to, mode)` gives a preview: the line, km, days and the slowest stretches;
  - `travel(to, mode, by)` moves the party leg by leg.
    - **One leg per call** (call). As in plateau 6, the call runs day by day and stops at an encounter.
    - **A stopped leg is kept** as the party's journey: its route, the mode, and the distance left. `travel()` with no
      destination carries it on.
    - The DM chains legs ("ride to the port, then sail") as separate calls.
  - `distance(a, b, mode)` gives the number only.
- **What players see:** the route of a journey under way (a stopped leg not yet finished), and the party's place on
  it.

### 3.5 What players see (owner)

- **Knowledge:** a campaign keeps what the party knows of each world map: areas (where the picture shows and the
  terrain is known) and features (which places, roads and rivers are known).
- **The DM sets the start:** everything, nothing, or a part. A part is drawn on the map, or named (for example "the
  Kingdom of Nyrond and its roads").
- **Travel reveals** the cells along the route and those within sight of it. The sight is 10 km by default, and more
  from hills and mountains (call). Places within sight become known, except `hidden` ones.
- **Who sets it** (call):
  - **The organiser** sets the start knowledge on the campaign page, by drawing an area or picking regions.
  - **The DM** (Claude) reveals or hides a place, an area or a road during play, through tools, for a map bought in a
    city or a rumour heard.
  - **Claude can add a place** mid-play (`add_place(name, kind, at, description, notes, hidden)`, as a GeoJSON point)
    for a village it makes up.
  - **Editing the map itself** stays the organiser's, on the campaign page. The host has no drawing tools on the play
    screen.
- **A known area shows the picture as printed** (owner, 2026-10-18).
  - Knowing an area means seeing everything printed in it, as when holding that map. Places read from the picture
    within it become known with it.
  - `hidden` is for places that aren't printed: ones the DM adds, or a secret the DM marks on an imported map that the
    picture doesn't show.
  - Tiles are cut once per map. A seat's fog is a mask over the unknown areas, computed on the server, and a fully
    unknown tile is never sent.
- **The seat's view:**
  - the base picture under a fog where the party knows nothing;
  - known features only, with their name and description, never `dm_notes`;
  - unknown and `hidden` features are left out entirely, from the feature lists, the route previews and the events.
    Fully unknown tiles aren't served.
  - The fog is computed on the server.

### 3.6 Engine (call)

- **Leaflet** with `CRS.Simple` in km, bundled into the SPA (no CDN, per the CSP).
- **Leaflet-Geoman** for editing.
- **The base picture** is cut at import into a tile pyramid of 256 px tiles in the blob store, served by a seat-aware
  tile route. Fogged areas come from the server already covered.
- **Routing runs on the server,** in Python, on a grid built once per map and kept until the map changes. The goal is a
  route across the whole Flanaess in under a second.

## 4. Dungeon maps (backlog 1 and 2)

- **A map from what the player says** (backlog 1):
  - a "Generate a map" action on a module's Maps tab, and for a campaign whose module has no map;
  - the player describes the place, and Claude writes it in the map language;
  - the draft is parsed (and retried once, like plateau 5's `sketch_map`), shown, and saved only when the player keeps
    it. Several drafts can be kept side by side and compared (call).
- **A map sketched from the book's map image** (backlog 2):
  - from a `map-page-<n>` attachment (walkthrough fixes), Claude draws the map in the map language, with the rooms
    where the book puts them and the levels apart, and the room key's numbers as anchors;
  - it replaces a sketch from the room key only when the organiser keeps it.
- **Both use a vision side call:** a `conversion` job that takes an image beside the text. The world-map reading
  (§3.2, steps 2 and 4) uses it too.

## 5. Taken along: the small items (owner: "fairly small, take them along")

The designer's proposals stand where the owner hadn't decided (owner, 2026-10-18: open decisions are the designer's
call).
- **From the backlog:**
  - pending acts shown to the table (3);
  - private acts (4), as a toggle "Only the DM" on Act, resolved in the beat and told back through `tell`;
  - campaign status (5): In progress, Paused, Complete, stored as an open enum ready for Pending;
  - a richer campaigns list (6);
  - follow-up questions and remarks while making a module (7), as a review list of questions with defaults when the
    job ends, not a pause in the middle;
  - module delete, export and import on the Modules list (8);
  - THAC0 per attack (9).
- **Also:**
  - **Ask the DM in the story:** questions and answers appear inline as "Only you" entries, folded, with Share, and
    the side panel goes;
  - **A notice when the event stream gets a 401**, instead of silently not updating;
  - **the walkthrough review's open findings:**
    - a second encounter keyed to the same room is listed on that room;
    - the beat's tool-call count is hidden from players;
    - a shared Ask answer is translated for its readers;
    - a room heading without a name ("## 31.") is keyed.
- **Not taken along,** because each needs its own design:
  - intelligent items and module entities carried into play;
  - sending "ooc:" questions to Ask;
  - the react-router upgrade.

## 6. Testing

- **Synthetic pictures made in the tests** (Pillow): a small hex map with four terrain colours, a sea, a river with a
  mouth, three labelled towns and a road. The reading must find the grid, the terrain of every cell, the river's flow,
  the towns with their names, and the road.
  - Claude and OCR are faked: the fake OCR returns the drawn labels' boxes, and the fake vision call answers from a
    script.
- **GeoJSON fixtures:** a hand-made one, and an Azgaar export cut down to a few features.
- **Route tests:**
  - the road is faster than across the hills;
  - a ship goes around a peninsula, not across it;
  - a river boat is faster downstream;
  - an impassable ridge is crossed only at its pass.
- **The fourth wall:** a planted `SECRET-XYZZY` in a hidden place, in `dm_notes` and in an unknown area never reaches a
  seat (tiles, features, route preview, events).
- **The owner's check by hand:** import `/tmp/greyhawk.jpg` with "1 hex = 30 miles" (owner: the map's key), review it, and travel Greyhawk to Hardby on foot and by river boat down the Selintan, and
  Greyhawk to Dyvers by ship across the Nyr Dyv. (A copy of the picture is in `~/claude/refactoring-assets/`.) The full-size picture
  isn't part of `make ci`.

## 7. Left to the builder

- The grid-detection and colour-clustering methods, within: deterministic, and tested on the synthetic pictures.
- The routing grid's resolution, within the speed goal.
- The review screen's layout, within: doubtful items first, and one decision per item.
- Exact speeds and terrain factors, from the 2e books, listed in the data dictionary.

## 8. Decided in the plan

The plan (`docs/superpowers/plans/2026-10-18-plateau-7-maps.md`, "Decisions taken in this plan") settled these, by
the quest's rules: the owner's and the design's decisions stand, the fourth wall wins, single-player play stays as
fast, plateau 6's names stay where this design doesn't replace them, and the smallest change. Its table has the reason
for each. The build's own decisions are in the plateau's chronicle.

| # | Question | Answer |
|---|---|---|
| 1 | Where does an imported world map live? | In a module's source or in a campaign, plateau 6's two homes. There is no install-wide library. |
| 2 | How is "the setting's map on this install" kept? | A pointer table `setting_world_maps` (setting → a module and its world map). New campaigns of that setting copy it instead of the built-in maps. |
| 3 | What is stored? | A Delve GeoJSON document (km from the top left; a `delve` member with the frame, grid, terrain letters and picture) in `world_maps.geo` and `WorldMapSource.geo`. |
| 4 | When are the `.map` maps converted? | On first read (a campaign's map) or on GET (a module's), never in the migration. The migration only adds columns. |
| 5 | What does a converted old campaign know? | Everything, plus what was revealed. A new campaign's copies know nothing. |
| 6 | Where does a `.map` feature's `description` go? | Into `dm_notes`. |
| 7 | The grid when the source has none? | Squares, 200 along the longer side (`DEFAULT_CELLS`). |
| 8 | The routing method? | Dijkstra (or A*) with a heap over the terrain cells, joined to the route and river lines, in pure Python with numpy. No scipy. |
| 9 | Do rivers block walking? | Only a river marked `barrier`, crossed at a route or a place tagged `ford` or `bridge`. Routes cross rivers and ridges (bridges, passes). |
| 10 | Where can a ship go? | Sea cells, lakes of 3 cells or more, and rivers up to their `navigable_km` from the mouth. |
| 11 | The speeds? | On foot 2 × MV a day; horse 2 × the mount's MV (24 without one); cart 12 miles a day; river boat 2 mph (or the boat's `mph`) ± a 1 mph current for 10 hours; ship 3 mph (or the ship's `mph`) for 12 hours. `mph` is a new possession stats key. The terrain and route rates are plateau 6's. |
| 12 | The weather's terrain on water and ridges? | Sea and lake are `ocean`, impassable is `mountain`. |
| 13 | Whose knowledge? | The campaign's (the party's), shared by its seats, with cells stored as runs. |
| 14 | What of a road or a journey line that runs into unknown land? | It is cut at the known edge, and an unknown destination's name is left out. |
| 15 | Which world maps does a seat see listed? | Only those the party knows something of, or is on. |
| 16 | Does `place_party` reveal anything? | Yes: the land within sight. |
| 17 | `edit_world_map`? | Removed, in Task 11, after its last caller has moved. The DM gets `add_place`, `hide_place` and `reveal_area`, and `reveal_place` takes any feature. |
| 18 | A tile with nothing known? | 404 `{"error": "unknown"}`, drawn in the browser as a fog `data:` tile. A partly known tile is fogged on the server, opaque. Tiles are JPEG at quality 85. |
| 19 | How big a picture? | 200 million pixels at most. The analysis runs on a copy of at most 40 million. |
| 20 | How is the picture carried in a `.dscn`, and can the DM show it? | As an asset with audience `gm`, named in the document's `delve.picture.asset`, kept out of the attachments. `show_image` can't show it. |
| 21 | How is the scale given? | As separate fields (grid kind, number, unit, or two points), never parsed from free text. |
| 22 | The colour clustering? | Pillow's median cut on each cell's middle 70%, up to 16 colours. A cell under 60% one colour is a doubt. |
| 23 | The vision call? | `claude -p --input-format stream-json --output-format stream-json`, one user message with a base64 image, the side calls' model rule, pictures fitted to 1,568 px. |
| 24 | Dungeon-map drafts? | Conversion jobs `dungeon-map` and `book-map` whose `result` holds the draft. Keep makes (or, from the book, replaces) the map; several can be compared. |
| 25 | "Generate a map" for a campaign? | A link to its module's Maps tab, and the host's existing upgrade. |
| 26 | A map in review? | Not copied, travelled, listed to a seat or exported. Accept needs every colour mapped, to a terrain or to "outside the map". |
| 27 | Greyhawk's region map's scale? | `scale 0.44`, so Greyhawk to Hardby is about 80 miles. |
| 28 | Pending acts in another language? | The act's own words for seats of its language, else the English. No translation pass. |
| 29 | Private acts? | An "Only the DM" toggle. The entry's audience is the act's seat, `dm_message` marks it, and the DM answers through `tell`. A pass can't be private. |
| 30 | The tool count? | Out of the table's `beat` event and `play/state`; a `beat_tools` event for the host and co-hosts only. |
| 31 | Campaign status? | `in_progress` (default), `paused`, `complete`, stored as open text. The host may set it. |
| 32 | Questions while making a module? | A review list after the job. Answers and remarks go into the `gm` text `making-notes`, which the DM reads; the job doesn't run again. |
| 33 | THAC0 per attack? | Worked out whenever an attack has no stored `thac0`; a stored one is the DM's override. The parts are shown. |
| 34 | "## 31."? | The key pattern allows an empty title, in the copied `dscn/text.py` and the editor's `KEY`. GUILD.md records it. |
| 35 | A second encounter on a room? | `room` answers `encounters` (all), keeping `encounter`. `keys[]` is unchanged. |
| 36 | The shared answer's translation? | A nullable `translations.answer` beside `text`. |
| 37 | Detecting a 401 on the stream? | On a closed EventSource, probe `GET /api/me`; a 401 shows the notice. |
| 38 | react-leaflet? | Not used; a small `useLeaflet` hook. |
| 39 | OCR in tests? (review 10) | An autouse fixture sets `DELVE_OCR=off` for every test, and both OCR factories answer None under it. In-process tests are covered too, not only `delve serve`. Labels then come from the vision call. |
| 40 | Must each task leave `make ci` green on its own? (review 1, owner) | Yes, once its prerequisites are merged. A task that removes or changes a name changes every caller in the same task, or keeps the old name beside the new one until a named later task removes it. Task 9 adds the new world-map functions under new names (`geo`, `save_geo`, `locate_geo`, `party_point`) and removes nothing. Task 10 moves `travel`, and Task 11 moves the routes and removes plateau 6's functions and `edit_world_map`. |
| 41 | How does a plateau 6 position live beside the km ones until travel moves? | `WorldPosition.km` (False by default). Task 9's `party_point` converts a `km=False` point. `place_party` keeps writing `km=False` on a DSL map until Task 10, which writes `km=True` everywhere. |
| 42 | Does a table-scoped `world` event name the map? (review 2, owner) | No. It carries `{campaign_id}` only, and each browser reads again through its own routes. Nothing in plateau 7 needs the name, so no `organisers` event is added. A later need gets one in `organisers` scope. A planted-secret test covers the live stream and the `since=0` replay. |
| 43 | How does the organiser get a world map's picture back? (review 14, owner) | `GET …/world-maps/{name}/picture`, organiser only, the original bytes as an attachment, beside `export.geojson`. No zip. |
| 44 | How does the DM hide an area or a road? (review 21, owner: the smaller) | `hide_place` takes any feature, so a road too. `reveal_area` gains `forget=False`, whose inverse is Task 4's `forget_area`. No new tool. |
| 45 | How do house rules change the speeds? (review 21, owner: the smallest) | `travel` and `route` take `miles_per_day` (0 for the table's), which replaces the base pace for the leg, and the journey keeps it. A speed house rule is an `always` rule, already in the DM's system prompt, and the tool descriptions say to pass its pace. No new phase, no new table. |
| 46 | How are tasks ordered so that parallel ones share no file? (review 22, owner) | Seven waves: 1, 2, 17 / 3, 4, 5, 6, 7, 14 / 8, 9, 13, 15, 19 / 10, 16, 18 / 11, 20 / 12 / 21, 22. Tasks 19, 18 and 20 move later. Task 13's campaign-page link goes to Task 19. Task 16's review route goes into Task 15's `WorldMapRoutes.tsx`, not `App.tsx`. Task 13's client functions get their own file. |
| 47 | Task 12 and Task 11? (review 22, owner) | Task 12 comes after Task 11 (wave 6). |
| 48 | i18n keys from parallel tasks? (owner) | Each web task adds its keys as one block right after its named anchor, in both files. The anchors are distinct and not on neighbouring lines. Tasks 19 and 20 have one anchor each now. |
| 49 | Can a seat change its pending act, and do observers see pending acts? (review 26, owner) | A seat changes its own act (Change refills the Composer; acting again replaces it). An observer's `pending` is `[]`. |
| 50 | Azgaar's biomes? (review 28, owner) | Mapped by numeric id (0–12, Azgaar's defaults), with the name as a fallback. The test fixture is synthetic and says so; the owner checks a real export by hand. |
| 51 | Which water is sea on a picture with a frame? (review 4) | Water touching the detected grid's bounds, not the picture's edge. When none does, the largest body is sea, as a `water-kind-guessed` doubt. |
| 52 | Which way does a river flow when both its ends reach water? (review 4) | Toward the sea, else toward the larger body, with a `river-flow-guessed` doubt. The editor and the review can reverse it. |
| 53 | Frame colours, cell numbers and region or river labels in the review? (review 5) | Digit-only labels are dropped. A label along a river or across several cells is offered as a river or region name. "Decide all of this kind" exists. A colour may be "outside the map", which counts as mapped. |
| 54 | A place whose point lies in water? (review 12) | A land mode's end in a cell it can't cross snaps to the nearest crossable cell or route vertex within a cell. The terrain isn't changed. |
| 55 | Water cells after editing a coast? (review 11) | `water_from_areas` derives them on import and on every `save_geo`, against the stored map. Brushed water outside any area stays. |
| 56 | The fight's THAC0? (review 3) | `combat.start` takes the reference and gives an attack without a stored `thac0` the worked one. |
| 57 | How are drafts and questions found? (review 8) | `conversions.for_module`, uncapped; `GET /api/modules/{id}/questions`. |
| 58 | "## Treasure:" under the new key pattern? (review 9) | Unchanged plan: the digit check beside the pattern (`text.py:94`, `headingKey`) already leaves it unkeyed. A test says so. |
| 59 | Keeping `greyhawk.jpg` out? (review 27) | `.gitignore` and `tests/test_repository.py`: no tracked picture named `greyhawk*` or over 2 MB. Pictures only, because the reference snapshots are 5 MB. |
| 60 | A world-map or draft job's end notice? (review 7) | Nav links a world-map job to its review and a draft job to the module's Maps tab. `NewModule` lists module jobs only. |
| 61 | `start_job`'s mode? (review 19) | It opens the row with `"ready"`. |
