import { useState } from "react";
import type { ModuleSummary } from "../api";

/**
 * The Modules list's order (DEL-243): by title (the default), the last update first, or as added, the newest or the
 * oldest first. The server lists the modules in the order they were added.
 */
export type ModuleSort = "title" | "updated" | "newest" | "oldest";

export const MODULE_SORTS: readonly ModuleSort[] = ["title", "updated", "newest", "oldest"];

const KEY = "delve.modulesSort";

/** `modules`, as the server listed them, in the `sort` order; titles in any case, "Module 2" before "Module 10". */
export function sortModules<M extends ModuleSummary>(modules: M[], sort: ModuleSort): M[] {
  switch (sort) {
    case "title":
      return [...modules].sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base", numeric: true }));
    case "updated":
      return [...modules].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    case "newest":
      return [...modules].reverse();
    case "oldest":
      return modules;
  }
}

function stored(): ModuleSort {
  try {
    const value = localStorage.getItem(KEY);
    return MODULE_SORTS.includes(value as ModuleSort) ? (value as ModuleSort) : "title";
  } catch {
    return "title";
  }
}

/** The Modules list's order, this browser's choice, as the Table | Cards switch is (`useLayout`). */
export function useModuleSort(): [ModuleSort, (next: ModuleSort) => void] {
  const [sort, setSort] = useState<ModuleSort>(stored);
  const choose = (next: ModuleSort) => {
    setSort(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // A private window: the choice holds for this visit.
    }
  };
  return [sort, choose];
}
