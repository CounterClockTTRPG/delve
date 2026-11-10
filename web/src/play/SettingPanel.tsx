import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Suspense, lazy, useState, type MouseEvent } from "react";
import { ApiError, NeedsToken } from "../api";
import { useDebounce } from "../editor/useDebounce";
import { useT } from "../i18n";
import { originTag, Snippet } from "../setting/LoreTab";
import SettingText from "../setting/SettingText";
import {
  browseTableKind,
  getTableFacts,
  getTablePage,
  getTableSetting,
  getTableSettingMapView,
  listTableSettingMaps,
  searchTableSetting,
  settingKeys,
  tableSettingTileUrl,
  type SettingHit,
  type TableSetting,
} from "../setting/api";
import { usePhone } from "./usePhone";

// Leaflet comes with the map, in its own chunk, as in the World panel.
const WorldMapView = lazy(() => import("../worldmap/WorldMapView"));

type View = "lore" | "facts" | "maps";
const VIEWS: View[] = ["lore", "facts", "maps"];

/**
 * The play screen's Setting tab (settings plan, Task 14): the campaign's setting as a seat may know it, through the
 * table's own routes, which leave out every DM-only page, section, fact and map feature on the server. Three views:
 * Lore (a search, the kinds, a page read in place, its links followed in the panel with a Back), Facts (the
 * campaign's marked) and Maps (the setting's ready world maps, whole). Read-only, whoever's seat it is.
 */
export default function SettingPanel({ campaignId }: { campaignId: string }) {
  const t = useT();
  const [view, setView] = useState<View>("lore");
  const setting = useQuery({ queryKey: settingKeys.table(campaignId), queryFn: () => getTableSetting(campaignId) });
  const none = setting.error instanceof ApiError && setting.error.status === 404;
  const failed = setting.error && !none && !(setting.error instanceof NeedsToken) ? setting.error : null;

  return (
    <section className="setting-panel" aria-label={t("play.setting")} data-testid="setting-panel">
      {setting.data && <h2>{setting.data.title}</h2>}
      {none && <p className="placeholder">{t("play.setting.none")}</p>}
      {failed && (
        <p role="alert" className="notice error">
          {t("setting.loadFailed", { error: failed.message })}
        </p>
      )}
      {setting.data && (
        <>
          <div className="side-tabs" role="tablist" aria-label={t("play.setting")}>
            {VIEWS.map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                id={`setting-view-${v}`}
                aria-selected={view === v}
                aria-controls="setting-view-panel"
                onClick={() => setView(v)}
              >
                {t(`play.setting.${v}`)}
              </button>
            ))}
          </div>
          <div id="setting-view-panel" role="tabpanel" aria-labelledby={`setting-view-${view}`}>
            {view === "lore" ? (
              <Lore campaignId={campaignId} setting={setting.data} />
            ) : view === "facts" ? (
              <Facts campaignId={campaignId} />
            ) : (
              <Maps campaignId={campaignId} />
            )}
          </div>
        </>
      )}
    </section>
  );
}

/** A hit as a button that opens its page in the panel; a fact has no page. */
function Hit({ hit, onOpen }: { hit: SettingHit; onOpen: (title: string) => void }) {
  const t = useT();
  return (
    <li className="row">
      {hit.kind === "fact" ? (
        <span className="row-title">{hit.title}</span>
      ) : (
        <button type="button" className="link-button row-title" onClick={() => onOpen(hit.title)}>
          {hit.title}
        </button>
      )}
      {hit.kind && hit.kind !== "fact" && <span className="row-meta">{hit.kind}</span>}
      {originTag(t, hit.origin)}
      {hit.text && <Snippet text={hit.text} />}
    </li>
  );
}

function Lore({ campaignId, setting }: { campaignId: string; setting: TableSetting }) {
  const t = useT();
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<string | null>(null);
  // The pages opened, the last one shown; Back closes it.
  const [trail, setTrail] = useState<string[]>([]);
  const query = useDebounce(q.trim(), 300);
  const key = settingKeys.table(campaignId);
  const hits = useQuery({
    queryKey: [...key, "search", query],
    queryFn: () => searchTableSetting(campaignId, query),
    enabled: query !== "",
    placeholderData: keepPreviousData,
  });
  const rows = useQuery({
    queryKey: [...key, "kind", kind],
    queryFn: () => browseTableKind(campaignId, kind!),
    enabled: kind !== null,
  });
  const open = (title: string) => setTrail((was) => [...was, title]);
  const shown = trail.at(-1);

  if (shown !== undefined)
    return <Page campaignId={campaignId} title={shown} onOpen={open} onBack={() => setTrail((was) => was.slice(0, -1))} />;

  const failed = [hits.error, rows.error].find((e) => e && !(e instanceof NeedsToken));
  return (
    <div className="setting-lore">
      <input
        type="search"
        aria-label={t("setting.search")}
        placeholder={t("setting.search")}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
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
              <Hit key={`${hit.kind}:${hit.key}`} hit={hit} onOpen={open} />
            ))}
          </ul>
        ))}
      {setting.kinds.length > 0 && (
        <fieldset className="chips" role="group" aria-labelledby="setting-panel-kinds">
          <legend id="setting-panel-kinds">{t("setting.kinds")}</legend>
          {setting.kinds.map((k) => (
            <button key={k} type="button" className="chip" aria-pressed={kind === k} onClick={() => setKind(kind === k ? null : k)}>
              {k}
            </button>
          ))}
        </fieldset>
      )}
      {kind !== null &&
        rows.data &&
        (rows.data.length === 0 ? (
          <p className="placeholder">{t("setting.noHits")}</p>
        ) : (
          <ul className="rows">
            {rows.data.map((hit) => (
              <Hit key={hit.key} hit={hit} onOpen={open} />
            ))}
          </ul>
        ))}
    </div>
  );
}

/** A page read in place; a link in it opens the next page here, never a route of the Settings area. */
function Page({
  campaignId,
  title,
  onOpen,
  onBack,
}: {
  campaignId: string;
  title: string;
  onOpen: (title: string) => void;
  onBack: () => void;
}) {
  const t = useT();
  const page = useQuery({
    queryKey: [...settingKeys.table(campaignId), "page", title],
    queryFn: () => getTablePage(campaignId, title),
  });
  // Caught before SettingText's own handler, which would navigate.
  const follow = (e: MouseEvent<HTMLDivElement>) => {
    const link = (e.target as HTMLElement).closest("a[data-page]");
    if (!link) return;
    e.preventDefault();
    e.stopPropagation();
    onOpen(link.getAttribute("data-page")!);
  };
  const data = page.data;
  const fields = data ? Object.entries(data.fields) : [];
  return (
    <article className="setting-page">
      <button type="button" className="phone-back" onClick={onBack}>
        {t("play.setting.back")}
      </button>
      {page.error && !(page.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {page.error.message}
        </p>
      )}
      {data && (
        <>
          <h3>{data.title}</h3>
          <p className="row-meta">
            {data.kind}
            {data.origin === "proposal" ? (
              <> <span className="tag">{t("play.setting.thisCampaign")}</span></>
            ) : (
              originTag(t, data.origin)
            )}
          </p>
          {fields.length > 0 && (
            <dl className="setting-fields">
              {fields.map(([name, value]) => (
                <div key={name}>
                  <dt>{name}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          )}
          <div onClickCapture={follow}>
            <SettingText text={data.text} pageHref={(target) => `#${encodeURIComponent(target)}`} dmMarked={false} />
          </div>
        </>
      )}
    </article>
  );
}

function Facts({ campaignId }: { campaignId: string }) {
  const t = useT();
  const facts = useQuery({ queryKey: [...settingKeys.table(campaignId), "facts"], queryFn: () => getTableFacts(campaignId) });
  if (facts.error && !(facts.error instanceof NeedsToken))
    return (
      <p role="alert" className="notice error">
        {t("setting.loadFailed", { error: facts.error.message })}
      </p>
    );
  if (!facts.data) return null;
  if (facts.data.length === 0) return <p className="placeholder">{t("play.setting.noFacts")}</p>;
  return (
    <ul className="rows setting-facts">
      {facts.data.map((fact, i) => (
        <li key={i} className="row">
          <span>{fact.text}</span>
          {fact.origin === "campaign" && <span className="tag">{t("play.setting.thisCampaign")}</span>}
        </li>
      ))}
    </ul>
  );
}

function Maps({ campaignId }: { campaignId: string }) {
  const t = useT();
  const phone = usePhone();
  const key = settingKeys.table(campaignId);
  const maps = useQuery({ queryKey: [...key, "maps"], queryFn: () => listTableSettingMaps(campaignId) });
  const [picked, setPicked] = useState<string | null>(null);
  const listed = maps.data ?? [];
  const shown = listed.find((m) => m.name === picked) ?? listed[0] ?? null;
  const view = useQuery({
    queryKey: [...key, "maps", shown?.name, "view"],
    queryFn: () => getTableSettingMapView(campaignId, shown!.name),
    enabled: shown !== null,
  });
  const seen = view.data && view.data.name === shown?.name ? view.data : null;

  if (maps.data && listed.length === 0) return <p className="placeholder">{t("play.setting.noMaps")}</p>;
  return (
    <>
      {listed.length > 0 && (
        <div className="field world-map-picker">
          <label htmlFor="setting-map-picker">{t("world.map")}</label>
          <select id="setting-map-picker" value={shown?.name ?? ""} onChange={(e) => setPicked(e.target.value)}>
            {listed.map((m) => (
              <option key={m.name} value={m.name}>
                {m.title || m.name}
              </option>
            ))}
          </select>
        </div>
      )}
      {view.isError ? (
        <p role="status" className="offline">
          {t("mapState.offline")}
        </p>
      ) : (
        seen && (
          <div className={phone ? "world-map world-map-full" : "world-map"}>
            <Suspense fallback={null}>
              <WorldMapView
                view={seen}
                tileUrl={seen.picture ? tableSettingTileUrl(campaignId, seen.name, seen.tiles_version) : null}
              />
            </Suspense>
          </div>
        )
      )}
    </>
  );
}
