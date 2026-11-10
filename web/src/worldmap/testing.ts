// Test helpers for the world map: a seat's view as Task 11's `…/world-maps/{name}/view` answers it.
import type { SeatView } from "./api";

/** A 40 × 30 km map of 4 × 3 square cells, the left half known: two places and a road there, the party at Greyhawk. */
export function seatView(overrides: Partial<SeatView> = {}): SeatView {
  return {
    name: "greyhawk-region",
    title: "Greyhawk region",
    units: "miles",
    frame: { width_km: 40, height_km: 30 },
    grid: { kind: "square", size_km: 10, cols: 4, rows: 3, origin: [0, 0], orientation: "pointy" },
    picture: null,
    tiles_version: "v1",
    known: {
      all: false,
      cells: [
        [0, 2],
        [4, 6],
        [8, 10],
      ],
    },
    terrain: "pf..ph..pp..",
    features: [
      {
        id: "greyhawk",
        layer: "places",
        kind: "city",
        name: "Greyhawk",
        description: "The Gem of the Flanaess.",
        geometry: { type: "Point", coordinates: [5, 15] },
        tags: [],
      },
      {
        id: "hardby",
        layer: "places",
        kind: "port",
        name: "Hardby",
        description: "",
        geometry: { type: "Point", coordinates: [15, 25] },
        tags: [],
      },
      {
        id: "old-road",
        layer: "routes",
        kind: "road",
        name: "The old road",
        description: "",
        geometry: {
          type: "LineString",
          coordinates: [
            [5, 15],
            [15, 25],
          ],
        },
        tags: [],
      },
      {
        id: "selintan",
        layer: "water",
        kind: "river",
        name: "Selintan",
        description: "",
        geometry: {
          type: "LineString",
          coordinates: [
            [2, 0],
            [3, 30],
          ],
        },
        tags: [],
      },
    ],
    party: [5, 15],
    journey: {
      mode: "foot",
      to_label: "Hardby",
      points: [
        [5, 15],
        [10, 20],
        [15, 25],
      ],
      done_km: 7,
      km: 14.1,
    },
    ...overrides,
  };
}
