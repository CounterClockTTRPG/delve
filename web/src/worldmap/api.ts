import { apiFetch } from "../api";
import type { Point } from "./crs";

/** A world map as a seat may list it: only the maps the party knows something of. */
export interface WorldMapEntry {
  name: string;
  title: string;
}

export type Units = "km" | "miles";

export interface FrameView {
  width_km: number;
  height_km: number;
  units: Units;
}

/** The terrain grid (`delve.maps.geo.model.Grid`): `size_km` is the distance between two neighbouring cells' centres
 * in a row. */
export interface GridView {
  kind: "hex" | "square";
  size_km: number;
  cols: number;
  rows: number;
  origin: Point;
  orientation: "pointy" | "flat";
}

/** The map's picture, as far as the browser needs it to lay the tiles; the seat's view never names its id. */
export interface PictureView {
  width_px: number;
  height_px: number;
  km_per_px: number;
  max_zoom?: number;
}

export type Geometry =
  | { type: "Point"; coordinates: Point }
  | { type: "LineString"; coordinates: Point[] }
  | { type: "MultiLineString"; coordinates: Point[][] }
  | { type: "Polygon"; coordinates: Point[][] }
  | { type: "MultiPolygon"; coordinates: Point[][][] };

export type Layer = "places" | "routes" | "water" | "regions";

/** A feature as a seat sees it: within the known area, never hidden, without the DM's notes. */
export interface GeoFeatureView {
  id: string;
  layer: Layer;
  kind: string;
  name: string;
  description: string;
  geometry: Geometry;
  tags: string[];
}

/** The party's journey; in the seat's view its line is cut to the known area, and `to_label` is null while the place
 * isn't known. */
export interface JourneyView {
  mode: string;
  to_label: string | null;
  points: Point[];
  done_km: number;
  km: number;
}

/** `GET …/world-maps/{name}/view`: what the party knows of a world map, cut on the server (plan 7, Task 4). */
export interface SeatView {
  name: string;
  title: string;
  units: Units;
  /** The size alone: the map's units are `units`. */
  frame: Pick<FrameView, "width_km" | "height_km">;
  grid: GridView;
  picture: PictureView | null;
  tiles_version: string;
  /** The known cells as runs `[[start, stop), …]`; `all` when the party knows the whole map. */
  known: { all: boolean; cells: [number, number][] };
  /** One letter a cell, `.` where nothing is known. */
  terrain: string;
  features: GeoFeatureView[];
  party: Point | null;
  journey: JourneyView | null;
}

/** `GET …/world-maps/{name}/dm-view`: the whole map, for the organiser. */
export interface DmView extends Omit<SeatView, "features" | "picture"> {
  features: (GeoFeatureView & { dm_notes: string; hidden: boolean; known: boolean })[];
  picture: (PictureView & { id: string }) | null;
}

const campaignPath = (id: string) => `/api/campaigns/${encodeURIComponent(id)}`;
const mapPath = (id: string, name: string) => `${campaignPath(id)}/world-maps/${encodeURIComponent(name)}`;

export const listWorldMaps = (id: string) => apiFetch<WorldMapEntry[]>(`${campaignPath(id)}/world-maps`);
export const getSeatView = (id: string, name: string) => apiFetch<SeatView>(`${mapPath(id, name)}/view`);
export const getDmView = (id: string, name: string) => apiFetch<DmView>(`${mapPath(id, name)}/dm-view`);

/** Leaflet's URL template for the seat's fogged tiles; `version` (the view's `tiles_version`) reads new ones once the
 * party knows more. */
export const seatTileUrl = (id: string, name: string, version: string) =>
  `${mapPath(id, name)}/tiles/{z}/{x}/{y}?v=${encodeURIComponent(version)}`;

/** Leaflet's URL template for a picture's own tiles, unfogged: the organiser's. */
export const pictureTileUrl = (pictureId: string) =>
  `/api/world-pictures/${encodeURIComponent(pictureId)}/tiles/{z}/{x}/{y}`;
