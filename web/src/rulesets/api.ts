// The Rulesets area's calls (`/api/rulesets/...`, plan Rulesets Task 5): every seat and organiser reads them; the
// server decides what each reader may see (no monsters without the organiser role, no house rule's DM Notes).
// `campaign` is an organiser's choice of whose house rules to see beside the book; a seat's is ignored.
import { apiFetch } from "../api";

export interface RulesetSummary {
  id: string;
  title: string;
}

export interface SectionSummary {
  key: string;
  /** A list has a page per entry; a table's section page is the table itself. */
  kind: "list" | "table";
  count: number;
}

export interface RulesetInfo {
  id: string;
  title: string;
  sections: SectionSummary[];
  /** The campaign whose house rules are shown beside the book; null for none. */
  campaign_id: string | null;
  /** What the ruleset's licence asks to be said of it ("" for none); left out by an older server. */
  notice?: string;
}

export interface SearchHit {
  section: string;
  id: string;
  name: string;
}

export interface FacetOption {
  value: string | number;
  count: number;
}

export interface Facet {
  key: string;
  options: FacetOption[];
}

/** A list's row: its id and name, the section's columns (spells: caster, level, school; …), and whether it is a
 * house rule. */
export interface Row {
  id: string;
  name: string;
  house_rule: boolean;
  [column: string]: unknown;
}

export type TableRows = Record<string, unknown>[];

export type SectionView =
  | { kind: "list"; facets: Facet[]; total: number; offset: number; rows: Row[] }
  | { kind: "table"; table: unknown };

export interface Entry {
  section: string;
  id: string;
  name: string;
  /** Plain keys (`casting_time`), labelled by the web app. */
  fields: Record<string, unknown>;
  /** Markdown. */
  text: string;
  table: unknown;
  house_rule: boolean;
}

/** The list's page size, as the server's default. */
export const PAGE_SIZE = 50;

const rulesetPath = (id: string) => `/api/rulesets/${encodeURIComponent(id)}`;

/** `?campaign=<id>`, or nothing. */
export function campaignQuery(campaign: string | null | undefined): string {
  return campaign ? `?campaign=${encodeURIComponent(campaign)}` : "";
}

export const listRulesets = () => apiFetch<RulesetSummary[]>("/api/rulesets");
export const getRuleset = (id: string, campaign: string | null) =>
  apiFetch<RulesetInfo>(`${rulesetPath(id)}${campaignQuery(campaign)}`);
export const searchRuleset = (id: string, q: string, campaign: string | null) => {
  const params = new URLSearchParams({ q });
  if (campaign) params.set("campaign", campaign);
  return apiFetch<{ results: SearchHit[] }>(`${rulesetPath(id)}/search?${params}`).then((r) => r.results);
};
/** `search` is the address's query string, passed on as it is (filters, offset, campaign). */
export const getSection = (id: string, section: string, search: string) =>
  apiFetch<SectionView>(`${rulesetPath(id)}/${encodeURIComponent(section)}${search}`);
export const getEntry = (id: string, section: string, entryId: string, campaign: string | null) =>
  apiFetch<Entry>(
    `${rulesetPath(id)}/${encodeURIComponent(section)}/${encodeURIComponent(entryId)}${campaignQuery(campaign)}`,
  );

/** Every query of the area starts with ["rulesets"]. */
export const rulesetKeys = {
  list: ["rulesets"],
  one: (id: string, campaign: string | null) => ["rulesets", id, campaign],
  search: (id: string, q: string, campaign: string | null) => ["rulesets", id, campaign, "search", q],
  section: (id: string, section: string, search: string) => ["rulesets", id, "section", section, search],
  entry: (id: string, section: string, entryId: string, campaign: string | null) => [
    "rulesets",
    id,
    campaign,
    "entry",
    section,
    entryId,
  ],
};
