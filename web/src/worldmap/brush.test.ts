import { describe, expect, it } from "vitest";
import type { GridView } from "./api";
import { LETTER_OF_TERRAIN, cellsUnder, paint } from "./brush";

const squares: GridView = { kind: "square", size_km: 10, cols: 4, rows: 3, origin: [0, 0], orientation: "pointy" };
const hexes: GridView = { kind: "hex", size_km: 10, cols: 5, rows: 5, origin: [0, 0], orientation: "pointy" };

describe("cellsUnder", () => {
  it("is the one cell under the brush at radius 0", () => {
    expect(cellsUnder(squares, [15, 15], 0)).toEqual([5]);
    expect(cellsUnder(squares, [1, 29], 0)).toEqual([8]);
  });

  it("takes the cells whose centre is within the radius", () => {
    // From the corner of cells 0, 1, 4 and 5: their centres are √50 ≈ 7.1 km away.
    expect(cellsUnder(squares, [10, 10], 7.5)).toEqual([0, 1, 4, 5]);
    expect(cellsUnder(squares, [15, 15], 10)).toEqual([1, 4, 5, 6, 9]);
  });

  it("finds a hex by its nearest centre, the odd rows offset", () => {
    // Row 1 of pointy hexes is offset by half a cell: its first centre is at x = 10.
    const r = 10 / Math.sqrt(3);
    expect(cellsUnder(hexes, [10, r + 1.5 * r], 0)).toEqual([5]);
    expect(cellsUnder(hexes, [5, r], 0)).toEqual([0]);
  });

  it("is nothing off the grid", () => {
    expect(cellsUnder(squares, [100, 100], 0)).toEqual([]);
    expect(cellsUnder(squares, [-30, 5], 5)).toEqual([]);
  });
});

describe("paint", () => {
  it("changes only the brushed cells", () => {
    expect(paint("pppppppppppp", [1, 5, 6], "f")).toBe("pfpppffppppp");
    expect(paint("pf..ph..pp..", [2, 11], LETTER_OF_TERRAIN.mountain)).toBe("pfm.ph..pp.m");
  });

  it("ignores a cell off the string", () => {
    expect(paint("pp", [5, -1], "f")).toBe("pp");
  });
});
