import { useSearchParams } from "react-router-dom";
import type { ModuleCategory, ModuleSummary } from "../api";

/**
 * The module filter (backlog 37, 2026-10-24) of the Modules, Maps and New campaign lists: any part of the title, a
 * setting as written (or none), a starting level inside the module's level range, a tag, and a category (DEL-114,
 * by id, or none). Each is "" when not used; settings and tags match in any case.
 */
export interface ModuleFilter {
  title: string;
  setting: string;
  level: string;
  tag: string;
  category: string;
}

export const NO_FILTER: ModuleFilter = { title: "", setting: "", level: "", tag: "", category: "" };
/** The category filter's value for the modules in no category. */
export const NO_CATEGORY = "-";
/** The setting filter's value for the modules that name no setting. */
export const NO_SETTING = "-";

const fold = (text: string | null | undefined) => (text ?? "").trim().toLocaleLowerCase();

/** A whole level from 1, or null for anything else (no level filter). */
function levelOf(text: string): number | null {
  const level = Number(text.trim());
  return text.trim() && Number.isInteger(level) && level >= 1 ? level : null;
}

export const isFiltering = (filter: ModuleFilter) =>
  !!(filter.title.trim() || filter.setting || levelOf(filter.level) !== null || filter.tag || filter.category);

export function filterModules<M extends ModuleSummary>(modules: M[], filter: ModuleFilter): M[] {
  const title = fold(filter.title);
  const level = levelOf(filter.level);
  return modules.filter(
    (m) =>
      (!title || fold(m.title).includes(title)) &&
      (!filter.setting || (filter.setting === NO_SETTING ? !fold(m.setting) : fold(m.setting) === fold(filter.setting))) &&
      (level === null || (!!m.levels && m.levels.min <= level && level <= m.levels.max)) &&
      (!filter.tag || (m.tags ?? []).some((tag) => fold(tag) === fold(filter.tag))) &&
      (!filter.category || (filter.category === NO_CATEGORY ? !m.category : m.category?.id === filter.category)),
  );
}

/** `modules` under their categories (DEL-114), in the categories' order, then those in none (`category` null);
 * a category with no module here is left out. The modules keep their order within each. */
export function groupByCategory<M extends ModuleSummary>(
  modules: M[],
  categories: ModuleCategory[],
): { category: ModuleCategory | null; modules: M[] }[] {
  const groups = categories.map((category) => ({ category, modules: modules.filter((m) => m.category?.id === category.id) }));
  const known = new Set(categories.map((c) => c.id));
  const none = modules.filter((m) => !m.category || !known.has(m.category.id));
  return [...groups, { category: null, modules: none }].filter((group) => group.modules.length > 0);
}

/** The distinct settings and tags in `modules`, each as first written, sorted in any case; and whether a module
 * names no setting. */
export function filterOptions(modules: ModuleSummary[]): { settings: string[]; noSetting: boolean; tags: string[] } {
  const distinct = (values: string[]) => {
    const byFold = new Map<string, string>();
    for (const value of values) if (fold(value) && !byFold.has(fold(value))) byFold.set(fold(value), value.trim());
    return [...byFold.values()].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
  };
  return {
    settings: distinct(modules.map((m) => m.setting ?? "")),
    noSetting: modules.some((m) => !fold(m.setting)),
    tags: distinct(modules.flatMap((m) => m.tags ?? [])),
  };
}

const PARAMS = { title: "q", setting: "setting", level: "level", tag: "tag", category: "category" } as const;

/** The filter kept in the address (`?q=…&setting=…&level=…&tag=…`), so Back and a reload keep it. A change goes back
 * to the first page: it drops `pageParam`. */
export function useAddressFilter(pageParam = "page"): [ModuleFilter, (filter: ModuleFilter) => void] {
  const [params, setParams] = useSearchParams();
  const filter = Object.fromEntries(
    Object.entries(PARAMS).map(([key, param]) => [key, params.get(param) ?? ""]),
  ) as unknown as ModuleFilter;
  const set = (next: ModuleFilter) =>
    setParams(
      (current) => {
        const kept = new URLSearchParams(current);
        for (const [key, param] of Object.entries(PARAMS)) {
          const value = next[key as keyof ModuleFilter];
          if (value) kept.set(param, value);
          else kept.delete(param);
        }
        kept.delete(pageParam);
        return kept;
      },
      { replace: true },
    );
  return [filter, set];
}
