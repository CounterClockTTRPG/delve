import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { useDebounce } from "../editor/useDebounce";
import { useT } from "../i18n";
import { PAGE_SIZE, getSection, rulesetKeys, type Facet, type Row } from "./api";
import {
  Crumbs,
  HouseRuleTag,
  LoadFailed,
  NotFound,
  SectionTables,
  entryHref,
  facetLabel,
  fieldLabel,
  isNotFound,
  sectionLabel,
  useCampaign,
  valueLabel,
  withCampaign,
} from "./parts";
import styles from "./Rulesets.module.css";

/** A row's own columns, which show beside its name. */
const NOT_COLUMNS = new Set(["id", "name", "house_rule"]);

/**
 * `/rulesets/:rulesetId/:section`: a list's rows a page at a time, narrowed by name (250 ms after the last key) and by
 * its facets, or a table section's table. The filters and the offset live in the address, which goes to the API as
 * it is, so a filtered list can be linked, reloaded and reached with Back.
 */
export default function SectionPage() {
  const t = useT();
  const { rulesetId = "", section = "" } = useParams();
  const { search } = useLocation();
  const [params, setParams] = useSearchParams();
  const campaign = useCampaign();
  const view = useQuery({
    queryKey: rulesetKeys.section(rulesetId, section, search),
    queryFn: () => getSection(rulesetId, section, search),
    placeholderData: keepPreviousData,
  });
  const data = view.data;

  // A change of filter starts from the first page.
  const filter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next, { replace: true });
  };
  const goTo = (offset: number) => {
    const next = new URLSearchParams(params);
    if (offset > 0) next.set("offset", String(offset));
    else next.delete("offset");
    setParams(next);
  };

  return (
    <section className="page">
      <Crumbs rulesetId={rulesetId} section={section} />
      <LoadFailed error={view.error} />
      {isNotFound(view.error) && <NotFound />}

      {data && !isNotFound(view.error) && (
        <>
          <h1>{sectionLabel(t, section)}</h1>
          {data.kind === "table" ? (
            <SectionTables
              section={section}
              value={data.table}
              link={(row) => (typeof row.id === "string" ? withCampaign(entryHref(rulesetId, section, row.id), campaign) : null)}
            />
          ) : (
            <>
              <div className={styles.filters}>
                <NameFilter value={params.get("q") ?? ""} onChange={(q) => filter("q", q)} />
                {data.facets.map((facet) => (
                  <FacetSelect key={facet.key} facet={facet} value={params.get(facet.key) ?? ""} onChange={(v) => filter(facet.key, v)} />
                ))}
              </div>

              {data.rows.length === 0 ? (
                <p className="placeholder">{t("rulesets.noRows")}</p>
              ) : (
                <ul className="rows">
                  {data.rows.map((row) => (
                    <RowItem key={row.id} row={row} href={withCampaign(entryHref(rulesetId, section, row.id), campaign)} />
                  ))}
                </ul>
              )}

              <Pager
                label={t("pager.labelled", { name: sectionLabel(t, section) })}
                offset={data.offset}
                shown={data.rows.length}
                total={data.total}
                size={Number(params.get("limit")) || PAGE_SIZE}
                goTo={goTo}
              />
            </>
          )}
        </>
      )}

      {view.isPending && <p className="placeholder">{t("rulesets.loading")}</p>}
    </section>
  );
}

/** The name filter: typed here, written to the address 250 ms after the last key; Back brings its words back. */
function NameFilter({ value, onChange }: { value: string; onChange: (q: string) => void }) {
  const t = useT();
  const [text, setText] = useState(value);
  const typed = useDebounce(text.trim(), 250);
  useEffect(() => setText(value), [value]);
  useEffect(() => {
    if (typed !== value) onChange(typed);
    // Only the typing writes the address; a new address only sets the box.
  }, [typed]);
  return (
    <div className={`field ${styles.name}`}>
      <label htmlFor="rulesets-filter">{t("rulesets.filterByName")}</label>
      <input id="rulesets-filter" type="search" value={text} onChange={(e) => setText(e.target.value)} />
    </div>
  );
}

/** A facet as a select of `value (count)`, "Any" first. A value in the address that the facet no longer offers stays
 * chosen, so the page says what it shows. */
function FacetSelect({ facet, value, onChange }: { facet: Facet; value: string; onChange: (value: string) => void }) {
  const t = useT();
  const id = `rulesets-facet-${facet.key}`;
  const offered = facet.options.some((o) => String(o.value) === value);
  return (
    <div className="field">
      <label htmlFor={id}>{facetLabel(t, facet.key)}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t("rulesets.any")}</option>
        {value && !offered && <option value={value}>{valueLabel(t, facet.key, value)}</option>}
        {facet.options.map((o) => (
          <option key={String(o.value)} value={String(o.value)}>
            {t("rulesets.option", { value: valueLabel(t, facet.key, String(o.value)), count: String(o.count) })}
          </option>
        ))}
      </select>
    </div>
  );
}

function RowItem({ row, href }: { row: Row; href: string }) {
  const t = useT();
  const columns = Object.entries(row)
    .filter(([key]) => !NOT_COLUMNS.has(key))
    .map(([key, value]) => [key, valueLabel(t, key, value)] as const)
    .filter(([, text]) => text !== "");
  return (
    <li className={`row ${styles.row}`}>
      <Link to={href} className="row-title">
        {row.name}
      </Link>
      {row.house_rule && <HouseRuleTag />}
      {columns.length > 0 && (
        <span className={`row-meta ${styles.columns}`}>
          {columns.map(([key, text]) => (
            <span key={key}>
              {fieldLabel(t, key)}: {text}
            </span>
          ))}
        </span>
      )}
    </li>
  );
}

/** Previous / Next over the server's pages, as `usePages` draws them; nothing when everything fits on one. */
function Pager(props: { label: string; offset: number; shown: number; total: number; size: number; goTo: (offset: number) => void }) {
  const t = useT();
  const { label, offset, shown, total, size, goTo } = props;
  if (total <= size && offset === 0) return null;
  const range = t("pager.range", { from: String(shown ? offset + 1 : 0), to: String(offset + shown), total: String(total) });
  return (
    <nav className="pager" aria-label={label}>
      <button type="button" disabled={offset === 0} onClick={() => goTo(Math.max(0, offset - size))}>
        {t("pager.previous")}
      </button>
      <span className="pager-range">{range}</span>
      <button type="button" disabled={offset + shown >= total} onClick={() => goTo(offset + size)}>
        {t("pager.next")}
      </button>
    </nav>
  );
}
