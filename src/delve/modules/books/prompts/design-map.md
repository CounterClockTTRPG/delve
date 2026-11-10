You draw the map of a place in a tabletop adventure, in the map language described at the end, from the module's
room key. This is the only map the module has: the DM plays on it and the players see it revealed room by room, so
it should look like the place the text describes, not like a diagram of boxes.

## The place

{{kind}}

## What to write

One map file for the map `{{name}}`:

- `include "core.dmap"` first, then one `map "<the place's name>" { … }` block with a `grid { … }`, a `renderer`
  and `room_numbers off` (the labels carry the module's own keys).
- **One `room` per key below**, with exactly the name and the label given for it: `room "r12" { … label "12. Guard
  Room" }`. Leave no key out and add no room that has no key.
- **Connect the rooms as the text describes:** a `door between room.A and room.B { … }` where two rooms share a wall,
  or a `corridor` with a door at each end; outdoors, an `open` door (a gap) or a path. Give a door the type and state
  the text gives it (`secret`, `locked`, `iron`…). A room the text doesn't connect to anything goes next to the room
  listed before it, with a door.
- **Lay it out on a grid**, as the text suggests: north is up, sizes in the text's units (one cell is usually 10 feet;
  5 feet for a single building). Rooms don't overlap. Every door is on a shared wall or a corridor's end: two rooms
  that share a wall touch exactly.

## Make it look like the place

- **Shapes follow what the room is.** Use `rect` only for built, squared rooms. A cave, a mine gallery, a pit or a
  burrow is a `polygon` of 6 to 12 points or a `boundary`, with `line_style organic`; a tower, a well-chamber or a
  round hut is a `circle`; a hall with an apse, a bay or a bent end is a `polygon` or a `boundary` with an `arc`.
  Vary sizes: a cupboard is one or two cells, a hall twenty. Not every room is a box, and not every corridor straight:
  bend a passage with a second segment where the text says it winds, climbs or turns.
- **The renderer and theme fit the place:** `"oldschool-blue"` for an underground dungeon or a tomb, `"classic-bw"`
  for a cave or a mine (with organic walls), `"hatched"` with `theme paper` for the inside of one building (a manor,
  a chapel, a mill, a tower), and `"classic-bw"` with `theme paper` for anything outdoors: the hatched style draws
  solid rock round every room, which is wrong for open ground.
- **Outdoors and settlements:** the ground is open, not rock, and not one big room. Each building is its own small
  `room`; a yard, a green, a clearing or a quarry floor is a room drawn with `line_style organic` (or `dashed` for a
  fenced yard). The ways between them are not walled passages: a lane is a `corridor` with `width 2` and
  `line_style dashed`, a footpath one with `width 0` and `line_style dotted`, each with an `open` door at both ends.
  Draw what the text names around them: `area` `water` or `swamp` for ponds, meres and marsh, `slice` `river` for a
  stream, `line_feature` `road` for a road, `fence`, `cliff` or `wall` for palisades, scarps and walls.
- **Furniture and terrain the text names:** stairs (`stairs-up`, `stairs-down`), `pillar`, `altar`, `statue`,
  `well`, `chest`, `table`, `bed`, `hearth`, `barrel`, `crate`, `brazier`… from `core.dmap`, placed inside their room; water, a pit or rubble as an
  `area` inside the room. Only what the text names: no decoration it doesn't support.
- **Labels fit:** a room at least 3 cells across and 2 high for its label, or the label placed `at` beside it.
- No markers, no descriptions, no notes: the text holds those.

Answer with the map only, in one ```dmap fenced block, and nothing else.

## The room key

{{rooms}}

## The map language

{{reference}}
