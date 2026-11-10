import { renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Conversion } from "../api";
import { I18nProvider, useT } from "../i18n";
import { conversionLink, countLine, makesModule, markSeen, unseenEnd } from "./conversions";

const base: Conversion = {
  id: "cnv_000000000001",
  kind: "pdf",
  title: "Barrow of the Lost",
  mode: "ready",
  status: "done",
  step: "maps",
  done: 1,
  total: 1,
  steps: { index: 4, count: 4 },
  module_id: "mod_barrow",
  warnings: [],
  error: null,
  created_at: "2026-10-18T10:00:00Z",
  updated_at: "2026-10-18T10:00:00Z",
};

describe("conversionLink", () => {
  it("links a module job to its module", () => {
    expect(conversionLink(base)).toBe("/modules/mod_barrow");
    expect(conversionLink({ ...base, module_id: null })).toBeNull();
  });

  it("links a world map's reading to its review, in a module, a campaign or a setting", () => {
    const reading = { ...base, kind: "worldmap" as const, module_id: null };
    expect(conversionLink({ ...reading, target: { module_id: "mod_1", name: "flanaess" } })).toBe(
      "/world-maps/module/mod_1/flanaess/review",
    );
    expect(conversionLink({ ...reading, target: { campaign_id: "cmp 2", name: "the sea" } })).toBe(
      "/world-maps/campaign/cmp%202/the%20sea/review",
    );
    expect(conversionLink({ ...reading, target: { setting_id: "greyhawk", name: "flanaess" } })).toBe(
      "/world-maps/setting/greyhawk/flanaess/review",
    );
    expect(conversionLink({ ...reading, target: null })).toBeNull();
  });

  it("links a novel's job to its reader", () => {
    const novel = { ...base, kind: "novel" as const, module_id: null };
    expect(conversionLink({ ...novel, target: { novel_id: "nov_1" } })).toBe("/novels/nov_1");
    expect(conversionLink({ ...novel, target: null })).toBeNull();
    expect(makesModule(novel)).toBe(false);
  });

  it("links a history's job to its campaign's History", () => {
    const history = { ...base, kind: "history" as const, module_id: null };
    expect(conversionLink({ ...history, target: { campaign_id: "cmp 1" } })).toBe("/campaigns/cmp%201#history");
    expect(conversionLink({ ...history, target: null })).toBeNull();
    expect(makesModule(history)).toBe(false);
  });

  it("links a dungeon map's draft to the module's maps", () => {
    for (const kind of ["dungeon-map", "book-map"] as const)
      expect(conversionLink({ ...base, kind, module_id: null, target: { module_id: "mod_1" } })).toBe("/modules/mod_1?tab=maps");
  });
});

describe("makesModule", () => {
  it("is true only for a book and a request", () => {
    expect(["pdf", "generate", "worldmap", "dungeon-map", "book-map"].map((kind) => makesModule({ kind } as Conversion))).toEqual([
      true,
      true,
      false,
      false,
      false,
    ]);
  });

  it("the modules list's end notice skips a job that made no module", () => {
    localStorage.clear();
    expect(unseenEnd([{ ...base, kind: "worldmap", module_id: null }, base])).toBe(base);
  });
});

describe("countLine", () => {
  it("counts a history's texts, not chapters", () => {
    const { result } = renderHook(() => useT(), {
      wrapper: ({ children }: { children: ReactNode }) => createElement(I18nProvider, { language: "en", children }),
    });
    const writing = { ...base, step: "writing" as const, done: 1, total: 2 };
    expect(countLine(result.current, { ...writing, kind: "history" })).toBe("1 of 2 texts");
    expect(countLine(result.current, { ...writing, kind: "novel" })).toBe("1 of 2 chapters");
  });
});

describe("markSeen", () => {
  afterEach(() => vi.restoreAllMocks());

  it("throws nothing when the browser keeps no site data (DEL-174)", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(() => markSeen("cnv_000000000001")).not.toThrow();
  });
});
