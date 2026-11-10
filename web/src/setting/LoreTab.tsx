import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Fragment, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { NeedsToken } from "../api";
import { useDebounce } from "../editor/useDebounce";
import { useT, type Translate } from "../i18n";
import { browseKind, searchSetting, settingKeys, type SettingHit } from "./api";
import styles from "./Setting.module.css";

/** Where a page came from, when it isn't the book's: a tag beside it. */
export function originTag(t: Translate, origin: string): ReactNode {
  if (origin !== "addition" && origin !== "override" && origin !== "proposal") return null;
  return <span className="tag">{t(`setting.origin.${origin}`)}</span>;
}

/** A snippet with its `<<…>>` words marked; the rest stays text. */
export function Snippet({ text }: { text: string }) {
  const parts = text.split(/<<(.+?)>>/);
  return (
    <span className="row-meta">
      {parts.map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : <Fragment key={i}>{part}</Fragment>))}
    </span>
  );
}

/** One hit: its page (a fact has none), its kind, its origin and its snippet. */
export function HitRow({ hit, pageHref }: { hit: SettingHit; pageHref: (title: string) => string }) {
  const t = useT();
  return (
    <li className="row">
      {hit.kind === "fact" ? (
        <span className="row-title">{hit.title}</span>
      ) : (
        <Link to={pageHref(hit.title)} className="row-title">
          {hit.title}
        </Link>
      )}
      {hit.kind && hit.kind !== "fact" && <span className="row-meta">{hit.kind}</span>}
      {originTag(t, hit.origin)}
      {hit.text && <Snippet text={hit.text} />}
    </li>
  );
}

/**
 * A setting's lore: a search (300 ms after the last key), the kinds as chips, each listing its pages under a filter,
 * and "Write a page".
 */
export default function LoreTab({ settingId, kinds }: { settingId: string; kinds: string[] }) {
  const t = useT();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const query = useDebounce(q.trim(), 300);
  const filtered = useDebounce(filter.trim(), 300);
  const hits = useQuery({
    queryKey: settingKeys.search(settingId, query),
    queryFn: () => searchSetting(settingId, query),
    enabled: query !== "",
    // The last answer stays on screen while the next one comes.
    placeholderData: keepPreviousData,
  });
  const rows = useQuery({
    queryKey: settingKeys.kind(settingId, kind ?? "", filtered),
    queryFn: () => browseKind(settingId, kind!, filtered || undefined),
    enabled: kind !== null,
    placeholderData: keepPreviousData,
  });
  const base = `/settings/${encodeURIComponent(settingId)}`;
  const pageHref = (title: string) => `${base}/pages/${encodeURIComponent(title)}`;
  const failed = [hits.error, rows.error].find((e) => e && !(e instanceof NeedsToken));

  return (
    <div className={styles.lore}>
      <div className="toolbar">
        <input
          type="search"
          className={styles.search}
          aria-label={t("setting.search")}
          placeholder={t("setting.search")}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Link to={`${base}/new-page`} className="button-like primary">
          {t("setting.writePage")}
        </Link>
      </div>

      {failed && (
        <p role="alert" className="notice error">
          {t("setting.loadFailed", { error: failed.message })}
        </p>
      )}

      {query !== "" &&
        hits.data &&
        (hits.data.length === 0 ? (
          <p className="placeholder">{t("setting.noHits")}</p>
        ) : (
          <ul className="rows">
            {hits.data.map((hit) => (
              <HitRow key={`${hit.kind}:${hit.key}`} hit={hit} pageHref={pageHref} />
            ))}
          </ul>
        ))}

      {kinds.length > 0 && (
        <fieldset className="chips" role="group" aria-labelledby={`${settingId}-kinds`}>
          <legend id={`${settingId}-kinds`}>{t("setting.kinds")}</legend>
          {kinds.map((k) => (
            <button
              key={k}
              type="button"
              className="chip"
              aria-pressed={kind === k}
              onClick={() => {
                setKind(kind === k ? null : k);
                setFilter("");
              }}
            >
              {k}
            </button>
          ))}
        </fieldset>
      )}

      {kind !== null && (
        <div className={styles.browse}>
          <input
            type="search"
            aria-label={t("setting.filter")}
            placeholder={t("setting.filter")}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          {rows.data &&
            (rows.data.length === 0 ? (
              <p className="placeholder">{t("setting.noHits")}</p>
            ) : (
              <ul className="rows">
                {rows.data.map((hit) => (
                  <HitRow key={hit.key} hit={hit} pageHref={pageHref} />
                ))}
              </ul>
            ))}
        </div>
      )}
    </div>
  );
}
