// What a new, empty map opens with (dungml's STARTER_DMAP, routes/ProjectPage.tsx): with no source nothing renders,
// and the drawing tools have nothing to draw on. The map is named after the module's map.

export function starterMap(name: string): string {
  return `# Built-in feature library (pillar, stairs, chest, …). Remove this line
# if you don't use built-in features, or swap it for your own template.
include "core.dmap"

map ${JSON.stringify(name)} {
  grid {
    cell    32 px
    units   feet 5
    bounds  30 x 20
    origin  top-left
  }
  renderer "classic-bw"
  room_numbers off
  background "#CCC"
  corners straight
}

room "main" {
  rect 5,5 10 x 8
  label "Main"
  feature stairs-up at 9,9
}
`;
}
