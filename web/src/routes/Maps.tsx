import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { NeedsToken, listCampaigns, listModules, queryKeys } from "../api";
import { usePages } from "../components/Pager";
import { useT } from "../i18n";
import ModuleFilterBar from "../module/ModuleFilterBar";
import { filterModules, useAddressFilter } from "../module/filter";

/**
 * `/maps`: the modules that have maps, 20 a page, each with its count and opening its maps (`/maps/:moduleId`,
 * `ModuleMaps`); the maps themselves are one level down so the page stays short as modules grow (pagination,
 * 2026-10-23). The page and the module filter (backlog 37) are kept in the address.
 */
export default function Maps() {
  const t = useT();
  const modules = useQuery({ queryKey: queryKeys.modules, queryFn: listModules });
  const withMaps = (modules.data ?? []).filter((m) => m.maps.length > 0);
  const [filter, setFilter] = useAddressFilter("page");
  const filtered = filterModules(withMaps, filter);
  const { shown, pager } = usePages(filtered, 20, t("pager.labelled", { name: t("area.modules") }), { param: "page" });

  return (
    <section className="page">
      <h1>{t("area.maps")}</h1>
      {modules.error && !(modules.error instanceof NeedsToken) ? (
        <p role="alert" className="notice error">
          {t("modules.loadFailed", { error: modules.error.message })}
        </p>
      ) : !modules.data ? (
        <p className="placeholder">{t("modules.loading")}</p>
      ) : withMaps.length === 0 ? (
        <p className="placeholder">{t("maps.empty")}</p>
      ) : (
        <>
          <ModuleFilterBar modules={withMaps} value={filter} onChange={setFilter} />
          {filtered.length === 0 && <p className="placeholder">{t("moduleFilter.none")}</p>}
          <ul className="rows">
            {shown.map((m) => (
              <li key={m.id} className="row">
                <Link to={`/maps/${encodeURIComponent(m.id)}`} className="row-title">
                  {m.title}
                </Link>
                <span className="row-meta">
                  {m.maps.length === 1 ? t("modules.mapCount.one") : t("modules.mapCount", { count: String(m.maps.length) })}
                </span>
              </li>
            ))}
          </ul>
          {pager}
        </>
      )}
    </section>
  );
}

/**
 * `/maps/:moduleId`: one module's maps, 20 a page, each linking to its editor; a played map (not a library) also to
 * its DM view in each campaign that plays its module.
 */
export function ModuleMaps() {
  const t = useT();
  const { moduleId = "" } = useParams();
  const modules = useQuery({ queryKey: queryKeys.modules, queryFn: listModules });
  const campaigns = useQuery({ queryKey: queryKeys.campaigns, queryFn: listCampaigns });
  const module = modules.data?.find((m) => m.id === moduleId);
  const { shown, pager } = usePages(module?.maps ?? [], 20, t("pager.labelled", { name: t("area.maps") }), {
    param: "page",
  });
  const playing = campaigns.data?.filter((c) => c.module_id === moduleId) ?? [];

  return (
    <section className="page">
      <p>
        <Link to="/maps">{t("maps.allMaps")}</Link>
      </p>
      {modules.error && !(modules.error instanceof NeedsToken) ? (
        <p role="alert" className="notice error">
          {t("modules.loadFailed", { error: modules.error.message })}
        </p>
      ) : !modules.data ? (
        <p className="placeholder">{t("modules.loading")}</p>
      ) : !module ? (
        <p className="placeholder">{t("maps.noModule")}</p>
      ) : (
        <>
          <h1>{module.title}</h1>
          <p>
            <Link to={`/modules/${encodeURIComponent(module.id)}`}>{t("maps.modulePage")}</Link>
          </p>
          {module.maps.length === 0 ? (
            <p className="placeholder">{t("module.noMaps")}</p>
          ) : (
            <>
              <ul className="rows">
                {shown.map((map) => (
                  <li key={map.name} className="row">
                    <Link
                      to={`/maps/${encodeURIComponent(module.id)}/${encodeURIComponent(map.name)}`}
                      className="row-title"
                    >
                      {map.name}
                    </Link>
                    {map.is_default && <span className="tag">{t("module.map.default")}</span>}
                    {map.role === "library" && <span className="tag">{t("module.role.library")}</span>}
                    {map.role === "map" &&
                      playing.map((c) => (
                        <Link
                          key={c.id}
                          to={`/campaigns/${encodeURIComponent(c.id)}?map=${encodeURIComponent(map.name)}`}
                        >
                          {t("maps.dmView", { campaign: c.name })}
                        </Link>
                      ))}
                  </li>
                ))}
              </ul>
              {pager}
            </>
          )}
        </>
      )}
    </section>
  );
}
