// Realistic hair silhouettes, built from anatomical landmarks rather than the
// cartoon helmet shapes: volume over the skull, a natural hairline with temple
// recession, real partings, and long hair that drapes as curtains around the face.
import { pt, splineThrough, sampleSpline, decorateEdge } from '../../geometry.js';

// vol: hair thickness over the skull. line: hairline type. side: how the hair
// ends at the sides. edge: silhouette texture. buzz: shaved (speckle) density.
export const SHAPES = {
  buzz: { vol: 1, line: 'natural', side: 'cap', buzz: 0.55 },
  receding: { vol: 1, line: 'receding', side: 'cap', buzz: 0.6 },
  topknot: { vol: 3, line: 'back', side: 'cap', buzz: 0.5 },
  mohawk: { vol: 1, line: 'natural', side: 'cap', buzz: 0.35, top: 'strip' },
  undercut: { vol: 1, line: 'natural', side: 'cap', buzz: 0.35, top: 'swept' },
  // up: strands rise from the hairline (brushed up/back) rather than falling from the crown.
  // tips: the front edge breaks into small uneven tips instead of a smooth band.
  short: { vol: 13, line: 'natural', side: 'short', up: true, tips: true },
  sidepart: { vol: 12, line: 'swept', side: 'short', part: -0.42 },
  spiky: { vol: 12, line: 'natural', side: 'short', edge: 'spiky', up: true, tips: true },
  curly: { vol: 17, line: 'curly', side: 'short', edge: 'curly', curls: 6 },
  afro: { vol: 52, line: 'curly', side: 'afro', edge: 'curly', curls: 7 },
  pompadour: { vol: 10, quiff: 30, line: 'back', side: 'short', up: true },
  bob: { vol: 13, line: 'bangs', side: 'bob' },
  long: { vol: 11, line: 'middle', side: 'long' },
  longSwept: { vol: 12, line: 'swept', side: 'long', part: -0.42 },
  curlyLong: { vol: 20, line: 'middle', side: 'long', edge: 'curly', curls: 7 },
  ponytail: { vol: 6, line: 'back', side: 'tucked', up: true },
  bun: { vol: 6, line: 'back', side: 'tucked', up: true },
  wavy: { vol: 15, line: 'middle', side: 'long', wave: true },
  pixie: { vol: 8, line: 'swept', side: 'short', part: -0.3, tips: true },
  dreadlocks: { vol: 12, line: 'middle', side: 'short' },
  cornrows: { vol: 1, line: 'natural', side: 'cap', buzz: 0.75, rows: true },
  slickedBack: { vol: 6, line: 'back', side: 'short', up: true, sleek: true },
  manBun: { vol: 6, line: 'back', side: 'tucked', up: true },
  spaceBuns: { vol: 6, line: 'middle', side: 'tucked' },
  braids: { vol: 6, line: 'middle', side: 'tucked' },
};

const mirror = ([dx, y]) => [-dx, y];

/** Outer silhouette, right half: from the top centre down to where the hair ends at the side. */
function outerRight(g, s) {
  const { w, top, bottom, eyeY, jawY } = g;
  const H = bottom - top;
  const v = s.vol;
  const q = s.quiff ?? 0;
  // An afro is a rounded mass standing well clear of the head, reaching below the ears.
  if (s.side === 'afro') {
    const cy = top + H * 0.16, rx = w + v * 0.92, ryTop = cy - (top - v), ryBottom = (eyeY + 42 - cy) / 0.87;
    return [90, 64, 38, 12, -14, -38, -60].map((deg) => {
      const a = (deg * Math.PI) / 180;
      return [rx * Math.cos(a) * (deg < -30 ? 0.94 : 1), cy - Math.sin(a) * (a > 0 ? ryTop : ryBottom)];
    });
  }
  const cap = [[0, top - v - q], [w * 0.5, top - v * 0.95 - q * 0.6], [w * 0.85 + v * 0.45, top + H * 0.08], [w + v * 0.9, top + H * 0.25]];
  switch (s.side) {
    case 'short': return [...cap, [w + v * 0.6 + 1, eyeY - 18], [w + 1, eyeY + 4]];
    case 'bob': return [...cap, [w + v + 2, eyeY + 4], [w + v + 2, jawY - 6], [w + v - 6, jawY + 16]];
    case 'long': return [...cap, [w + v + 3, eyeY + 6], [w + v + 8, jawY + 10], [w + v + 14, 410], [w + v + 10, 474]];
    default: return [...cap, [w + v * 0.5 + 1, eyeY - 17]];
  }
}

/** Inner edge at the right side: from the outer end back up to the temple. */
function sideInner(g, s) {
  const { w, eyeY, browY, jawY, jawW, cheekW, neckW, mouthY, shoulderY } = g;
  switch (s.side) {
    case 'short': return [[w - 7, eyeY + 4], [w - 4, eyeY - 18]];
    case 'bob': return [[cheekW * 0.86 + 4, jawY + 12], [cheekW * 0.9, eyeY + 18], [w * 0.9, browY - 4]];
    case 'long': return [[neckW + 26, 472], [neckW + 12, shoulderY - 8], [jawW + 2, jawY + 6], [cheekW * 0.9, mouthY - 10], [cheekW * 0.88, eyeY + 6], [w * 0.86, browY - 6]];
    case 'afro': return [[cheekW * 0.99, eyeY + 34], [w * 0.99, browY - 6]];
    default: return [[w - 3, eyeY - 17]];
  }
}

/** Hairline from the right temple to the centre (symmetric types). */
function hairlineRight(g, s) {
  const { w } = g;
  const hy = g.hairY + 2;
  switch (s.line) {
    case 'receding': return [[w * 0.9, hy + 8], [w * 0.7, hy - 8], [w * 0.5, hy - 18], [w * 0.28, hy - 4], [0, hy - 2]];
    case 'back': return [[w * 0.9, hy + 14], [w * 0.7, hy + 4], [w * 0.45, hy - 2], [w * 0.2, hy - 4], [0, hy - 3]];
    case 'middle': return [[w * 0.8, hy + 26], [w * 0.55, hy + 12], [w * 0.25, hy + 2], [0, hy - 6]];
    default: {
      // A natural hairline sits a little higher; on masculine faces the temples recede into soft corners.
      const m = Math.max(0, g.masc ?? 0);
      const h = hy - 4;
      return [[w * 0.9, h + 18], [w * 0.74, h + 8 - m * 6], [w * 0.55, h + 1 - m * 5], [w * 0.28, h + 1], [0, h + 2]];
    }
  }
}

/** Full inner edge, right to left (relative x). */
function innerEdge(g, s, rng) {
  const side = sideInner(g, s);
  const left = side.map(mirror).reverse();
  const { w, browY } = g;
  const hy = g.hairY + 2;
  if (s.line === 'swept') {
    const p = s.part * w;
    return [...side, [w * 0.85, hy + 34], [w * 0.5, hy + 30], [w * 0.15, hy + 20], [p + w * 0.17, hy + 6], [p, hy - 6], [p - w * 0.2, hy + 5], [-w * 0.86, hy + 18], ...left];
  }
  if (s.line === 'bangs') {
    const j = () => rng.range(-2, 2);
    return [...side, [w * 0.88, browY - 2], [w * 0.5, browY - 7 + j()], [w * 0.15, browY - 6 + j()], [-w * 0.2, browY - 7 + j()], [-w * 0.55, browY - 6 + j()], [-w * 0.88, browY - 2], ...left];
  }
  const right = [...side, ...hairlineRight(g, s)];
  return [...right, ...right.slice(0, -1).map(mirror).reverse()];
}

const abs = (g) => ([dx, y]) => [g.cx + dx, y];

/**
 * Build the silhouette of a realistic hairstyle.
 * Returns { d, outer, inner, part } with absolute points, or null for bald.
 */
export function hairShape(g, s, rng) {
  const toAbs = abs(g);
  const R = outerRight(g, s);
  const outer = [...R.slice(1).map(mirror).reverse(), ...R].map(toAbs);
  const inner = innerEdge(g, s, rng).map(toAbs);
  let top = splineThrough(outer);
  let line = splineThrough(inner);
  let outerPts = sampleSpline(outer, 6);
  if (s.edge) {
    const amount = s.edge === 'spiky' ? 9 : s.side === 'afro' ? 8 : 4.5;
    top = decorateEdge(outerPts, [g.cx, g.eyeY], s.edge, amount, rng);
  } else if (s.wave) {
    // Loose waves: broad, gentle undulations along the silhouette.
    top = decorateEdge(sampleSpline(outer, 2), [g.cx, g.eyeY], 'curly', 5, rng);
  }
  const innerPts = sampleSpline(inner, 5);
  if (s.line === 'curly') line = decorateEdge(innerPts, [g.cx, g.top - 60], 'curly', 3, rng);
  else if (s.tips) line = decorateEdge(sampleSpline(inner, 9), [g.cx, g.top - 60], 'spiky', 2.6, rng);
  const d = `M${pt(...outer[0])}${top}L${pt(...inner[0])}${line}Z`;
  const part = s.line === 'middle' ? 0 : s.line === 'swept' ? s.part * g.w : null;
  return { d, outer: outerPts, inner: innerPts, part };
}

/** Hair mass behind the head and shoulders for long styles and bobs. */
export function backShape(g, s, rng) {
  if (s.side !== 'long' && s.side !== 'bob') return null;
  const { w, top, bottom, eyeY, jawY } = g;
  const H = bottom - top;
  const v = s.vol + (s.edge || s.wave ? 8 : 0);
  const R = s.side === 'long'
    ? [[0, top - v], [w * 0.6, top - v], [w + v, top + H * 0.27], [w + v + 6, eyeY + 50], [w + v + 16, 400], [w + v + 14, 478], [w * 0.4, 490], [0, 488]]
    : [[0, top - v], [w * 0.6, top - v], [w + v, top + H * 0.27], [w + v + 2, eyeY + 40], [w + v - 2, jawY + 16], [w * 0.5, jawY + 24], [0, jawY + 22]];
  const pts = [...R.map(mirror).reverse(), ...R.slice(1)].map(abs(g));
  const edge = s.edge ? decorateEdge(sampleSpline(pts, 5), [g.cx, eyeY + 40], 'curly', 6, rng)
    : s.wave ? decorateEdge(sampleSpline(pts, 2), [g.cx, eyeY + 40], 'curly', 7, rng) : splineThrough(pts);
  return `M${pt(...pts[0])}${edge}Z`;
}

/**
 * Longer hair kept on top of shaved sides: 'swept' (undercut, combed over to
 * the right) or 'strip' (mohawk). Returns { d, outer, inner, origin } or null.
 */
export function topShape(g, s, rng) {
  if (!s.top) return null;
  const { cx, w, top, bottom } = g;
  const H = bottom - top;
  const hy = g.hairY + 2;
  let outer, inner, origin;
  if (s.top === 'swept') {
    const v = 18;
    outer = [[-w * 0.86, top + H * 0.2], [-w * 0.78, top - 2], [-w * 0.3, top - v], [w * 0.2, top - v - 3], [w * 0.7, top - v * 0.45], [w * 0.97, top + H * 0.12], [w * 0.9, top + H * 0.24]];
    inner = [[w * 0.74, hy + 6], [w * 0.3, hy - 1], [-w * 0.2, hy - 5], [-w * 0.6, hy - 1], [-w * 0.86, top + H * 0.2]];
    origin = [cx - w * 0.9, top + 10];
  } else {
    const v = 26, sw = w * 0.27;
    outer = [[-sw, hy + 2], [-sw * 1.1, top + 10], [-sw * 0.85, top - v * 0.7], [0, top - v], [sw * 0.85, top - v * 0.7], [sw * 1.1, top + 10], [sw, hy + 2]];
    inner = [[sw * 0.5, hy + 6], [0, hy + 8], [-sw * 0.5, hy + 6]];
    origin = [cx, top + 40];
  }
  const toAbs = abs(g);
  const O = outer.map(toAbs), I = inner.map(toAbs);
  const outerPts = sampleSpline(O, 6);
  const edge = s.top === 'strip' ? decorateEdge(outerPts, [cx, top + 30], 'spiky', 4.5, rng) : splineThrough(O);
  return { d: `M${pt(...O[0])}${edge}L${pt(...I[0])}${splineThrough(I)}Z`, outer: outerPts, inner: sampleSpline(I, 5), origin };
}
