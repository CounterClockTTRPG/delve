<!-- Built from docs/maps/ by `make dsl-reference`: don't edit it here. -->

# The dungml DSL

A `.dmap` file describes a single tabletop map — a building, a dungeon
level, an outdoor encounter site — in a small, declarative language.
The parser turns text into a typed semantic model; one of the bundled
renderers turns that model into SVG.

This is the index of the DSL reference. The material is split into
focused sections (links open in a new tab):

- **Map header** — the required `map` block, grid,
  renderer, theme, grid overlay.
- **Features & glyphs** — `feature_def`, the
  `glyph` drawing primitives, feature instances, the bundled `core.dmap`
  library, and the **glyph index**.
- **Geometry** — `room`, `corridor`, `slice`,
  `door`, `window`, `marker`, `layer`.
- **Validation & tooling** — semantic checks, the
  connectivity graph, the MCP authoring/play-session tools, the CLI,
  and a worked example.
- **Language reference** — every keyword, its
  legal child elements, a description, and an example.

---

## At a glance

```dmap
include "core.dmap"          # built-in feature library (hearth, table, …)

map "Miller's Cottage" {
  grid {
    cell   32 px
    units  feet 5
    bounds 30 x 20
  }
  renderer "floorplan"
}

room "kitchen" {
  rect 2,2 8 x 7
  label "Kitchen"
  feature hearth at 9,4 rotate 90
  feature table  at 6,6
}

door at 15,2 {
  connects room.kitchen
  type wooden
  state closed
  facing south
}

window at 4,2 { in room.kitchen width 1 }
```

A `.dmap` file is a flat sequence of top-level declarations. Order does
not matter — declarations are collected, then validated and rendered.

The grammar lives at `packages/dsl/src/dungml/grammar.lark`. The
semantic model lives at `packages/dsl/src/dungml/model.py`.

---

## File structure

A file is any number of top-level declarations in any order:

| Declaration   | Cardinality | Purpose |
|---------------|-------------|---------|
| `map`         | exactly 1   | Bounds, grid, renderer choice |
| `feature_def` | any         | Reusable furniture / dressing |
| `room`        | any         | Walled spaces with features |
| `corridor`    | any         | Connecting passages |
| `door`        | any         | Openings on walls |
| `window`      | any         | Window slits on exterior walls |
| `layer`       | any         | Logical group, optionally hidden |
| `include`     | any         | Pull in another `.dmap` library |

### Comments

Comments start with `#` and run to end of line:

```dmap
# This is a comment.
room "vault" { rect 0,0 5 x 5 }  # trailing comments are fine too
```

### Strings

Strings use double quotes. `\n`, `\t`, `\r`, `\"`, and `\\` are
honored. Multi-line strings use Python-style triple quotes (`"""`)
and trim a single leading and trailing newline:

```dmap
description """
The pride of Cael Voren. Vaulted ceiling lost to gloom;
book-spines reach higher than the eye can follow.
"""
```

### Numbers and coordinates

Numbers are integers or decimals, optionally negative. Coordinates are
written as `x,y` (no spaces inside the pair) in **world units** —
typically the same unit declared in `grid { units ... }`. The origin
is `top-left` by default; pass `origin bottom-left` to flip the Y
axis. Bounds are inclusive: a position of `(0,0)` and `(bounds_w,
bounds_h)` are both legal.

### Identifiers and references

`CNAME` identifiers match `[a-zA-Z_][a-zA-Z0-9_-]*`. References use
dotted form: `room.kitchen`, `corridor.south_passage`. The kind prefix
(`room` / `corridor`) is required.

---

## `include` — pulling in another file

```dmap
include "core.dmap"            # the built-in feature library
include "common-dungeon.dmap"  # extra dungeon dressing
```

`include` brings in a library of `feature_def`s (or any other top-level
declarations) from another file. In Delve, includes are resolved by name
against the module's own library maps, then the bundled libraries shipped
with the parser; no file on disk is read. The `dmap` command line also
reads files: relative to the including file, then to `--include-root DIR`
(by default the input's folder), and never one outside that root, `..` or
a symlink out included. Local declarations — and earlier
includes — win on name collision, so you can shadow any included feature
without editing the library. This is the supported way to **toggle an
alternate rendering** of a feature: define it locally, or include a
template that redefines it.

Two libraries ship with dungml:

- **`core.dmap`** — the built-in feature library (`pillar`, `chest`,
  `stairs-up`, `bridge`, `hearth`, …). Built-in features are *not*
  implicit: a map must `include "core.dmap"` to use them. See
  **Features & glyphs** for the full list.
- **`common-dungeon.dmap`** — extra dressing as filled-shape
  `feature_def`s: `magic_circle`, `sarcophagus`, `runestone`,
  `arcane_pillar`, `bookcase_tall`, `water_pool`, `sarcophagus_grand`,
  `spike_trap`, `ritual_brazier`, `obelisk`.

A library file is just a `.dmap` with no `map { }` block. New maps
created in the web app start with `include "core.dmap"` already in place.

---

# Map header


## `map` — required header

Every file must contain exactly one `map`:

```dmap
map "The Sunken Library" {
  grid {
    cell   20 px
    units  feet 5
    bounds 100 x 70
    origin top-left
  }
  renderer "classic-bw"
  theme    paper
  party_start "entry_hall"   # optional: room the PCs begin in on load
}
```

### `party_start`

`party_start` (optional) marks where the characters begin when the map loads.
It's drawn as a green **S** marker and, when it names a room/corridor, becomes
the default party location for new play-sessions (auto-revealed on load; an
explicit start passed to session-create overrides it).

Three forms:

- `party_start X,Y` — a bare marker at a world cell (no session linkage).
- `party_start "name"` — a room (or, failing that, corridor) named `name`; the
  marker is drawn at its centroid.
- `party_start "name" at X,Y` — as above, but the marker is forced to the
  absolute cell `X,Y` instead of the centroid.

### `room_numbers`

Rooms are auto-numbered in source order, and on-map labels are prefixed with
that number (`1. Hall`). `room_numbers off` in the map block suppresses the
prefix so labels render bare (`Hall`). Default `on`.

### `grid`

| Property | Form | Default | Meaning |
|----------|------|---------|---------|
| `cell N px`        | integer pixels | `32`  | Pixel size of one world-unit cell in the output SVG |
| `units NAME N`     | `units feet 5` | none  | Real-world unit name and how many of them per cell |
| `bounds W x H`     | two numbers    | `60 x 40` | Map extent in world units |
| `origin K`         | `top-left` \| `bottom-left` | `top-left` | Which corner is `(0,0)` |

### `renderer`

Pick the visual style. Built-in renderers:

- `"classic-bw"` — flat fill, hard outline. Dungeon default.
- `"floorplan"` — alias of `classic-bw`. Use for buildings.
- `"hatched"` — diagonal hatching outside walls. Architectural drawing style.
- `"oldschool-blue"` — classic blue-ink dungeon style: blue line-work over a
  solid blue page with white room floors, so rooms read as carved out of rock.
  A `grid_overlay` / `cell_grid` is tinted blue to match if the map declares
  one (no grid is forced).

If omitted, defaults to `"classic-bw"`.

### `theme`

The palette and font to draw with, independent of the renderer's geometry:
`renderer "hatched"` + `theme blue` is blue ink on a hatched halo. Built-in
themes:

- `mono` — black line-work on white (default for `classic-bw` / `floorplan`)
- `paper` — warm paper page and floors, sepia hatching (default for `hatched`)
- `blue` — blue ink, white floors, light-blue page (default for `oldschool-blue`)

If omitted, the renderer's default theme applies. An unknown name draws with
that default too, and validation warns (with a suggestion). Semantic colours —
marker tags, area and slice kinds, the party-start and exit accents — are not
part of a theme.

### `grid_overlay` — graph-paper grid across the canvas

A faint grid drawn across the whole map. Useful for tactical / square-
based grids on outdoor or freeform maps where you don't have a single
"room" to attach a per-room grid to.

```dmap
map "X" {
  grid { cell 20 px bounds 60 x 40 }
  grid_overlay                  # default — 1-unit spacing, default colour
  # grid_overlay 2              # 2-unit spacing
  # grid_overlay 1 "#444444"    # 1-unit spacing, custom colour
}
```

| Form                       | Result |
|----------------------------|--------|
| (omitted)                  | No overlay (default). |
| `grid_overlay`             | 1 world-unit spacing, default faint grey. |
| `grid_overlay N`           | N-unit spacing. |
| `grid_overlay N "#color"`  | N-unit spacing with explicit CSS colour. |

The overlay is drawn AFTER all map content (rooms, corridors, slices,
features) but BEFORE labels, so labels remain readable on top of it.
Per-room `grid` overlays still work and are clipped to their room — the
two stack cleanly when both are set.

---

# Geometry

declarations: rooms, corridors, slices, doors, windows, markers, exits,
layers.

## `room` — walled spaces

```dmap
room "kitchen" {
  rect 2,2 8 x 7
  label "Kitchen"
  description "Flour on every surface."
  dm_notes  "Hidden trapdoor under the rug at (5,5)."

  feature hearth at 9,4 rotate 90
  feature table  at 6,6 {
    description "Flour-dusted oak slab."
  }
}
```

| Property      | Notes |
|---------------|-------|
| shape decl    | exactly one of `rect`, `circle`, `polygon`, `boundary { ... }` |
| `label`       | optional, see below |
| `description` | text shown to players ("read aloud") |
| `dm_notes`    | private text — traps, secrets, hooks |
| `feature`     | zero or more — see feature instance |
| `grid N`      | overlay a per-room sub-grid at spacing `N` (world units) |
| `line_style K [N]` | wall edge style: `solid` (default) or `organic` (hand-drawn wobble). For `organic`, an optional number scales the waviness (`1.0` default, e.g. `line_style organic 3` = wavier, `0.5` = subtler). Also valid on `corridor`. |

Features placed in a room are listed with `feature` lines; the syntax
and built-in names are documented in
**Features & glyphs**.

### Shapes

```dmap
rect 2,2 8 x 7
circle at 15,15 radius 8
polygon (0,0) (10,0) (12,4) (10,8) (0,8)
boundary {
  start 4,22
  line to 17,22
  arc  to 17,40 via 23,31
  line to 4,40
  line to 4,22
}
```

- `rect X,Y W x H` — axis-aligned, `X,Y` is the top-left corner.
- `circle at X,Y radius R` — `X,Y` is the centre. Treated geometrically as
  a finely-sampled polygon, so walls, door cut-outs, and overlap checks all
  work the same as for any other room.
- `polygon (x,y) ...` — three points minimum, implicitly closed.
- `boundary { ... }` — mixed straight + arc edges. `start` is required.
  Each `line to X,Y` adds a straight edge ending at the point. Each
  `arc to X,Y via X,Y` adds a circular arc ending at `to`, passing
  through `via` — three points uniquely determine the arc. The
  boundary is implicitly closed by the renderer.

### `label`

```dmap
label "Grand Library" at 46,9 size 1.4 rotate 0
label "Atrium"        align top center
label "Vault"         align bottom right size 0.9
```

| Modifier        | Default | Notes |
|-----------------|---------|-------|
| `at X,Y`        | room centroid | Absolute world coords. |
| `align V H`     | none → centroid | Relative to the room's bounding box. `V` is `top` \| `middle` \| `bottom`; `H` is `left` \| `center` \| `right`. Vertical first. |
| `size N`        | `1.0` | Multiplier; renderer picks a base size. |
| `rotate N`      | `0` (degrees) | |

`at` and `align` are mutually exclusive in effect — if both are
specified, `at` wins. Aligned labels also align the text itself
(`left` → text-anchor start, `right` → end, `top` → baseline at the
top of the glyph, etc.) so the text doesn't overflow the room.

---

## `corridor` — connecting passages

```dmap
corridor "atrium_to_library" {
  width 2
  segment line from 20,11 to 26,11
}

corridor "back_crawl" "Back Crawl" {       # second STRING is a display name —
  width 1                                  # shown in tooltips / print legend,
  segment line from 5,4 to 25,4            # never drawn on the map.
}

corridor "named_route" "Pilgrim's Way" {   # opt-in on-map label: include an
  width 1.5                                # explicit `label` block.
  segment line from 10,5 to 40,5
  label "Pilgrim's Way" align top center size 0.8
}
```

| Property        | Notes |
|-----------------|-------|
| `width N`       | world units, default `1.0` |
| `segment`       | zero or more (see below) |
| `node NAME at X,Y` | a named junction point (see "Branches and intersections") |
| `run A to B`    | a straight run between two named nodes |
| `label "..."`   | optional on-map label. Same modifiers as room labels (`at X,Y`, `align V H`, `size N`, `rotate N`). With no `at`/`align`, the label is auto-placed along the longest line segment and rotated to read along the corridor. |
| `description`   | optional |
| `dm_notes`      | optional |

The second `STRING` immediately after the slug (e.g. `"Back Crawl"` above)
is a **display name** used only by the tooltip and the print key. It is
*never* rendered as text on the map. To draw a corridor label on the map,
add an explicit `label "..."` block inside the corridor.

### Segment kinds

```dmap
segment line from X,Y to X,Y
segment arc  center X,Y radius N from-angle DEG to-angle DEG sweep ccw
```

- `line` is a straight segment between two points.
- `arc` describes a circular arc by center, radius, and start/end
  angles in degrees. `sweep` is optional and is one of `ccw` (default)
  or `cw`.

### Branches and intersections

A single corridor can branch. Instead of chasing coordinates, name the
junction points with `node` and join them with `run`:

```dmap
corridor "crossroads" {
  width 2
  node hub at 15,15
  node n   at 15,4
  node s   at 15,26
  node e   at 26,15
  node w   at 4,15
  run hub to n      # ┐
  run hub to s      # ┤ four runs sharing `hub` → a 4-way crossing
  run hub to e      # ┤ (3 runs → a T-junction; ≥3 from any node → a branch)
  run hub to w      # ┘
}
```

- A `run A to B` is a **straight** segment between two named nodes. The
  number of runs meeting at a node sets the junction: two collinear runs
  read as a straight pass-through, three as a **T**, four as a **crossing**,
  and any node with three-or-more runs is a **branch**. Runs that form a
  cycle make a **loop**.
- Nodes guarantee that the meeting runs share *exactly* one point, so the
  renderer draws a clean junction (no parallel-wall stitching, no sliver
  overlap warnings against the corridor itself).
- Curved branches: keep using `segment arc` for the curved leg — `run` and
  `segment` can be mixed freely in the same corridor.
- A branching corridor is still **one node in the connectivity graph**
  (see Validation & tooling): the whole shape is one
  connected space, so it is fully traversable without placing a door at
  every junction. This is the recommended way to author an intersecting
  passage network — model it as a single corridor rather than many
  corridors that merely touch.

`run`s are sugar: they desugar into `line` segments, so everything that
consumes segments (rendering, overlap checks, the graph) works unchanged.

---

## `slice` — cross-slice terrain (rivers, ravines, splits)

A `slice` cuts ACROSS the map rather than connecting rooms. The geometry
is the same as a corridor (line + arc segments with a width), but the
rendering treats the band as terrain — water for rivers, dirt with shadow
for ravines, a hairline crack for splits.

```dmap
slice "river_branwen" {
  kind  river                  # river | ravine | split
  width 3.2
  segment line from 22,0  to 22,8
  segment arc  center 24,11 radius 3 from-angle 180 to-angle 270 sweep ccw
  segment line from 23,17 to 23,28
  label "R. Branwen" at 26,23 rotate -85 size 0.9
  description "Cold and quick. Knee-deep at the ford."
}

# A bridge is the built-in `bridge` feature placed on top of the slice.
# Default deck is 1.6 (along) × 1.0 (across); rotate to align with the
# slice direction and scale to match its width.
feature bridge at 22,14 rotate 90 scale 1.4 {
  description "Three squat stone arches."
}
```

| Property        | Notes |
|-----------------|-------|
| `kind K`        | `river` (blue band + flow dashes), `ravine` (dirt band + depth shadow), `split` (thin dark crack). Default `river`. |
| `width N`       | World units. For `split` this acts as the soft-shadow width since the crack itself is always thin. Default `2.0`. |
| `segment`       | Same `line` / `arc` syntax as corridors. |
| `label "..."`   | Optional, same modifiers as room labels. With no `at`/`align`, the label auto-orients along the longest line segment. |
| `description`   | Optional. |
| `dm_notes`      | Optional. |

Slices render after corridors and before doors/windows/features, so
bridges and other crossing features sit cleanly on top of the band.
The slice itself does **not** model crossings or movement obstruction —
that's purely a feature-placement convention.

The `bridge` built-in (deck rectangle with rails and plank ticks) comes
from `core.dmap`, so `include "core.dmap"` to use it. It can also be
placed independently of any slice — e.g. a deck over a corridor — and as
a top-level declaration outside any room.

---

## `door` — openings on walls

```dmap
door at 15,2 {
  connects room.parlor
  type     wooden
  state    closed
  facing   south
  width    2
  description "Heavy oak. The hinges complain."
}
```

| Property      | Default       | Notes |
|---------------|---------------|-------|
| `connects`    | required for full semantics | One or two `room.NAME` / `corridor.NAME` refs, comma-separated |
| `type`        | `wooden`      | `wooden`, `iron`, `stone`, `secret` (`S`-in-circle on wall), `concealed` (`C`-in-circle on wall), `smashed` (arch with debris), `arch`, `portcullis`, `open` (bare gap), `double` (two leaves), `one-way` |
| `state`       | `closed`      | `open`, `closed`, `locked` (`arch` / `open` ignore state) |
| `facing`      | inferred      | `north`, `south`, `east`, `west` — hints the leaf side; sets the `one-way` arrow direction |
| `width`       | `1.0`         | World units across the opening |
| `description` | none          | Long-form text |

A door's position should sit *on a wall*; renderers project it onto
the nearest wall within ~½ world unit. Doors that miss every wall by
more than that are drawn as a small circle at the literal position.

`type open` draws nothing (the wall gap is the door) but is still a real
connector. `type one-way` is passable in one direction only — from the
first `connects` reference to the second — and the connectivity graph /
pathfinding honour that.

`type secret` draws as an S-in-circle on top of the wall with no
opening cut.

`connects` may name only one side (e.g. a front door whose other side
is exterior). At least one `connects` is recommended — validation
emits a warning when missing.

---

## `window` — slits on exterior walls

```dmap
window at 4,9 { in room.entry_atrium width 1.5 }
```

| Property      | Notes |
|---------------|-------|
| `in`          | required — `room.NAME` or `corridor.NAME` |
| `width`       | default `1.0` |
| `description` | optional |

Like doors, the position is projected onto the nearest wall of the
named room.

---

## `marker` — dynamic tokens (party, NPCs, monsters)

```dmap
marker "Aragorn" at 5,5 tag party initial "A"
marker "Goblin Boss" at 20,4
    tag boss
    label "Broken-Tooth"
    size 0.6
    image "tokens/goblin-boss.png"
    in room.guardroom
    description "Wields a notched scimitar."
    dm_notes "Surrenders below 6 HP."
```

A marker is a lightweight named token placed at a single point on the
map. Unlike `feature`, which is static furniture, markers represent
*who is here right now* — party members, NPCs, monsters — so they're
typically rewritten between scenes by an outer tool (e.g. a combat
tracker) rather than authored once.

| Property      | Notes |
|---------------|-------|
| `at X,Y`      | required — token position in world units |
| `tag`         | palette key (`party`, `ally`, `npc`, `enemy`, `boss`, `neutral`, `unknown`) **or** a CSS color literal in quotes (`tag "#ff8800"`). Default `neutral`. |
| `label`       | optional display caption rendered below the token. Defaults to no caption. |
| `initial`     | 1–2 character glyph drawn inside the disc. Default: first character of the name. Ignored when `image` is set. |
| `size`        | token radius in world units. Default `0.5`. |
| `in`          | optional `room.NAME` / `corridor.NAME` reference, recorded as a `data-location` attribute on the rendered group. |
| `image`       | optional path or URL to a portrait. When set, the renderer emits an `<image>` clipped to the token circle and uses `tag` as the ring color instead of the disc fill. |
| `description` | optional free text — surfaced via `data-description`. |
| `dm_notes`    | optional DM-only text — surfaced via `data-dm-notes`. |

The colored disc/ring uses the tag palette so party / ally / enemy /
boss read at a glance even when the portrait art doesn't follow a
strict convention.

Markers inside a `hidden` layer are parsed and validated, but the
renderer skips them — useful for tokens that should only appear in
DM-facing exports.

---

## `exit` — cross-map transitions

```dmap
exit at 3,4 {
  to "cellar" at 10,2
  label "Down to the cellar"
  description "A trapdoor set into the flagstones."
  dm_notes "Lands the party beside the wine racks (area 7)."
  secret
}
```

An `exit` is a point that links *out of this map* to a position on
**another map in the same project**. Stepping onto it sends the party to
`target_map` at the given landing coordinates — the cross-map equivalent
of a stairway between floors. The minimal form is just the placement plus
a target:

```dmap
exit at 3,4 { to "cellar" at 10,2 }
```

| Property        | Notes |
|-----------------|-------|
| `at X,Y`        | required — where the exit sits on *this* map (world units) |
| `to "MAP" at TX,TY` | required — the destination map's name/id within the project, and the landing coordinates on it |
| `label`         | optional on-map caption, drawn beneath the portal pad |
| `description`   | optional free text — surfaced via `data-description` |
| `dm_notes`      | optional DM-only text — surfaced via `data-dm-notes` |
| `secret`        | mark the exit GM-only: stripped from the fogged players' view until discovered, like a secret door |

Unlike a `door` — which `connects` two nodes
*within* one map and so feeds the connectivity graph
— an exit leaves the map entirely. It is therefore **not** a graph node
or edge: pathfinding within a single map ignores it. Resolving
`target_map` to an actual map is a whole-project concern (the DSL
validator only checks that the target name is non-empty and the placement
is in bounds, since the other map isn't visible from this file).

The renderer draws an indigo "portal" pad with an up-and-out arrow and
emits the target as data attributes (`data-exit-to`, `data-target-x`,
`data-target-y`) so an interactive play view can route a click to the
destination map. Like markers, exits inside a `hidden` layer are skipped
by the renderer.

---

## `layer` — grouping declarations

```dmap
layer "secrets" hidden {
  feature trap at 84,32 {
    description "Floor plate. Releases steam from the niche above."
  }
  feature chest at 88,38
}
```

A layer wraps any number of `room`, `corridor`, `feature`, `door`, and
`window` declarations. The `hidden` flag tells renderers to omit the
layer from the visible output — useful for DM-only secrets that
still parse and validate alongside the rest of the map.

Rooms inside a hidden layer do not contribute to room numbering or
visible walls. Doors and windows inside a hidden layer are skipped
likewise.

---

# Language reference

A keyword-by-keyword reference for the dungml DSL. Every keyword that can
appear in a `.dmap` file is listed here with the elements it may contain,
a short description, and an example.

For prose walkthroughs see the topic guides:
**Map header**, **Geometry**,
**Features & glyphs**, **Validation & tooling**.
The authoritative grammar lives at `packages/dsl/src/dungml/grammar.lark`
and the typed model at `packages/dsl/src/dungml/model.py`.

## How to read this reference

Each entry gives:

- **Context** — where the keyword may legally appear (which parent block,
  or *top level* for a standalone declaration).
- **Children** — the properties / nested elements it accepts. Order never
  matters; every child is optional unless marked *required*.
- An **example** in `dmap`.

Syntax conventions: `STRING` is a double-quoted string, `NUMBER` an
integer or decimal (optionally negative), `NAME` a bare identifier
(`[a-zA-Z_][a-zA-Z0-9_-]*`), and `REF` a dotted reference such as
`room.kitchen` or `corridor.south_passage`. Coordinates are written
`x,y` (no spaces) in world units.

---

## Top-level declarations

These may appear at the top level of a file, in any order. Exactly one
`map` (or one `scenario`) is required; everything else is optional and
may repeat.

| Keyword | Cardinality | Purpose |
|---------|-------------|---------|
| `map` | exactly 1 (or one `scenario`) | Bounds, grid, renderer choice |
| `scenario` | alternative to `map` | Multi-map adventure bundle |
| `include` | any | Pull in another `.dmap` library |
| `feature_def` | any | Define reusable furniture / dressing |
| `room` | any | Walled spaces |
| `corridor` | any | Connecting passages |
| `slice` | any | Cross-cutting terrain (river / ravine / split) |
| `door` | any | Openings on walls |
| `window` | any | Window slits on walls |
| `marker` | any | Dynamic tokens (party, NPCs, monsters) |
| `text` | any | Freestanding map text |
| `area` | any | Decorative terrain pools |
| `line_feature` | any | Styled polyline decoration |
| `exit` | any | Cross-map transition |
| `layer` | any | Logical group, optionally hidden |
| `feature` | any | Place a defined feature (also nests in rooms) |

---

## `include`

Pull every top-level declaration from another `.dmap` file into this one —
typically a `feature_def` library. Local declarations and earlier includes
win on name collision, so you can shadow any included feature.

**Context:** top level.
**Children:** none (takes a single `STRING` path).

```dmap
include "core.dmap"            # the built-in feature library
include "common-dungeon.dmap"  # extra dungeon dressing
```

---

## `scenario`

An adventure-level bundle: scenario-wide prose plus references to the
`.dmap` files it spans. Use *instead of* a top-level `map`. The scenario
renderer pulls in each referenced map.

**Context:** top level (mutually exclusive with `map`).

| Child | Description |
|-------|-------------|
| `map STRING` | A path reference to a `.dmap` file in the scenario. Repeatable. |
| `description` | Scenario-wide read-aloud / summary text. |
| `dm_notes` | Scenario-wide GM-only notes. |

```dmap
scenario "The Sunless Citadel" {
  description "A fallen fortress swallowed by a ravine."
  map "maps/overgrown-courtyard.dmap"
  map "maps/goblin-warren.dmap"
}
```

---

## `map`

The required map header: declares the canvas, the renderer, and map-wide
display options.

**Context:** top level (exactly one).

| Child | Description |
|-------|-------------|
| `grid { … }` | *Required.* Cell size, units, bounds, origin. See `grid`. |
| `renderer STRING` | Renderer id, e.g. `"classic-bw"`, `"floorplan"`. |
| `theme NAME` | Palette + font: `mono`, `paper`, `blue`. Defaults to the renderer's own (see dsl-map). |
| `legend` | Draw a symbol-legend strip below the map. |
| `grid_overlay [NUMBER [STRING]]` | Graph-paper grid across the whole canvas; optional spacing + CSS colour. |
| `cell_grid [NUMBER [STRING]]` | Per-cell grid inside rooms/corridors; optional spacing + colour. |
| `background STRING` | Map-wide background fill (CSS colour or texture id). |
| `party_start NUMBER,NUMBER` | Marker at a world cell. |
| `party_start STRING [at NUMBER,NUMBER]` | Party begins in room/corridor `STRING` (marker at its centroid, or the `at` cell). Becomes a new session's default start node. |
| `room_numbers NAME` | Auto-number rooms (`on` / `off`). |
| `title STRING` | On-map title; accepts `label` modifiers (`at`, `align`, `size`, `rotate`). |
| `corners NAME` | Map-wide default corridor corner style (`round` or `straight`). |
| `description` | Map read-aloud / summary text. |
| `dm_notes` | Map-wide GM-only notes. |

```dmap
map "Miller's Cottage" {
  grid { cell 32 px  units feet 5  bounds 30 x 20 }
  renderer "floorplan"
  legend
  grid_overlay 1 "#444"
  party_start 2,18
}
```

### `grid`

The canvas definition. Required inside `map`.

**Context:** inside `map`.

| Child | Description |
|-------|-------------|
| `cell NUMBER px` | Pixels per world unit when rasterising. |
| `units NAME NUMBER` | Real-world unit name + size per cell, e.g. `units feet 5`. |
| `bounds NUMBER x NUMBER` | Map width × height in world units (inclusive). |
| `origin top-left \| bottom-left` | Y-axis direction; default `top-left`. |

```dmap
grid {
  cell   32 px
  units  feet 5
  bounds 40 x 30
  origin bottom-left
}
```

---

## `room`

A walled space. Exactly one shape is required; everything else is optional.

**Context:** top level, or inside a `layer`.

`room "name" at X,Y { … }` makes everything inside the room — its shape,
label position, features, texts, areas, line features and exits — relative
to `X,Y`, so the room moves by editing one line. (Doors placed with
`between` move with it.) Without `at`, coordinates are absolute.

| Child | Description |
|-------|-------------|
| *a shape* | *Required.* One of `rect`, `polygon`, `circle`, `boundary` (below). |
| `label STRING …` | On-map label. See `label`. |
| `feature …` | Furniture placed in the room. See `feature`. |
| `text STRING at X,Y …` | Text bound to the room — only drawn when the room is visible. See `text`. |
| `exit at X,Y { … }` | A cross-map exit anchored in the room — only drawn when the room is visible. See `exit`. |
| `line_feature STRING { … }` | A polyline decoration bound to the room — only drawn when the room is visible. See `line_feature`. |
| `grid NUMBER [STRING]` | Per-room grid overlay: spacing + optional CSS colour. |
| `background STRING` | Floor fill: a CSS colour or a texture id — `stone`, `parchment`, `water`, `grass`, `dirt`, `forest`, `cemetery` (small grave crosses, spaced out), `building` (close diagonal hatching, a built-up block). |
| `line_style NAME [NUMBER]` | Wall edge style: `solid` or `organic` (+ optional waviness); also `dashed`, `dotted`, `ruined`, `trail` (x-marks) and `ticked` (short strokes across the wall, close together: a dome's rim). |
| `allow_overlap` | Opt out of the interior-overlap validation warning. |
| `description` | Read-aloud text. |
| `dm_notes` | GM-only notes. |

```dmap
room "kitchen" {
  rect 2,2 8 x 7
  label "Kitchen"
  feature hearth at 9,4 rotate 90
  text "A" at 6,6 description "Bloodstain — see area 4"
  description "Warm, low-ceilinged, smelling of woodsmoke."
}
```

### Room shapes

A room takes exactly one of these.

| Shape | Syntax | Description |
|-------|--------|-------------|
| `rect` | `rect X,Y W x H` | Axis-aligned rectangle from a corner. |
| `polygon` | `polygon (X,Y) (X,Y) …` | Closed polygon from points. |
| `circle` | `circle at X,Y radius R` | Circular room. |
| `boundary` | `boundary { … }` | Mixed straight/arc outline (below). |

```dmap
room "well_chamber" { circle at 12,12 radius 4 }
room "cave"  { polygon (2,2) (9,3) (8,9) (1,7) }
```

### `boundary`

A closed outline mixing straight lines and 3-point arcs. The final edge
implicitly connects back to `start`.

**Context:** inside a `room` (as its shape).

| Child | Description |
|-------|-------------|
| `start X,Y` | *Required first edge.* The opening vertex. |
| `line to X,Y` | A straight edge to a point. |
| `arc to X,Y via X,Y` | An arc ending at a point, bowing through a midpoint. |

```dmap
room "apse" {
  boundary {
    start 0,0
    line to 6,0
    arc  to 6,6 via 8,3
    line to 0,6
  }
}
```

---

## `corridor`

A connecting passage drawn as a centerline with walls. The optional
second `STRING` is a display name (tooltip / legend only — not drawn).
A dead end with no door/exit at it is capped with a flat wall.

**Context:** top level, or inside a `layer`.

| Child | Description |
|-------|-------------|
| `width NUMBER` | Corridor width in world units. `width 0` draws a bare centerline (a route marker). |
| `segment line from X,Y to X,Y` | A straight run. See segments. |
| `segment arc center X,Y radius R from-angle A to-angle A [sweep cw\|ccw]` | A curved run. |
| `node NAME at X,Y` | A named junction point (used with `run`). |
| `run NAME to NAME [width NUMBER]` | A straight run between two named nodes (desugars to a segment). `width` overrides the corridor's for this run alone — a passage that widens into a hall stays one corridor. |
| `corners NAME` | Corner style at bends: `round` (default) or `straight`. |
| `feature …` | Furniture on the corridor (e.g. a portcullis). |
| `text STRING at X,Y …` | Text bound to the corridor — only drawn when it is visible. |
| `exit at X,Y { … }` | A cross-map exit anchored in the corridor — only drawn when it is visible. |
| `line_feature STRING { … }` | A polyline decoration bound to the corridor — only drawn when it is visible. |
| `label STRING …` | An on-map label drawn over the corridor. |
| `background STRING` | Floor fill override. |
| `line_style NAME [NUMBER]` | Wall edge style. |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
corridor "south_passage" "Servants' Run" {
  width 2
  segment line from 14,9 to 24,9
  segment line from 24,9 to 24,4
  corners straight
}
```

### Segments

`segment` accepts one of two geometries. Branches form where ≥3 segments
share an endpoint (T / crossing).

| Segment | Syntax |
|---------|--------|
| `line` | `segment line from X,Y to X,Y` |
| `arc` | `segment arc center X,Y radius R from-angle A to-angle A [sweep cw\|ccw]` |
| `arc` (three points) | `segment arc from X,Y to X,Y via X,Y` — through a point on the curve, the same form a room `boundary` uses. |

```dmap
corridor "bend" {
  width 1.5
  node a at 4,4
  node b at 4,12
  node c at 14,12
  run a to b
  run b to c
}
```

---

## `slice`

Cross-cutting terrain (rivers, ravines, splits): the same line/arc segment
geometry as a corridor, but rendered as an impassable terrain band rather
than a passable interior. Bridges are regular `feature`s placed on top.

**Context:** top level, or inside a `layer`.

| Child | Description |
|-------|-------------|
| `kind river \| ravine \| split` | The terrain band style. |
| `width NUMBER` | Band width in world units. |
| `segment …` | Line/arc geometry (same as a corridor). |
| `label STRING …` | On-map label. |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
slice "the_rift" {
  kind ravine
  width 3
  segment line from 0,10 to 30,12
}
```

---

## `door`

An opening on a wall, and a connector in the connectivity graph. Its
position is projected onto the nearest wall.

**Context:** top level, or inside a `layer`.

Header forms:

- `door at X,Y { … }` — at a point.
- `door between REF and REF { … }` — the position is computed: the middle
  of two rooms' shared wall, where a corridor meets a room, or where one
  corridor ends at another. `connects` is filled in (in the order written).
  Spaces that don't meet are an error.
- `door "name" at … / between …` — a named door. Play sessions record found
  and opened doors by key; an unnamed door's key is its position, so moving
  it makes sessions forget it, while a name survives the move. (Naming an
  existing door changes its key once.)

| Child | Description |
|-------|-------------|
| `connects REF[, REF]` | One or two `room.NAME` / `corridor.NAME` refs. Recommended (validation warns when absent). |
| `type NAME` | `wooden` (default), `iron`, `stone`, `secret`, `concealed`, `smashed`, `arch`, `portcullis`, `open`, `double`, `one-way`, `false`. |
| `state NAME` | `closed` (default), `open`, `locked`. |
| `facing NAME` | `north` / `south` / `east` / `west`; hints the leaf side and sets the `one-way` direction. |
| `width NUMBER` | Opening width; default `1.0`. |
| `trapped` | Flag the door as trapped (GM-only; hidden in the fogged view). |
| `secret` | Concealed until found, whatever its `type` — `type iron secret` is a hidden iron door. (`type secret` still works.) |
| `description` / `dm_notes` | Read-aloud / GM text. |

A **false door** (`type false`) is drawn on one space's wall and leads
nowhere: give it a single `connects`. The GM's view marks it **F**; the
players see an ordinary wooden door (fog and the room context's perceived
exits report it as `wooden`), and the room context lists it under
`dm_only.false_doors`.

```dmap
door "cellar" between room.kitchen and corridor.stair { type iron secret }
door at 4,9 { connects room.vault  type false }

door at 15,2 {
  connects room.parlor, corridor.hall
  type wooden
  state locked
  facing south
  trapped
}
```

---

## `window`

A window slit on a wall. Like a door, the position is projected onto the
nearest wall of the named node.

**Context:** top level, or inside a `layer`.

| Child | Description |
|-------|-------------|
| `in REF` | *Required.* The `room.NAME` / `corridor.NAME` the window sits on. |
| `width NUMBER` | Slit width; default `1.0`. |
| `description` | Optional free text. |

```dmap
window at 4,9 { in room.entry_atrium width 1.5 }
```

---

## `marker`

A lightweight named token (party member, NPC, monster) at a single point.
Unlike `feature` (static furniture), markers represent *who is here now*.
Modifiers may appear in any order.

**Context:** top level, or inside a `layer`.

| Child | Description |
|-------|-------------|
| `at X,Y` | *Required.* Token position. |
| `tag NAME \| STRING` | Palette key (`party`, `ally`, `npc`, `enemy`, `boss`, `neutral`, `unknown`) or a CSS colour literal. Default `neutral`. |
| `label STRING` | Caption rendered below the token. |
| `initial STRING` | 1–2 char glyph in the disc; defaults to the name's first char. |
| `size NUMBER` | Token radius; default `0.5`. |
| `in REF` | Optional `room.NAME` / `corridor.NAME` location. |
| `image STRING` | Portrait path/URL clipped to the token circle. |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
marker "Aragorn" at 5,5 tag party initial "A"
marker "Goblin Boss" at 20,4 tag boss label "Broken-Tooth" size 0.6 in room.guardroom
```

---

## `text`

Freestanding map text. At the top level (or in a `layer`) it is always-on
decoration; nested inside a `room`/`corridor` it is bound to that node and
drawn only when the node is visible (fog prunes them together). Accepts an
inline modifier list **or** a braced block — they are interchangeable.

**Context:** top level, inside a `layer`, or inside a `room` / `corridor`.

| Child | Description |
|-------|-------------|
| `at X,Y` | *Required.* Anchor position (absolute world coords, even when nested). |
| `size NUMBER` | Multiplier on the base label size; default `1.0`. |
| `rotate NUMBER` | Rotation in degrees. |
| `description` | Meaning of the glyph — surfaced as a hover tooltip / key. |
| `dm_notes` | GM-only note. |

```dmap
text "A" at 6,6 size 1.5 description "Altar of the Old Gods"

text "D" at 12.5,26.5 {
  description "A glyph carved into the wall. Touching it teleports to area 24."
}
```

---

## `area`

Decorative terrain (water / lava / pit / …) drawn as a filled shape. It
reuses the room shape grammar but is **not** a room — no walls, no graph,
no numbering.

**Context:** top level, or inside a `layer`.

| Child | Description |
|-------|-------------|
| *a shape* | One of `rect` / `polygon` / `circle` / `boundary`. |
| `kind NAME` | Built-in fill palette: terrain (`water`, `lava`, `pit`, `chasm`, `mud`, `acid`, `ice`, `blood`, `slime`, `swamp`) or floor that isn't terrain — `dais` (a raised dais or platform), `sunken` (a floor a step down), `darkness` (a translucent pall: magical darkness), `inlay` (outline only: a ring or pattern set in the floor). May also follow the name: `area "pool" kind water { … }`. |
| `background STRING` | Override the palette fill. |
| `label STRING …` | On-map label. |
| `line_style NAME [NUMBER]` | Edge style (`organic` for natural pools). |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
area "reflecting_pool" kind water {
  polygon (4,4) (10,4) (10,9) (4,9)
  line_style organic
}
```

---

## `line_feature`

A styled polyline decoration drawn along a path of points: `bars` (dotted),
`curtain` (wavy), `barred`, `step` (two thin parallel lines), and for water
too thin to be an area at the map's scale, `stream` (one water-coloured line)
and `canal` (two water-coloured banks). `bridge` is a span over a drop
(`width` sets its breadth), `rope-bridge` the same with planks and a rope each
side, `zipline` a cable with an anchor at each end, `path` a dashed trail (a
safe way through traps or a marsh), `road` a street or road at town or
overland scale (a pale band with inked edges; `width`), `cliff` a cliff, ridge
or steep slope (hachure ticks on the left of the path's direction — the
downhill side), `fence` a fence or palisade (a line with posts), and `wall` a
wall drawn inside a space —
a half-wall, a partition, a chamfered corner — in the walls' own ink. Not a
connector — excluded from the graph (a `wall` line doesn't split a room).

**Context:** top level, inside a `layer`, or inside a `room` / `corridor`.
A nested line feature is drawn only when its node is visible (fog prunes them
together).

| Child | Description |
|-------|-------------|
| `kind NAME` | The polyline style. May also sit before the brace: `line_feature "x" kind bars { … }`. |
| `point X,Y` | A vertex along the path. Repeatable. |
| `width NUMBER` | `bridge` / `rope-bridge` / `road` only: the band's breadth. |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
line_feature "portcullis_track" kind bars {
  point 10,4
  point 14,4
}
```

---

## `exit`

A cross-map transition: stepping on it sends the party to a position on
another map in the same project.

**Context:** top level, inside a `layer`, or inside a `room` / `corridor`.

| Child | Description |
|-------|-------------|
| `to STRING at X,Y [roll STRING]` | *Required.* Target map name and the landing position on it. Repeat it for an exit with several destinations (a teleporter that rolls where it sends you), each with the die result that picks it; the first is the exit's main target. |
| `label STRING …` | An on-map label. |
| `secret` | Hide from the fogged players' view until discovered. |
| `description` / `dm_notes` | Read-aloud / GM text. |

```dmap
exit at 3,4 {
  to "cellar" at 10,2
  label "Down to the cellar"
  secret
}

exit at 15.5,19.5 {
  to "Level 3" at 40,12 roll "1-2"
  to "Level 5" at 99,77 roll "3-6"
  label "teleporter"
}
```

---

## `feature_def`

Define a reusable feature (furniture / dressing) that `feature` instances
then place. A definition uses *either* a filled `shape` (with optional
`overlay`) *or* a `glyph` of line-art commands.

**Context:** top level.

| Child | Description |
|-------|-------------|
| `shape SHAPE` | A filled base shape: `circle radius R`, `rect W x H`, or `polygon …`. |
| `glyph { … }` | Line-art draw commands (below) — an alternative to `shape`. |
| `outline { … }` | Stroke styling for the shape: `color`, `width`, `stroke`. |
| `overlay SHAPE [offset X,Y] [fill STRING]` | A second shape layered on the base. |
| `background STRING` | Base fill colour / texture. |
| `name STRING` | Human-readable display name. |
| `secret` | Mark the whole feature type GM-only. |
| `description` | Feature description. |

```dmap
feature_def "altar" {
  shape rect 2 x 1
  background "#d8d2c4"
  outline { color "#333" width 0.08 stroke solid }
  overlay circle radius 0.3 offset 0,0 fill "#a33"
}
```

### `glyph`

An ordered list of raw draw primitives. Each begins with a **role**
(`stroke`, `fill`, or `plain`) selecting its CSS class, followed by
geometry, then optional style overrides.

**Context:** inside a `feature_def`.

| Primitive | Syntax |
|-----------|--------|
| `circle` | `circle ROLE at X,Y radius R` |
| `rect` | `rect ROLE at X,Y W x H` |
| `line` | `line ROLE from X,Y to X,Y` |
| `polygon` | `polygon ROLE (X,Y) …` |
| `polyline` | `polyline ROLE (X,Y) …` |
| `path` | `path ROLE STRING` (raw SVG path data) |

Style overrides (after the geometry): `fill-color STRING`,
`stroke-color STRING`, `stroke-width NUMBER`, `rx NUMBER`, `class STRING`.

```dmap
feature_def "chest" {
  glyph {
    rect stroke at -0.5,-0.4 1 x 0.8 stroke-width 0.06
    line stroke from -0.5,0 to 0.5,0
  }
}
```

---

## `feature`

Place a defined feature at a point. Used at the top level, in a `layer`,
or nested in a `room` / `corridor`.

**Context:** top level, inside a `layer`, or inside a `room` / `corridor`.

| Element | Description |
|---------|-------------|
| `feature REF at X,Y [X,Y …]` | *Required.* The feature id (bare name or quoted) and its position — or several, one copy at each. |
| `rotate NUMBER` | Rotation in degrees. |
| `scale NUMBER[:NUMBER]` | Uniform scale, or independent `X:Y`. |
| `id NAME` | A stable handle for revealing it in play (see `secret`). |
| `{ … }` (optional block) | `description`, `dm_notes`, `secret` and/or `id` for this instance. |

```dmap
feature pillar at 4,6 4,12 12,6 12,12
feature hearth at 9,4 rotate 90
feature "stairs-up" at 12,2 scale 1.5

feature pit at 7,7 {
  secret
  dm_notes "Falls 20ft into area 12."
}
```

---

## `layer`

A logical grouping of declarations, optionally `hidden`. A hidden layer is
parsed and validated but skipped by the renderer — useful for DM-only
content or alternate states.

**Context:** top level.

| Child | Description |
|-------|-------------|
| `hidden` | (After the name.) Exclude the layer's contents from rendering. |
| *contents* | Any of: `room`, `corridor`, `slice`, `door`, `window`, `marker`, `text`, `area`, `line_feature`, `exit`, `feature`. |

```dmap
layer "gm_only" hidden {
  marker "Ambush" at 14,8 tag enemy
  text "trap here" at 14,9 description "Pressure plate"
}
```

---

## Shared properties

These appear inside several blocks (noted in each entry above).

### `label`

An on-map text label. Used by `room`, `corridor`, `slice`, `area`, and the
map `title`.

| Modifier | Description |
|----------|-------------|
| `at X,Y` | Absolute position. |
| `align ALIGN_V ALIGN_H` | Anchor within the parent: vertical `top`/`middle`/`bottom`, horizontal `left`/`center`/`right`. |
| `size NUMBER` | Size multiplier. |
| `rotate NUMBER` | Rotation in degrees. |

```dmap
label "Great Hall" align top center size 1.4
```

### `description`

Read-aloud / summary text. Accepts a normal string or a triple-quoted
(`"""`) multi-line string. Surfaced via `data-description`.

```dmap
description """
The pride of Cael Voren. Vaulted ceiling lost to gloom.
"""
```

### `dm_notes`

GM-only text (traps, secrets, hooks). Same string forms as `description`;
surfaced via `data-dm-notes` and stripped from the fogged players' view.

```dmap
dm_notes "The third flagstone triggers a dart trap (DC 14)."
```

### `secret`

A bare flag marking an element GM-only: drawn in the full GM view, hidden
from the fogged players' view until the DM reveals it. Valid on a
`feature_def` (every instance of the type — core.dmap's traps), a `feature`
instance (inside its block), a `text`, an `area`, a `line_feature`, a
`marker`, an `exit`, and a `door` (where "revealed" means found).

A play session keeps the DM's reveal list, keyed by the element's `id` if it
has one (`feature pit-trap at 3,3 id pit_1`), else by where it sits
(`room.crypt/feature@3,3`). A room's context lists its secrets with their
keys under `dm_only.secrets`; the campaign contract's
`POST …/secrets {key, revealed}` shows or hides one. Content in a `hidden`
layer is GM-only outright and not revealable.

```dmap
exit at 3,4 { to "vault" at 2,2  secret }
feature pit-trap at 7,7 id pit_1
text "The eyes follow you" at 5,5 secret
```
