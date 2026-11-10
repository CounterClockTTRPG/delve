// Extras that only emotes draw: a blush on the cheeks, tears running down, snoring z's, hearts.
// Each is faded in and out by its emote track (see emote.js); tears and z's also move.
import { pt, blurFilter } from './geometry.js';
import { mix, darken } from './color.js';
import { baseStyle } from './registry.js';

const f = (n) => +n.toFixed(2);
// Distance from the eye's centre to its inner corner, per base style (realistic and anime eyes are larger).
const INNER = { realistic: 17, anime: 18 };

/** A soft flush over both cheeks. */
export function blushMarkup({ g, colors, uid }) {
  const id = uid('blush');
  const c = mix(colors.skin, '#ff3d64', 0.55);
  const y = (g.eyeY + g.noseY) / 2 + 8;
  const cheeks = [-1, 1].map((s) => `<ellipse cx="${f(g.cx + s * (g.eyeDX + 4))}" cy="${f(y)}" rx="19" ry="9" fill="${c}" opacity="0.75"/>`).join('');
  return { defs: blurFilter(id, 4.5), markup: `<g filter="url(#${id})">${cheeks}</g>` };
}

/** A wet streak down each cheek and a drop that keeps running down it. */
export function tearsMarkup(ctx, animator) {
  const { g, style } = ctx;
  const inner = INNER[baseStyle(style)] ?? INNER[style] ?? 11;
  return [-1, 1].map((s, i) => {
    const x = g.cx + s * (g.eyeDX - inner), y = g.eyeY + 9;
    const end = g.noseY + 24;
    const streak = `M${pt(x, y)}C${pt(x - s * 1.5, y + 14)} ${pt(x + s * 3, end - 14)} ${pt(x + s * 4, end)}`;
    const drop = `<ellipse cx="${f(x)}" cy="${f(y + 3)}" rx="2.4" ry="3.4" fill="#d6ecff" stroke="#6f9cc8" stroke-width="0.7"/>` +
      `<circle cx="${f(x - 0.8)}" cy="${f(y + 2)}" r="0.8" fill="#fff"/>`;
    return `<path d="${streak}" fill="none" stroke="#5f8fc0" stroke-width="3.6" stroke-linecap="round" opacity="0.35"/>` +
      `<path d="${streak}" fill="none" stroke="#bfe0ff" stroke-width="2.4" stroke-linecap="round" opacity="0.85"/>` +
      `<path d="${streak}" fill="none" stroke="#fff" stroke-width="0.8" stroke-linecap="round" opacity="0.8" transform="translate(-0.6,0)"/>` +
      animator.fall(drop, end - y - 4, 1.5, i * 0.7, s * 4);
  }).join('');
}

/** Little hearts floating up beside the head, one after another, alternating sides. */
export function heartsMarkup({ g }, animator) {
  return [0, 1, 2, 3].map((i) => {
    const s = i % 2 ? -1 : 1;
    const k = 0.9 + (i % 3) * 0.25;
    const x = g.cx + s * (g.w * 0.85 + i * 3), y = g.eyeY - 6 - i * 4;
    const d = `M${pt(x, y + 4 * k)}C${pt(x - 7 * k, y - 2 * k)} ${pt(x - 4 * k, y - 8 * k)} ${pt(x, y - 4 * k)}C${pt(x + 4 * k, y - 8 * k)} ${pt(x + 7 * k, y - 2 * k)} ${pt(x, y + 4 * k)}Z`;
    const heart = `<path d="${d}" fill="#ff5d8f" stroke="#9e2450" stroke-width="1.2" stroke-linejoin="round"/>` +
      `<circle cx="${f(x - 2.6 * k)}" cy="${f(y - 3.6 * k)}" r="${f(1.1 * k)}" fill="#fff" opacity="0.8"/>`;
    return animator.fall(heart, -58, 2.4, i * 0.6, s * 10);
  }).join('');
}

/** Z's drifting up and away from the side of the head, one after another. */
export function zzzMarkup({ g, colors }, animator) {
  const x = g.cx + g.w * 0.95, y = g.top + 6;
  const ink = darken(colors.background ?? '#333', 0.6);
  return [0, 1, 2].map((i) => {
    const k = 0.8 + i * 0.35;
    const d = `M${pt(x, y)}h${f(8 * k)}l${f(-8 * k)},${f(9 * k)}h${f(8 * k)}`;
    const z = `<path d="${d}" fill="none" stroke="${ink}" stroke-width="${f(4.2 * k)}" stroke-linecap="round" stroke-linejoin="round" opacity="0.55"/>` +
      `<path d="${d}" fill="none" stroke="#f6f4ff" stroke-width="${f(2.2 * k)}" stroke-linecap="round" stroke-linejoin="round"/>`;
    return animator.fall(z, -46, 2.7, i * 0.9, 22);
  }).join('');
}
