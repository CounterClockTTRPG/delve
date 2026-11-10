You draw a schematic map of a tabletop adventure's dungeon, in the map language described at the end, from the
module's room key. The DM plays on this map; the module's own map is a picture they compare it with afterwards, so the
sketch has to get the rooms and how they connect right, not their exact shapes.

## What to write

One map file for the map `{{name}}`:

- `include "core.dmap"` first, then one `map "<the dungeon's name>" { … }` block with a `grid { … }`, and
  `room_numbers off` (the labels carry the module's own keys).
- **One `room` per key below**, with exactly the name and the label given for it: `room "r12" { … label "12. Guard
  Room" }`. Leave no key out and add no room that has no key.
- **Connect the rooms as the text describes:** a `door between room.A and room.B { … }` where two rooms share a wall,
  or a `corridor` with a door at each end. Give a door the type and state the text gives it (`secret`, `locked`,
  `iron`…). A room the text doesn't connect to anything goes next to the room listed before it, with a door.
- **Lay it out on a grid** in whole cells, as the text suggests: north is up, sizes in the text's units (one cell is
  usually 10 feet in a dungeon). Rooms don't overlap. Every door is on a shared wall or a corridor's end: two rooms
  that share a wall touch exactly (`rect 1,1 6 x 5` and `rect 7,1 4 x 5` share the wall at x = 7).
- Keep it schematic: rooms, corridors and doors. Add a feature from `core.dmap` (`stairs-up`, `stairs-down`,
  `pillar`, `altar`, `statue`, `well`, `chest`…) only where the text names it. No markers, no descriptions, no notes: the text holds those.

Answer with the map only, in one ```dmap fenced block, and nothing else.

## The room key

{{rooms}}

## The map language

{{reference}}
