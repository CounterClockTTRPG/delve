import type { GridView } from "./api";
import type { Point } from "./crs";

/** The cells of the server's runs, `[[start, stop), …]` (`WorldKnowledge.to_dict`). */
export function knownCells(runs: [number, number][]): Set<number> {
  const cells = new Set<number>();
  for (const [start, stop] of runs) for (let i = start; i < stop; i++) cells.add(i);
  return cells;
}

const SQRT3 = Math.sqrt(3);

/** A cell's centre, as `delve.maps.geo.grid.cell_centre`: pointy hexes offset their odd rows, flat ones their odd
 * columns. */
export function cellCentre(grid: GridView, i: number): Point {
  const col = i % grid.cols;
  const row = Math.floor(i / grid.cols);
  const [ox, oy] = grid.origin;
  const s = grid.size_km;
  if (grid.kind === "square") return [ox + (col + 0.5) * s, oy + (row + 0.5) * s];
  const r = s / SQRT3;
  if (grid.orientation === "pointy") return [ox + s * (col + 0.5 + 0.5 * (row & 1)), oy + r + 1.5 * r * row];
  return [ox + r + 1.5 * r * col, oy + s * (row + 0.5 + 0.5 * (col & 1))];
}

/** A cell's outline, a closed ring, as `delve.maps.geo.grid.cell_polygon`. */
export function cellPolygon(grid: GridView, i: number): Point[] {
  const [cx, cy] = cellCentre(grid, i);
  let ring: Point[];
  if (grid.kind === "square") {
    const h = grid.size_km / 2;
    ring = [
      [cx - h, cy - h],
      [cx + h, cy - h],
      [cx + h, cy + h],
      [cx - h, cy + h],
    ];
  } else {
    const r = grid.size_km / SQRT3;
    const start = grid.orientation === "pointy" ? 30 : 0;
    ring = Array.from({ length: 6 }, (_, k) => {
      const angle = ((start + 60 * k) * Math.PI) / 180;
      return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)] as Point;
    });
  }
  return [...ring, ring[0]];
}

/** The server's terrain letters (`delve.maps.geo.terrain.TERRAIN_LETTERS`); `.` is no terrain. */
export const TERRAIN_OF_LETTER: Record<string, string> = {
  p: "plains",
  f: "forest",
  h: "hills",
  m: "mountain",
  s: "swamp",
  d: "desert",
  a: "arctic",
  j: "jungle",
  u: "urban",
  w: "sea",
  l: "lake",
  x: "impassable",
};

/** Delve's colour per terrain class (`delve.maps.geo.terrain.TERRAIN_COLOURS`). */
export const TERRAIN_COLOURS: Record<string, string> = {
  plains: "#c9b870",
  forest: "#2d5a2d",
  hills: "#8a7350",
  mountain: "#6e6e6e",
  swamp: "#4a6b3a",
  desert: "#d4a25a",
  arctic: "#dcdcd2",
  jungle: "#2d5a3a",
  urban: "#9a8a7a",
  sea: "#2d5f8f",
  lake: "#3a6da3",
  impassable: "#3a3030",
};

/** The fog's colour, the tiles' `FOG` (`delve.maps.geo.tiles`). */
export const FOG = "#d8cfbd";

/** A 1 × 1 PNG of `FOG`, for the tiles the server doesn't send: a `data:` picture, which the CSP allows. */
export const FOG_TILE =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mO4cX4vAATnAmVKEFdwAAAAAElFTkSuQmCC";

/** The known cells' outlines grouped by terrain class, one multi-polygon each; an unknown or unread cell is left out. */
export function terrainAreas(grid: GridView, terrain: string, known: Set<number>): Record<string, Point[][]> {
  const areas: Record<string, Point[][]> = {};
  for (const i of known) {
    const terrainClass = TERRAIN_OF_LETTER[terrain[i] ?? "."];
    if (!terrainClass) continue;
    (areas[terrainClass] ??= []).push(cellPolygon(grid, i));
  }
  return areas;
}
