import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { TEXTURE_MAX, over, ratio, type Rgb } from "./contrast";

const here = dirname(fileURLToPath(import.meta.url));

function stylesheet(name: string): string {
  return readFileSync(join(here, name), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
}

/** The custom properties of the look's token block, `:root[data-look="<look>"] { … }`, read as text. */
function tokens(look: string): Record<string, string> {
  const css = stylesheet(`${look}.css`);
  const block = css.match(new RegExp(`:root\\[data-look="${look}"\\]\\s*\\{([^}]*)\\}`));
  if (!block) throw new Error(`no token block for ${look}`);
  const found: Record<string, string> = {};
  for (const [, name, value] of block[1].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) found[name] = value.trim();
  return found;
}

/** A token's value with every var(--x) put in, as the browser would. */
function resolve(all: Record<string, string>, name: string): string {
  const value = all[name];
  if (value === undefined) throw new Error(`the look has no ${name}`);
  return value.replace(/var\((--[\w-]+)\)/g, (_, inner: string) => resolve(all, inner));
}

/** The one hex colour a token holds. */
function colour(all: Record<string, string>, name: string): string {
  const found = colours(all, name);
  if (found.length !== 1) throw new Error(`${name} is not one colour: ${resolve(all, name)}`);
  return found[0];
}

/** Every hex colour in a token (a gradient's stops, say). */
function colours(all: Record<string, string>, name: string): string[] {
  return resolve(all, name).match(/#[0-9a-f]{3,6}\b/gi) ?? [];
}

/** A wash token, `rgba(r, g, b, a)`, as its colour and alpha. */
function wash(all: Record<string, string>, name: string): [string, number] {
  const m = resolve(all, name).match(/^rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)$/);
  if (!m) throw new Error(`${name} is not an rgba wash`);
  const hex = "#" + m.slice(1, 4).map((c) => Number(c).toString(16).padStart(2, "0")).join("");
  return [hex, Number(m[4])];
}

function rgbOf(hex: string): Rgb {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as Rgb;
}

describe("the contrast check", () => {
  test("ratio follows WCAG", () => {
    expect(ratio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(ratio("#ffffff", "#000000")).toBeCloseTo(21, 5);
    expect(ratio("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
  });

  test("over lays a wash on a pixel", () => {
    expect(over("#000000", 0.5, [200, 100, 0])).toBe("#643200");
    expect(over("#ffffff", 0, [1, 2, 3])).toBe("#010203");
  });
});

/** Delve today's tokens: styles.css's `:root { … }`, and with `dark` its dark block laid over them. */
function delveToday(dark: boolean): Record<string, string> {
  const css = stylesheet("../styles.css");
  const block = (re: RegExp): Record<string, string> => {
    const m = css.match(re);
    if (!m) throw new Error(`no token block ${re}`);
    return Object.fromEntries([...m[1].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(([, n, v]) => [n, v.trim()]));
  };
  const light = block(/^:root\s*\{([^}]*)\}/m);
  return dark ? { ...light, ...block(/@media \(prefers-color-scheme: dark\)\s*\{\s*:root\s*\{([^}]*)\}/) } : light;
}

describe.each([
  ["light", false],
  ["dark", true],
])("Delve today, %s", (_, dark) => {
  const t = delveToday(dark);

  test.each([
    ["--link", "the page", "--bg"],
    ["--link", "a card", "--surface"],
    ["--link-visited", "the page", "--bg"],
    ["--link-visited", "a card", "--surface"],
  ])("%s on %s is at least 4.5", (fg, _, against) => {
    expect(ratio(colour(t, fg), colour(t, against))).toBeGreaterThanOrEqual(4.5);
  });
});

describe("links follow the look", () => {
  test("one base rule colours every link from the tokens, and a look sets only the tokens", () => {
    const css = stylesheet("../styles.css");
    expect(css).toMatch(/:where\(a\)\s*\{\s*color:\s*var\(--link\);/);
    expect(css).toMatch(/:where\(a:visited\)\s*\{\s*color:\s*var\(--link-visited\);/);
    for (const look of ["gold-wood", "dark-dungeon"]) {
      expect(stylesheet(`${look}.css`)).not.toMatch(/\)\s+a\s*[,{]/);
    }
  });
});

describe("Gold and wood", () => {
  const t = tokens("gold-wood");
  const bg = colour(t, "--bg");
  const [glow, glowAlpha] = wash(t, "--page-glow");
  // The page's brightest spot is the glow's centre; the nav's is the wash over the wood's brightest pixel.
  const lit = over(glow, glowAlpha, rgbOf(bg));
  const [navWash, navAlpha] = wash(t, "--nav-wash");
  const nav = over(navWash, navAlpha, TEXTURE_MAX.wood);
  const surface = colour(t, "--surface");

  test.each([
    ["--ink", "the page", bg],
    ["--ink", "the glow", lit],
    ["--ink", "a card", surface],
    ["--ink", "the nav", nav],
    ["--muted", "a card", surface],
    ["--muted", "the glow", lit],
    ["--heading", "the page", lit],
    ["--heading", "the nav", nav],
    ["--accent", "the page", lit],
    ["--accent", "a card", surface],
    ["--link", "the page", bg],
    ["--link", "the glow", lit],
    ["--link", "a card", surface],
    ["--link-visited", "the page", bg],
    ["--link-visited", "the glow", lit],
    ["--link-visited", "a card", surface],
    ["--notice-ink", "a notice", colour(t, "--notice-bg")],
    ["--error", "an error notice", colour(t, "--error-bg")],
    ["--error", "a card", surface],
  ])("%s on %s is at least 4.5", (fg, _, against) => {
    expect(ratio(colour(t, fg), against)).toBeGreaterThanOrEqual(4.5);
  });

  test("dark ink on every stop of the buttons and the current menu item", () => {
    for (const stop of colours(t, "--button-bg")) {
      expect(ratio(colour(t, "--accent-ink"), stop)).toBeGreaterThanOrEqual(4.5);
    }
    for (const stop of colours(t, "--nav-current-bg")) {
      expect(ratio(colour(t, "--nav-current-ink"), stop)).toBeGreaterThanOrEqual(4.5);
    }
    expect(colours(t, "--button-bg")).toHaveLength(2);
    expect(colours(t, "--nav-current-bg")).toHaveLength(2);
  });

  test.each([
    ["--focus", "the page", bg],
    ["--focus", "the glow", lit],
    ["--focus", "the nav", nav],
    ["--focus", "a card", surface],
    ["--rule", "the page", bg],
    ["--rule", "a card", surface],
  ])("%s on %s is at least 3", (fg, _, against) => {
    expect(ratio(colour(t, fg), against)).toBeGreaterThanOrEqual(3);
  });

  test("the look stays under its attribute and loads nothing from outside", () => {
    staysScoped("gold-wood", /url\("\.\/textures\/wood-Wood051\.jpg"\)/);
  });
});

describe("Dark dungeon", () => {
  const t = tokens("dark-dungeon");
  // The page's brightest spot: the heavy wash over the rock's brightest pixel, under the torch glow at its centre.
  const [shade, shadeAlpha] = wash(t, "--page-shade");
  const [glow, glowAlpha] = wash(t, "--page-glow");
  const lit = over(glow, glowAlpha, rgbOf(over(shade, shadeAlpha, TEXTURE_MAX.rock)));
  // A card is see-through: its wash over that same spot.
  const [cardWash, cardAlpha] = wash(t, "--card-bg");
  const card = over(cardWash, cardAlpha, rgbOf(lit));
  const nav = colour(t, "--nav-bg");
  const surface = colour(t, "--surface");

  test.each([
    ["--ink", "the page", lit],
    ["--ink", "a card", card],
    ["--ink", "a control", surface],
    ["--ink", "the nav", nav],
    ["--accent", "the page", lit],
    ["--accent", "a card", card],
    ["--link", "the page", colour(t, "--bg")],
    ["--link", "the lit page", lit],
    ["--link", "a card", card],
    ["--link-visited", "the page", colour(t, "--bg")],
    ["--link-visited", "the lit page", lit],
    ["--link-visited", "a card", card],
    ["--muted", "the page", lit],
    ["--muted", "a card", card],
    ["--heading", "the page", lit],
    ["--nav-current-ink", "the current menu item", colour(t, "--nav-current-bg")],
    ["--accent-ink", "a button", colour(t, "--button-bg")],
    ["--notice-ink", "a notice", colour(t, "--notice-bg")],
    ["--error", "an error notice", colour(t, "--error-bg")],
    ["--error", "a card", card],
  ])("%s on %s is at least 4.5", (fg, _, against) => {
    expect(ratio(colour(t, fg), against)).toBeGreaterThanOrEqual(4.5);
  });

  test("torch orange is the accent, the buttons and the current menu item", () => {
    expect(colour(t, "--button-bg")).toBe(colour(t, "--accent"));
    expect(resolve(t, "--accent")).toBe(colour(t, "--accent"));
  });

  test.each([
    ["--focus", "the page", lit],
    ["--focus", "a card", card],
    ["--focus", "the nav", nav],
    ["--focus", "a control", surface],
    ["--rule", "the page", lit],
    ["--rule", "a control", surface],
  ])("%s on %s is at least 3", (fg, _, against) => {
    expect(ratio(colour(t, fg), against)).toBeGreaterThanOrEqual(3);
  });

  test("the rock is one fixed body background, left out for print and to save data", () => {
    const css = stylesheet("dark-dungeon.css");
    expect(resolve(t, "--page-texture")).toMatch(/^url\("\.\/textures\/stone-Rock030\.jpg"\)$/);
    expect(css).toMatch(/:where\(:root\[data-look="dark-dungeon"\]\) body\s*\{[^}]*background-attachment:[^;]*fixed/);
    for (const media of ["print", "\\(prefers-reduced-data: reduce\\)"]) {
      expect(css).toMatch(new RegExp(`@media ${media}\\s*\\{\\s*:root\\[data-look="dark-dungeon"\\]\\s*\\{[^}]*--page-texture:\\s*none`));
    }
    // Only the body carries the rock: no other rule lays a texture under the story's list.
    expect(css.match(/url\(/g)).toHaveLength(1);
  });

  test("the look stays under its attribute and loads nothing from outside", () => {
    staysScoped("dark-dungeon", /url\("\.\/textures\/stone-Rock030\.jpg"\)/);
  });
});

/** Every selector of the look is under its attribute, and nothing comes from outside Delve. */
function staysScoped(look: string, texture: RegExp): void {
  const css = stylesheet(`${look}.css`);
  expect(css).not.toMatch(/https?:/);
  const root = `:root\\[data-look="${look}"\\]`;
  const selectors = css
    .replace(/@import[^;]+;/g, "")
    .match(/[^{}]+(?=\{)/g)!
    .flatMap((s) => s.split(/,(?![^(]*\))/))
    .map((s) => s.trim())
    .filter((s) => s && !s.startsWith("@"));
  expect(selectors.length).toBeGreaterThan(1);
  for (const s of selectors) expect(s).toMatch(new RegExp(`^(${root}|:where\\(${root}\\))`));
  expect(css).toMatch(texture);
}
