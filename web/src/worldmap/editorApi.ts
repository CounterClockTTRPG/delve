import { apiFetch, deleteJson, putJson } from "../api";
import type { FrameView, Geometry, GridView, Layer } from "./api";

/** Whose world map it is: a module's (its source), a campaign's own copy, or a setting's on this install. */
export type WorldMapOwner =
  | { kind: "module"; moduleId: string }
  | { kind: "campaign"; campaignId: string }
  | { kind: "setting"; settingId: string };

/** The `owner` segment of the editor's route, `/world-maps/:owner/:ownerId/:name`, as an owner. */
export function ownerOf(kind: string | undefined, id: string | undefined): WorldMapOwner | null {
  if (!id) return null;
  if (kind === "module") return { kind: "module", moduleId: id };
  if (kind === "campaign") return { kind: "campaign", campaignId: id };
  if (kind === "setting") return { kind: "setting", settingId: id };
  return null;
}

/** The owner's id, whatever its kind. */
export function ownerId(owner: WorldMapOwner): string {
  return owner.kind === "module" ? owner.moduleId : owner.kind === "campaign" ? owner.campaignId : owner.settingId;
}

/** The map's picture as the document names it (`delve.maps.geo.model.PictureRef`). */
export interface PictureRef {
  id: string;
  width_px: number;
  height_px: number;
  km_per_px: number;
  asset: string | null;
}

/** A feature of the Delve document, the DM's whole of it: its `properties` beyond these are its `props` (a river's
 * `navigable_km` and `barrier`, a route's `surface`, a reading's `doubt`). */
export interface GeoDocFeature {
  type: "Feature";
  id: string;
  geometry: Geometry;
  properties: {
    layer: Layer;
    kind: string;
    name: string;
    description: string;
    dm_notes: string;
    tags: string[];
    hidden: boolean;
    [prop: string]: unknown;
  };
}

/** The Delve GeoJSON document (`delve.maps.geo.geojson.to_geojson`): km from the top left, y growing down. */
export interface GeoDocument {
  type: "FeatureCollection";
  delve: {
    version: number;
    frame: FrameView;
    grid: GridView;
    /** One letter a cell, row-major; `.` is no terrain. */
    terrain: string;
    picture: PictureRef | null;
  };
  features: GeoDocFeature[];
}

/** `GET …/world-maps/{name}`: a world map as the organiser edits it (plan 7, Task 11). */
export interface WorldMapDoc {
  name: string;
  title: string;
  source: string;
  status: "ready" | "review";
  geo: GeoDocument;
  picture: string | null;
  knowledge: unknown;
  reading: unknown;
}

const OWNER_PATHS = { module: "modules", campaign: "campaigns", setting: "settings" } as const;

/** `/api/{modules|campaigns|settings}/{id}/world-maps`. */
export function basePath(owner: WorldMapOwner): string {
  return `/api/${OWNER_PATHS[owner.kind]}/${encodeURIComponent(ownerId(owner))}/world-maps`;
}

const mapPath = (owner: WorldMapOwner, name: string) => `${basePath(owner)}/${encodeURIComponent(name)}`;

export const worldMapKey = (owner: WorldMapOwner, name: string) => ["world-map", owner.kind, ownerId(owner), name] as const;

export const getWorldMap = (owner: WorldMapOwner, name: string) => apiFetch<WorldMapDoc>(mapPath(owner, name));

/** Saves the map; the server's answer holds what it derived (the water cells of a reshaped lake or sea). A document
 * that doesn't hold together is 422 `{error, problems}`. */
export const putWorldMap = (owner: WorldMapOwner, name: string, body: { title: string; geo: GeoDocument }) =>
  putJson<WorldMapDoc>(mapPath(owner, name), body);

export const deleteWorldMap = (owner: WorldMapOwner, name: string) => deleteJson(mapPath(owner, name));

/** The Delve document with a polygon per terrain cell, for QGIS, as an attachment. */
export const exportUrl = (owner: WorldMapOwner, name: string) => `${mapPath(owner, name)}/export.geojson`;

/** The original picture the map was read from, as an attachment. */
export const pictureUrl = (owner: WorldMapOwner, name: string) => `${mapPath(owner, name)}/picture`;

/** Where the editor's Back goes: the module's page, the campaign's, or the setting's Maps tab. */
export const ownerPage = (owner: WorldMapOwner) =>
  owner.kind === "module"
    ? `/modules/${encodeURIComponent(owner.moduleId)}`
    : owner.kind === "campaign"
      ? `/campaigns/${encodeURIComponent(owner.campaignId)}`
      : `/settings/${encodeURIComponent(owner.settingId)}?tab=maps`;
