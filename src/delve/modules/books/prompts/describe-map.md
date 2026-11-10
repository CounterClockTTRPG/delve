You draw the map of a tabletop adventure's dungeon, in the map language described at the end, from the organiser's
description. The DM plays on this map and the players see it revealed room by room: get the rooms and how they
connect right, and make it look like the place described, not like a diagram of boxes.

## What to write

One map file for the map `{{name}}`:

- `include "core.dmap"` first, then one `map "<the dungeon's name>" { … }` block with a `grid { … }`, a
  `renderer` and `room_numbers off` (the labels carry the rooms' keys).
- **The rooms:** as the room key below gives them, when there is one, with exactly the name and the label given for
  each: `room "r12" { … label "12. Guard Room" }`. Leave no key out. Without a room key, invent the rooms the
  description asks for, named `r1`, `r2`… and labelled `1. Guard Room`, `2. …`.
- **Connect the rooms as the description says:** a `door between room.A and room.B { … }` where two rooms share a
  wall, or a `corridor` with a door at each end. Give a door the type and state the text gives it (`secret`,
  `locked`, `iron`…).
- **Lay it out on a grid** in whole cells: north is up, one cell is usually 10 feet. Rooms don't overlap. Every door
  is on a shared wall or a corridor's end: two rooms that share a wall touch exactly (`rect 1,1 6 x 5` and
  `rect 7,1 4 x 5` share the wall at x = 7).
## Make it look like the place

- **Shapes follow what the room is.** Use `rect` only for built, squared rooms. A cave, a mine gallery, a pit or a
  burrow is a `polygon` of 6 to 12 points or a `boundary`, with `line_style organic`; a tower, a well-chamber or a
  round hut is a `circle`; a hall with an apse, a bay or a bent end is a `polygon` or a `boundary` with an `arc`.
  Vary sizes: a cupboard is one or two cells, a hall twenty. Not every room is a box, and not every corridor straight:
  bend a passage with a second segment where the description says it winds, climbs or turns.
- **The renderer and theme fit the place:** `"oldschool-blue"` for an underground dungeon or a tomb, `"classic-bw"`
  for a cave or a mine (with organic walls), `"hatched"` with `theme paper` for buildings, a manor, a village or a
  farm, and the same for an outdoor site.
- **Outdoors and settlements:** the ground is open, not one big room. Each building is its own small `room`; a yard,
  a green, a clearing or a quarry floor is a room drawn with `line_style organic` (or `dashed` for a fenced yard).
  Join them with `line_feature` `road` or `path` lines and `open` doors, and draw what the description or the key names around them:
  `area` `water` or `swamp` for ponds, meres and marsh, `slice` `river` for a stream, `line_feature` `fence`, `cliff`
  or `wall` for palisades, scarps and walls.
- **Furniture and terrain the description or the key names:** stairs (`stairs-up`, `stairs-down`), `pillar`, `altar`, `statue`,
  `well`, `chest`, `table`, `bed`, `hearth`, `barrel`, `crate`, `brazier`… from `core.dmap`, placed inside their room; water, a pit or rubble as an
  `area` inside the room. Only what the description or the key names: no decoration it doesn't support.
- **Labels fit:** a room at least 3 cells across and 2 high for its label, or the label placed `at` beside it.
- No markers, no descriptions, no notes: the text holds those.

Answer with the map only, in one ```dmap fenced block, and nothing else.

## The description

{{description}}

## The room key

{{rooms}}

## The map language

{{reference}}
