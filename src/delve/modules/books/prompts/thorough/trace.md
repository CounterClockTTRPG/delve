PIECE: {piece}

# Tracing the book's maps: the shared brief

You trace maps from the book into Delve's map language (`.dmap`). The owner wants each map **faithful to the book's
map**: the rooms where the book puts them, their sizes and shapes as near as you can, the corridors, doors, secret
doors and stairs the book shows, and its room numbers. **Never invent**: what you can't read on the scan is a doubt,
not a guess drawn as fact.

Your maps (each a map of `parts.json`, with the part it belongs to):

{maps}

- The book's map page, a 200 dpi scan: `scan/p-NNN.png` (the page given for the map). When the page holds several
  maps, yours is the drawing under its `level` words in `parts.json`.
- The map's part: its text `draft/<part id>.md` (or `clean/<part id>.md` when it is there), for reading what a room
  holds: stairs, pools, pillars, secret doors, where the stairs go. Its keys, one per line: `keys/<part id>.txt`
  (gathered from the text and from the book's OCR, so it can hold a stray or miss one; **the map's own numbers are the
  truth**).
- Write your output to `maps/`: `<map name>.dmap`, its render `<map name>.svg` and `<map name>.png` (`{qa} mapcheck`
  draws them), and `<map name>.exits.json` (below). Nothing else goes in `maps/`: rotated scans, tiles and trials go
  in `work/{piece}/`.
- Finished, reviewed maps from earlier modules to read before you start (one or two): `ref/*.dmap`.
- The map language: `ref/dsl.md`, `ref/dsl-map.md`, `ref/dsl-geometry.md`, `ref/dsl-features.md`,
  `ref/dsl-tooling.md` (`ref/dsl-reference.md` has every statement). Built-in features (only these exist): altar,
  barrel, bath, bed, bookshelf, brazier, bridge, ceiling-trapdoor, chair, chest, crate, dart-trap, desk,
  direction-sign, fire-trap, floor-trapdoor, fountain, hearth, marker, pillar, pit, pit-trap, portcullis, rubble,
  shock-trap, slime-trap, spear-trap, spiral-stairs, stairs-down, stairs-left, stairs-right, stairs-spiral, stairs-up,
  statue, stove, table, trap, wall-glyph, wardrobe, water, well. Anything else goes in a room `description`.

## Reading the map

- **Read the scale printed on YOUR map first** ("1 square = 10 feet", "1" = 30 feet", a scale bar). The scan is 200 px
  per inch, so 1" = 30 feet makes 10 feet ≈ 66.7 px and 5 feet ≈ 33.3 px; with a printed grid, measure the squares on
  the scan. Check the scale against a room the text gives a size for.
- **One `.dmap` cell = 5 feet** (`units feet 5`, `cell 16 px` in the grid block), so rooms keep their shapes; when the
  book prints a grid of 10-foot squares, a square is two cells. Coordinates may be halves (x.5) where a wall needs it.
- **A map can be drawn rotated** (the compass not pointing up, the walls off the page's axes). Measure the main wall
  angle (the long straight walls of the biggest built rooms), then rotate the scan so those walls are axis-aligned:
  `{qa} rotate scan/p-NNN.png work/{piece}/<map name>-rot.png <degrees>` (positive = counter-clockwise). Trace on the
  rotated image. Walls in other directions become polygons. Say the rotation in the map's first comment.
- **Colours and fills** are the book's way of telling areas apart: they don't need drawing. Patterned fill (cobbles,
  dots) is rubble: a `rubble` feature or a description. Water is `water`.
- **Symbols on the book's map**: read the map's legend when it prints one. Commonly: a small rectangle across a wall is
  a door; an `S` beside a wall (often hatched) is a secret door (`type secret`); hatched stripes or steps are stairs;
  letters and numbers beside stairs, chutes, shafts and pits are the book's level connections: their text says where
  they go.
- Natural caves: `line_style organic` on the room.
- **The renderer**: `classic-bw` for most books; `oldschool-blue` when the book's maps are the old blue-ink plans
  (blue lines, white rooms on blue); `floorplan` for a building's floor plans. The page decides it, not the level: the
  maps cut from one page (the decks of a ship, the floors of a house) all use the renderer its ink calls for, so the
  levels of one plate look alike.

## How to work

1. **Look at the whole map first** (Read a downscaled copy). Find the numbers, the scale, the main wall angle.
2. Rotate when needed; then **calibrate a grid** on the scan with
   `{qa} tile <scan or rotated.png> work/{piece}/<tile>.png X0 Y0 X1 Y1 <px of 5 ft> OX OY 1400`
   (crops squares X0..X1 × Y0..Y1 of a grid of `<px>` squares whose square (0,0) starts at pixel (OX,OY), numbers every
   line, scales to 1400 px). Choose OX,OY so the main walls (or the printed grid) sit on grid lines. One grid square =
   one `.dmap` cell.
3. **Cut the map into tiles** of about 15–20 squares and read each one at full size; write what you read straight
   into the `.dmap` as you go, so nothing is lost if you run long.
4. **Rooms**: `rect` where the room is rectangular (on the rotated image), `polygon` for any other shape, `circle` for
   round rooms, `line_style organic` for natural caves. Corridors are rooms too (narrow `rect`/`polygon` rooms, named
   `c_<n>`), or `corridor` for straight built passages. Rooms must not overlap (adjoining walls are fine).
5. **Doors**: `door between room.A and room.B { type wooden }` where two rooms share a wall; `door at X,Y { connects
   room.A, room.B type … }` otherwise. Types: wooden, iron, stone, secret, concealed, arch, portcullis, open (a bare
   opening: use it where a passage simply runs into a room), double, one-way. Every room must be reachable from the
   map's entry where the book's map allows it (a sealed area the book seals stays sealed: say so in your doubts).
6. **Room names and labels: this is how Delve links the text to the map.** Each numbered room is named after its key
   in lower case, with an `r` before a key that starts with a digit (a name can't start with one): key `12` is
   `room "r12"`, `33a` is `room "r33a"`, `W211` is `room "w211"`, `WB05` is `room "wb05"`. Its label is the key **as
   printed** (`label "12" at X,Y size 0.6`). Where the book prints the same number in two places, the first is `r12`,
   the others `r12_2`, `r12_3` … with the same label. Unnumbered rooms and corridors get a name of your own (not a key
   of the part's pattern, with or without the `r`) and no label, or the book's own words. Stairs and connections are
   labelled as printed, on a feature or a small room.
7. **Header**: `include "core.dmap"`, then
   `map "<the map's title>" { grid { cell 16 px  units feet 5  bounds W x H }  renderer "classic-bw"  room_numbers off
   party_start "<room>" at X,Y }`; start at the map's arrival (the stairs from the level above, or the entrance from
   outside). First lines: `#` comments naming the source ("Traced from page 10 of the PDF: The House, Ground Floor.
   Rotated 28° clockwise; 1 cell = 5 ft.").
8. **Exits file** `maps/<map name>.exits.json`: a list of every stair, chute, shaft or passage that leaves the map for
   another map of the book: `[{"label": "S4", "at": [x, y], "room": "r18", "to_map": "<map name in parts.json>",
   "to_room": "<the room it arrives in there, when the text says>", "text": "what the book says", "page": n}]`.
   Delve joins the maps with these, so give the exact cell you'd put the exit on, and the label the book prints at
   both ends. An exit to a place the book has no map of (outside, a wilderness) gets no `to_map`. Write `[]` when the
   map has no exits.
9. **Check**: `{qa} mapcheck maps/<map name>.dmap --fix-doors` once after writing doors (it moves `door between` for
   rooms that don't quite share a wall to a placed door), then `{qa} mapcheck maps/<map name>.dmap` after every
   change. Fix every error; fix warnings that point at a real mistake (overlaps, unconnected parts, a label on a
   feature). It draws `maps/<map name>.png`.
10. **Compare your render with the book's map, side by side** (Read both, the scan, rotated as you traced it, and your
    PNG), and fix what differs: missing rooms, wrong sizes, doors in the wrong wall, numbers missing. Do it **at least
    twice**, carefully: the owner will compare them too. Then check that **every number printed on the book's map** is
    a room name, and that every key of `keys/<part id>.txt` has a room or a doubt (`missing-room`, with why); a number
    on the map with no text in the book is a doubt of kind `missing-text`. What on the book's map you left out is a
    doubt of kind `left-out`; a stair whose far end you guessed, `guessed-landing`.

## What to report back

Per map: the files, rooms, doors, how many keyed rooms it carries, the keys it doesn't carry (and why), what on the
book's map you left out. Keep it short. Your doubts go in `doubts/{piece}.json` (see below).
