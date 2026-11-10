// Fix-it comments on a module (table voice and fixes Task F2.3): a comment in plain words ("the exit from room 2 to
// room 3 is not yet in place, fix it"), optionally tied to a map, a room, a text or an entity, starts a background job
// that proposes the change. Nothing is saved before Keep, and a kept change is a new revision of the module.
import { apiFetch, postJson, type ConversionStatus, type ConversionStep, type ConversionSteps } from "../api";

export type FixitStatus = "open" | "working" | "review" | "kept" | "rejected" | "failed" | "closed";

/** What a comment is tied to; null for the whole module. */
export type FixitAnchor =
  | { kind: "map"; map: string }
  | { kind: "room"; map: string; node: string }
  | { kind: "text"; text_id: string }
  | { kind: "entity"; entity_kind: string; entity_id: string };

/** A comment's job, as far as the list needs it: its status and where it is. */
export interface FixitJob {
  id: string;
  status: ConversionStatus;
  step: ConversionStep;
  done: number;
  total: number;
  steps: ConversionSteps;
}

export interface FixitComment {
  id: string;
  module_id: string;
  text: string;
  anchor: FixitAnchor | null;
  status: FixitStatus;
  /** The job that acts on it; null while it waits for one. */
  conversion_id: string | null;
  /** The revision it was read on, or (kept) the revision it made. */
  revision: number | null;
  /** Why it failed. */
  error: string | null;
  author: string;
  created_at: string;
  updated_at: string;
  job: FixitJob | null;
}

export interface FixitTextChange {
  id: string;
  title: string;
  /** Null for a text the change adds, or (`after`) removes. */
  before: string | null;
  after: string | null;
}

export interface FixitMapChange {
  name: string;
  before: string | null;
  after: string | null;
  /** The map drawn before and after; null when it isn't drawn (a library, or a source that doesn't parse). */
  before_svg: string | null;
  after_svg: string | null;
}

export interface FixitEntity {
  kind: string;
  id: string;
  name: string;
  record: Record<string, unknown>;
  /** A changed entity's record before the change. */
  before?: Record<string, unknown>;
}

/** What Keep would write over the module as it is now. */
export interface FixitReview {
  conversion_id: string;
  module_id: string;
  revision: number | null;
  summary: string;
  /** The module was changed since the job read it: Keep refuses, and the comment can be run again. */
  stale: boolean;
  comments: string[];
  texts: FixitTextChange[];
  maps: FixitMapChange[];
  entities: { added: FixitEntity[]; changed: FixitEntity[]; removed: FixitEntity[] };
}

/** A 409 from Keep: the module changed since the job read it. */
export const STALE = "stale";

const part = encodeURIComponent;

/** Under the module's key, so the module's own refreshes reach them. */
export const fixitsKey = (moduleId: string) => ["module", moduleId, "fixits"] as const;
export const fixitReviewKey = (moduleId: string, conversionId: string) => [...fixitsKey(moduleId), "review", conversionId] as const;

export const listFixits = (moduleId: string) => apiFetch<FixitComment[]>(`/api/modules/${part(moduleId)}/fixits`);

export const sendFixit = (moduleId: string, text: string, anchor: FixitAnchor | null) =>
  postJson<FixitComment>(`/api/modules/${part(moduleId)}/fixits`, anchor ? { text, anchor } : { text });

export const getFixitReview = (conversionId: string) => apiFetch<FixitReview>(`/api/fixits/${part(conversionId)}/review`);

export const keepFixit = (conversionId: string) => postJson<{ revision: number }>(`/api/fixits/${part(conversionId)}/keep`);

export const rejectFixit = (conversionId: string) => postJson<{ rejected: string }>(`/api/fixits/${part(conversionId)}/reject`);

export const rerunFixit = (commentId: string) => postJson<FixitComment>(`/api/fixit-comments/${part(commentId)}/rerun`);

export const closeFixit = (commentId: string) => postJson<FixitComment>(`/api/fixit-comments/${part(commentId)}/close`);

/** The anchor of a picker's value; null for "" or one that isn't an anchor. */
export function anchorOf(value: string): FixitAnchor | null {
  const [kind, rest = ""] = value.split(/:(.*)/s, 2);
  const slash = rest.indexOf("/");
  const [head, tail] = slash < 0 ? [rest, ""] : [rest.slice(0, slash), rest.slice(slash + 1)];
  if (kind === "map" && rest) return { kind: "map", map: rest };
  if (kind === "room" && head && tail) return { kind: "room", map: head, node: tail };
  if (kind === "text" && rest) return { kind: "text", text_id: rest };
  if (kind === "entity" && head && tail) return { kind: "entity", entity_kind: head, entity_id: tail };
  return null;
}

export type DiffLine = { kind: "same" | "added" | "removed"; text: string };

/** The lines of `before` and `after`, each kept, added or removed: the longest common subsequence of their lines. */
export function lineDiff(before: string | null, after: string | null): DiffLine[] {
  const a = before === null ? [] : before.split("\n");
  const b = after === null ? [] : after.split("\n");
  const lengths = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lengths[i][j] = a[i] === b[j] ? lengths[i + 1][j + 1] + 1 : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
    }
  }
  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      lines.push({ kind: "same", text: a[i] });
      i++;
      j++;
    } else if (lengths[i + 1][j] >= lengths[i][j + 1]) {
      lines.push({ kind: "removed", text: a[i++] });
    } else {
      lines.push({ kind: "added", text: b[j++] });
    }
  }
  while (i < a.length) lines.push({ kind: "removed", text: a[i++] });
  while (j < b.length) lines.push({ kind: "added", text: b[j++] });
  return lines;
}
