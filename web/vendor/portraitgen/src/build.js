// Body build: shoulders, neck and face fullness, plus build-specific modelling
// (muscle, bust, double chin). Shared by every render style.
import { pt } from './geometry.js';
import { darken, lighten } from './color.js';
import { blurFilter } from './geometry.js';

// shoulders: horizontal scale of the torso. neck: neck width. face: overall
// face width. jaw: jaw and chin width.
export const BUILDS = {
  slender: { label: 'Slender', shoulders: 0.82, neck: 0.82, face: 0.94, jaw: 0.92 },
  average: { label: 'Average', shoulders: 1, neck: 1, face: 1, jaw: 1 },
  athletic: { label: 'Athletic', shoulders: 1.1, neck: 1.12, face: 1, jaw: 1.05, muscle: 0.6 },
  muscular: { label: 'Muscular', shoulders: 1.24, neck: 1.34, face: 1.01, jaw: 1.06, muscle: 1 },
  curvy: { label: 'Curvy', shoulders: 1.02, neck: 0.95, face: 1.03, jaw: 1, bust: 1 },
  heavy: { label: 'Heavy', shoulders: 1.2, neck: 1.26, face: 1.08, jaw: 1.12, soft: 1 },
};

/** Likelihood of each build per presentation. */
export const BUILD_WEIGHTS = {
  masculine: { slender: 1, average: 3, athletic: 2, muscular: 1.2, heavy: 1 },
  feminine: { slender: 1.6, average: 3, athletic: 1, curvy: 1.8, heavy: 0.7 },
  androgynous: { slender: 2, average: 3, athletic: 1, heavy: 0.4 },
};

/** Face shape adjusted for a build (applied before the face geometry is derived). */
export function buildShape(shape, build) {
  const b = BUILDS[build];
  if (!b || build === 'average') return shape;
  const cheekW = (shape.cheekW ?? shape.w) * b.face;
  return { ...shape, w: shape.w * b.face, cheekW, jawW: Math.min(cheekW * 0.98, shape.jawW * b.jaw), chinW: shape.chinW * b.jaw };
}

/**
 * Build-specific modelling drawn over the clothing (the 'shade' layer): it sits
 * under the face, so it can also model the neck below the chin.
 * `soft` = true renders it blurred (realistic-based styles).
 */
export function buildModelling({ g, colors, uid }, build, soft) {
  const b = BUILDS[build];
  if (!b) return { defs: '', markup: '' };
  const cx = g.cx, sY = g.shoulderY;
  const sh = darken(colors.clothing, 0.4);
  const hi = lighten(colors.clothing, 0.25);
  // Blurred modelling needs more weight to read at all.
  const line = (d, c, w, o) => `<path d="${d}" fill="none" stroke="${c}" stroke-width="${soft ? w * 2.4 : w}" stroke-linecap="round" opacity="${+Math.min(0.9, o * (soft ? 1.7 : 1.2)).toFixed(2)}"/>`;
  let m = '';
  if (b.muscle) {
    const s = b.shoulders;
    // Trapezius slopes from the neck to the shoulders, and the line of the chest.
    for (const k of [1, -1]) {
      m += line(`M${pt(cx + k * (g.neckW + 4), sY - 6)}Q${pt(cx + k * (g.neckW + 40) * s, sY + 2)} ${pt(cx + k * 120 * s, sY + 26)}`, sh, 3, 0.35 * b.muscle);
      m += line(`M${pt(cx + k * 8, sY + 92)}Q${pt(cx + k * 50 * s, sY + 106)} ${pt(cx + k * 96 * s, sY + 86)}`, sh, 3, 0.4 * b.muscle);
      m += line(`M${pt(cx + k * 30 * s, sY + 70)}Q${pt(cx + k * 60 * s, sY + 66)} ${pt(cx + k * 90 * s, sY + 74)}`, hi, 4, 0.25 * b.muscle);
    }
  }
  if (b.bust) {
    // Volume, not outlines: a soft shadow beneath each breast, a soft highlight on top and a
    // short, faint cleavage shadow. (Arcs high on the chest read as collarbones.)
    const blob = (x, y, rx, ry, c, o) => `<ellipse cx="${x}" cy="${y}" rx="${rx}" ry="${ry}" fill="${c}" opacity="${+Math.min(0.9, o * (soft ? 1.4 : 1)).toFixed(2)}"/>`;
    for (const k of [1, -1]) {
      m += line(`M${pt(cx + k * 12, sY + 122)}Q${pt(cx + k * 50, sY + 150)} ${pt(cx + k * 90, sY + 118)}`, sh, 4, 0.32);
      m += blob(cx + k * 48, sY + 98, 26, 13, hi, 0.16);
    }
    m += line(`M${pt(cx, sY + 100)}L${pt(cx, sY + 126)}`, sh, 2, 0.25);
  }
  if (b.soft) {
    // A soft fold under the chin.
    m += line(`M${pt(cx - g.jawW * 0.55, g.bottom + 8)}Q${pt(cx, g.bottom + 22)} ${pt(cx + g.jawW * 0.55, g.bottom + 8)}`, darken(colors.skin, 0.3), 3, 0.45);
  }
  if (!m) return { defs: '', markup: '' };
  if (!soft) return { defs: '', markup: m };
  const id = uid('buildSoft');
  return { defs: blurFilter(id, 3), markup: `<g filter="url(#${id})">${m}</g>` };
}
