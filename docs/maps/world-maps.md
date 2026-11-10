# World maps

A world map describes the land around the dungeons: its terrain, its towns and places, its roads, its rivers, lakes
and seas, and its regions. It is for the journey between dungeons; it doesn't draw rooms to play in (those are the
dungeon maps, `.dmap`, [the dungml DSL](dsl.md)).

Since plateau 7 a world map is a **geo map** (`delve.maps.geo`): GeoJSON in km, over a grid of terrain cells, with an
optional picture under it. It is imported from a GeoJSON file or read from a picture of a map, reviewed, then edited,
travelled and fogged per campaign. Plateau 6's maps, written in ttrpg2's `.map` language, are converted the first time
they are read ([below](#plateau-6s-maps-and-how-they-convert)).

## The document

A world map is stored as a Delve GeoJSON document (`delve.maps.geo.geojson`, `world_maps.geo` and
`WorldMapSource.geo`):

- a `FeatureCollection` whose coordinates are **km from the map's top left, y growing down**;
- each feature has an `id`, a geometry, and `properties` `{layer, kind, name, description, dm_notes, tags, hidden}`
  plus its own (a river's `navigable_km` and `barrier`, a route's `surface`);
- a `delve` member: the frame `{width_km, height_km, units}` (`units` is how distances are shown, `miles` or `km`),
  the grid, `terrain` (one letter a cell) and the picture `{id, width_px, height_px, km_per_px, asset}`.

Its export (`…/export.geojson`) is the same document, which QGIS opens.

## The grid

The terrain is a grid of cells (`delve.maps.geo.grid`, `model.Grid`): squares, or hexes (pointy, in odd-row offset
rows, or flat, in odd-column offset columns), `size_km` from one centre to the next. A map read from a picture keeps
the picture's grid ("1 hex = 30 miles" is a `size_km` of 48.28); a map without one gets `DEFAULT_CELLS` (200)
squares along its longer side. Each cell has one terrain class:

| Class | plains | forest | hills | mountain | swamp | desert | arctic | jungle | urban | sea | lake | impassable |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Letter | `p` | `f` | `h` | `m` | `s` | `d` | `a` | `j` | `u` | `w` | `l` | `x` |

`.` is a cell with none. The water areas set their cells to `sea` or `lake` on import and on every save
(`water_from_areas`); water brushed outside any area stays.

## The layers

| Layer | Kinds | Geometry |
|---|---|---|
| `places` | `city`, `town`, `village`, `castle`, `ruin`, `dungeon`, `port`, `other` | a point |
| `routes` | `road`, `track`, `trail` | a line |
| `water` | `river` (a line from its source to its mouth), `lake`, `sea` (areas) | a line or an area |
| `regions` | free: `kingdom`, `region`, … | an area |

A feature tagged `hidden` is the DM's until revealed. `dm_notes` are never a seat's; `description` is what the
characters may learn.

## Import

- **GeoJSON:** a Delve document reads back exactly. Any other is read through a mapping (which property holds the
  names, which the kinds, and what each kind found is) and needs its size: the map's width in km, or a known distance
  between two named places (`422 {needs: "scale", properties, kinds}` until it has one). **Azgaar's Fantasy Map
  Generator** exports map themselves: their cells' biome ids (0 to 12, Azgaar's defaults, with the name as a
  fallback) and heights, burgs, rivers, routes and markers. The test fixture is synthetic; a real export is the
  owner's to check.
- **A picture** (`POST /api/conversions/worldmap`, PNG, JPEG or WebP, at most 64 MB and 200 million pixels) comes with
  its key as separate fields: the grid (`hex`, `square` or `none`) and what one cell is (`distance` and `units`), or,
  with no grid, two points on the picture and their distance. The picture is kept in the blob store and cut into
  256 px tiles (`world_pictures`); it is read as a conversion job of kind `worldmap`, and makes a map in review.

## Reading a picture

`delve.maps.geo.reading.read.read_picture` runs five steps on a copy of at most 40 million pixels, deterministically
(numpy and Pillow, no random):

1. **`grid`:** the grid's size, offset and extent, from the ink folded into one repeating tile (the frame stays out).
2. **`terrain`:** each cell's middle 70%, clustered by colour with median cut (up to 16 colours); a cell under 60%
   one colour is a doubt. One vision call suggests each colour's terrain.
3. **`water`:** blue areas touching the grid's bounds are sea, others lakes; narrow blue lines are rivers, each with
   its mouth, flowing toward the sea (else the larger water) when both ends reach water.
4. **`places`:** symbols (small solid or ringed blobs of ink) and labels (OCR, when `tesseract` is there and
   `DELVE_OCR` isn't `off`), paired; labels OCR can't read, and symbols without one, go to a vision call on numbered
   crops. A label along a river is offered as its name, a wide one as a region's.
5. **`routes`:** lines of a colour that is no terrain's, blue or ink, at least 3 cells long; a dashed one is a trail.

## Review

A map read from a picture is `status` `review`: no seat's, never copied, travelled or exported. Its `reading` lists:

- **the colours**, each with Claude's suggestion, to map to a terrain or to **outside the map** (`outside`: the frame,
  the legend, the margin; its cells get no terrain);
- **the doubts**, in this order: `cluster-unmapped`, `water-kind-guessed`, `river-flow-guessed`, `label-unpaired`,
  `symbol-unlabelled`, `label-uncertain`, `kind-guessed`, `cell-mixed`, `river-no-mouth`. Each has its choices (a
  kind, a terrain, `keep`, `drop`, `reverse`; an unpaired label `place`, `river-name` or `region-name`), and **Decide
  all of this kind** settles every open one of a kind at once.

**Accept** waits until every colour is mapped; the map is then `ready`, and keeps its reading.

## Routing

`delve.maps.geo.routing` finds a leg's way by Dijkstra over the terrain cells, joined to the routes and the rivers,
in pure Python with numpy, one graph per map and mode (cached by `world_maps.graph` until the document changes):

- **On land** (`foot`, `horse`, `cart`): every land cell at its terrain's rate, a route at its surface's (road 1,
  track 1/1.2, trail 1/1.5 of the road's pace), never water or `impassable`; a river marked `barrier` is crossed only
  at a route or a place tagged `ford` or `bridge`. A destination in water snaps to the nearest land within a cell.
- **By river boat** (`river`): along the rivers and the lakes, faster downstream.
- **By ship** (`ship`): the sea, lakes of 3 cells or more, and rivers up to their `navigable_km` from the mouth.
- A flyer crosses every cell at rate 1.

The speeds and the terrain rates are in `docs/data-dictionary.md` (travel `mode`). `travel` walks a leg a day at a
time; an encounter stops it, and the `Journey` keeps the rest.

## Knowledge and the fog

What the party knows is the campaign's (`world_maps.knowledge`): everything, or cells (as runs) and features. A new
campaign's copy knows nothing, and its organiser sets the start (everything, nothing, some regions, or an area);
`place_party` and travel reveal the land within sight (10 km, farther from hills and mountains). The DM reveals a
feature or an area, adds a place, and hides a place, a road or an area again.

**The seat's view** (`knowledge.seat_view`) holds only the known cells' terrain, the features in them that aren't
hidden, without `dm_notes` or `props`, the routes and the journey cut at the known edge, and an unknown destination
unnamed. A tile with nothing known is never sent (404, drawn as fog in the browser); a partly known tile is fogged on
the server, opaque, as a JPEG. The picture's id is never a seat's.

## The setting's map

`setting_world_maps` points a setting (such as Greyhawk) to a module's ready world map: a new campaign of that
setting copies it instead of the setting's built-in maps. Nothing printed ships with Delve.

## In a `.dscn`

A geo map is a `worldmaps[]` entry of type `geojson` ([scenario format](scenario-format.md)); its picture is an asset
with audience `gm`, named in `delve.picture.asset` and kept out of the attachments, so the DM can't show it. A map in
review is left out of an export, with the warning `worldmap-in-review`.

## Plateau 6's maps, and how they convert

> Ported from ttrpg2 (`tools/world_map.py`, `WORLD-MAP-PLAN.md`) as `delve.maps.world`.

Plateau 6's world maps are `.map` texts in ttrpg2's world-map language, `worldmaps[]` entries of type
`ttrpg2-worldmap` in a `.dscn`. Delve still reads them, and converts each once into a geo map
(`delve.maps.geo.from_dsl`): a campaign's map on first read, a module's on GET, never in a migration.

- The view's units through its `scale` make km (a mile is 1.609344 km), y is flipped, and the frame is the features'
  bounding box plus 5% on every side.
- The grid is `DEFAULT_CELLS` squares; a cell under no terrain is plains. A terrain's `biome` names its class
  (`marsh` is swamp, `tundra` arctic, `mountains` mountain); another biome is plains, with a warning.
- Each feature keeps its name as its id. A feature's `description` goes into `dm_notes` (plateau 6 made it the DM's).
- A converted campaign knows everything, plus what was revealed, and its party's position is converted to km.
- The Greyhawk setting's region map has `scale 0.44`, so Greyhawk to Hardby by the road is about 80 miles, as its
  text says.

### At a glance

```
workspace greyhawk-region {
    styles {
        terrain.biome=forest { color #2d5a2d; fill-opacity 0.5 }
        [walled]             { stroke #444; stroke-width 2 }
    }

    model {
        terrain gnarley-forest { polygon 470,300 430,300 300,330 330,440 450,460; biome forest }
        lake nyr-dyv { polygon 380,560 620,560 640,680 360,680 }
        river selintan { points 510,400 505,450 500,500 }

        city greyhawk { at 500,500; pop 60000; tags [walled, capital] }
        city hardby   { at 640,385; pop 5000; label "Hardby" }
        poi castle-greyhawk { at 508,485; tags [ruined, dungeon]; description "Twelve sublevels." }

        road south-coast  { from greyhawk; to hardby; surface dirt }
        road castle-track { from greyhawk; to castle-greyhawk; via 504,492; surface track }
    }

    views {
        view world {
            scope greyhawk-region
            include kingdoms, cities, roads, rivers, lakes, terrain, poi
            units miles
            scale 1
        }
    }
}
```


### The language

- **Blocks** use braces. Statements end at a newline or a `;`. `#` starts a comment, except in a string and in a colour
  such as `#2d5a2d`.
- **Identifiers** are names like `greyhawk` or `castle-greyhawk`. A dotted name such as `orlane.temple` refers to a
  feature inside another one.
- **Values:** numbers, `"strings"` (with `\"` inside), `#hex` colours, identifiers, coordinates `x,y` (no space around
  the comma), coordinate lists `x,y x,y …`, and tags `[a, b, c]`.
- **Coordinates** are the author's: x grows east and **y grows north**. A view's `scale` turns map units into its
  `units`.
- **`!include <name>`** inlines another text where it stands, anywhere a statement fits. It can be nested 8 deep, and a
  cycle is refused. In a module, a map may include any other world map of the module, by its name or its file's name
  (`!include sulm-akar-buildings.map`). Such a fragment, a text without `workspace`, reads only through the map that
  includes it.

#### The workspace

`workspace <name> { … }` holds three sections. Each is optional, and each may come more than once:

- `styles { … }`: the style defaults for the whole map;
- `model { … }`: the features;
- `views { … }`: the views.

Nothing may follow the workspace's closing brace.

#### Features

`<kind> <name> { <properties> }`. There are 12 kinds, and the set is closed:

| Kind | Drawn as | From |
|---|---|---|
| `kingdom`, `terrain`, `lake` | area | `polygon x,y …` (a kingdom without one is not drawn) |
| `city`, `poi` | marker with a label | `at x,y` |
| `building`, `room` | area | `polygon …`, or `at x,y` + `size w,h` (a rectangle from `at`) |
| `road` | line | `from <place>; to <place>; via x,y …` |
| `river`, `street` | line | `points x,y …` |
| `passage` | line between two rooms' centres | `from <room>; to <room>` (a passage has no name) |
| `dungeon` | nothing: a frame for its rooms | `in <feature>` |

- **Properties on every feature:**
  - `description "…"`;
  - `tags [a, b]`;
  - `doc <path>`;
  - `label "…"`: the name on the map. Without it, the name is written out (`castle-greyhawk` is "Castle Greyhawk").
- **Properties of some kinds:**
  - `pop` and `in` on a city;
  - `biome` on terrain: `forest`, `hills`, `mountain`, `plains`, `desert`, `marsh`, `tundra`, `jungle`, or any word of
    your own;
  - `surface` on a road (see Distances);
  - `kind` on a POI (`kind gate`), shown as its `category`;
  - `roughness` on an area (0 for straight edges; 0.04 by default).
- **The fourth wall:** `description` and `doc` are the DM's and never reach the players: not in the SVG, and not in
  a seat's answer. The tag **`hidden`** keeps a place off the players' map until the DM reveals it.
- **Children:** `contains { … }` gives a feature its own features, such as a town's buildings and streets. `room`,
  `building`, `street` and `passage` written straight inside a feature are its children too.
- **References:** `from`, `to` and `in` must name a feature, in the feature's own scope or a wider one. A dangling
  reference is an error. So are an unknown kind and a duplicate name.

#### Styles

A style block is a list of rules, `selector { attribute value; … }`.

- **Selectors:**
  - `city`: every city;
  - `terrain.biome=forest` or `city.pop>1000`: a kind with a property test, one of `=`, `!=`, `>`, `<`, `>=` or `<=`;
  - `[walled]`: every feature with that tag.
- **Attributes:**
  - `color`;
  - `stroke`;
  - `stroke-width`;
  - `fill-opacity`;
  - `marker`: `circle`, `square`, `diamond` or `pin`;
  - `marker-size`.
- **The cascade:** the built-in styles come first, then the workspace's `styles`, then the view's own `styles`. The
  last rule that matches wins, attribute by attribute.

#### Views

`view <name> { scope <feature or workspace>; include <kinds>; units <word>; scale <n>; styles { … } }`

- **`scope`**: the workspace draws its top-level features, and a feature draws its children (a town's view).
- **`include`** takes plural words: `kingdoms`, `cities`, `roads`, `rivers`, `lakes`, `terrain`, `poi`, `buildings`,
  `streets`, `dungeons`, `rooms`, `passages`. Without it, every kind is drawn.
- **`units`** defaults to `miles`.
- **`scale`** (new in Delve) is the units per map unit, 1 by default.
- **Which view is used:** without a view name, a map shows its first view. A map without views shows its whole
  workspace.

Distances, routes and drawing are the geo map's (see Routing above); plateau 6's `geometry` and `render` are gone.

### Errors

A map that doesn't read raises `WorldMapError(line, message)`, with the line in the map's own text. An error inside an
include names the `!include` line, and the include's own line in the message.

- **On import,** a module's world map that doesn't read is kept as it is, with the warning `worldmap-unreadable`.
- **On a campaign's map,** a save with an invalid map is refused with its line and message (plan 6 Task 8).

### What changed from ttrpg2

- **The texts are handed in.** ttrpg2 read maps and includes from the campaign's folder. Delve reads no files: the
  caller passes the texts.
- **Errors carry the line as a number,** in the root text.
- **Stricter parsing:** text after the workspace is refused instead of ignored.
- **The output is an SVG** drawn on the server, instead of GeoJSON for Leaflet in the browser.
- **The roughening hashes its seed.** It used `random`, which only `Dice` may use in Delve.
- **New:** `scale`, `label`, the straight-line fallback, and a point on a road joining that road.
