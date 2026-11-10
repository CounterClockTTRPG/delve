import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ChangeEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  NeedsToken,
  deleteModule,
  exportModuleUrl,
  importModule,
  listModuleCategories,
  listModules,
  moduleOwnBannerUrl,
  queryKeys,
  type Conversion,
  type ModuleDetail,
  type ModuleSummary,
} from "../api";
import { useConfirm } from "../components/dialogs";
import { CardBanner, LayoutSwitch, useLayout } from "../components/Layout";
import { usePages } from "../components/Pager";
import RowMenu from "../components/RowMenu";
import { useT } from "../i18n";
import ModuleFilterBar, { ModuleFacets } from "../module/ModuleFilterBar";
import Library, { hasLibrary, useLibrary } from "../modules/Library";
import CardSummary from "../module/CardSummary";
import CategoriesDialog from "../module/CategoriesDialog";
import { filterModules, groupByCategory, useAddressFilter } from "../module/filter";
import { isHomebrew } from "../module/homebrew";
import { MODULE_SORTS, sortModules, useModuleSort } from "../module/sort";
import {
  conversionLink,
  countLine,
  makesModule,
  markSeen,
  runningOf,
  stepLine,
  unseenEnd,
  useConversions,
} from "../module/conversions";

/** A module's head revision, or that it has none until a campaign starts from it (S4). */
export function revisionLine(t: ReturnType<typeof useT>, revision: number | null): string {
  return revision === null ? t("modules.notPinned") : t("modules.revision", { revision: String(revision) });
}

/**
 * `/modules`: every module, its drafts marked, with Export .dscn and Delete; "New module", which opens the four ways
 * to get one; and Import .dscn, which opens the imported module with its warnings. A running conversion is a row at
 * the top, and so is the latest finished one until its module is opened or it is dismissed. Once there are
 * categories (DEL-114), the modules are grouped under them, "No category" last, each heading with its count among
 * the modules the filter shows; Categories opens the dialog that keeps them. Table | Cards (DEL-123) switches the list
 * to cards with each module's banner, or its title's first letter where it has none; the choice is this browser's.
 * Sort by (DEL-243) orders them by title (the default), the last update or as added, within each category; that
 * choice is this browser's too.
 */
export default function Modules() {
  const t = useT();
  const client = useQueryClient();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const modules = useQuery({ queryKey: queryKeys.modules, queryFn: listModules });
  const categories = useQuery({ queryKey: queryKeys.moduleCategories, queryFn: listModuleCategories }).data ?? [];
  const [keeping, setKeeping] = useState(false);
  const [layout, chooseLayout] = useLayout("delve.modulesLayout");
  const library = useLibrary();
  const [params, setParams] = useSearchParams();
  const view = hasLibrary(library) && params.get("view") === "library" ? "library" : "modules";
  const [filter, setFilter] = useAddressFilter("page");
  const [sort, chooseSort] = useModuleSort();
  // In their categories' order (DEL-114), so a category's modules stay together across the pages, each in the sort's.
  const matching = sortModules(filterModules(modules.data ?? [], filter), sort);
  const filtered = categories.length > 0 ? groupByCategory(matching, categories).flatMap((group) => group.modules) : matching;
  const modulePages = usePages(filtered, 20, t("pager.labelled", { name: t("area.modules") }), { param: "page" });
  // An import's warnings travel along to the module's page, which shows them.
  const upload = useMutation({
    mutationFn: importModule,
    onSuccess: (module: ModuleDetail & { warnings?: string[] }) => {
      client.invalidateQueries({ queryKey: queryKeys.modules });
      navigate(`/modules/${encodeURIComponent(module.id)}`, { state: { warnings: module.warnings ?? [] } });
    },
  });
  // A module campaigns play from is refused with 409, whose message is shown.
  const remove = useMutation({
    mutationFn: deleteModule,
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.modules }),
  });
  const conversions = useConversions();
  const [, setDismissed] = useState(0);
  const running = runningOf(conversions);
  const ended = unseenEnd(conversions);
  const shown = [running, ended].filter((c): c is Conversion => c !== null);
  const seen = (id: string) => {
    markSeen(id);
    setDismissed((n) => n + 1);
  };
  // A book's or a request's progress is on New module; a world map's reading and a map draft show it where they went.
  const progressOf = (c: Conversion) => (makesModule(c) ? "/modules/new" : conversionLink(c));

  function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // the same file can be picked again after a refusal
    if (file) upload.mutate(file);
  }

  const failed = [upload.error, remove.error].find((e) => e && !(e instanceof NeedsToken));
  // Under their categories once there are any (DEL-114); each heading counts its modules among all the filter shows.
  const groups =
    categories.length > 0 ? groupByCategory(modulePages.shown, categories) : [{ category: null, modules: modulePages.shown }];
  const known = new Set(categories.map((c) => c.id));
  const countIn = (categoryId: string | null) =>
    filtered.filter((m) => (categoryId ? m.category?.id === categoryId : !m.category || !known.has(m.category.id))).length;

  function card(m: ModuleSummary) {
    const href = `/modules/${encodeURIComponent(m.id)}`;
    return (
      <li key={m.id} className="module-card">
        <Link to={href} className="module-card-link">
          <CardBanner src={m.banner?.version ? moduleOwnBannerUrl(m.id, m.banner.version, "card") : null} title={m.title} />
          <span className="module-card-title">{m.title}</span>
        </Link>
        {m.summary && <CardSummary text={m.summary} />}
        <div className="module-card-meta">
          {m.draft && <span className="tag">{t("modules.draft")}</span>}
          {isHomebrew(m.tags) && <span className="tag">{t("modules.homebrew")}</span>}
          {m.library?.newer != null && <span className="tag">{t("library.updateAvailable")}</span>}
          <ModuleFacets module={m} onTag={(tag) => setFilter({ ...filter, tag })} />
        </div>
      </li>
    );
  }

  function row(m: ModuleSummary) {
    return (
      <li key={m.id} className="row">
        <Link to={`/modules/${encodeURIComponent(m.id)}`} className="row-title">
          {m.title}
        </Link>
        {m.draft && <span className="tag">{t("modules.draft")}</span>}
        {isHomebrew(m.tags) && <span className="tag">{t("modules.homebrew")}</span>}
        {m.library?.newer != null && <span className="tag">{t("library.updateAvailable")}</span>}
        <span className="row-meta">
          {m.maps.length === 1 ? t("modules.mapCount.one") : t("modules.mapCount", { count: String(m.maps.length) })}
        </span>
        <span className="row-meta">{revisionLine(t, m.head_revision)}</span>
        <ModuleFacets module={m} onTag={(tag) => setFilter({ ...filter, tag })} />
        <RowMenu
          label={t("rowMenu.of", { name: m.title })}
          actions={[
            { label: t("modules.openIt"), to: `/modules/${encodeURIComponent(m.id)}` },
            { label: t("modules.printIt"), to: `/modules/${encodeURIComponent(m.id)}/print` },
            { label: t("module.export"), download: exportModuleUrl(m.id) },
            {
              label: t("dialog.delete"),
              danger: true,
              disabled: remove.isPending,
              onSelect: async () =>
                (await confirm({ title: t("module.deleteConfirm", { title: m.title }), confirm: t("dialog.delete"), danger: true })) &&
                remove.mutate(m.id),
            },
          ]}
        />
      </li>
    );
  }

  return (
    <section className="page">
      <h1>{t("area.modules")}</h1>

      <div className="toolbar">
        <Link to="/modules/new" className="button-like primary">
          {t("modules.new")}
        </Link>
        <label htmlFor="modules-import" className="button-like">
          {upload.isPending ? t("modules.importing") : t("modules.import")}
        </label>
        <input
          id="modules-import"
          type="file"
          accept=".dscn,application/zip,application/vnd.dscn+zip"
          className="visually-hidden"
          onChange={pick}
          disabled={upload.isPending}
        />
        <button type="button" onClick={() => setKeeping(true)}>
          {t("moduleCategories.open")}
        </button>
      </div>
      {keeping && <CategoriesDialog modules={modules.data ?? []} onClose={() => setKeeping(false)} />}

      {hasLibrary(library) && (
        <div role="tablist" className="view-tabs modules-tabs" aria-label={t("library.tabs")}>
          {(["modules", "library"] as const).map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              id={`modules-tab-${name}`}
              aria-selected={view === name}
              aria-controls={`modules-panel-${name}`}
              className="view-tab"
              onClick={() =>
                setParams(
                  (now) => {
                    if (name === "library") now.set("view", name);
                    else now.delete("view");
                    return now;
                  },
                  { replace: true },
                )
              }
            >
              {t(name === "library" ? "library.tab" : "area.modules")}
            </button>
          ))}
        </div>
      )}

      {view === "library" ? (
        <div role="tabpanel" id="modules-panel-library" aria-labelledby="modules-tab-library">
          <Library />
        </div>
      ) : (
        <>
          {failed && (
            <p role="alert" className="notice error">
              {t(failed === upload.error ? "modules.importFailed" : "modules.deleteFailed", {
                error: failed.message,
                file: upload.variables instanceof File ? upload.variables.name : "",
              })}
            </p>
          )}

          {modules.error && !(modules.error instanceof NeedsToken) && (
            <p role="alert" className="notice error">
              {t("modules.loadFailed", { error: modules.error.message })}
            </p>
          )}

          {shown.length > 0 && (
            <ul className="rows conversion-rows">
              {shown.map((c) => (
                <li key={c.id} className="row conversion-row" data-status={c.status}>
                  <span className="row-title">{c.title}</span>
                  {c.status === "running" ? (
                    <>
                      <span className="tag">{t("modules.converting")}</span>
                      <span className="row-meta">{stepLine(t, c)}</span>
                      {countLine(t, c) && <span className="row-meta">{countLine(t, c)}</span>}
                      {progressOf(c) && <Link to={progressOf(c)!}>{t("modules.conversionProgress")}</Link>}
                    </>
                  ) : c.status === "done" && c.module_id ? (
                    <Link to={`/modules/${encodeURIComponent(c.module_id)}`} onClick={() => seen(c.id)}>
                      {t("modules.conversionDone")}
                    </Link>
                  ) : (
                    <>
                      <span role="alert" className="row-meta error">
                        {t("modules.conversionFailed", { error: c.error ?? "" })}
                      </span>
                      <button type="button" onClick={() => seen(c.id)}>
                        {t("conversion.dismiss")}
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}

          {modules.data ? (
            modules.data.length === 0 ? (
              <p className="placeholder">{t("modules.empty")}</p>
            ) : (
              <>
                <div className="module-list-head">
                  <ModuleFilterBar modules={modules.data} value={filter} onChange={setFilter} />
                  <div className="field module-sort">
                    <label htmlFor="module-sort">{t("modules.sort")}</label>
                    <select id="module-sort" value={sort} onChange={(e) => chooseSort(e.target.value as typeof sort)}>
                      {MODULE_SORTS.map((name) => (
                        <option key={name} value={name}>
                          {t(`modules.sort.${name}`)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <LayoutSwitch value={layout} onChange={chooseLayout} />
                </div>
                {filtered.length === 0 && <p className="placeholder">{t("moduleFilter.none")}</p>}
                {groups.map((group) => (
                  <section
                    key={group.category?.id ?? "none"}
                    className="module-group"
                    aria-label={group.category?.name ?? t("moduleCategories.none")}
                  >
                    {categories.length > 0 && (
                      <h2 className="module-group-title">
                        {group.category?.name ?? t("moduleCategories.none")}{" "}
                        <span className="module-group-count">{countIn(group.category?.id ?? null)}</span>
                      </h2>
                    )}
                    {layout === "cards" ? (
                      <ul className="module-cards">{group.modules.map(card)}</ul>
                    ) : (
                      <ul className="rows">{group.modules.map(row)}</ul>
                    )}
                  </section>
                ))}
                {modulePages.pager}
              </>
            )
          ) : !modules.error ? (
            <p className="placeholder">{t("modules.loading")}</p>
          ) : null}
        </>
      )}
    </section>
  );
}
