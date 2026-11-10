import { CATEGORIES, COLOR_SLOTS, STYLES, getTheme, getPart, listParts, styledTheme } from './registry.js';
import { createRng, randomSeed } from './rng.js';
import { PRESENTATIONS, DEFAULT_PRESENTATION_WEIGHTS, applyPresentation, presentationChances } from './presentation.js';
import { BUILDS, BUILD_WEIGHTS } from './build.js';
import { AGES, AGE_WEIGHTS, applyAge } from './age.js';
import { EXPRESSIONS, EXPRESSION_WEIGHTS, applyExpression } from './expression.js';
import { LIGHTS, lightingWeights } from './lighting.js';
import { describe as parseDescription } from './describe.js';
import { hexToRgb } from './color.js';

export const FRAMINGS = { head: { label: 'Head' }, shoulders: { label: 'Head & shoulders' }, bust: { label: 'Bust' } };

export const TRAITS_VERSION = 1;

function weightsFor(theme, archetype, category, presentation, age, expression) {
  const fromArch = archetype?.weights?.[category];
  const map = fromArch ?? theme.weights?.[category];
  let base = null;
  if (map) {
    const valid = Object.fromEntries(Object.entries(map).filter(([id]) => getPart(category, id)));
    if (Object.keys(valid).length) base = valid;
  }
  base ??= Object.fromEntries(listParts(category).map((p) => [p.id, 1]));
  return applyExpression(applyAge(applyPresentation(base, presentation, category), age, category), expression, category);
}

/** Relative likelihood of each presentation for a theme/archetype. */
export function presentationWeights(theme, archetype) {
  return archetype?.presentations ?? theme.presentations ?? DEFAULT_PRESENTATION_WEIGHTS;
}

function paletteFor(theme, archetype, slot, naturalSkin) {
  const p = archetype?.colors?.[slot] ?? theme.colors?.[slot] ?? ['#888888'];
  const map = Array.isArray(p) ? Object.fromEntries(p.map((c) => [c, 1])) : p;
  if (slot !== 'skin' || !naturalSkin) return map;
  // Natural tones: warm hues (red >= green >= blue), so no surprise lavender or blue skin.
  const natural = Object.fromEntries(Object.entries(map).filter(([c]) => { const [r, g, b] = hexToRgb(c); return r >= g && g >= b - 6; }));
  return Object.keys(natural).length ? natural : map;
}

export function accessoryChances(theme, archetype, presentation) {
  return presentationChances({ ...(theme.accessories ?? {}), ...(archetype?.accessories ?? {}) }, presentation);
}

/**
 * Produce a complete, serialisable traits object.
 *
 * options:
 *   theme      theme id (default 'fantasy')
 *   seed       any string/number; same seed + same options => same portrait
 *   archetype  optional archetype id within the theme (e.g. 'elf')
 *   presentation  'masculine' | 'feminine' | 'androgynous'; steers feature likelihoods
 *   build      'slender' | 'average' | 'athletic' | 'muscular' | 'curvy' | 'heavy'
 *   age        'young' | 'adult' | 'middle' | 'elder'
 *   expression 'neutral' | 'smile' | 'stern' | 'sad' | 'surprised' | 'smug' | 'tired'
 *   lighting   'rembrandt' | 'studio' | 'rim' | 'candle' | 'neon' (realistic-based styles)
 *   framing    'head' | 'shoulders' (default) | 'bust'
 *   turn       head turn, -1 (to the viewer's left) .. 1 (right); random small turn if omitted
 *   describe   plain-language request, e.g. 'a stout old male dwarf' (see describe.js)
 *   include    decorations that must appear; avoid: decorations never rolled
 *   naturalSkin  only natural (warm-hued) skin tones from the palette
 *   tweaks     fine-tuning: { eyeSize, jaw, hairLength, saturation, age, turn } (see render)
 *   style      render style ('illustrated' | 'realistic'); defaults to the theme's style
 *   <category> force a part, e.g. { hair: 'long', face: 'heart' }
 *   colors     force colours, e.g. { hair: '#ff0000' }
 *   accessories  explicit list of accessory ids (otherwise rolled randomly)
 */
export function generate(input = {}) {
  // A plain-language description fills in options; explicit options always win.
  let options = input;
  if (input.describe) {
    const d = parseDescription(input.describe).options;
    // Unset (undefined) options don't erase what the description asked for.
    const given = Object.fromEntries(Object.entries(input).filter(([, v]) => v !== undefined));
    options = { ...d, ...given, colors: { ...d.colors, ...input.colors }, include: [...(d.include ?? []), ...(input.include ?? [])], avoid: [...(d.avoid ?? []), ...(input.avoid ?? [])], tweaks: input.tweaks ?? d.tweaks };
    if (!options.tweaks) delete options.tweaks;
  }
  const baseTheme = getTheme(options.theme ?? 'fantasy');
  const style = STYLES.includes(options.style) ? options.style : baseTheme.style ?? 'illustrated';
  const theme = styledTheme(baseTheme, style);
  const seed = options.seed ?? randomSeed();
  const rng = createRng(seed);

  let archetypeId = options.archetype;
  const archetypes = theme.archetypes ?? {};
  if (!archetypeId || !archetypes[archetypeId]) {
    const ids = Object.keys(archetypes);
    archetypeId = ids.length ? rng.fork('archetype').weighted(Object.fromEntries(ids.map((id) => [id, archetypes[id].weight ?? 1]))) : null;
  }
  const archetype = archetypeId ? archetypes[archetypeId] : null;

  const presentation = PRESENTATIONS[options.presentation]
    ? options.presentation
    : rng.fork('presentation').weighted(presentationWeights(theme, archetype));
  const build = BUILDS[options.build]
    ? options.build
    : rng.fork('build').weighted(archetype?.builds ?? BUILD_WEIGHTS[presentation] ?? BUILD_WEIGHTS.androgynous);
  const age = AGES[options.age] ? options.age : rng.fork('age').weighted(archetype?.ages ?? theme.ages ?? AGE_WEIGHTS);
  const expression = EXPRESSIONS[options.expression] ? options.expression : rng.fork('expression').weighted(theme.expressions ?? EXPRESSION_WEIGHTS);
  const lighting = LIGHTS[options.lighting] ? options.lighting : rng.fork('lighting').weighted(lightingWeights(theme));
  const framing = FRAMINGS[options.framing] ? options.framing : 'shoulders';
  const trng = rng.fork('turn');
  const turn = typeof options.turn === 'number' ? Math.max(-1, Math.min(1, options.turn))
    : trng.chance(0.45) ? 0 : +(trng.range(0.2, 0.65) * (trng.chance(0.5) ? -1 : 1)).toFixed(2);
  const traits = { version: TRAITS_VERSION, seed: String(seed), theme: theme.id, archetype: archetypeId, presentation, build, age, expression, lighting, framing, turn, style };
  if (options.tweaks && typeof options.tweaks === 'object') traits.tweaks = { ...options.tweaks };
  // Each category gets its own forked stream so locking one part doesn't reshuffle the rest.
  for (const cat of CATEGORIES) {
    const forced = options[cat];
    traits[cat] = forced && getPart(cat, forced) ? forced : rng.fork(cat).weighted(weightsFor(theme, archetype, cat, presentation, age, expression));
  }

  traits.colors = {};
  for (const slot of COLOR_SLOTS) {
    traits.colors[slot] = options.colors?.[slot] ?? rng.fork(`color:${slot}`).weighted(paletteFor(theme, archetype, slot, options.naturalSkin));
  }

  if (Array.isArray(options.accessories)) {
    traits.accessories = options.accessories.filter((id) => getPart('accessories', id));
  } else {
    const arng = rng.fork('accessories');
    const groupsOf = (def) => [def.group, ...(def.alsoGroups ?? [])].filter(Boolean);
    // Race-defining features (an archetype's `features`) are always present and don't count
    // towards the theme's maximum of rolled decorations.
    // `include` (requested decorations) behaves the same way; `avoid` is never rolled.
    const features = [...new Set([...(archetype?.features ?? []), ...(options.include ?? [])])].filter((id) => getPart('accessories', id));
    const avoid = new Set(options.avoid ?? []);
    const chosen = [...features];
    const groups = new Set(features.flatMap((id) => groupsOf(getPart('accessories', id))));
    const max = (theme.maxAccessories ?? 3) + features.length;
    for (const [id, p] of Object.entries(accessoryChances(theme, archetype, presentation))) {
      const def = getPart('accessories', id);
      if (!def || chosen.includes(id) || avoid.has(id) || !arng.chance(p)) continue;
      // `alsoGroups`: extra exclusive groups (e.g. a helmet with an eye guard counts as eyewear too).
      const gs = [def.group, ...(def.alsoGroups ?? [])].filter(Boolean);
      if (gs.some((x) => groups.has(x))) continue;
      if (chosen.length >= max) break;
      chosen.push(id);
      for (const x of gs) groups.add(x);
    }
    traits.accessories = chosen;
  }
  return traits;
}
