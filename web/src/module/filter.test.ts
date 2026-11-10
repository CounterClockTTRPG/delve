import { describe, expect, it } from "vitest";
import type { ModuleSummary } from "../api";
import { NO_CATEGORY, NO_FILTER, NO_SETTING, filterModules, filterOptions, groupByCategory, isFiltering, type ModuleFilter } from "./filter";

const mod = (title: string, extra: Partial<ModuleSummary> = {}): ModuleSummary => ({
  id: `mod_${title}`,
  title,
  maps: [],
  head_revision: null,
  updated_at: "2026-10-24T00:00:00Z",
  draft: false,
  ...extra,
});

const saltmarsh = mod("Sinister Secret of Saltmarsh", { setting: "Greyhawk", levels: { min: 1, max: 3 }, tags: ["U1", "coast"] });
const tomb = mod("Tomb of Horrors", { setting: "greyhawk ", levels: { min: 10, max: 14 }, tags: ["S1", "traps"] });
const phlan = mod("Ruins Of Adventure", { setting: "Forgotten Realms", tags: ["Phlan", "city"] });
const keep = mod("The Keep on the Borderlands", { setting: null, levels: { min: 1, max: 3 }, tags: ["b2", "Caves"] });
const old = mod("Crypt of Saint Vellis"); // a list from before the filter: no setting, levels or tags at all
const all = [saltmarsh, tomb, phlan, keep, old];

const titles = (filter: Partial<ModuleFilter>) => filterModules(all, { ...NO_FILTER, ...filter }).map((m) => m.title);

describe("filterModules", () => {
  it("lets everything through with no filter", () => {
    expect(titles({})).toEqual(all.map((m) => m.title));
    expect(isFiltering(NO_FILTER)).toBe(false);
  });

  it("finds any part of the title, in any case", () => {
    expect(titles({ title: "  OF h" })).toEqual(["Tomb of Horrors"]);
    expect(titles({ title: "the" })).toEqual(["The Keep on the Borderlands"]);
    expect(isFiltering({ ...NO_FILTER, title: "x" })).toBe(true);
  });

  it("filters on the setting as written, in any case and trimmed, or on no setting", () => {
    expect(titles({ setting: "Greyhawk" })).toEqual(["Sinister Secret of Saltmarsh", "Tomb of Horrors"]);
    expect(titles({ setting: NO_SETTING })).toEqual(["The Keep on the Borderlands", "Crypt of Saint Vellis"]);
  });

  it("filters on a starting level inside the module's range, leaving out modules that don't say", () => {
    expect(titles({ level: "1" })).toEqual(["Sinister Secret of Saltmarsh", "The Keep on the Borderlands"]);
    expect(titles({ level: "12" })).toEqual(["Tomb of Horrors"]);
    expect(titles({ level: "6" })).toEqual([]);
    expect(titles({ level: "x" })).toEqual(all.map((m) => m.title)); // not a level: no filter
  });

  it("filters on a tag in any case, and combines the filters", () => {
    expect(titles({ tag: "caves" })).toEqual(["The Keep on the Borderlands"]);
    expect(titles({ tag: "u1", level: "2", setting: "greyhawk", title: "salt" })).toEqual(["Sinister Secret of Saltmarsh"]);
    expect(titles({ tag: "u1", level: "12" })).toEqual([]);
  });
});

describe("filterOptions", () => {
  it("lists each setting and tag in use once, sorted, as first written; no setting when a module has none", () => {
    expect(filterOptions(all)).toEqual({
      settings: ["Forgotten Realms", "Greyhawk"],
      noSetting: true,
      tags: ["b2", "Caves", "city", "coast", "Phlan", "S1", "traps", "U1"],
    });
    expect(filterOptions([saltmarsh]).noSetting).toBe(false);
  });
});

describe("categories (DEL-114)", () => {
  const mega = { id: "cat_mega", name: "Megadungeons", position: 0 };
  const shots = { id: "cat_shots", name: "One-shots", position: 1 };
  const empty = { id: "cat_empty", name: "Empty", position: 2 };
  const inMega = mod("Greyhawk Ruins", { category: { id: mega.id, name: mega.name } });
  const inShots = mod("Tomb of Horrors", { category: { id: shots.id, name: shots.name } });
  const lost = mod("Lost", { category: { id: "cat_gone", name: "Gone" } });
  const none = mod("Keep");

  it("filters by category, or by none", () => {
    const pick = (category: string) => filterModules([inMega, inShots, none], { ...NO_FILTER, category }).map((m) => m.title);
    expect(pick(mega.id)).toEqual(["Greyhawk Ruins"]);
    expect(pick(NO_CATEGORY)).toEqual(["Keep"]);
    expect(isFiltering({ ...NO_FILTER, category: mega.id })).toBe(true);
  });

  it("groups in the categories' order, those in none (or an unknown one) last, empty ones left out", () => {
    const groups = groupByCategory([none, inShots, lost, inMega], [mega, shots, empty]);
    expect(groups.map((g) => [g.category?.name ?? null, g.modules.map((m) => m.title)])).toEqual([
      ["Megadungeons", ["Greyhawk Ruins"]],
      ["One-shots", ["Tomb of Horrors"]],
      [null, ["Keep", "Lost"]],
    ]);
  });
});
