// Lighting presets for the realistic-based styles: the photographic finish laid
// over the portrait (key light, falloff, colour, rim light, vignette, grain).
import { SIZE, facePath } from './geometry.js';
import { grainFilter, blur } from './realism.js';

export const LIGHTS = {
  rembrandt: { label: 'Rembrandt' },
  studio: { label: 'Soft studio' },
  rim: { label: 'Rim light' },
  candle: { label: 'Candlelight' },
  neon: { label: 'Neon' },
};

const THEME_LIGHTS = {
  fantasy: { rembrandt: 3, studio: 1.2, rim: 1, candle: 2.2 },
  modern: { studio: 3, rembrandt: 2, rim: 1, neon: 0.4 },
  scifi: { rim: 2, neon: 2.5, studio: 1, rembrandt: 0.8 },
};

/** Lighting likelihoods for a theme (themes may set `lights`). */
export const lightingWeights = (theme) => theme.lights ?? THEME_LIGHTS[theme.id] ?? { rembrandt: 2, studio: 2, rim: 1 };

const rect = (fill, extra = '') => `<rect width="${SIZE}" height="${SIZE}" fill="${fill}"${extra}/>`;

/** The finish for a portrait's lighting preset. */
export function lightingGrade(ctx) {
  const { uid, rng, g } = ctx;
  const light = LIGHTS[ctx.traits.lighting] ? ctx.traits.lighting : 'rembrandt';
  const grain = uid('grain');
  let defs = grainFilter(grain, { fx: 0.9, octaves: 2, strength: 0.5, rng });
  let markup = '';
  const radial = (id, cx, cy, r, stops) => {
    defs += `<radialGradient id="${id}" cx="${cx}" cy="${cy}" r="${r}">${stops.map(([o, c, a]) => `<stop offset="${o}" stop-color="${c}" stop-opacity="${a}"/>`).join('')}</radialGradient>`;
    return `url(#${id})`;
  };
  const vignette = (strength) => rect(radial(uid('vig'), 0.5, 0.45, 0.72, [[0.55, '#000', 0], [1, '#000', strength]]));
  if (light === 'rembrandt') {
    markup += rect(radial(uid('key'), 0.3, 0.22, 0.95, [[0, '#fff3df', 0.1], [0.5, '#fff3df', 0], [1, '#0b0a14', 0.28]])) + vignette(0.5);
  } else if (light === 'studio') {
    // Soft, even and neutral: a broad fill from the front, a light vignette.
    markup += rect(radial(uid('key'), 0.45, 0.35, 0.9, [[0, '#ffffff', 0.1], [0.6, '#ffffff', 0], [1, '#101418', 0.12]])) + vignette(0.25);
  } else if (light === 'rim') {
    // Dark front, bright light skimming the edges of the head from behind.
    const rim = uid('rim');
    const clip = uid('rimClip');
    const sides = uid('rimSides');
    // Only the left and right edges catch the light from behind, not the whole outline.
    const below = uid('rimBelow');
    defs += blur(rim, 4) + `<clipPath id="${clip}"><path d="${facePath(g)}"/></clipPath>` +
      `<clipPath id="${below}"><rect x="0" y="${g.browY}" width="${SIZE}" height="${SIZE}"/></clipPath>` +
      `<linearGradient id="${sides}" x1="0" y1="0" x2="1" y2="0" gradientUnits="userSpaceOnUse" gradientTransform="translate(${g.cx - g.w - 10},0) scale(${2 * g.w + 20},1)">` +
      `<stop offset="0" stop-color="#fff"/><stop offset="0.2" stop-color="#fff" stop-opacity="0"/><stop offset="0.8" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff"/></linearGradient>`;
    markup += rect('#05070c', ' opacity="0.32"') +
      `<g clip-path="url(#${below})"><g clip-path="url(#${clip})"><path d="${facePath(g)}" fill="none" stroke="url(#${sides})" stroke-width="10" opacity="0.6" filter="url(#${rim})"/></g></g>` +
      rect(radial(uid('back'), 0.5, 0.3, 0.6, [[0, '#9ab8ff', 0.18], [1, '#9ab8ff', 0]])) + vignette(0.55);
  } else if (light === 'candle') {
    // Warm, low light from below and to one side; the darkness closes in.
    markup += rect('#ff9a40', ' opacity="0.2" style="mix-blend-mode:multiply"') +
      rect(radial(uid('flame'), 0.28, 0.85, 0.75, [[0, '#ffb060', 0.28], [0.6, '#ff8a30', 0.06], [1, '#000', 0]])) +
      rect(radial(uid('dark'), 0.42, 0.6, 0.75, [[0.3, '#0a0402', 0], [1, '#0a0402', 0.62]]));
  } else if (light === 'neon') {
    // Two coloured lights from opposite sides over a dim base.
    markup += rect('#050510', ' opacity="0.28"') +
      rect(radial(uid('cyan'), 0.0, 0.45, 0.75, [[0, '#30e0ff', 0.32], [1, '#30e0ff', 0]]), ' style="mix-blend-mode:screen"') +
      rect(radial(uid('pink'), 1.0, 0.5, 0.75, [[0, '#ff3ad0', 0.3], [1, '#ff3ad0', 0]]), ' style="mix-blend-mode:screen"') + vignette(0.45);
  }
  markup += rect('#808080', ` filter="url(#${grain})" opacity="0.07"`);
  return { defs, markup };
}
