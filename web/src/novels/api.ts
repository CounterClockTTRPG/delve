// The novels' calls (novelization plan Task 5's routes, `/api/novels/...`), all the owner's: a seat gets 403 on
// every one, a read included. The shapes are `delve.domain.novels.Novel.to_dict`.
import { apiFetch, deleteJson, patchJson, postJson } from "../api";

export type NovelLength = "recap" | "short-story" | "novella";
export const NOVEL_LENGTHS: NovelLength[] = ["recap", "short-story", "novella"];
export type NovelStatus = "writing" | "done" | "failed" | "cancelled";

/** One chapter of the outline; `text` (Markdown, no heading) is null until it is written. */
export interface Chapter {
  title: string;
  summary: string;
  text: string | null;
}

/** A novel of a campaign (with an optional range of sessions, first and last) or of a module at a revision. In the
 * list (`listNovels`) the chapters come without their text. `tone` is `custom` with `custom_tone`, or a play tone. */
export interface Novel {
  id: string;
  title: string;
  campaign_id: string | null;
  module_id: string | null;
  revision: number | null;
  sessions: [number, number] | null;
  length: NovelLength;
  tone: string;
  custom_tone: string;
  language: string;
  instructions: string;
  chapters: Chapter[];
  status: NovelStatus;
  error: string | null;
  conversion_id: string | null;
  cost_usd: number | null;
  created_at: string;
  updated_at: string;
}

/** A novel as the list has it: each chapter says whether it is written, without its text. */
export type ListedNovel = Omit<Novel, "chapters"> & { chapters: { title: string; summary: string; written: boolean }[] };

export interface NovelSource {
  kind: "campaign" | "module";
  id: string;
}

/** What `POST /api/novels` takes. `sessions` is for a campaign (null: all of them), `revision` for a module (null:
 * the latest). */
export interface NovelRequest {
  source: NovelSource["kind"];
  id: string;
  length: NovelLength;
  tone: string;
  custom_tone: string;
  language: string;
  instructions: string;
  sessions: [number, number] | null;
  revision: number | null;
}

const novelPath = (id: string) => `/api/novels/${encodeURIComponent(id)}`;

export const novelKeys = {
  all: ["novels"] as const,
  lists: ["novels", "list"] as const,
  list: (source: NovelSource) => ["novels", "list", source.kind, source.id] as const,
  one: (id: string) => ["novels", "one", id] as const,
};

export const listNovels = (source: NovelSource) =>
  apiFetch<ListedNovel[]>(`/api/novels?${source.kind}_id=${encodeURIComponent(source.id)}`);
export const getNovel = (id: string) => apiFetch<Novel>(novelPath(id));
/** 202 with the novel, its job started; 409 while another job runs, 422 for a bad choice or range. */
export const createNovel = (request: NovelRequest) => postJson<Novel>("/api/novels", request);
export const renameNovel = (id: string, title: string) => patchJson<Novel>(novelPath(id), { title });
/** 409 while it is being written. */
export const deleteNovel = (id: string) => deleteJson(novelPath(id));
/** For a failed or cancelled novel: a new job writes the chapters it lacks. */
export const continueNovel = (id: string) => postJson<Novel>(`${novelPath(id)}/continue`);
export const cancelNovel = (id: string) => postJson<Novel>(`${novelPath(id)}/cancel`);

/** The chapters written so far. */
export const writtenChapters = (novel: Pick<Novel, "chapters">) => novel.chapters.filter((c) => c.text !== null);
