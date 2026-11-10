// The dungeon-map drafts' client functions (plan 7 Task 13): a draft is a map Claude drew from a description or from
// the book's map page, kept or discarded by the organiser. Nothing is saved in the module until a draft is kept.
// Faithful modules (Task 3): any map page or full-page picture of the book can be drawn, for a part, as a new map.
import { deleteJson, postJson, apiFetch, type Conversion, type ConversionWarning } from "../api";
import type { MapDetail } from "../editor/types";

export type MapDraftKind = "dungeon-map" | "book-map";

/** One map of a draft: a level of a book's page (faithful modules Task 4), or a description draft's one map. */
export interface DraftMap {
  name: string;
  /** The page's words for the level ("Ground floor"); a description draft's name. */
  title: string;
  source: string;
  /** The part (a text's id) the level is for; null when Claude named none. */
  part: string | null;
}

/** One open draft: done, and neither kept nor discarded. `source` is null when no map was drawn. */
export interface MapDraft {
  id: string;
  kind: MapDraftKind;
  /** The map it makes, or (a book draft drawn for a map) replaces. */
  name: string;
  source: string | null;
  warnings: ConversionWarning[];
  created_at: string;
  /** The map a book draft replaces once kept; null for a new map, and for a description draft. */
  replaces: string | null;
  /** The part (a text's id) a book draft was drawn for, and the book's picture it was drawn from. */
  part: string | null;
  page: string | null;
  /** Its maps, one per level: `name` and `source` are the first's. Empty when no map was drawn. */
  maps: DraftMap[];
}

/** The ids of the book's pictures a map can be drawn from, as the server's `BOOK_PICTURE`. */
const BOOK_PICTURE = /^(?:map-)?page-(\d+)(?:-\d+)?$/;

/** Whether a map can be drawn from the attachment: a map page of the book, or a full-page picture of it as the
 * conversion describes one. A smaller picture of a page can't. */
export function isBookPicture(attachment: { id: string; type: string; description: string }): boolean {
  const match = BOOK_PICTURE.exec(attachment.id);
  if (!match || !attachment.type.startsWith("image/")) return false;
  return attachment.id.startsWith("map-") || attachment.description.startsWith(`Page ${match[1]}: a map or full-page picture`);
}

/** A 409 from Keep: the draft's rooms don't match its part. */
export interface DraftMismatch {
  error: string;
  problems: string[];
}

const draftsPath = (moduleId: string) => `/api/modules/${encodeURIComponent(moduleId)}/map-drafts`;
const draftPath = (moduleId: string, id: string) => `${draftsPath(moduleId)}/${encodeURIComponent(id)}`;

/** Under the module's key, so a `modules` event's refresh of the module refreshes its drafts too. */
export const mapDraftsKey = (moduleId: string) => ["module", moduleId, "map-drafts"] as const;

/** Draw a map from `description`, named `name` (else after the description): the conversion that draws it. */
export const startMapDraft = (moduleId: string, description: string, name?: string) =>
  postJson<Conversion>(draftsPath(moduleId), { description, ...(name ? { name } : {}) });

/** Draw the map `map` (null for a new map) from the book's picture `page`, with the rooms of the text `part`. */
export const startBookMap = (moduleId: string, map: string | null, page: string, part?: string) =>
  postJson<Conversion>(`${draftsPath(moduleId)}/from-book`, { map, page, ...(part ? { part } : {}) });

/** The module's open drafts, newest first. */
export const listMapDrafts = (moduleId: string) => apiFetch<MapDraft[]>(draftsPath(moduleId));

/** Save the draft in the module: a new map (named `name`, else its own), or over the map it replaces. `force` keeps
 * a draft whose rooms don't match its part. */
export const keepMapDraft = (moduleId: string, id: string, name?: string, force = false) =>
  postJson<MapDetail>(`${draftPath(moduleId, id)}/keep`, { ...(name ? { name } : {}), ...(force ? { force } : {}) });

export const discardMapDraft = (moduleId: string, id: string) => deleteJson(draftPath(moduleId, id));
