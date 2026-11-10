import { describe, expect, it } from "vitest";
import { cellCentre, cellPolygon, knownCells, terrainAreas } from "./fog";
import type { GridView } from "./api";

const square: GridView = { kind: "square", size_km: 10, cols: 4, rows: 3, origin: [0, 0], orientation: "pointy" };

describe("knownCells", () => {
  it("decodes the server's runs, [start, stop)", () => {
    expect(
      [
        ...knownCells([
          [1, 4],
          [7, 8],
        ]),
      ].sort((a, b) => a - b),
    ).toEqual([1, 2, 3, 7]);
    expect(knownCells([]).size).toBe(0);
  });
});

describe("cellPolygon", () => {
  it("draws a square cell as the server does, a closed ring", () => {
    expect(cellPolygon(square, 5)).toEqual([
      [10, 10],
      [20, 10],
      [20, 20],
      [10, 20],
      [10, 10],
    ]);
  });

  it("offsets the odd rows of pointy hexes, and the odd columns of flat ones", () => {
    const pointy: GridView = { ...square, kind: "hex", orientation: "pointy" };
    const r = 10 / Math.sqrt(3);
    expect(cellCentre(pointy, 0)).toEqual([5, r]);
    const [x, y] = cellCentre(pointy, 4); // row 1, column 0
    expect(x).toBeCloseTo(10);
    expect(y).toBeCloseTo(2.5 * r);
    const flat: GridView = { ...square, kind: "hex", orientation: "flat" };
    const [fx, fy] = cellCentre(flat, 1); // row 0, column 1
    expect(fx).toBeCloseTo(2.5 * r);
    expect(fy).toBeCloseTo(10);
    const ring = cellPolygon(pointy, 0);
    expect(ring).toHaveLength(7);
    expect(ring[0]).toEqual(ring[6]);
  });
});

describe("terrainAreas", () => {
  it("groups the known cells by their terrain, and leaves out the unknown ones", () => {
    const areas = terrainAreas(square, "pf.pwwww.ppf", knownCells([[0, 12]]));
    expect(Object.keys(areas).sort()).toEqual(["forest", "plains", "sea"]);
    expect(areas.plains).toHaveLength(4);
    expect(areas.sea).toHaveLength(4);
    const fewer = terrainAreas(square, "pf.pwwww.ppf", knownCells([[0, 2]]));
    expect(Object.keys(fewer).sort()).toEqual(["forest", "plains"]);
  });
});
