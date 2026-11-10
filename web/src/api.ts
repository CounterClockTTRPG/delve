// Every call to the Delve API goes through apiFetch.
import { createContext } from "react";
import type {
  ConnectivityResponse,
  FeatureNamesResponse,
  MapDetail,
  MapRole,
  ParsedMap,
  RenderResponse,
  SimplifyResponse,
} from "./editor/types";
import type { CampaignBanner, Waiting } from "./play/api";
import type { Language } from "./i18n";
import type { TablePerson } from "./profile/TableFaces";

/** The server answered 401: Delve doesn't know this browser, which logs in. The message is the server's, such as
 * "Wrong username or password." for a refused login. */
export class NeedsToken extends Error {
  constructor(message = "needs token") {
    super(message);
    this.name = "NeedsToken";
  }
}

/** Any other non-2xx answer. `body` is the parsed JSON error, e.g. `{error, warnings}`. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public body: { error?: string; warnings?: string[] } & Record<string, unknown>,
  ) {
    super(body.error ?? `HTTP ${status}`);
    this.name = "ApiError";
  }
}

const WRITES = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  // The server refuses writes that aren't JSON (415); the raw uploads (a .dscn, an attachment, a PDF) set their own type.
  if (WRITES.has(method) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, method, headers, credentials: "same-origin" });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) throw new NeedsToken(typeof body.error === "string" ? body.error : undefined);
  if (!response.ok) throw new ApiError(response.status, body);
  return body as T;
}

export function putJson<T>(path: string, data: unknown): Promise<T> {
  return apiFetch<T>(path, { method: "PUT", body: JSON.stringify(data) });
}

export function postJson<T>(path: string, data: unknown = {}): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body: JSON.stringify(data) });
}

export function patchJson<T>(path: string, data: unknown): Promise<T> {
  return apiFetch<T>(path, { method: "PATCH", body: JSON.stringify(data) });
}

export function deleteJson<T = unknown>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: "DELETE" });
}

// Shapes from the Preferences API (plateau 0, task 9).

export type Effort = "auto" | "low" | "medium" | "high" | "max";
export type { Language };

export interface ProviderCapabilities {
  id: string;
  title: string;
  jobs: string[];
  models: string[];
  efforts: Effort[];
  default_model: string | null;
  /** Each model's label, backend and price (portraits plan Task 4); a model without one shows its id. */
  model_info?: Record<string, ModelInfo>;
  /** Why a live provider can't be used now (assetgen not answering), or null. */
  problem?: string | null;
  /** A fake, for developing Delve rather than for play (Preferences warn on its pictures). */
  development?: boolean;
}

export interface ModelInfo {
  label: string;
  backend: string;
  price: string | null;
  paid: boolean;
}

export interface Backends {
  jobs: string[];
  providers: ProviderCapabilities[];
  /** The image style's presets (DEL-202); `sample` says /image-styles/{id}.webp shows one. */
  image_styles: ImageStylePreset[];
}

export interface ImageStylePreset {
  id: string;
  name: string;
  prompt: string;
  sample: boolean;
}

/** The install's image style: "tone" (the campaign's), a preset's id, or "custom" with its own words. */
export interface ImageStyle {
  preset: string;
  custom: string;
}

export interface BackendChoice {
  provider: string;
  model: string | null;
  effort: Effort | null;
}

export interface AppPreferences {
  choices: Record<string, BackendChoice>;
  language: Language;
  image_style: ImageStyle;
}

/** A settings warning with its code, so the web says it in the reader's language; `text` is the English one. */
export interface SettingsWarning {
  code: string;
  args: Record<string, string>;
  text: string;
}

export interface PreferencesResponse extends AppPreferences {
  warnings: string[];
  /** The same warnings with their codes (open fixes Task 6); a server from before has none. */
  coded_warnings?: SettingsWarning[];
}

export const getBackends = () => apiFetch<Backends>("/api/backends");
export const getPreferences = () => apiFetch<PreferencesResponse>("/api/preferences");
/** Without `choices` (the side bar's switch) the server changes only the language, and keeps the stored choices. */
export const putPreferences = (p: AppPreferences | Pick<AppPreferences, "language">) =>
  putJson<PreferencesResponse>("/api/preferences", p);

/**
 * Listens to the server's event stream (`/api/events`, server-sent events).
 * Returns a function that closes it. EventSource reconnects by itself and
 * resends Last-Event-ID, so the server replays what was missed.
 */
export function subscribeEvents(handlers: Record<string, (data: unknown) => void>): () => void {
  if (typeof EventSource === "undefined") return () => {};
  const source = new EventSource("/api/events");
  for (const [type, handle] of Object.entries(handlers)) listen(source, type, handle);
  return () => source.close();
}

function listen(source: EventSource, type: string, handle: (data: unknown) => void) {
  source.addEventListener(type, (e) => {
    const raw = (e as MessageEvent).data;
    let data: unknown = raw;
    try {
      data = JSON.parse(raw);
    } catch {
      // not JSON: hand over the text
    }
    handle(data);
  });
}

export type Subscribe = (handlers: Record<string, (data: unknown) => void>) => () => void;

/**
 * One event stream for many listeners: `subscribe` adds handlers to the one
 * EventSource, opened on first use, and returns a function that removes them.
 * `close` closes the stream.
 *
 * A stream the browser gave up on (an `error` with the stream CLOSED) may mean
 * Delve no longer knows this browser: `GET /api/me` is asked, and on a 401 the
 * `onLost` listeners are called (plan 7 Task 18). Otherwise a new stream is opened, after a wait that doubles each
 * time, and the handlers move to it.
 *
 * `campaign` names the table an account listens at (`/api/events?campaign=…`, players and tavern Task E3).
 *
 * When the stream opens again after a break, the `reconnected` listeners are called (not a server event): the replay
 * covers a short break, and they read again what a longer one, or a restarted Delve, may have lost (DEL-168).
 */
/** What `sharedEvents` tells its listeners when the stream is back after a break. */
export const RECONNECTED = "reconnected";

export function sharedEvents(campaign: string | null = null): {
  subscribe: Subscribe;
  close: () => void;
  onLost: (listener: () => void) => () => void;
} {
  const listeners = new Map<string, Set<(data: unknown) => void>>();
  const lost = new Set<() => void>();
  let source: EventSource | null = null;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let attempts = 0;
  const open = () => {
    const opened = new EventSource(campaign ? `/api/events?campaign=${encodeURIComponent(campaign)}` : "/api/events");
    let broken = attempts > 0;
    opened.addEventListener("error", () => {
      broken = true;
      void closed(opened);
    });
    opened.addEventListener("open", () => {
      attempts = 0;
      if (!broken) return;
      broken = false;
      listeners.get(RECONNECTED)?.forEach((handle) => handle(null));
    });
    for (const [type, handlersOfType] of listeners) {
      if (type !== RECONNECTED) listen(opened, type, (data) => handlersOfType.forEach((h) => h(data)));
    }
    source = opened;
  };
  const closed = async (from: EventSource) => {
    if (from !== source || from.readyState !== EventSource.CLOSED) return;
    try {
      const me = await fetch("/api/me", { headers: { Accept: "application/json" }, credentials: "same-origin" });
      if (me.status === 401) {
        lost.forEach((listener) => listener());
        return;
      }
    } catch {
      // Delve isn't answering at all: nothing to say about this browser, so try the stream again.
    }
    // The browser gave up (a proxy's 502 while Delve restarts, say), yet Delve still knows this browser: open a new
    // stream, waiting longer each time, up to half a minute; its `open` tells the `reconnected` listeners.
    if (from !== source || retry) return;
    const wait = Math.min(30_000, 1000 * 2 ** attempts++);
    retry = setTimeout(() => {
      retry = null;
      if (from === source) open();
    }, wait);
  };
  const subscribe: Subscribe = (handlers) => {
    if (typeof EventSource === "undefined") return () => {};
    if (!source) open();
    for (const [type, handle] of Object.entries(handlers)) {
      let set = listeners.get(type);
      if (!set) {
        const handlersOfType = new Set<(data: unknown) => void>();
        listeners.set(type, (set = handlersOfType));
        if (type !== RECONNECTED) listen(source!, type, (data) => handlersOfType.forEach((h) => h(data)));
      }
      set.add(handle);
    }
    return () => {
      for (const [type, handle] of Object.entries(handlers)) listeners.get(type)?.delete(handle);
    };
  };
  return {
    subscribe,
    close: () => {
      if (retry) clearTimeout(retry);
      retry = null;
      source?.close();
      source = null;
      listeners.clear();
      lost.clear();
    },
    onLost: (listener) => {
      lost.add(listener);
      return () => void lost.delete(listener);
    },
  };
}

/** The app's one event stream (App provides it); outside the app, each subscriber opens its own. */
export const EventsContext = createContext<Subscribe>(subscribeEvents);

// Shapes from the module, map and DSL routes (plateau 1, task 6).

export interface ModuleMapSummary {
  name: string;
  role: MapRole;
  is_default: boolean;
}

export interface ModuleSummary {
  id: string;
  title: string;
  maps: ModuleMapSummary[];
  head_revision: number | null;
  updated_at: string;
  /** A draft can't start a campaign until it is marked ready. */
  draft: boolean;
  /** No texts, no entities and no rooms yet: it can't start a campaign. */
  empty?: boolean;
  /** What the list's filter works on (the list only; the module itself has them in its metadata): the setting as
   * written, the character levels as a range (one level is both ends), and the tags. */
  setting?: string | null;
  levels?: { min: number; max: number } | null;
  tags?: string[];
  /** Its one-line summary (the Details tab's, DEL-360) for the card under its title; null for none (the list only). */
  summary?: string | null;
  /** The module's library entry (cloud storage plan Task 10): its key and the version it is at, whether it was
   * published from here or downloaded, the entry's newer version (null when there is none) and whether it was edited
   * here since; null when it has none. */
  library?: ModuleLibrary | null;
  /** Its category (DEL-114), null for none. */
  category?: { id: string; name: string } | null;
  /** Its banner (DEL-123), null for none: `version` names the picture shown (null while the first is painting),
   * `source` where it came from, and `status` a painting under way or failed (with its `error`). */
  banner?: ModuleBannerState | null;
}

export interface ModuleBannerState {
  version: string | null;
  source: string | null;
  status: "painting" | "failed" | null;
  error: string | null;
}

/** One of the organisers' categories of modules (DEL-114), in their order. */
export interface ModuleCategory {
  id: string;
  name: string;
  position: number;
}

export interface ModuleLibrary {
  key: string;
  version: number;
  origin: "published" | "downloaded";
  newer: number | null;
  edited: boolean;
}

export interface ModuleMapEntry extends ModuleMapSummary {
  source: string;
}

export interface ModuleDetail extends Omit<ModuleSummary, "maps" | "setting" | "levels" | "tags"> {
  metadata: Record<string, unknown>;
  maps: ModuleMapEntry[];
}

const modulePath = (id: string) => `/api/modules/${encodeURIComponent(id)}`;
const mapPath = (id: string, name: string) => `${modulePath(id)}/maps/${encodeURIComponent(name)}`;

export const listModules = () => apiFetch<ModuleSummary[]>("/api/modules");
export const createModule = (title: string) => postJson<ModuleDetail>("/api/modules", { title });
export const getModule = (id: string) => apiFetch<ModuleDetail>(modulePath(id));
/** A module's metadata, with its maps named but not their sources (DEL-172): Thracia's are 667 KB. */
export type ModuleMetadata = Omit<ModuleDetail, "maps"> & { maps: ModuleMapSummary[] };
export const getModuleMetadata = (id: string) => apiFetch<ModuleMetadata>(`${modulePath(id)}?map_sources=false`);
export const patchModule = (
  id: string,
  patch: { title?: string; metadata?: Record<string, unknown>; draft?: false; category_id?: string | null },
) => patchJson<ModuleDetail>(modulePath(id), patch);
/** Put a module in a category, or in none (DEL-114). */
export const setModuleCategory = (id: string, categoryId: string | null) => patchModule(id, { category_id: categoryId });

export const listModuleCategories = () => apiFetch<ModuleCategory[]>("/api/module-categories");
export const createModuleCategory = (name: string) => postJson<ModuleCategory>("/api/module-categories", { name });
/** Rename it or move it to `position` (from 0); the whole list, in its new order. */
export const updateModuleCategory = (id: string, change: { name?: string; position?: number }) =>
  putJson<ModuleCategory[]>(`/api/module-categories/${encodeURIComponent(id)}`, change);
export const deleteModuleCategory = (id: string) => deleteJson(`/api/module-categories/${encodeURIComponent(id)}`);
/** A draft becomes ready to play; a module can't become a draft again. */
export const markModuleReady = (id: string) => patchModule(id, { draft: false });
export const deleteModule = (id: string) => deleteJson(modulePath(id));

/** Uploads a `.dscn` bundle as it is: the body is the zip, the type application/zip. */
export const importModule = (file: Blob) =>
  apiFetch<ModuleDetail & { warnings: string[] }>("/api/modules/import", {
    method: "POST",
    headers: { "Content-Type": "application/zip" },
    body: file,
  });

export const exportModuleUrl = (id: string) => `${modulePath(id)}/export.dscn`;

/** A module's banner picture (DEL-123); `version` changes the address when the picture does. `card` is its small copy,
 * for the modules list's cards (DEL-234). */
export const moduleOwnBannerUrl = (id: string, version: string, size?: "card") =>
  `${modulePath(id)}/banner?v=${encodeURIComponent(version)}${size ? `&size=${size}` : ""}`;
/** An uploaded picture becomes the banner, its 21:9 band at `position` (0 the top, 1 the bottom). */
export const uploadModuleBanner = (id: string, file: Blob, position: number) =>
  apiFetch<ModuleDetail>(`${modulePath(id)}/banner/upload?position=${position}`, {
    method: "POST",
    headers: { "Content-Type": file.type },
    body: file,
  });
/** One of the module's own pictures becomes the banner, its band at `position`. */
export const pictureModuleBanner = (id: string, picture: string, position: number) =>
  putJson<ModuleDetail>(`${modulePath(id)}/banner`, { picture, position });
export const removeModuleBanner = (id: string) => deleteJson(`${modulePath(id)}/banner`);
/** Whether painting a banner costs money, and whether this caller may paint (only the owner, with a paid model). */
export const getBannerPaintInfo = (id: string) => apiFetch<{ paid: boolean; allowed: boolean }>(`${modulePath(id)}/banner/paint`);
export const paintModuleBanner = (id: string, hint: string) => postJson<ModuleDetail>(`${modulePath(id)}/banner/paint`, { hint });

export const getMap = (id: string, name: string) => apiFetch<MapDetail>(mapPath(id, name));
export const putMap = (id: string, name: string, patch: { source?: string; role?: MapRole; new_name?: string }) =>
  putJson<MapDetail>(mapPath(id, name), patch);
export const createMap = (id: string, name: string, role: MapRole) =>
  postJson<MapDetail>(`${modulePath(id)}/maps`, { name, role });
export const deleteMap = (id: string, name: string) => deleteJson(mapPath(id, name));
export const setDefaultMap = (id: string, name: string) => putJson<unknown>(`${mapPath(id, name)}/default`, {});

/** A campaign's own map (campaign maps, 2026-10-23): a dungeon map made for one campaign, never its module's. */
export interface OwnMapDetail extends Omit<MapDetail, "updated_at"> {
  campaign_id: string;
  own: true;
  updated_at: string | null;
}

const ownMapsPath = (campaignId: string) => `/api/campaigns/${encodeURIComponent(campaignId)}/own-maps`;
const ownMapPath = (campaignId: string, name: string) => `${ownMapsPath(campaignId)}/${encodeURIComponent(name)}`;

export const listOwnMaps = (campaignId: string) => apiFetch<OwnMapDetail[]>(ownMapsPath(campaignId));
export const createOwnMap = (campaignId: string, name: string) =>
  postJson<OwnMapDetail>(ownMapsPath(campaignId), { name });
export const getOwnMap = (campaignId: string, name: string) => apiFetch<OwnMapDetail>(ownMapPath(campaignId, name));
export const putOwnMap = (campaignId: string, name: string, patch: { source?: string; new_name?: string }) =>
  putJson<OwnMapDetail>(ownMapPath(campaignId, name), patch);
export const deleteOwnMap = (campaignId: string, name: string) => deleteJson(ownMapPath(campaignId, name));
export const renderOwnMap = (campaignId: string, name: string, source?: string, renderer?: string) =>
  postJson<RenderResponse>(`${ownMapPath(campaignId, name)}/render`, { source, renderer });
export const ownMapFeatureNames = (campaignId: string, name: string, source?: string) =>
  postJson<FeatureNamesResponse>(`${ownMapPath(campaignId, name)}/feature-names`, { source });
export const simplifyOwnMap = (campaignId: string, name: string, source: string, doorSpurs = false) =>
  postJson<SimplifyResponse>(`${ownMapPath(campaignId, name)}/simplify`, { source, door_spurs: doorSpurs });

/** Module-aware preview: includes resolve against the module's libraries. `source` is the live buffer. */
export const renderMap = (id: string, name: string, source?: string, renderer?: string) =>
  postJson<RenderResponse>(`${mapPath(id, name)}/render`, { source, renderer });
export const mapFeatureNames = (id: string, name: string, source?: string) =>
  postJson<FeatureNamesResponse>(`${mapPath(id, name)}/feature-names`, { source });
/** Geometry-preserving simplification of the live buffer; nothing is saved. */
export const simplifyMap = (id: string, name: string, source: string, doorSpurs = false) =>
  postJson<SimplifyResponse>(`${mapPath(id, name)}/simplify`, { source, door_spurs: doorSpurs });

export const dsl = {
  connectivity: (source: string, moduleId?: string) =>
    postJson<ConnectivityResponse>("/api/dsl/connectivity", { source, module_id: moduleId }),
  render: (source: string, moduleId?: string, renderer?: string) =>
    postJson<RenderResponse>("/api/dsl/render", { source, renderer, module_id: moduleId }),
  parse: (source: string, moduleId?: string) =>
    postJson<{ map: ParsedMap }>("/api/dsl/parse", { source, module_id: moduleId }),
};

// Shapes from the conversion routes (plateau 5, task 5).

/**
 * `paused` is a thorough conversion's only: stopped by Delve, the usage limit, an error or the organiser, its work kept
 * to resume. `queued`: a book uploaded while another job ran (or the queue was paused), waiting its turn.
 */
export type ConversionStatus = "queued" | "running" | "paused" | "done" | "failed" | "cancelled";
/**
 * `reading`, `converting`, `entities`, `pictures` and `maps` for a PDF; `scoping`, `generating` and `maps` for a
 * request, and `scoping`, `planning`, `campaign`, `levels` and `maps` for a request scoped as a campaign; `tiles`,
 * `grid`, `terrain`, `water`, `places` and `routes` for a world map's picture; `drawing` for a dungeon map's draft;
 * `condensing`, `outlining` and `writing` for a novel. A thorough PDF's are `reading`, `classifying`, `drafting`,
 * `sorting`, `cleaning`, `tracing`, `joining`, `describing`, `entities` and `making`.
 */
export type ConversionStep =
  | "reading"
  | "classifying"
  | "converting"
  | "gaps"
  | "entities"
  | "pictures"
  | "maps"
  | "generating"
  | "painting"
  | "scoping"
  | "planning"
  | "campaign"
  | "levels"
  | "sites"
  | "tiles"
  | "grid"
  | "terrain"
  | "water"
  | "places"
  | "routes"
  | "drawing"
  | "condensing"
  | "outlining"
  | "writing"
  | "drafting"
  | "sorting"
  | "cleaning"
  | "tracing"
  | "joining"
  | "describing"
  | "making"
  | "fixing";
/** A book and a request make a module; a world map's reading, a dungeon map's draft and a novel make none. */
export type ConversionKind = "pdf" | "generate" | "worldmap" | "dungeon-map" | "book-map" | "novel" | "history" | "fixit";
export type ConversionMode = "ready" | "draft";

export interface ConversionWarning {
  code: string;
  message: string;
  ref: string;
}

export interface Conversion {
  id: string;
  kind: ConversionKind;
  title: string;
  mode: ConversionMode;
  status: ConversionStatus;
  step: ConversionStep;
  done: number;
  total: number;
  /** Which step of how many it is at, "Step 2 of 4"; the index is 0 before the first. */
  steps: ConversionSteps;
  /** The module made at the end; null until it is done. */
  module_id: string | null;
  warnings: ConversionWarning[];
  /** Why it failed; null otherwise. */
  error: string | null;
  created_at: string;
  updated_at: string;
  /** What a job that makes no module works on: `{module_id | campaign_id, name?, title?}`, or a novel's `{novel_id}`. */
  target?: Record<string, string> | null;
  /** What its Claude calls cost so far, in USD; null while none reported a cost. */
  cost_usd?: number | null;
  /** A thorough PDF conversion's, by agents in a job folder (thorough conversion). */
  thorough?: boolean;
  /** Why a paused conversion paused, and when the usage limit resets (then it resumes by itself); null otherwise. */
  paused?: ConversionPause | null;
  /** The organiser's comments on the PDF form, given to every prompt of the job; "" for none (table voice and fixes F1). */
  comments?: string;
  /** The keys of its closed questions and doubts, `question:<id>` and `doubt:<index>` (table voice and fixes F3). */
  closed?: string[];
}

export interface ConversionPause {
  reason: string;
  resets_at: string | null;
}

/** What the PDF form may offer: Thorough, unless the Claude CLI isn't there for it (`reason`). */
export interface ConversionOptions {
  thorough: { available: boolean; reason: string | null };
  /** Whether a generated module's pictures cost money, and whether this caller may ask for them. */
  pictures?: { paid: boolean; allowed: boolean };
}

export interface ConversionSteps {
  index: number;
  count: number;
}

/** The `conversion` event: the progress of one conversion, and what it cost so far. */
export type ConversionEvent = Pick<Conversion, "id" | "status" | "step" | "done" | "total" | "steps" | "cost_usd">;

const conversionPath = (id: string) => `/api/conversions/${encodeURIComponent(id)}`;

/** The last 20 conversions, newest first. */
export const listConversions = () => apiFetch<Conversion[]>("/api/conversions");
export const getConversion = (id: string) => apiFetch<Conversion>(conversionPath(id));
export const conversionOptions = () => apiFetch<ConversionOptions>("/api/conversions/options");
/**
 * Uploads the book as it is: the body is the PDF, the type application/pdf. Thorough (the default) checks every page
 * and traces every map from the book; the quick one, with `bookMaps`, then draws each sketched map from the book's map
 * page, as a draft kept only on Keep. The organiser's `comments` (at most 2000 characters) travel in the query string,
 * as the body is the book, and every prompt of the job is given them.
 */
export const convertPdf = (file: Blob, title: string, mode: ConversionMode, bookMaps = true, thorough = true, comments = "") =>
  apiFetch<Conversion>(
    `/api/conversions/pdf?title=${encodeURIComponent(title)}&mode=${mode}` +
      (thorough ? "&thorough=true" : `&thorough=false&book_maps=${bookMaps}`) +
      (comments.trim() ? `&comments=${encodeURIComponent(comments.trim())}` : ""),
    {
      method: "POST",
      headers: { "Content-Type": "application/pdf" },
      body: file,
    },
  );
/** How big a request is (DEL-134): one module, written in one call, or a campaign, written in steps. */
export type GenerateScale = "module" | "campaign" | "sandbox";
/** A question Claude asks before it writes a module, with what it assumes when it isn't answered. */
export interface ScopeQuestion {
  id: string;
  text: string;
  default: string;
}
export interface GenerateScope {
  scale: GenerateScale;
  questions: ScopeQuestion[];
}
/** A scope question as the organiser answered it: an empty `answer` keeps the assumption. */
export interface ScopeAnswer {
  text: string;
  default: string;
  answer: string;
}
/** Before Generate: the request's scale and what to ask first, from one short call; it starts no job. */
export const scopeRequest = (request: string) => postJson<GenerateScope>("/api/conversions/generate/scope", { request });
/** Generate a module from a request; with its `scale` and `answers` when it was scoped first (DEL-134). */
export const generateModule = (
  request: string,
  mode: ConversionMode = "ready",
  scope?: { scale: GenerateScale; answers: ScopeAnswer[] },
  pictures = 0,
) => postJson<Conversion>("/api/conversions/generate", { request, mode, ...scope, ...(pictures ? { pictures } : {}) });
export const cancelConversion = (id: string) => postJson<Conversion>(`${conversionPath(id)}/cancel`);
/** Puts a paused thorough conversion back in the queue, to run again from its first unfinished piece. */
export const resumeConversion = (id: string) => postJson<Conversion>(`${conversionPath(id)}/resume`);
/** Pauses a running thorough conversion now: its agents stop, and the next queued conversion starts. */
export const pauseConversion = (id: string) => postJson<Conversion>(`${conversionPath(id)}/pause`);

/** The conversion queue: the jobs that aren't over, in the order they get the slot, and its switch. */
export interface ConversionQueue {
  paused: boolean;
  jobs: Conversion[];
}
export const getConversionQueue = () => apiFetch<ConversionQueue>("/api/conversions/queue");
/** Pauses the queue (no queued conversion starts; a running one runs on) or unpauses it. */
export const setConversionQueuePaused = (paused: boolean) => putJson<ConversionQueue>("/api/conversions/queue", { paused });

/** The running conversion a start was refused for (409), if the answer names it. */
export function runningConversionOf(error: unknown): Conversion | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const found = error.body.conversion;
  return found && typeof found === "object" ? (found as Conversion) : null;
}

// Shapes from the module source routes (plateau 3, tasks 3 and 4).

/** Delve's audience words; the format's `gm` is `dm` here. */
export type Audience = "gm" | "player";

export interface ModuleTextDoc {
  id: string;
  title: string;
  audience: Audience;
  map: string | null;
  /** The whole file, front matter included. */
  markdown: string;
}

export interface Attachment {
  id: string;
  type: string;
  sha256: string;
  size: number;
  description: string;
  audience: Audience;
  /** The original a cut picture is cut from, its turn and its box (DEL-40); null for a picture as uploaded. */
  cut?: AttachmentCut | null;
}

/** A box of a picture: `[x, y, w, h]` in fractions of the (turned) picture. */
export type CutBox = [number, number, number, number];

export interface AttachmentCut {
  original: string;
  original_type: string;
  original_size: number;
  /** Degrees clockwise: 0, 90, 180 or 270. */
  rotate: number;
  /** Of the turned original; null for all of it. */
  box: CutBox | null;
  /** Proposed by a conversion, until the organiser says it looks right. */
  proposed: boolean;
}

/** A piece of a cut: the first is the attachment itself, each other a new picture with its description and audience. */
export interface CutPiece {
  box: CutBox | null;
  description?: string;
  audience?: Audience;
}

/** A keyed heading linked to a room: by an explicit key, or by itself. */
export interface RoomLink {
  text_id: string;
  anchor: string;
  key: string;
  map: string;
  node: string;
  label: string;
  explicit: boolean;
}

/** A keyed heading of a text, linked to a room or not: its key as written (scoped to its part when two share it). */
export interface KeyedHeading {
  key: string;
  title: string;
  text_id: string;
  anchor: string;
}

export type SourceWarningCode =
  | "room-without-text"
  | "key-without-room"
  | "missing-attachment"
  | "missing-entity"
  | "missing-key"
  | "worldmap-unreadable"
  | "worldmap-in-review";

export interface SourceWarning {
  code: SourceWarningCode;
  message: string;
  /** `map:<name>#<node>`, `text:<id>#<anchor>`, `asset:<id>`, `npc:<id>`… or `worldmap:<name>` */
  ref: string;
}

export const ENTITY_KINDS = ["npcs", "encounters", "factions", "quests", "pregens"] as const;
export type EntityKind = (typeof ENTITY_KINDS)[number];

/** An entity as the format's record; its audience is the format's `gm` or `player`. */
export type EntityRecord = { id: string; name: string } & Record<string, unknown>;

export interface ModuleSource {
  texts: ModuleTextDoc[];
  entities: Partial<Record<string, EntityRecord[]>>;
  attachments: Attachment[];
  keys: Record<string, unknown>[];
  /** The module's world maps, as their DSL (plan 6). */
  worldmaps?: WorldMapSource[];
  links: RoomLink[];
  warnings: SourceWarning[];
  /** Every keyed heading, in text order (faithful modules). */
  headings?: KeyedHeading[];
}

export interface WorldMapSource {
  name: string;
  title: string;
  dsl: string;
}

export interface TextSaved {
  text: ModuleTextDoc;
  links: RoomLink[];
  warnings: SourceWarning[];
  headings?: KeyedHeading[];
}

const textPath = (id: string, textId: string) => `${modulePath(id)}/texts/${encodeURIComponent(textId)}`;

export const getModuleSource = (id: string) => apiFetch<ModuleSource>(`${modulePath(id)}/source`);
export const createText = (id: string, text: { id: string; title: string; audience?: Audience; map?: string | null }) =>
  postJson<ModuleTextDoc>(`${modulePath(id)}/texts`, text);
export const putText = (
  id: string,
  textId: string,
  patch: { title?: string; audience?: Audience; map?: string | null; markdown?: string },
) => putJson<TextSaved>(textPath(id, textId), patch);
export const deleteText = (id: string, textId: string) => deleteJson(textPath(id, textId));

/** One finding of the server's schema check, at a field (`disposition`, `party/levels`). */
export interface SchemaDiagnostic {
  severity: string;
  code: string;
  message: string;
  path: string;
}

/** The diagnostics of a 422 refusal; none for any other error. */
export function diagnosticsOf(error: unknown): SchemaDiagnostic[] {
  if (!(error instanceof ApiError) || error.status !== 422) return [];
  const found = error.body.diagnostics;
  return Array.isArray(found) ? (found as SchemaDiagnostic[]) : [];
}

const entityPath = (id: string, kind: EntityKind, entityId: string) =>
  `${modulePath(id)}/entities/${kind}/${encodeURIComponent(entityId)}`;

export const putEntity = (id: string, kind: EntityKind, record: EntityRecord) =>
  putJson<{ record: EntityRecord; warnings: SourceWarning[] }>(entityPath(id, kind, record.id), record);
export const deleteEntity = (id: string, kind: EntityKind, entityId: string) => deleteJson(entityPath(id, kind, entityId));

/**
 * An attachment's bytes, for `<img>` (the owner's cookie goes with it). With `version` (its sha256) the URL changes
 * when a cut or a reset changes the picture under the same id.
 */
export const attachmentUrl = (id: string, assetId: string, version?: string) =>
  `${modulePath(id)}/assets/${encodeURIComponent(assetId)}${version ? `?v=${version.slice(0, 12)}` : ""}`;
/** The original a cut picture is cut from (the picture itself when it has no cut): the organiser's only. */
export const originalUrl = (id: string, assetId: string) => `${attachmentUrl(id, assetId)}?original=true`;

/** Uploads a file as it is: the body is its bytes, the type its own (the server refuses other kinds with 415). */
export const uploadAttachment = (id: string, file: File) =>
  apiFetch<Attachment>(`${modulePath(id)}/assets?name=${encodeURIComponent(file.name)}`, {
    method: "POST",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
export const describeAttachment = (
  id: string,
  assetId: string,
  patch: { description?: string; audience?: Audience; reviewed?: boolean },
) => patchJson<Attachment>(attachmentUrl(id, assetId), patch);
/** Cuts a picture into `pieces` of its original turned by `rotate`: the answer's first is the attachment itself. */
export const cutAttachment = (id: string, assetId: string, cut: { rotate: number; pieces: CutPiece[] }) =>
  postJson<{ attachments: Attachment[] }>(`${attachmentUrl(id, assetId)}/cut`, cut);
/** The picture back to its whole original; a split's other pieces stay. */
export const resetCut = (id: string, assetId: string) => deleteJson<Attachment>(`${attachmentUrl(id, assetId)}/cut`);
export const deleteAttachment = (id: string, assetId: string) => deleteJson(attachmentUrl(id, assetId));

/**
 * Gives every item named the audience, in one save: `text:<id>`, `npc:<id>` (any entity kind) or `asset:<id>`. All or
 * nothing: an unknown ref is a 422 that names it.
 */
export const setAudiences = (id: string, refs: string[], audience: Audience) =>
  postJson<{ changed: number }>(`${modulePath(id)}/audience`, { refs, audience });

// Shapes from the campaign, character and map-state routes (plateau 1, task 7).

export interface Campaign {
  id: string;
  name: string;
  module_id: string;
  revision: number;
  created_at: string;
  ruleset: string;
  /** Null: the campaign plays in no setting. */
  setting: string | null;
  /** One of `CAMPAIGN_STATUSES` as Delve sets it, kept as text: an open enum. */
  status: string;
  /** Whether the table may talk in voice, set by the host; "allowed" by default (table voice and fixes). Left out by
   * an older server. */
  voice?: "allowed" | "off";
  /** How the campaign's fights roll initiative, set by the host: per combatant (the default) or per side. */
  initiative?: "combatant" | "side";
  /** Who may watch the table (DEL-215): anyone with the link, those a host lets in, or nobody. */
  observers?: "anyone" | "approved" | "nobody";
  /** The campaign its party was carried on from: null when it wasn't, or that one was deleted. Left out by an older
   * server. */
  carried_from?: CampaignLink | null;
  /** The campaigns its party was carried on to, oldest first. */
  carried_to?: CampaignLink[];
  /** Who can find the table (DEL-204): only through the invite link, or listed for accounts on this Delve. */
  visibility?: Visibility;
  /** For players only, in Markdown: how the table plays together. The DM never reads it. */
  description?: string;
  /** The places for players (the host and observers take none); null for no limit. */
  slots?: number | null;
  /** When the table plays (DEL-204 part C); null without a schedule. Left out by an older server. */
  schedule?: Schedule | null;
  next_sessions?: NextSession[];
}

export type Visibility = "private" | "public";

/** A table's recurring schedule (DEL-204): every N weeks from `first` (its weekday is the rule's), from `start` to
 * `end` local time in `time_zone`; `changes` move (`to`, a local date-time) or skip (`to` null) a session `on` a date. */
export interface Schedule {
  every_weeks: number;
  first: string;
  start: string;
  end: string;
  time_zone: string;
  changes?: { on: string; to: string | null }[];
}

/** One of a table's next sessions, as instants: each viewer shows it in their own time zone. */
export interface NextSession {
  on: string;
  starts_at: string;
  ends_at: string;
  moved: boolean;
}

export interface CampaignLink {
  id: string;
  name: string;
}

export const CAMPAIGN_STATUSES = ["in_progress", "paused", "complete"] as const;
export type CampaignStatus = (typeof CAMPAIGN_STATUSES)[number];

/** A campaign as the campaigns list has it: its module's title, its players and how much it has been played. */
export interface CampaignListed extends Campaign {
  module_title: string;
  /** The names of the seats that haven't left, observers excepted. */
  players: string[];
  /** Who sits at the table, as its card shows them, and the places they take (DEL-230); left out by an older server. */
  people?: TablePerson[];
  taken?: number;
  /** The latest closed beat, else the latest session's start or end; null when never played. */
  last_played: string | null;
  sessions: number;
  playtime_s: number;
  /** The banner it shows, its own or else its module's (`bannerUrl`'s `imageId`, DEL-207); null for none. Left out by
   * an older server. */
  banner?: string | null;
}

/** A ruleset or a setting a campaign can name (spec §10); `preferred` when its pack says a new campaign takes it. */
export interface World {
  id: string;
  title: string;
  preferred?: boolean;
}

export interface Worlds {
  rulesets: World[];
  settings: World[];
}

/** A new campaign's ruleset and setting; left out, the server takes the module's. */
export interface CampaignWorld {
  ruleset: string;
  setting: string | null;
}

export const getWorlds = () => apiFetch<Worlds>("/api/worlds");

export interface CampaignDetail extends Campaign {
  module_title: string;
  /** The map names in the pinned revision, then the campaign's own. */
  maps: string[];
  /** The names of the campaign's own maps (campaign maps, 2026-10-23); left out by an older server. */
  own_maps?: string[];
  upgrade_available: boolean;
  /** Left out by a server from before banners: the page then has no Banner section. */
  banner?: CampaignBanner;
}

// Shapes of a character's sheet and state (plateau 2a, tasks 4 and 5). Fields a server doesn't send yet are optional.

export interface Attack {
  name: string;
  speed: number | null;
  attacks: number | string;
  thac0: number | null;
  /** The THAC0 the fight rolls against, worked out on the server, with its parts; none without a reference. */
  thac0_worked?: { value: number; parts: [string, number][] };
  damage_sm: string;
  damage_l: string;
  range: string | null;
}

export interface Effect {
  name: string;
  duration: number;
  to_hit?: number;
  ac?: number;
  dmg?: number;
  save?: number;
  source?: string;
}

/** Spells by spell level ("1", "2"…). */
export type SpellsByLevel = Record<string, string[]>;

export interface SpellLoadout {
  known: SpellsByLevel;
  default: SpellsByLevel;
}

export interface Sheet {
  kind: "pc" | "npc";
  label: string;
  race: string;
  gender: string;
  cls: string;
  levels: Record<string, number>;
  hp_max: number;
  ac: number;
  thac0: number;
  saves: Record<string, number>;
  ability_scores: Record<string, number | string>;
  attacks: Attack[];
  /** The weapon in prose, for the DM's narration. */
  weapon: string;
  weapon_profs?: string[];
  nwps?: string[];
  natural_abilities?: string[];
  /** Thief and other percentile skills. */
  skills?: Record<string, number>;
  size?: string;
  /** An AC bonus against attackers larger than this character (a pixie's +2). */
  ac_vs_larger?: number;
  movement_rate: number;
  alignment: string;
  background?: string;
  spell_slots: Record<string, number>;
  spell_loadout?: SpellLoadout;
  /** An NPC's story: the organiser's `listDmCharacters` only, never a seat's. */
  notes_md?: string;
  /** An NPC's attitude to the party, -100 … 100: the organiser's only. */
  disposition?: number;
  /** Drawn by portraitgen in the browser, or painted (plan 6); null or missing: the initial. */
  portrait?: Portrait | null;
}

/** A portraitgen description and seed, which the browser draws, or a painted picture of the campaign. */
/** A drawn portrait is a description and a seed; one edited in portraitgen's editor (DEL-238) also has its `traits`,
 * which are drawn instead. */
export type Portrait =
  | { kind: "traits"; describe: string; seed: string; traits?: Record<string, unknown> }
  | { kind: "image"; image_id: string };

export interface Item {
  name: string;
  qty: number;
  weight_lb: number | null;
  notes: string;
  /** What only the DM knows of it (DEL-181): in the organiser's view only, never a seat's. */
  dm_notes?: string;
}

export interface MemorizedSpell {
  name: string;
  level: number;
  cast: boolean;
}

export interface CharacterState {
  hp: number;
  xp: number;
  conditions: string[];
  effects: Effect[];
  inventory?: Item[];
  memorized?: MemorizedSpell[];
}

export type EncumbranceBand = "light" | "moderate" | "heavy" | "severe" | "overloaded";

/** Computed by the server from the inventory, the reference weights and Strength. */
export interface Encumbrance {
  total_lb: number;
  band: EncumbranceBand;
  movement: number;
  penalty: number;
}

/** What a sheet's portrait shows of the character's state (`portraits.sheet_emote`). */
export type SheetEmote = "sleep" | "afraid" | "upset" | "idle";

export interface Character {
  id: string;
  campaign_id: string;
  name: string;
  kind: "pc" | "npc";
  sheet: Sheet;
  state: CharacterState;
  emote?: SheetEmote;
  /** The PC's place in the marching order, front first; null for NPCs. */
  order: number | null;
  encumbrance: Encumbrance | null;
  /** Each class's XP share and the share its next level needs (`class_xp.progress`); null without the reference. */
  xp_progress?: XpProgress[] | null;
  created_at: string;
  /** Why the PC left the party, and when; null while it is in it (table voice and fixes). Left out by an older
   * server. */
  departure?: "died" | "retired" | "left" | null;
  departed_at?: string | null;
  /** While a portrait is being painted, its painter and its place in the painter's queue (DEL-138); null otherwise.
   * Only the character lists have it. */
  portrait_painting?: Waiting | null;
  /** Whether its newest portrait failed to paint and the free one still stands in, for Try again (DEL-135). */
  portrait_failed?: boolean;
  /** Whether the sheet edits its portrait in portraitgen's editor rather than repainting it: a PC's, while
   * Preferences draw PCs' portraits with portraitgen (DEL-238). */
  portrait_editable?: boolean;
}

/** One class's XP: its share of the total, its level, the share its next level needs (null at the top or unknown)
 * and whether the share already reaches a higher level. */
export interface XpProgress {
  class: string;
  level: number;
  xp: number;
  xp_floor: number | null;
  xp_next: number | null;
  total_next: number | null;
  earned_level: number | null;
  ready: boolean;
}

/** An NPC as a seat gets it: who it is, and nothing the DM knows of it. */
export interface NpcAtTable {
  id: string;
  name: string;
  kind: "npc";
}

/** A character as `listCharacters` gives it: a PC with its sheet, or an NPC by name. */
export type TableCharacter = Character | NpcAtTable;

export const hasSheet = (c: TableCharacter): c is Character => "sheet" in c;

export interface CharacterKnowledge {
  location: string | null;
  nodes: string[];
  doors: string[];
}

/** A node an unknown or ambiguous name could mean, from a 404 `{error, candidates}`. */
export interface NodeCandidate {
  id: string;
  label: string;
}

/** The DM side of one map state: every character's position and knowledge, and the world's facts. */
export interface MapStateResponse {
  characters: Record<string, CharacterKnowledge>;
  door_states: Record<string, string>;
  revealed: string[];
  groups: unknown;
}

const campaignPath = (id: string) => `/api/campaigns/${encodeURIComponent(id)}`;
const mapStatePath = (id: string, map: string) => `${campaignPath(id)}/maps/${encodeURIComponent(map)}`;

export const listCampaigns = () => apiFetch<CampaignListed[]>("/api/campaigns");
export const createCampaign = (
  name: string,
  moduleId: string,
  houseRules: CampaignHouseRules = NO_HOUSE_RULES,
  world?: CampaignWorld,
) => postJson<Campaign>("/api/campaigns", { name, module_id: moduleId, ...world, ...houseRules });
export const getCampaign = (id: string) => apiFetch<CampaignDetail>(campaignPath(id));
export const deleteCampaign = (id: string) => deleteJson(campaignPath(id));
/** The host or a co-host sets the campaign's status. */
export const patchCampaign = (id: string, patch: { status: CampaignStatus }) => patchJson<Campaign>(campaignPath(id), patch);
export const upgradeCampaign = (id: string) => postJson<Campaign>(`${campaignPath(id)}/upgrade`);

/** Carry the party on into a new campaign (carry-the-party-on plan). Left out, the ruleset, the setting and the house
 * rules are the old campaign's. */
export interface CarryRequest extends CampaignHouseRules {
  name: string;
  module_id: string;
  character_ids: string[];
  ruleset: string;
  setting: string | null;
}

export const carryCampaign = (id: string, carry: CarryRequest) =>
  postJson<Campaign & { history: { status: HistoryStatus } }>(`${campaignPath(id)}/carry`, carry);

export type HistoryStatus = "writing" | "done" | "failed";

/** A carried party's history, as the host reads it: the DM's text and the table's. */
export interface History {
  campaign_id: string;
  dm_md: string;
  table_md: string;
  status: HistoryStatus;
  error: string | null;
  /** Set once the host has replaced the texts by hand: Write again asks before replacing them. */
  edited: boolean;
  conversion_id: string | null;
  cost_usd: number | null;
  created_at: string;
  updated_at: string;
}

/** What `GET …/history` answers: the whole history for the host, its status and the table's text alone for every
 * other seat, a co-host too; null for a campaign with none. */
export type HistoryView = Pick<History, "status" | "table_md"> & Partial<History>;

/** The most characters each of a history's texts holds (`HISTORY_MAX_CHARS`). */
export const HISTORY_MAX_CHARS = 6000;

export const getHistory = (id: string) => apiFetch<HistoryView | null>(`${campaignPath(id)}/history`);
export const putHistory = (id: string, texts: { dm_md: string; table_md: string }) =>
  putJson<History>(`${campaignPath(id)}/history`, texts);
export const writeHistoryAgain = (id: string, overwrite = false) =>
  postJson<History>(`${campaignPath(id)}/history/write`, { overwrite });

export const listCharacters = (id: string) => apiFetch<TableCharacter[]>(`${campaignPath(id)}/characters`);
/** Every character with its whole sheet, an NPC's story too: the organiser's, for the campaign page. */
export const listDmCharacters = (id: string) => apiFetch<Character[]>(`${campaignPath(id)}/dm/characters`);
/** Paint the character's portrait again with Preferences' painter (DEL-135): the free portrait, or a painting. */
export const repaintPortrait = (id: string, characterId: string) =>
  postJson<{ portrait?: Portrait; image_id?: string; status?: string }>(
    `${campaignPath(id)}/characters/${encodeURIComponent(characterId)}/portrait/repaint`,
  );
/** Save the traits made in portraitgen's editor as the PC's portrait (DEL-238). */
export const editPortrait = (id: string, characterId: string, traits: Record<string, unknown>) =>
  putJson<{ portrait: Portrait }>(`${campaignPath(id)}/characters/${encodeURIComponent(characterId)}/portrait`, {
    traits,
  });
export const renameCharacter = (id: string, characterId: string, name: string) =>
  patchJson<Character>(`${campaignPath(id)}/characters/${encodeURIComponent(characterId)}`, { name });
export const deleteCharacter = (id: string, characterId: string) =>
  deleteJson(`${campaignPath(id)}/characters/${encodeURIComponent(characterId)}`);

export const getMapState = (id: string, map: string) => apiFetch<MapStateResponse>(`${mapStatePath(id, map)}/state`);
export const startMapState = (id: string, map: string, characters: string[]) =>
  postJson<MapStateResponse>(`${mapStatePath(id, map)}/start`, { characters });
export const moveCharacters = (id: string, map: string, characters: string[], to: string) =>
  postJson<MapStateResponse>(`${mapStatePath(id, map)}/move`, { characters, to });
export const revealNode = (id: string, map: string, characters: string[], node: string, revealDoors = true) =>
  postJson<MapStateResponse>(`${mapStatePath(id, map)}/reveal`, { characters, node, reveal_doors: revealDoors });
export const setDoor = (id: string, map: string, door: string, state: string) =>
  postJson<MapStateResponse>(`${mapStatePath(id, map)}/door`, { door, state });
export const revealSecret = (id: string, map: string, key: string) =>
  postJson<MapStateResponse>(`${mapStatePath(id, map)}/secret`, { key });
/** The pinned map's doors and secrets, revealed or not, for the host's pickers (organisers only). */
export interface DoorsAndSecrets {
  doors: { key: string; type: string; nodes: string[] }[];
  secrets: { key: string; kind: string; label: string; node: string | null }[];
}
export const getDoorsAndSecrets = (id: string, map: string) =>
  apiFetch<DoorsAndSecrets>(`${mapStatePath(id, map)}/doors-and-secrets`);

/** The characters' fog view: only what these characters know. It has no way to become the DM view. */
export const getCharactersView = (id: string, map: string, characters: string[]) =>
  apiFetch<{ svg: string }>(`${mapStatePath(id, map)}/view?characters=${characters.map(encodeURIComponent).join(",")}`);
/** The full map with every group: a separate route, for the host. */
/** The DM log summed for one beat, or for one Ask the DM's side pass (`ask`, a row of its own in its place among the
 * beats), in the order the beats began. */
export interface DmCostRow {
  beat: string;
  at: string;
  ask: boolean;
  tools: number;
  input: number;
  output: number;
  /** Null while no usage of the beat carried a cost. */
  cost: number | null;
}

/** The campaign's DM log summed per beat by the server (DEL-172): the organiser's. The raw log is `/dm/log`. */
export const getDmCosts = (id: string) => apiFetch<{ rows: DmCostRow[] }>(`${campaignPath(id)}/dm/costs`);
export const getDmView = (id: string, map: string) => apiFetch<{ svg: string }>(`${mapStatePath(id, map)}/dm-view`);

// Shapes from the house-rules routes (plateau 2a, task 9).

export const PHASES = ["character-creation", "level-up", "combat", "items", "behaviour", "always"] as const;
export const RULE_KINDS = ["general", "race", "class", "item", "behaviour"] as const;
export type Phase = (typeof PHASES)[number];
export type RuleKind = (typeof RULE_KINDS)[number];

export interface HouseRuleInput {
  title: string;
  body_md: string;
  kind: RuleKind;
  phases: Phase[];
  /** A ruleset's id; null means any. */
  ruleset: string | null;
  /** A setting's id ("aun"); null means any. */
  setting: string | null;
  /** The race, class or item the rule is about: "lizardfolk". */
  subject: string | null;
  enabled: boolean;
}

export interface HouseRule extends HouseRuleInput {
  id: string;
}

export interface BundleInput {
  title: string;
  description_md: string;
  rule_ids: string[];
}

export interface Bundle extends BundleInput {
  id: string;
}

/** What a campaign points to: bundles and single rules, in order. */
export interface CampaignHouseRules {
  bundle_ids: string[];
  rule_ids: string[];
}

export const NO_HOUSE_RULES: CampaignHouseRules = { bundle_ids: [], rule_ids: [] };

const rulePath = (id: string) => `/api/house-rules/${encodeURIComponent(id)}`;
const bundlePath = (id: string) => `/api/house-rule-bundles/${encodeURIComponent(id)}`;

export const listHouseRules = () => apiFetch<HouseRule[]>("/api/house-rules");
export const createHouseRule = (rule: HouseRuleInput) => postJson<HouseRule>("/api/house-rules", rule);
export const updateHouseRule = (id: string, rule: HouseRuleInput) => putJson<HouseRule>(rulePath(id), rule);
export const deleteHouseRule = (id: string) => deleteJson(rulePath(id));
/** Import the example rules Delve ships into the library; again, it answers the same bundle and changes nothing. */
export const importExampleHouseRules = () => postJson<Bundle>("/api/house-rules/import-example");

export const listBundles = () => apiFetch<Bundle[]>("/api/house-rule-bundles");
export const createBundle = (bundle: BundleInput) => postJson<Bundle>("/api/house-rule-bundles", bundle);
export const updateBundle = (id: string, bundle: BundleInput) => putJson<Bundle>(bundlePath(id), bundle);
export const deleteBundle = (id: string) => deleteJson(bundlePath(id));

export const getCampaignHouseRules = (id: string) => apiFetch<CampaignHouseRules>(`${campaignPath(id)}/house-rules`);
export const putCampaignHouseRules = (id: string, choice: CampaignHouseRules) =>
  putJson<CampaignHouseRules>(`${campaignPath(id)}/house-rules`, choice);

// The campaign's world, for the organisers (plan 6 Task 12): every field, the DM-only ones too. Its world maps have
// their own clients, in web/src/worldmap/.

export interface Faction {
  id: string;
  name: string;
  alignment: string;
  goals: string;
  scope: string;
  known: boolean;
  strength: number;
  reputation: number;
  standing: string;
  notes_md: string;
}

export type ClockKind = "countdown" | "progress";
export const CLOCK_KINDS: ClockKind[] = ["countdown", "progress"];

export interface Clock {
  id: number;
  label: string;
  kind: ClockKind;
  faction: string | null;
  days_remaining: number | null;
  segments: number | null;
  filled: number | null;
  on_complete: string;
  started_day: number;
  done_day: number | null;
}

export const QUEST_STATUSES = ["available", "active", "paused", "complete", "failed"] as const;
export const QUEST_SCOPES = ["local", "regional", "continental"] as const;

export interface QuestNote {
  day: number;
  text: string;
  known: boolean;
}

export interface Quest {
  id: string;
  title: string;
  giver: string;
  scope: string;
  stakes: string;
  status: string;
  known: boolean;
  started_day: number | null;
  ended_day: number | null;
  related: string[];
  log: QuestNote[];
  notes_md: string;
}

export const POSSESSION_KINDS = ["mount", "vehicle", "ship", "house", "stronghold", "domain", "other"] as const;

export interface Possession {
  id: string;
  name: string;
  kind: string;
  owner: string | null;
  owner_id: string | null;
  location: string;
  value_gp: number;
  description: string;
  notes_md: string;
  inventory: string[];
  stats: Record<string, unknown>;
  portrait: Portrait | null;
}

/** What a possession's form sends: `owner` is a character's id or name, "" for the party. */
export type PossessionInput = Partial<Omit<Possession, "id" | "owner_id" | "portrait" | "owner">> & {
  owner?: string;
  species?: string;
};

const worldRecord = (id: string, collection: string, recordId?: string | number) =>
  `${campaignPath(id)}/${collection}${recordId === undefined ? "" : `/${encodeURIComponent(String(recordId))}`}`;
export const listFactions = (id: string) => apiFetch<Faction[]>(worldRecord(id, "factions"));
export const putFaction = (id: string, factionId: string, faction: Partial<Faction>) =>
  putJson<Faction>(worldRecord(id, "factions", factionId), faction);
export const deleteFaction = (id: string, factionId: string) => deleteJson(worldRecord(id, "factions", factionId));
export const listClocks = (id: string) => apiFetch<Clock[]>(worldRecord(id, "clocks"));
export const addClock = (id: string, clock: Partial<Clock>) => postJson<Clock>(worldRecord(id, "clocks"), clock);
export const putClock = (id: string, clockId: number, clock: Partial<Clock>) =>
  putJson<Clock>(worldRecord(id, "clocks", clockId), clock);
export const deleteClock = (id: string, clockId: number) => deleteJson(worldRecord(id, "clocks", clockId));
export const listQuests = (id: string) => apiFetch<Quest[]>(worldRecord(id, "quests"));
export const putQuest = (id: string, questId: string, quest: Partial<Quest>) =>
  putJson<Quest>(worldRecord(id, "quests", questId), quest);
export const deleteQuest = (id: string, questId: string) => deleteJson(worldRecord(id, "quests", questId));
export const listPossessions = (id: string) => apiFetch<Possession[]>(worldRecord(id, "possessions"));
export const addPossession = (id: string, possession: PossessionInput) =>
  postJson<Possession>(worldRecord(id, "possessions"), possession);
export const putPossession = (id: string, possessionId: string, possession: PossessionInput) =>
  putJson<Possession>(worldRecord(id, "possessions", possessionId), possession);
export const deletePossession = (id: string, possessionId: string) =>
  deleteJson(worldRecord(id, "possessions", possessionId));

export const queryKeys = {
  backends: ["backends"],
  preferences: ["preferences"],
  modules: ["modules"],
  moduleCategories: ["module-categories"],
  module: (id: string) => ["module", id],
  moduleMetadata: (id: string) => ["module", id, "metadata"],
  map: (id: string, name: string) => ["module", id, "map", name],
  moduleSource: (id: string) => ["module", id, "source"],
  conversions: ["conversions"],
  conversion: (id: string) => ["conversions", id],
  conversionOptions: ["conversion-options"],
  conversionQueue: ["conversion-queue"],
  campaigns: ["campaigns"],
  worlds: ["worlds"],
  campaign: (id: string) => ["campaign", id],
  ownMaps: (campaignId: string) => ["campaign", campaignId, "own-maps"],
  ownMap: (campaignId: string, name: string) => ["campaign", campaignId, "own-maps", name],
  characters: (id: string) => ["campaign", id, "characters"],
  /** Under `characters`, so that a `characters` event refreshes it too. */
  dmCharacters: (id: string) => ["campaign", id, "characters", "dm"],
  dmCosts: (id: string) => ["campaign", id, "dm-costs"],
  history: (id: string) => ["campaign", id, "history"],
  /** Everything about one map state: the state and both views. */
  mapState: (id: string, map: string) => ["campaign", id, "map", map],
  /** Everything about house rules starts with this key, so one `house_rules` event refreshes it all. */
  houseRules: ["house-rules"],
  bundles: ["house-rules", "bundles"],
  campaignHouseRules: (id: string) => ["house-rules", "campaign", id],
  /** The campaign's world for the organisers, under the play screen's `world` key: one `world` event refreshes both. */
  campaignWorld: (id: string, part: string) => ["campaign", id, "world", part],
} as const;
