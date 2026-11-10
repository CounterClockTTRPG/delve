import { describe, expect, it } from "vitest";
import { defineNightTheme, defineTheme } from "./dmapLanguage";

type Theme = { base: string; rules: { token: string }[] };

function themes() {
  const defined: Record<string, Theme> = {};
  const monaco = { editor: { defineTheme: (id: string, theme: Theme) => (defined[id] = theme) } };
  const fake = monaco as unknown as typeof import("monaco-editor");
  return { paper: defineTheme(fake), night: defineNightTheme(fake), defined };
}

describe("the editor's themes", () => {
  it("has a night theme on vs-dark with the paper theme's token classes", () => {
    const { paper, night, defined } = themes();
    expect([paper, night]).toEqual(["dmap-paper", "dmap-night"]);
    expect(defined["dmap-night"].base).toBe("vs-dark");
    const tokens = (id: string) => defined[id].rules.map((r) => r.token);
    expect(tokens("dmap-night")).toEqual(tokens("dmap-paper"));
  });
});
