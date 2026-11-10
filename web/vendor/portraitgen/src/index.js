// portraitgen - procedural, themeable character portraits.
//
//   import { generate, render } from 'portraitgen';
//   const traits = generate({ theme: 'scifi', seed: 'captain-vex', hair: 'undercut' });
//   const svg = render(traits, { size: 1024 });

import './parts/face.js';
import './parts/eyes.js';
import './parts/nose.js';
import './parts/mouth.js';
import './parts/hair.js';
import './parts/facialHair.js';
import './parts/clothing.js';
import './parts/background.js';
import './parts/accessories.js';
import './parts/accessoriesMore.js';
import './parts/gear.js';
import './parts/layers.js';
import './parts/races.js';
import './parts/props.js';
import './parts/realistic/face.js';
import './parts/realistic/eyes.js';
import './parts/realistic/nose.js';
import './parts/realistic/mouth.js';
import './parts/realistic/hair.js';
import './parts/realistic/facialHair.js';
import './parts/realistic/accessories.js';
import './parts/realistic/clothing.js';
import './themes.js';
import './styles/pixel.js';
import './styles/engraving.js';
import './styles/painterly.js';
import './styles/anime.js';
import './styles/inkwash.js';

import { CATEGORIES, COLOR_SLOTS, getTheme, listParts, listThemes, styledTheme } from './registry.js';
import { generate, accessoryChances, presentationWeights } from './generate.js';
import { PRESENTATIONS, applyPresentation } from './presentation.js';
import { render } from './render.js';

export { CATEGORIES, COLOR_SLOTS, STYLES, RENDER_STYLES, registerRenderStyle, registerPart, registerStyle, registerTheme, getPart, getTheme, listParts, listThemes } from './registry.js';
export { generate } from './generate.js';
export { PRESENTATIONS } from './presentation.js';
export { BUILDS } from './build.js';
export { AGES } from './age.js';
export { EXPRESSIONS } from './expression.js';
export { EMOTES, registerEmote, emoteDuration } from './emote.js';
export { LIGHTS } from './lighting.js';
export { FRAMINGS } from './generate.js';
export { describe, resolveColor, COLOR_NAMES } from './describe.js';
export { render, LAYERS } from './render.js';
export { createRng, randomSeed, hashSeed } from './rng.js';
export { SIZE, faceGeometry, mirrorPath, mirrored, pt } from './geometry.js';
export * as color from './color.js';

/** Convenience: generate + render in one call. Returns { traits, svg }. */
export function portrait(options = {}) {
  const traits = generate(options);
  return { traits, svg: render(traits, { size: options.size }) };
}

/**
 * Describe everything selectable for a theme (used by the GUI). Weights
 * reflect the archetype, presentation and render style when given.
 * Options that the theme does not weight are still listed with weight 0
 * so they can be picked manually.
 */
export function catalog(themeId, archetypeId, presentation, style) {
  const base = getTheme(themeId);
  const theme = styledTheme(base, style ?? base.style ?? 'illustrated');
  const arch = theme.archetypes?.[archetypeId];
  const categories = {};
  for (const cat of CATEGORIES) {
    const w = applyPresentation(arch?.weights?.[cat] ?? theme.weights?.[cat] ?? {}, presentation, cat);
    categories[cat] = listParts(cat).map((p) => ({ id: p.id, label: p.label, weight: w[p.id] ?? 0 }));
  }
  const chances = accessoryChances(theme, arch, presentation);
  const accessories = listParts('accessories').map((p) => ({ id: p.id, label: p.label, group: p.group ?? null, chance: chances[p.id] ?? 0 }));
  const colors = {};
  for (const slot of COLOR_SLOTS) {
    const p = arch?.colors?.[slot] ?? theme.colors?.[slot] ?? [];
    colors[slot] = Array.isArray(p) ? p : Object.keys(p);
  }
  const archetypes = Object.entries(theme.archetypes ?? {}).map(([id, a]) => ({ id, label: a.label ?? id }));
  const pw = presentationWeights(theme, arch);
  const presentations = Object.entries(PRESENTATIONS).map(([id, p]) => ({ id, label: p.label, weight: pw[id] ?? 0 }));
  return { theme: { id: theme.id, label: theme.label }, archetypes, presentations, categories, accessories, colors };
}

export const themes = () => listThemes().map((t) => ({ id: t.id, label: t.label, style: t.style ?? 'illustrated' }));
