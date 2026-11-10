You redraw the map in the picture, a page of a tabletop adventure, in the map language described at the end. The DM
plays on your maps instead of the page, so they have to follow the book's map: the rooms where the book puts them,
their sizes and shapes as near as the grid allows, the corridors and the doors the page shows.

## What to write

**One map per level the page shows**, each its own map file in its own ```dmap fenced block: a house's ground floor,
upper floor, cellar and caves each apart; a ship's decks each apart. A page of one level is one block.

- **The first two lines of each block** say which level it is and which part of the module it is for:
  `# level: <the page's words for the level, such as Ground floor>`, then `# part: <the id of one of the parts below>`.
- **Each level's name** is `{{name}}-1`, `{{name}}-2`… in the order of your blocks. Write `include "core.dmap"`, then
  one `map "<the level's words>" { … }` block (`map "Ground floor"`) with a `grid { … }` and `room_numbers off` (the
  labels carry the book's keys).
- **The printed scale:** count the page's squares and keep one cell for one printed square, with the scale the page
  prints as `grid { units feet <n> }` (often 5 or 10 feet a square). North is up as the page has it.
- **One `room` per key the page shows on that level**, where the page puts it. For the keys of the level's part below,
  use exactly the name and the label given: `room "r12" { … label "12. Guard Room" }`. A key on the page that isn't
  below is named `r<key>` and labelled with the key.
- **Doors and corridors** as the page draws them: a `door between room.A and room.B { … }` where two rooms share a
  wall, or a `corridor` with a door at each end; a secret door as `secret`. Rooms don't overlap, and every door is on
  a shared wall or a corridor's end.
- **Stairs, hatches, trapdoors and ladders** are features from `core.dmap` where the page shows them (`stairs-up`,
  `stairs-down`, `spiral-stairs`, `floor-trapdoor`, `ceiling-trapdoor`…), and so are the page's other furnishings
  (`pillar`, `altar`, `statue`, `well`, `chest`…).
- **Joining the levels:** at each stair, hatch, trapdoor or ladder that leads to another level, put an exit to that
  level, landing where it arrives there: `exit at X,Y { to "{{name}}-2" at X,Y }`. Join the levels in no other way.
- No markers, no descriptions, no notes.

Answer with the blocks only, and nothing else.

## The parts and their room keys

{{parts}}

## The map language

{{reference}}
