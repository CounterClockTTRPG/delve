import L from "leaflet";
import { describe, expect, it } from "vitest";
import { fromLatLng, kmCrs, mapCrs, niceScale, toLatLng } from "./crs";

describe("kmCrs", () => {
  it("puts the picture's corner pixels at the frame's corners at the picture's own zoom", () => {
    // A 1,000 × 700 px picture of a 500 × 350 km frame: max zoom 2 (⌈log2(1000 / 256)⌉).
    const crs = kmCrs(2, 0.5);
    const topLeft = crs.latLngToPoint(L.latLng(toLatLng([0, 0])), 2);
    const bottomRight = crs.latLngToPoint(L.latLng(toLatLng([500, 350])), 2);
    expect([topLeft.x, topLeft.y]).toEqual([0, 0]);
    expect([bottomRight.x, bottomRight.y]).toEqual([1000, 700]);
    // Each zoom below halves it.
    const half = crs.latLngToPoint(L.latLng(toLatLng([500, 350])), 1);
    expect([half.x, half.y]).toEqual([500, 350]);
  });

  it("keeps lat as y in km, growing down", () => {
    const crs = kmCrs(0, 1);
    const below = crs.latLngToPoint(L.latLng(toLatLng([0, 10])), 0);
    expect(below.y).toBeGreaterThan(0);
    expect(toLatLng([3, 7])).toEqual([7, 3]);
    expect(fromLatLng(L.latLng(7, 3))).toEqual([3, 7]);
  });

  it("gives a map without a picture 1,024 px along its longer side at zoom 2", () => {
    const { crs, maxZoom } = mapCrs({ width_km: 2048, height_km: 512 }, null);
    expect(maxZoom).toBe(2);
    expect(crs.latLngToPoint(L.latLng(toLatLng([2048, 512])), 2).x).toBeCloseTo(1024);
  });

  it("uses the picture's scale and pyramid when there is one", () => {
    const { crs, maxZoom } = mapCrs(
      { width_km: 500, height_km: 350 },
      { width_px: 1000, height_px: 700, km_per_px: 0.5 },
    );
    expect(maxZoom).toBe(2);
    expect(crs.latLngToPoint(L.latLng(toLatLng([500, 350])), 2).x).toBeCloseTo(1000);
  });
});

describe("niceScale", () => {
  it("picks a round length in the map's units that fits", () => {
    // 1 km a pixel: 100 px is 100 km.
    expect(niceScale(1, "km", 120)).toEqual({ length: 100, px: 100 });
    // In miles, 1 km a pixel: 50 miles is 80.5 px.
    const miles = niceScale(1, "miles", 120);
    expect(miles.length).toBe(50);
    expect(miles.px).toBeCloseTo(80.47, 1);
  });
});
