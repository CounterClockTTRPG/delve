import { describe, expect, it, vi } from "vitest";
import { isStaleBuild, reloadForNewBuild } from "./staleBuild";

function memory() {
  const kept = new Map<string, string>();
  return { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
}

describe("staleBuild", () => {
  it("knows each browser's words for a part of the app it couldn't fetch", () => {
    expect(isStaleBuild(new TypeError("Failed to fetch dynamically imported module: https://x/assets/A-1.js"))).toBe(true);
    expect(isStaleBuild(new TypeError("Importing a module script failed."))).toBe(true);
    expect(isStaleBuild(new Error("error loading dynamically imported module"))).toBe(true);
    expect(isStaleBuild(new Error("Cannot read properties of undefined"))).toBe(false);
  });

  it("reloads once, not again within a minute", () => {
    const storage = memory();
    const reload = vi.fn();
    expect(reloadForNewBuild(storage, 1_000_000, reload)).toBe(true);
    expect(reloadForNewBuild(storage, 1_030_000, reload)).toBe(false);
    expect(reloadForNewBuild(storage, 1_061_000, reload)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("doesn't reload without somewhere to remember it", () => {
    const reload = vi.fn();
    expect(reloadForNewBuild(undefined, 0, reload)).toBe(false);
    const broken = { getItem: () => null, setItem: () => { throw new Error("full"); } };
    expect(reloadForNewBuild(broken, 0, reload)).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});
