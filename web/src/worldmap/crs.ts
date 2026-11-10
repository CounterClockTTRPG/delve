import L from "leaflet";
import type { FrameView, PictureView } from "./api";

/** A map point in km from the top left: x east, y down, as the server's geo documents hold them. */
export type Point = [number, number];

export const MILES_TO_KM = 1.609344;
/** A map without a picture is this many px along its longer side at its deepest zoom. */
const PLAIN_PX = 1024;
const PLAIN_MAX_ZOOM = 2;
const TILE_SIZE = 256;

/**
 * Leaflet's flat CRS in km: lat is y in km, growing down, and lng is x. At `maxZoom` one screen pixel is `kmPerPx` km,
 * which puts a picture's pixel on a tile pixel at its own deepest zoom; each zoom below halves it.
 */
export function kmCrs(maxZoom: number, kmPerPx: number): L.CRS {
  const s = 2 ** -maxZoom / kmPerPx;
  return L.extend({}, L.CRS.Simple, { transformation: new L.Transformation(s, 0, s, 0) });
}

export const toLatLng = ([x, y]: Point): L.LatLngTuple => [y, x];

export const fromLatLng = (latLng: L.LatLng): Point => [latLng.lng, latLng.lat];

/** The picture's tile pyramid's deepest zoom, as the server cuts it: ⌈log2(longer side / 256)⌉, at least 0. */
export function pictureMaxZoom(picture: PictureView): number {
  if (picture.max_zoom !== undefined) return picture.max_zoom;
  return Math.max(0, Math.ceil(Math.log2(Math.max(picture.width_px, picture.height_px) / TILE_SIZE)));
}

/** The CRS of a map: the picture's scale when it has one, else 1,024 px along the frame's longer side at zoom 2. */
export function mapCrs(
  frame: Pick<FrameView, "width_km" | "height_km">,
  picture: PictureView | null,
): { crs: L.CRS; maxZoom: number; kmPerPx: number } {
  const maxZoom = picture ? pictureMaxZoom(picture) : PLAIN_MAX_ZOOM;
  const kmPerPx = picture ? picture.km_per_px : Math.max(frame.width_km, frame.height_km) / PLAIN_PX;
  return { crs: kmCrs(maxZoom, kmPerPx), maxZoom, kmPerPx };
}

/** The longest round length (1, 2 or 5 × 10ⁿ in the map's units) at most `maxPx` long, and its length in px. */
export function niceScale(kmPerPx: number, units: "km" | "miles", maxPx: number): { length: number; px: number } {
  const unitKm = units === "miles" ? MILES_TO_KM : 1;
  const most = (maxPx * kmPerPx) / unitKm;
  const power = 10 ** Math.floor(Math.log10(most));
  const length = [5, 2, 1].map((step) => step * power).find((candidate) => candidate <= most) ?? power;
  return { length, px: (length * unitKm) / kmPerPx };
}
