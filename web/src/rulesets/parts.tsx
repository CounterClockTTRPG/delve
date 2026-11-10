// What the Rulesets screens share: the campaign kept in the address, the labels with the raw value as their fallback,
// the way back, and a table drawn from whatever rows the book gives.
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Fragment, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, NeedsToken } from "../api";
import { useT, type Translate } from "../i18n";
import { isOrganiser } from "../account/api";
import { useMe } from "../account/useMe";
import { getRuleset, rulesetKeys } from "./api";
import styles from "./Rulesets.module.css";

/** An organiser's choice of campaign, from the address (`?campaign=`), or null. */
export function useCampaign(): string | null {
  const [params] = useSearchParams();
  return params.get("campaign") || null;
}

/** `path` with the campaign's `?campaign=` kept, so every link of the area shows the same house rules. */
export function withCampaign(path: string, campaign: string | null): string {
  return campaign ? `${path}?campaign=${encodeURIComponent(campaign)}` : path;
}

export const rulesetHref = (rulesetId: string) => `/rulesets/${encodeURIComponent(rulesetId)}`;
export const sectionHref = (rulesetId: string, section: string) =>
  `${rulesetHref(rulesetId)}/${encodeURIComponent(section)}`;
export const entryHref = (rulesetId: string, section: string, id: string) =>
  `${sectionHref(rulesetId, section)}/${encodeURIComponent(id)}`;

/** `key` translated, or `fallback` when the dictionaries don't have it. */
function labelled(t: Translate, key: string, fallback: string): string {
  const text = t(key);
  return text === key ? fallback : text;
}

export const sectionLabel = (t: Translate, key: string) => labelled(t, `rulesets.section.${key}`, key);
/** What a section holds, in a line; nothing for a section Delve has no words for. */
export const sectionLine = (t: Translate, key: string) => labelled(t, `rulesets.sectionLine.${key}`, "");
export const fieldLabel = (t: Translate, key: string) => labelled(t, `rulesets.field.${key}`, key);
export const facetLabel = (t: Translate, key: string) => labelled(t, `rulesets.facet.${key}`, fieldLabel(t, key));

/** A value in words: an item type through `rulesets.itemType.*`, a facet's value (size M, alignment NE, rarity
 * very rare…) through `rulesets.value.<facet>.*`; anything else, and any value Delve has no words for, as it is. */
export function valueLabel(t: Translate, key: string, value: unknown): string {
  const raw = cellText(t, value);
  if (typeof value !== "string" || !raw) return raw;
  if (key === "item_type") return labelled(t, `rulesets.itemType.${value}`, raw);
  return labelled(t, `rulesets.value.${key}.${value.trim().toLowerCase().replace(/[\s-]+/g, "_")}`, raw);
}

/** Any value as text: a list joined by commas, an object as `key: value` pairs, nothing for null. */
export function cellText(t: Translate, value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return t(value ? "rulesets.yes" : "rulesets.no");
  if (Array.isArray(value)) return value.map((v) => cellText(t, v)).join(", ");
  if (typeof value === "object")
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${fieldLabel(t, k)}: ${cellText(t, v)}`)
      .join("; ");
  return String(value);
}

/** The ruleset's page, which the section and entry pages read for their way back (and the sections the reader may
 * see). */
export function useRuleset(rulesetId: string) {
  const campaign = useCampaign();
  // Another campaign's house rules replace the page's counts without emptying it (and its search box) first.
  return useQuery({
    queryKey: rulesetKeys.one(rulesetId, campaign),
    queryFn: () => getRuleset(rulesetId, campaign),
    placeholderData: keepPreviousData,
  });
}

/** A seat's way back from the area to its table (the play header's Rulesets link opened the area in a new tab, and a
 * seat has no nav); a player account's is to the table whose `?campaign=` it came with. Nothing for the owner and
 * organisers without a seat. */
export function BackToTable() {
  const t = useT();
  const campaign = useCampaign();
  const me = useMe();
  const account = me.data?.account;
  const table = me.data?.seat?.campaign_id ?? (account && !isOrganiser(account) ? campaign : null);
  if (!table) return null;
  return (
    <p className={styles.back}>
      <Link to={`/play/${encodeURIComponent(table)}`}>{t("rulesets.backToTable")}</Link>
    </p>
  );
}

/** Rulesets › the ruleset › its section, each a link that keeps the campaign. The section shows only when the reader
 * may see it, so a page that isn't there names nothing. */
export function Crumbs({ rulesetId, section }: { rulesetId: string; section?: string }) {
  const t = useT();
  const campaign = useCampaign();
  const ruleset = useRuleset(rulesetId);
  const shown = section && ruleset.data?.sections.some((s) => s.key === section);
  return (
    <>
      <BackToTable />
      <nav className={styles.crumbs} aria-label={t("rulesets.crumbs")}>
        <Link to={withCampaign("/rulesets", campaign)}>{t("rulesets.title")}</Link>
        {section !== undefined && (
          <>
            <span aria-hidden="true">›</span>
            <Link to={withCampaign(rulesetHref(rulesetId), campaign)}>{ruleset.data?.title ?? rulesetId}</Link>
          </>
        )}
        {shown && (
          <>
            <span aria-hidden="true">›</span>
            <Link to={withCampaign(sectionHref(rulesetId, section), campaign)}>{sectionLabel(t, section)}</Link>
          </>
        )}
      </nav>
    </>
  );
}

export const isNotFound = (error: unknown) => error instanceof ApiError && error.status === 404;

/** The error to show: none for a missing token (the gate takes over) or a "not found" (its own page). */
export function failure(error: Error | null): Error | null {
  return error && !(error instanceof NeedsToken) && !isNotFound(error) ? error : null;
}

export function NotFound() {
  const t = useT();
  return <p className="placeholder">{t("rulesets.notFound")}</p>;
}

export function LoadFailed({ error }: { error: Error | null }) {
  const t = useT();
  const shown = failure(error);
  if (!shown) return null;
  return (
    <p role="alert" className="notice error">
      {t("rulesets.loadFailed", { error: shown.message })}
    </p>
  );
}

export function HouseRuleTag() {
  const t = useT();
  return <span className={`tag ${styles.houseRule}`}>{t("rulesets.houseRule")}</span>;
}

type Rows = Record<string, unknown>[];

/** A table section's tables, as the rulebook gives them: each `{key, note, rows}`. */
type SubTable = { key: string; note?: unknown; rows: Rows };
const isSubTable = (value: unknown): value is SubTable =>
  isRecord(value) && typeof value.key === "string" && Array.isArray(value.rows) && value.rows.every(isRecord);

/** A table's heading: the section's name for its own table, else the field's (`crossover`), else the key. */
const tableLabel = (t: Translate, key: string) => labelled(t, `rulesets.section.${key}`, fieldLabel(t, key));

/**
 * A table section's page: each of its tables with its note (in the book's English) under a heading, but the section's
 * one table under the page's own. Anything of another shape is drawn as `DataTable` draws it.
 */
export function SectionTables({
  section,
  value,
  link,
}: {
  section: string;
  value: unknown;
  link?: (row: Record<string, unknown>) => string | null;
}) {
  const t = useT();
  if (!Array.isArray(value) || value.length === 0 || !value.every(isSubTable))
    return <DataTable value={value} link={link} />;
  const headed = !(value.length === 1 && value[0].key === section);
  return (
    <div className={styles.blocks}>
      {value.map((table) => (
        <section key={table.key} className={styles.block}>
          {headed && <h2>{tableLabel(t, table.key)}</h2>}
          {typeof table.note === "string" && table.note && <p className="row-meta">{table.note}</p>}
          {table.rows.length > 0 ? (
            <DataTable value={table.rows} link={link} />
          ) : (
            <p className="placeholder">{t("rulesets.emptyTable")}</p>
          )}
        </section>
      ))}
    </div>
  );
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isRows = (value: unknown): value is Rows => Array.isArray(value) && value.length > 0 && value.every(isRecord);

/** The columns of `rows`, in the order they first appear, without the internal `id`. */
function columnsOf(rows: Rows): string[] {
  const seen = new Set<string>();
  for (const row of rows) for (const key of Object.keys(row)) if (key !== "id") seen.add(key);
  return [...seen];
}

/**
 * A table drawn from the book's rows, whatever their columns: their keys are the headings (labelled, the key as the
 * fallback). Rows that hold tables of their own (an ability with its scores) show one by one, their plain values as a
 * list and each of their tables under it. `link` gives a row's entry page, when it has one. The table scrolls on its
 * own, so the page never scrolls sideways.
 */
export function DataTable({ value, link }: { value: unknown; link?: (row: Record<string, unknown>) => string | null }) {
  const t = useT();
  if (isRows(value)) {
    if (value.some((row) => Object.values(row).some(isRows)))
      return (
        <div className={styles.blocks}>
          {value.map((row, i) => (
            <Block key={i} row={row} link={link} />
          ))}
        </div>
      );
    const columns = columnsOf(value);
    return (
      <div className={styles.tableScroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} scope="col">
                  {fieldLabel(t, c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {value.map((row, i) => {
              const to = link?.(row);
              return (
                <tr key={i}>
                  {columns.map((c, n) => (
                    <td key={c}>{n === 0 && to ? <Link to={to}>{valueLabel(t, c, row[c])}</Link> : valueLabel(t, c, row[c])}</td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }
  if (isRecord(value)) return <Block row={value} link={link} />;
  const text = cellText(t, value);
  return text ? <p>{text}</p> : null;
}

/** One row that holds tables: its name as a heading, its plain values as fields, then its tables. */
function Block({
  row,
  link,
}: {
  row: Record<string, unknown>;
  link?: (row: Record<string, unknown>) => string | null;
}) {
  const t = useT();
  const nameKey = ["name", "ability", "title"].find((k) => typeof row[k] === "string" && row[k]);
  const to = link?.(row);
  const plain = Object.entries(row).filter(
    ([k, v]) => k !== "id" && k !== nameKey && !isRows(v) && cellText(t, v) !== "",
  );
  const tables = Object.entries(row).filter(([, v]) => isRows(v));
  return (
    <section className={styles.block}>
      {nameKey && <h2>{to ? <Link to={to}>{String(row[nameKey])}</Link> : String(row[nameKey])}</h2>}
      {plain.length > 0 && <Fields fields={Object.fromEntries(plain)} />}
      {tables.map(([key, rows]) => (
        <Fragment key={key}>
          {key !== "rows" && <h3>{fieldLabel(t, key)}</h3>}
          <DataTable value={rows} />
        </Fragment>
      ))}
    </section>
  );
}

/** Fields as a list of labels and values; the empty ones are left out. */
export function Fields({ fields }: { fields: Record<string, unknown> }): ReactNode {
  const t = useT();
  const shown = Object.entries(fields).filter(([, v]) => cellText(t, v) !== "");
  if (shown.length === 0) return null;
  return (
    <dl className={styles.fields}>
      {shown.map(([key, value]) => (
        <Fragment key={key}>
          <dt>{fieldLabel(t, key)}</dt>
          <dd>{valueLabel(t, key, value)}</dd>
        </Fragment>
      ))}
    </dl>
  );
}
