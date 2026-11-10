// Central registry of part options and themes. Everything is data-driven so
// new parts and themes can be plugged in with registerPart / registerTheme.

/** Single-choice categories, in the order they are presented. */
export const CATEGORIES = [
  'face', 'ears', 'eyes', 'brows', 'nose', 'mouth',
  'hair', 'facialHair', 'clothing', 'background', 'frame',
];

/** Render style ids, in presentation order. Parts may provide a renderer per style (see registerStyle). */
export const STYLES = ['illustrated', 'realistic'];

/**
 * Render style definitions.
 *   base      style whose part renderers (and theme overrides) are reused when a
 *             part has none of its own (e.g. 'engraving' builds on 'realistic')
 *   prepare   (markup, layer) => markup, applied to every part's output
 *   prepareGeneric  same, but only for parts without a renderer of this style
 *   geometry  (g, traits) => g, adjusts the face geometry (e.g. anime proportions)
 *   finish    false to skip the realistic photographic grade
 *   post      ({ content, ctx }) => { defs, markup }, wraps the finished portrait
 */
export const RENDER_STYLES = {
  illustrated: { id: 'illustrated', label: 'Illustrated' },
  realistic: { id: 'realistic', label: 'Realistic' },
};

export function registerRenderStyle(def) {
  if (!def.id) throw new Error('Render style needs an id');
  RENDER_STYLES[def.id] = { label: def.id, ...def };
  if (!STYLES.includes(def.id)) STYLES.push(def.id);
  return def;
}

/** The style a style builds on (itself for the built-in ones). */
export const baseStyle = (style) => RENDER_STYLES[style]?.base ?? style;

/** Colour slots every portrait has. */
export const COLOR_SLOTS = ['skin', 'hair', 'eyes', 'clothing', 'accent', 'background'];

const parts = Object.fromEntries([...CATEGORIES, 'accessories'].map((c) => [c, new Map()]));
const themes = new Map();

/**
 * Register a part option.
 * def: { id, label, render(ctx) => { [layer]: svgString }, ...categorySpecific }
 * Accessories may also define `group` (mutually exclusive set) and `layer`.
 */
export function registerPart(category, def) {
  if (!parts[category]) throw new Error(`Unknown part category "${category}"`);
  if (!def.id) throw new Error('Part definition needs an id');
  parts[category].set(def.id, { label: def.id, ...def });
  return def;
}

/**
 * Attach an alternative renderer for an existing part under a render style,
 * e.g. registerStyle('nose', 'straight', 'realistic', (ctx) => ({ nose: '...' })).
 * Parts without a renderer for the active style fall back to their default render().
 */
export function registerStyle(category, id, style, render) {
  const part = getPart(category, id);
  if (!part) throw new Error(`Unknown ${category} part "${id}"`);
  if (!RENDER_STYLES[style]) registerRenderStyle({ id: style });
  part.styles = { ...part.styles, [style]: render };
}

export function getPart(category, id) {
  return parts[category]?.get(id);
}

export function listParts(category) {
  return [...(parts[category]?.values() ?? [])];
}

/**
 * Register a theme.
 * def: {
 *   id, label,
 *   weights: { [category]: { [optionId]: weight } },   // random selection weights
 *   accessories: { [accessoryId]: probability },         // independent chance each
 *   colors: { [slot]: [hex, ...] | { [hex]: weight } },  // palettes
 *   maxAccessories?: number,
 *   style?: 'illustrated' | 'realistic',              // default render style
 *   styles?: { [style]: { weights?, colors?, accessories? } } // per-style overrides
 * }
 * Categories missing from `weights` fall back to all registered options.
 */
export function registerTheme(def) {
  if (!def.id) throw new Error('Theme definition needs an id');
  themes.set(def.id, { label: def.id, weights: {}, accessories: {}, colors: {}, maxAccessories: 3, ...def });
  return def;
}

export function getTheme(id) {
  const t = themes.get(id);
  if (!t) throw new Error(`Unknown theme "${id}" (known: ${[...themes.keys()].join(', ')})`);
  return t;
}

/** A theme with its overrides for a render style applied (weights/colours/accessories per category or slot). */
export function styledTheme(theme, style) {
  const o = theme.styles?.[style] ?? theme.styles?.[baseStyle(style)];
  if (!o) return theme;
  return {
    ...theme,
    weights: { ...theme.weights, ...o.weights },
    colors: { ...theme.colors, ...o.colors },
    accessories: { ...theme.accessories, ...o.accessories },
  };
}

export function listThemes() {
  return [...themes.values()];
}
