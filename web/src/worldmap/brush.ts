import type { GridView } from "./api";
import type { Point } from "./crs";
import { TERRAIN_OF_LETTER, cellCentre } from "./fog";

/** The terrain classes in the server's order (`delve.maps.geo.terrain.TERRAIN_CLASSES`), for the brush's picker. */
export const TERRAIN_CLASSES = Object.values(TERRAIN_OF_LETTER);

/** Each class's letter in the map's `terrain` string. */
export const LETTER_OF_TERRAIN: Record<string, string> = Object.fromEntries(
  Object.entries(TERRAIN_OF_LETTER).map(([letter, terrainClass]) => [terrainClass, letter]),
);

/** How far a cell's corners are from its centre: a point further than this from every centre is off the grid. */
const circumradius = (grid: GridView) => (grid.kind === "square" ? grid.size_km / Math.SQRT2 : grid.size_km / Math.sqrt(3));

/**
 * The cells under a brush of `radiusKm` at `centre`: those whose centre is within the radius, and always the cell the
 * centre is in (the nearest centre, which for hexes is the cell itself), so that radius 0 paints one cell. Sorted.
 */
export function cellsUnder(grid: GridView, centre: Point, radiusKm: number): number[] {
  const [x, y] = centre;
  const [ox, oy] = grid.origin;
  // Rows are at most `size_km` apart and columns `size_km` too, hexes included: look a cell beyond the radius.
  const reach = Math.max(radiusKm, circumradius(grid)) + grid.size_km;
  const rowStep = grid.kind === "hex" && grid.orientation === "pointy" ? (grid.size_km * Math.sqrt(3)) / 2 : grid.size_km;
  const colStep = grid.kind === "hex" && grid.orientation === "flat" ? (grid.size_km * Math.sqrt(3)) / 2 : grid.size_km;
  const cols = [Math.floor((x - ox - reach) / colStep), Math.ceil((x - ox + reach) / colStep)];
  const rows = [Math.floor((y - oy - reach) / rowStep), Math.ceil((y - oy + reach) / rowStep)];
  const cells: number[] = [];
  let nearest = -1;
  let nearestDistance = Infinity;
  for (let row = Math.max(0, rows[0]); row <= Math.min(grid.rows - 1, rows[1]); row++) {
    for (let col = Math.max(0, cols[0]); col <= Math.min(grid.cols - 1, cols[1]); col++) {
      const i = row * grid.cols + col;
      const [cx, cy] = cellCentre(grid, i);
      const distance = Math.hypot(cx - x, cy - y);
      if (distance <= radiusKm) cells.push(i);
      if (distance < nearestDistance) {
        nearest = i;
        nearestDistance = distance;
      }
    }
  }
  if (nearest >= 0 && nearestDistance <= circumradius(grid) && !cells.includes(nearest)) cells.push(nearest);
  return cells.sort((a, b) => a - b);
}

/** `terrain` with `letter` in each of `cells`; a cell off the string is left out. */
export function paint(terrain: string, cells: number[], letter: string): string {
  const letters = terrain.split("");
  for (const i of cells) if (i >= 0 && i < letters.length) letters[i] = letter;
  return letters.join("");
}
