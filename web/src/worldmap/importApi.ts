import { apiFetch, postJson, putJson, type Conversion } from "../api";
import type { Point } from "./crs";
import { basePath, ownerId, type WorldMapDoc, type WorldMapOwner } from "./editorApi";

/** A world map as the organiser lists it: in review until its reading is accepted. */
export interface WorldMapRow {
  name: string;
  title: string;
  status: "ready" | "review";
  source: string;
  /** Whether it was read from a picture, which can be downloaded. */
  picture: boolean;
}

/** One colour of the picture: its cells, Claude's suggestion, and the terrain the organiser gave it, or `outside`. */
export interface ClusterReading {
  id: number;
  colour: [number, number, number];
  cells: number[];
  suggestion: string | null;
  terrain: string | null;
}

/** A doubtful reading (`delve.maps.geo.reading.review.Doubt`). `ref` is the feature it is about, a cluster's id, or
 * `cell:<index>`; `data.at` is where it is, in km. */
export interface Doubt {
  id: string;
  kind: string;
  ref: string;
  message: string;
  reading: string;
  alternatives: string[];
  resolved: boolean;
  choice?: string | null;
  data?: { at?: Point } & Record<string, unknown>;
}

/** A map's reading (`Reading.to_dict()`), as `GET …/world-maps/{name}` answers it while the map is in review. */
export interface Reading {
  clusters: ClusterReading[];
  doubts: Doubt[];
}

/** A cluster mapped to it is the frame, the legend or the margin: no terrain, and mapped all the same. */
export const OUTSIDE = "outside";

/** What the party knows at the start: everything, nothing, some regions, or an area drawn as a ring in km. */
export type StartHow = "everything" | "nothing" | "regions" | "area";

/** The picture's key: its grid and what one cell is; with no grid, two points on the picture (px) and their distance. */
export interface PictureKey {
  name: string;
  title: string;
  cell: "hex" | "square" | "none";
  distance: number;
  units: "km" | "miles";
  points?: [Point, Point];
}

/** A GeoJSON import; without `width_km` or `known`, a document that isn't in km answers 422 `needs: "scale"`. */
export interface GeojsonImport {
  name: string;
  title: string;
  document: unknown;
  mapping?: { name?: string; kind?: string; values?: Record<string, string> };
  width_km?: number;
  known?: { from: string; to: string; distance: number; units: "km" | "miles" };
}

/** The 422 of a GeoJSON import that needs its size: the properties and kinds found, for the mapping step. */
export interface NeedsScale {
  error: string;
  needs: "scale";
  properties: string[];
  kinds: string[];
}

const mapPath = (owner: WorldMapOwner, name: string) => `${basePath(owner)}/${encodeURIComponent(name)}`;

/** The review's route for a map: `/world-maps/:owner/:ownerId/:name/review`. */
export function reviewPath(owner: WorldMapOwner, name: string): string {
  return `/world-maps/${owner.kind}/${encodeURIComponent(ownerId(owner))}/${encodeURIComponent(name)}/review`;
}

/** The editor's route for a map. */
export function editorPath(owner: WorldMapOwner, name: string): string {
  return reviewPath(owner, name).replace(/\/review$/, "");
}

/** A campaign's list sits under its world, so that a `world` event reads it again; a setting's under the setting, so
 * that a `setting` event does. */
export const worldMapsKey = (owner: WorldMapOwner) =>
  owner.kind === "module"
    ? ["module", owner.moduleId, "world-maps"]
    : owner.kind === "campaign"
      ? ["campaign", owner.campaignId, "world", "organiser-maps"]
      : ["setting", owner.settingId, "world-maps"];

/** Every world map of the owner, those in review too: the organiser's list, never a seat's. */
export const listWorldMaps = (owner: WorldMapOwner) =>
  apiFetch<WorldMapRow[]>(
    owner.kind === "campaign"
      ? `/api/campaigns/${encodeURIComponent(owner.campaignId)}/organiser/world-maps`
      : basePath(owner),
  );

export const importGeojson = (owner: WorldMapOwner, body: GeojsonImport) =>
  postJson<WorldMapDoc>(`${basePath(owner)}/geojson`, body);

/** Starts reading a picture in the background; the body is the picture itself, its own type. */
export function readPicture(owner: WorldMapOwner, file: Blob, key: PictureKey): Promise<Conversion> {
  const query = new URLSearchParams({ [`${owner.kind}_id`]: ownerId(owner) });
  query.set("name", key.name);
  query.set("title", key.title);
  query.set("cell", key.cell);
  query.set("distance", String(key.distance));
  query.set("units", key.units);
  if (key.points) query.set("points", key.points.flat().map((v) => String(Math.round(v))).join(","));
  return apiFetch<Conversion>(`/api/conversions/worldmap?${query}`, {
    method: "POST",
    headers: { "Content-Type": file.type },
    body: file,
  });
}

export const review = (
  owner: WorldMapOwner,
  name: string,
  body: { clusters?: Record<string, string>; decisions?: Record<string, string>; kinds?: Record<string, string> },
) => postJson<WorldMapDoc>(`${mapPath(owner, name)}/review`, body);

/** The map becomes ready; 422 while a colour has no terrain. */
export const accept = (owner: WorldMapOwner, name: string) => postJson<WorldMapDoc>(`${mapPath(owner, name)}/accept`);

export const setKnowledge = (
  campaignId: string,
  name: string,
  body: { how: StartHow; regions?: string[]; ring?: Point[] },
) => putJson<unknown>(`${mapPath({ kind: "campaign", campaignId }, name)}/knowledge`, body);

/** A module's ready map becomes the setting's own copy: 409 for a name the setting has, 422 for a map in review. */
export const copyToSetting = (settingId: string, body: { module_id: string; name: string; as_name?: string }) =>
  postJson<WorldMapDoc>(`${basePath({ kind: "setting", settingId })}/copy`, body);
