// Maps never follow a look (looks and banners design): every token a map's drawing takes that a look overrides is
// restated, under :root[data-look], at Delve today's value, in light and in dark. Read from the stylesheets as text.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const src = join(dirname(fileURLToPath(import.meta.url)), "..");

type Rule = { media: string; selector: string; body: string };

function stylesheet(path: string): string {
  return readFileSync(join(src, path), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
}

/** The style rules of a stylesheet, each with the @media it sits in ("" for none). */
function rules(css: string): Rule[] {
  const found: Rule[] = [];
  const walk = (text: string, media: string) => {
    let i = 0;
    while (i < text.length) {
      const open = text.indexOf("{", i);
      if (open < 0) break;
      // A statement before the rule (an @import) ends at its semicolon.
      const head = text.slice(i, open).replace(/^[^]*;/, "").trim();
      let depth = 1;
      let j = open + 1;
      for (; depth > 0 && j < text.length; j++) depth += text[j] === "{" ? 1 : text[j] === "}" ? -1 : 0;
      const body = text.slice(open + 1, j - 1);
      if (head.startsWith("@media")) walk(body, head);
      else if (!head.startsWith("@")) found.push({ media, selector: head.replace(/\s+/g, " "), body });
      i = j;
    }
  };
  walk(css, "");
  return found;
}

function declarations(body: string): Record<string, string> {
  const found: Record<string, string> = {};
  for (const [, name, value] of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) found[name] = value.trim().replace(/\s+/g, " ");
  return found;
}

const DARK = "@media (prefers-color-scheme: dark)";
const base = rules(stylesheet("styles.css"));
const rootOf = (media: string) => declarations(base.find((r) => r.selector === ":root" && r.media === media)!.body);
const today = { light: rootOf(""), dark: { ...rootOf(""), ...rootOf(DARK) } };

/** A token's value in Delve today, every var(--x) put in. */
function resolve(all: Record<string, string>, name: string): string {
  const value = all[name];
  if (value === undefined) throw new Error(`Delve today has no ${name}`);
  return value.replace(/var\((--[\w-]+)\)/g, (_, inner: string) => resolve(all, inner));
}

/** The tokens a look changes: those it declares, and Delve today's that are made of them (--border of --rule). */
const overridden = (() => {
  const names = new Set<string>();
  for (const look of ["gold-wood", "dark-dungeon"])
    for (const rule of rules(stylesheet(`looks/${look}.css`)))
      for (const name of Object.keys(declarations(rule.body))) names.add(name);
  const uses = (name: string): boolean =>
    names.has(name) || [...(today.light[name] ?? "").matchAll(/var\((--[\w-]+)\)/g)].some(([, inner]) => uses(inner));
  return new Set(Object.keys(today.light).filter(uses).concat([...names]));
})();

const used = (body: string) => [...body.matchAll(/var\((--[\w-]+)/g)].map(([, name]) => name);

const MAPS = [
  {
    name: "the .dmap preview (editor, play screen, campaign, drafts)",
    file: "editor/SvgPreview.module.css",
    pin: ":global(:root[data-look]) .stageHost",
    // The whole map's area is .stageHost and what it holds; the controls and the tooltip over it are chrome.
    drawing: (selector: string) => !/\.(controls|ctrlBtn|zoomReadout|coordReadout|tooltip)/.test(selector),
  },
  {
    name: "the world map",
    file: "styles.css",
    pin: ":root[data-look] .world-leaflet",
    drawing: (selector: string) => /\.world-(leaflet|terrain|place|party|scale)|\.leaflet-/.test(selector),
  },
];

describe.each(MAPS)("$name never follows a look", ({ file, pin, drawing }) => {
  const all = rules(stylesheet(file));
  const pinned = declarations(all.find((r) => r.selector === pin && r.media === "")?.body ?? "");
  const pinnedDark = { ...pinned, ...declarations(all.find((r) => r.selector === pin && r.media === DARK)?.body ?? "") };
  const drawn = all.filter((r) => r.selector !== pin && drawing(r.selector));
  const taken = [...new Set(drawn.flatMap((r) => used(r.body)))].filter((name) => overridden.has(name)).sort();

  test("it takes some look's tokens, and they are all restated", () => {
    expect(drawn.length).toBeGreaterThan(3);
    expect(taken.length).toBeGreaterThan(0);
    expect(taken.filter((name) => !(name in pinned))).toEqual([]);
  });

  test("at Delve today's values, in light and in dark", () => {
    for (const name of taken) {
      expect(pinned[name], name).toBe(resolve(today.light, name).replace(/\s+/g, " "));
      expect(pinnedDark[name], `${name} in dark`).toBe(resolve(today.dark, name).replace(/\s+/g, " "));
    }
  });
});

test("the .dmap preview's frame, outside the pinned area, takes no look's token", () => {
  const wrap = rules(stylesheet("editor/SvgPreview.module.css")).filter((r) => r.selector === ".wrap");
  expect(wrap).toHaveLength(1);
  expect(used(wrap[0].body).filter((name) => overridden.has(name))).toEqual([]);
});
