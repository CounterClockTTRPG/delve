// The Settings area's calls (organisers, `/api/settings/...`) and the play screen's Setting tab's (a seat,
// `/api/campaigns/{id}/setting/...`, read-only and without DM-only content). Every title is encodeURIComponent'd.
import { apiFetch, deleteJson, postJson, putJson } from "../api";
import type { SeatView } from "../worldmap/api";

export interface SettingSummary {
  id: string;
  title: string;
}

export interface CalendarMonth {
  name: string;
  days: number;
  season: string;
  weather_season: string;
  festival: boolean;
}

export interface CalendarView {
  id: string;
  era: string;
  months: CalendarMonth[];
  /** [year, day of the year]. */
  default_start: [number, number];
}

export interface SettingInfo {
  id: string;
  title: string;
  kinds: string[];
  calendar: CalendarView | null;
  /** The install's pages and facts, and the pending proposals. */
  counts: { pages: number; facts: number; proposals: number };
  maps_in_use: "install" | "built-in";
  built_in_maps: { name: string; title: string }[];
}

/** What a seat may know of its campaign's setting. */
export type TableSetting = Pick<SettingInfo, "id" | "title" | "kinds" | "calendar">;

export type SettingOrigin = "shipped" | "addition" | "override" | "proposal";

/** A search or browse hit. `text` is a snippet with the words found marked `<<…>>`. */
export interface SettingHit {
  kind: string;
  key: string;
  title: string;
  text: string;
  origin: SettingOrigin | "fact";
  campaign_id?: string | null;
}

export interface SettingPage {
  title: string;
  kind: string;
  fields: Record<string, string>;
  /** Always Markdown, with `[[Target|label]]` links and `::: dm` sections. */
  text: string;
  categories: string[];
  origin: SettingOrigin;
  dm_only: boolean;
  campaign_id: string | null;
  /** An override, which a DELETE reverts to the shipped page. */
  revertible: boolean;
  /** The title asked for, when a redirect led elsewhere. */
  redirected_from: string | null;
}

export interface PageInput {
  kind: string;
  fields: Record<string, string>;
  text: string;
  dm_only: boolean;
}

export interface SettingFact {
  id: number;
  text: string;
  category: string;
  dm_only: boolean;
  created_at: string;
}

export interface ShippedFact {
  id: number;
  text: string;
  category: string;
}

export interface FactInput {
  text: string;
  category: string;
  dm_only: boolean;
}

export interface TableFact {
  text: string;
  category: string;
  origin: "shipped" | "install" | "campaign";
}

export interface Proposal {
  id: number;
  campaign_id: string;
  campaign_title: string;
  kind: "page" | "edit" | "fact";
  title: string;
  text: string;
  mode: "append" | "replace";
  page_kind: string;
  category: string;
  dm_only: boolean;
  status: "pending" | "accepted" | "rejected";
  created_at: string;
  decided_at: string | null;
}

/** What an organiser may change in a pending proposal; every field optional. */
export type ProposalEdit = Partial<Pick<Proposal, "title" | "text" | "category" | "page_kind" | "dm_only">>;

/** An accepted proposal and what it became: a page for a new page or an edit, a fact for a fact. */
export type Accepted = { proposal: Proposal } & ({ page: SettingPage } | { fact: SettingFact });

interface Hits {
  results: SettingHit[];
}

const settingPath = (id: string) => `/api/settings/${encodeURIComponent(id)}`;
const tablePath = (campaignId: string) => `/api/campaigns/${encodeURIComponent(campaignId)}/setting`;
const pagePath = (base: string, title: string) => `${base}/pages/${encodeURIComponent(title)}`;

function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== "") q.set(key, String(value));
  const s = q.toString();
  return s ? `?${s}` : "";
}

const search = (base: string, q: string, limit?: number) =>
  apiFetch<Hits>(`${base}/search${query({ q, limit })}`).then((r) => r.results);
const browse = (base: string, kind: string, q?: string) =>
  apiFetch<Hits>(`${base}/kinds/${encodeURIComponent(kind)}${query({ q })}`).then((r) => r.results);

// The organisers'.

export const listSettings = () => apiFetch<SettingSummary[]>("/api/settings");
export const getSetting = (id: string) => apiFetch<SettingInfo>(settingPath(id));
export const searchSetting = (id: string, q: string, limit = 10) => search(settingPath(id), q, limit);
export const browseKind = (id: string, kind: string, q?: string) => browse(settingPath(id), kind, q);
export const getPage = (id: string, title: string) => apiFetch<SettingPage>(pagePath(settingPath(id), title));
export const putPage = (id: string, title: string, body: PageInput) => putJson<SettingPage>(pagePath(settingPath(id), title), body);
export const deletePage = (id: string, title: string) => deleteJson(pagePath(settingPath(id), title));
export const getFacts = (id: string) => apiFetch<{ shipped: ShippedFact[]; own: SettingFact[] }>(`${settingPath(id)}/facts`);
export const addFact = (id: string, body: FactInput) => postJson<SettingFact>(`${settingPath(id)}/facts`, body);
export const putFact = (id: string, factId: number, body: FactInput) => putJson<SettingFact>(`${settingPath(id)}/facts/${factId}`, body);
export const deleteFact = (id: string, factId: number) => deleteJson(`${settingPath(id)}/facts/${factId}`);
export const listProposals = (id: string, status = "pending") =>
  apiFetch<Proposal[]>(`${settingPath(id)}/proposals${query({ status })}`);
export const editProposal = (id: string, pid: number, body: ProposalEdit) =>
  putJson<Proposal>(`${settingPath(id)}/proposals/${pid}`, body);
export const acceptProposal = (id: string, pid: number) => postJson<Accepted>(`${settingPath(id)}/proposals/${pid}/accept`);
export const rejectProposal = (id: string, pid: number) => postJson<Proposal>(`${settingPath(id)}/proposals/${pid}/reject`);

// The table's.

export const getTableSetting = (campaignId: string) => apiFetch<TableSetting>(tablePath(campaignId));
export const searchTableSetting = (campaignId: string, q: string) => search(tablePath(campaignId), q);
export const browseTableKind = (campaignId: string, kind: string, q?: string) => browse(tablePath(campaignId), kind, q);
export const getTablePage = (campaignId: string, title: string) => apiFetch<SettingPage>(pagePath(tablePath(campaignId), title));
export const getTableFacts = (campaignId: string) =>
  apiFetch<{ facts: TableFact[] }>(`${tablePath(campaignId)}/facts`).then((r) => r.facts);

// The setting's ready world maps, as a seat sees them: the whole map, without a hidden feature or the DM's notes.
const tableMapPath = (campaignId: string, name: string) => `${tablePath(campaignId)}/maps/${encodeURIComponent(name)}`;
export const listTableSettingMaps = (campaignId: string) =>
  apiFetch<{ name: string; title: string }[]>(`${tablePath(campaignId)}/maps`);
export const getTableSettingMapView = (campaignId: string, name: string) =>
  apiFetch<SeatView>(`${tableMapPath(campaignId, name)}/view`);
/** Leaflet's URL template for a setting map's tiles; `version` is the view's `tiles_version`. */
export const tableSettingTileUrl = (campaignId: string, name: string, version: string) =>
  `${tableMapPath(campaignId, name)}/tiles/{z}/{x}/{y}?v=${encodeURIComponent(version)}`;

/** Every query of a setting starts with ["setting", id], which its `setting` event invalidates. */
export const settingKeys = {
  list: ["settings"],
  one: (id: string) => ["setting", id],
  search: (id: string, q: string) => ["setting", id, "search", q],
  kind: (id: string, kind: string, q: string) => ["setting", id, "kind", kind, q],
  page: (id: string, title: string) => ["setting", id, "page", title],
  facts: (id: string) => ["setting", id, "facts"],
  proposals: (id: string) => ["setting", id, "proposals"],
  table: (campaignId: string) => ["campaign", campaignId, "setting"],
};
