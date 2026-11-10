// Expressions: brows, eyes and mouth chosen together so a face reads as one
// feeling (not an angry brow over a grin), plus the modelling that sells it
// (smile crinkles, a furrowed brow, tired eyes).
import { pt, blurFilter } from './geometry.js';
import { darken, lighten, mix } from './color.js';

export const EXPRESSIONS = {
  neutral: { label: 'Neutral', weights: { mouth: { neutral: 4, smirk: 1, full: 1.5, pursed: 0.6, smile: 0.5, grin: 0.05, open: 0.05, frown: 0.3 }, brows: { angry: 0.4, worried: 0.3 } } },
  smile: { label: 'Warm smile', weights: { mouth: { smile: 6, grin: 2.5, neutral: 0.1, frown: 0, open: 0, pursed: 0 }, brows: { angry: 0, worried: 0.2, natural: 2, arched: 1.5 }, eyes: { sleepy: 0.5 } } },
  stern: { label: 'Stern', weights: { mouth: { neutral: 2, frown: 3, smile: 0, grin: 0, smirk: 0.3, open: 0 }, brows: { angry: 6, straight: 2, thick: 1.4, worried: 0, arched: 0.2 }, eyes: { narrow: 2, large: 0.3 } } },
  sad: { label: 'Sad', weights: { mouth: { frown: 5, neutral: 1, smile: 0, grin: 0, smirk: 0, open: 0.2 }, brows: { worried: 8, angry: 0 }, eyes: { sleepy: 1.5 } } },
  surprised: { label: 'Surprised', weights: { mouth: { open: 6, pursed: 1, neutral: 0.2, smile: 0, frown: 0 }, brows: { worried: 3, arched: 3, angry: 0 }, eyes: { round: 4, large: 3, narrow: 0, sleepy: 0 } } },
  smug: { label: 'Smug', weights: { mouth: { smirk: 7, neutral: 0.3, smile: 0.3, grin: 0, frown: 0 }, brows: { arched: 2, straight: 2, worried: 0 }, eyes: { sleepy: 2 } } },
  tired: { label: 'Tired', weights: { mouth: { neutral: 4, frown: 1, smile: 0.1, grin: 0, open: 0.2 }, brows: { worried: 1.5, angry: 0.3 }, eyes: { sleepy: 6, narrow: 1, large: 0.2 } } },
};
export const EXPRESSION_WEIGHTS = { neutral: 3, smile: 3, stern: 1, sad: 0.6, surprised: 0.4, smug: 1, tired: 0.6 };

export function applyExpression(weights, expression, category) {
  const f = EXPRESSIONS[expression]?.weights?.[category];
  if (!f) return weights;
  const out = Object.fromEntries(Object.entries(weights).map(([id, w]) => [id, w * (f[id] ?? 1)]));
  return Object.values(out).some((w) => w > 0) ? out : weights;
}

/** Expression-specific modelling on the face ('marks' layer). */
export function expressionModelling({ g, colors, uid }, expression, soft) {
  const { cx, eyeY, eyeDX, browY, noseY } = g;
  const sh = mix(darken(colors.skin, 0.4), '#4a1e14', 0.15);
  const hi = lighten(colors.skin, 0.3);
  const line = (d, o, w = 1.6, c = sh) => `<path d="${d}" fill="none" stroke="${c}" stroke-width="${soft ? w * 1.4 : w}" stroke-linecap="round" opacity="${o}"/>`;
  let m = '';
  if (expression === 'smile') {
    for (const s of [1, -1]) {
      const ox = cx + s * (eyeDX + 22);
      m += line(`M${pt(ox, eyeY + 2)}l${s * 7},2M${pt(ox - s * 2, eyeY + 7)}l${s * 6},5`, 0.35); // smile crinkles
      m += line(`M${pt(cx + s * (eyeDX - 12), eyeY + 12)}Q${pt(cx + s * eyeDX, eyeY + 9)} ${pt(cx + s * (eyeDX + 12), eyeY + 11)}`, 0.3); // raised lower lid
      if (soft) m += `<ellipse cx="${cx + s * (eyeDX + 4)}" cy="${noseY + 2}" rx="18" ry="10" fill="${hi}" opacity="0.25"/>`; // lifted cheeks
    }
  } else if (expression === 'stern') {
    m += line(`M${pt(cx - 5, browY - 2)}l1,9M${pt(cx + 5, browY - 2)}l-1,9`, 0.45, 1.8); // furrow between the brows
  } else if (expression === 'sad') {
    m += line(`M${pt(cx - 10, browY - 10)}Q${pt(cx, browY - 14)} ${pt(cx + 10, browY - 10)}`, 0.3);
  } else if (expression === 'tired') {
    for (const s of [1, -1]) {
      m += line(`M${pt(cx + s * (eyeDX - 14), eyeY + 13)}Q${pt(cx + s * eyeDX, eyeY + 21)} ${pt(cx + s * (eyeDX + 16), eyeY + 12)}`, 0.4, 2.2, mix(sh, '#5a3a5a', 0.3));
    }
  } else if (expression === 'surprised') {
    for (let i = 0; i < 2; i++) m += line(`M${pt(cx - 26, browY - 20 - i * 7)}Q${pt(cx, browY - 25 - i * 7)} ${pt(cx + 26, browY - 20 - i * 7)}`, 0.3);
  }
  if (!m) return { defs: '', marks: '' };
  if (!soft) return { defs: '', marks: m };
  const id = uid('expr');
  return { defs: blurFilter(id, 1), marks: `<g filter="url(#${id})">${m}</g>` };
}
