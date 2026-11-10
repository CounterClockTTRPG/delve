> Ported from dungml (commit a66a1bb).

# Validation & tooling

Part of the [dungml DSL reference](/docs/dsl).

## Validation

After parsing, the model is checked for semantic errors. Diagnostics
have severity `error` (renderers may still attempt to render but the
result is unreliable) or `warning` (informational; render proceeds).
The editor shows these inline; the CLI surfaces them via
`dmap validate`.

Common diagnostics:

- **unknown feature** — a `feature` references something with no matching
  `feature_def`. If the name is a built-in (e.g. `pillar`), the message
  reminds you to `include "core.dmap"`.
- **non-positive room dimensions** — `rect 0,0 0 x 0`, etc.
- **polygon too small** — fewer than three points (also checked for glyph
  polygons; glyph polylines need at least two).
- **door references unknown room/corridor**.
- **out of bounds** — a position outside `grid.bounds` (warning, not error).
- **overlapping rooms/corridors** — two room/corridor areas intersect
  (warning, not error).

---

## Connectivity graph and pathfinding

A `.dmap` file is geometry on its face, but it also encodes a **graph**:
the *nodes* are rooms and corridors, and the *edges* are doors. A door's
`connects [room.a, corridor.b]` is literally an edge, so a corridor
joining two rooms appears as the two-hop path
`room.a → corridor.b → room.c`. Node ids are the same dotted references
doors use (`room.NAME`, `corridor.NAME`).

`dungml.graph` derives this graph and runs pathfinding as a pure function
of the parsed model — no spatial reasoning required at call sites:

```python
from dungml import parse, build_graph

g = build_graph(parse(open("samples/crypt.dmap").read()))
g.neighbors("room.antechamber")          # [(node_id, edge), ...]
g.incident_edges("room.antechamber")     # the doors of a room
path = g.find_path("room.antechamber", "room.vault")   # shortest BFS route
path.to_dict()  # {found, nodes, doors, steps, length}
```

`find_path` takes optional `passable(edge)` and `node_ok(node)`
predicates, which is how callers express constraints like "only
already-explored rooms" or "skip locked doors". A door whose state is one
of `locked`/`barred`/`stuck`/`sealed` is considered impassable by
`is_blocked`; everything else (open, closed, ajar…) is walk-through.

A door with a single `connects` reference is treated as a **boundary
exit** (an opening to outside the mapped area, or a secret door whose far
side is unmapped) rather than a routable edge.

### Play-sessions (fog-of-war), via MCP

The connectivity graph is static DM-truth. To track a *single
play-through* — which rooms the party has discovered, which doors they've
found, the live state of those doors, and where they are — the MCP server
exposes **play-session** tools that layer this runtime state on top of an
unchanged map:

- `create_session` / `list_sessions` / `get_session` / `delete_session`
- `mark_discovered(node)` — reveal a room/corridor (and its visible doors)
- `mark_door(door, discovered?, state?)` — find a secret door, or open/unlock/lock one
- `set_party_location(node)` — move the party (reveals the node)
- `get_exits(node, mode)` — "what are the ways out of here?"
- `find_path(from, to, mode)` — server-side BFS between two nodes
- `get_known_map()` — the discovered subgraph + the unexplored *frontier*
- `render_session(mode)` — render fog-of-war (explored only) or the full map

`mode` is `discovered` (only explored nodes and found, currently-passable
doors — what the party can actually walk *now*) or `any` (the full
authored topology, ignoring discovery and locks — the DM question "does a
route exist at all?"). `dungml.fog_of_war(dmap, nodes, doors)` does the
pruning that backs `render_session`, returning a valid `DungeonMap` any
renderer can draw.

### Building a map as you go, via MCP

The MCP server can also *grow* a map — start from one room and add space
as the party pushes into it — without the model inventing coordinates.
The structured-authoring tools take a description of *where* relative to
existing geometry and compute the placement server-side, then append a
valid snippet to the source and re-validate (nothing is saved if the edit
would break the map):

- `add_room(name, width, height, direction, anchor, …)` — place a room
  `north`/`south`/`east`/`west` of an existing node. `gap 0` shares a wall
  (one connecting door); `gap > 0` inserts a short corridor. The first room
  uses `position "x,y"` instead of an anchor.
- `add_corridor(name, from_node, to_node, …)` — join two existing nodes
  with a corridor and a door at each end.
- `add_door(between=[a, b] | position+connects, type, state, …)` — add an
  extra, locked, or secret door between existing nodes.

Grid `bounds` grow automatically to fit new geometry. Node names must be
bare identifiers (so doors can reference them as `room.NAME`). Each tool
accepts `discover_in_session` to reveal the new geometry in a play-session
at the same time — the "party as cartographer" flow, where building the
map and discovering it are the same act.

---

## Simplification

Maps drawn with the editor's corridor tool (or generated by another tool)
often carry more nodes than the shape needs. **Simplify** (the editor's
header button, `dmap simplify`, `POST /api/maps/{id}/simplify`) removes
them **without changing what is drawn**:

| Change | What goes |
|---|---|
| straight-through node | a node joining two runs that carry on in a straight line: `run a to m` + `run m to b` → `run a to b` |
| stub inside the corridor | a dead-end run no longer than half the corridor's width, lying inside a straight stretch of it (its floor is already drawn) — this often frees the junction it hung off |
| duplicate node / repeated run / zero-length run / unused node | the redundant declaration |
| straight segments merged | two `segment line`s that continue each other |
| point on a straight wall | a `polygon` vertex between two collinear neighbours, or a repeated vertex |
| straight edges merged | a `boundary` `line to` whose next line edge carries on in the same direction |

Some candidates are deliberately **left alone** and reported with the
reason:

- a stub whose free end has a door or exit at it. The door uses that end
  as the corridor's mouth, and the fog-of-war fade starts there. Tick *Also
  remove stubs that end at a door* (`--door-spurs`, `door_spurs: true`) to
  drop them anyway: the map draws the same, but the door's fade then starts
  at the nearest remaining corridor end;
- a node whose removal would change which corridor end a connected door
  is nearest to (the same fog-fade anchor);
- a repeated or zero-length run at a dead end — it suppresses that end's
  wall cap, so removing it would draw one;
- rooms and zero-width corridors drawn `dashed`, `dotted`, `ruined` or
  `trail`, whose pattern restarts per wall or segment.

Arcs, `rect` and `circle` rooms are never touched. Nodes are local to their
corridor, so dropping one breaks no reference elsewhere. The only visible
side effect: an unpositioned label or the party marker sits at the
*average of the vertices*, which can move when vertices go.

In the editor the result is applied to the buffer, not saved: review it,
Save, or Ctrl+Z to undo. Comments and layout outside the touched lines are
kept; a removed statement's trailing `# comment` goes with it.

```bash
dmap simplify map.dmap --check      # report; exit 1 if anything can go
dmap simplify map.dmap -i           # rewrite in place
dmap simplify map.dmap --json       # change report as JSON
```

```python
from dungml import simplify
result = simplify(source)           # .source, .changes, .stats, .changed
```

---

## CLI and library

```bash
uv run dmap validate samples/cottage.dmap          # diagnostics
uv run dmap render   samples/crypt.dmap -o crypt.svg
uv run dmap renderers                              # list registered renderers
uv run dmap path samples/crypt.dmap room.entry room.crypt   # shortest route
```

The Python entry points live in `packages/dsl`:

```python
from dungml import parse, validate, render

m = parse(open("samples/cottage.dmap").read())
diags = validate(m)
svg = render(m, "floorplan")
```

---

## Worked example: a complete tiny map

```dmap
include "core.dmap"

map "Hermit's Hut" {
  grid { cell 32 px units feet 5 bounds 14 x 10 }
  renderer "floorplan"
}

room "main" {
  rect 2,2 10 x 6
  label "One Room"
  feature hearth at 11,3 rotate 90
  feature bed    at 3,3
  feature table  at 7,5
  feature chair  at 6,5
  feature chair  at 8,5
}

door at 7,8 {
  connects room.main
  type wooden
  state closed
  facing south
}

window at 4,2 { in room.main width 1 }
window at 10,2 { in room.main width 1 }
```

For a feature-by-feature exercise of every construct in the DSL, see
`samples/sunken_library.dmap`.
