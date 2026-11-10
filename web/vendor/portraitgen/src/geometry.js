// Shared geometry helpers. All portraits are drawn on a 512x512 canvas.

export const SIZE = 512;
export const CX = 256;

const f = (n) => Math.round(n * 100) / 100;
export const pt = (x, y) => `${f(x)},${f(y)}`;

/**
 * Build a closed, left/right symmetric path from its right half.
 * `start` is [dx, y] on the centre line, `segs` are cubic segments
 * [[c1x,c1y],[c2x,c2y],[ex,ey]] with x relative to the centre `cx`.
 * The last segment should end on the centre line (dx = 0).
 */
export function mirrorPath(cx, start, segs) {
  let d = `M${pt(cx + start[0], start[1])}`;
  for (const [c1, c2, e] of segs) {
    d += `C${pt(cx + c1[0], c1[1])} ${pt(cx + c2[0], c2[1])} ${pt(cx + e[0], e[1])}`;
  }
  for (let i = segs.length - 1; i >= 0; i--) {
    const [c1, c2] = segs[i];
    const s = i === 0 ? start : segs[i - 1][2];
    d += `C${pt(cx - c2[0], c2[1])} ${pt(cx - c1[0], c1[1])} ${pt(cx - s[0], s[1])}`;
  }
  return d + 'Z';
}

export function cubicPoint(p0, p1, p2, p3, t) {
  const u = 1 - t;
  return [
    u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
  ];
}

/** Sample points along a cubic bezier. */
export function sampleCubic(p0, p1, p2, p3, n) {
  const out = [];
  for (let i = 0; i <= n; i++) out.push(cubicPoint(p0, p1, p2, p3, i / n));
  return out;
}

/**
 * Turn a list of points into a decorated edge: 'spiky' (zigzag tips pushed
 * away from `center`) or 'curly' (scalloped bumps). Returns path commands
 * (no leading M) that continue from points[0].
 */
export function decorateEdge(points, center, style, amount, rng) {
  let d = '';
  for (let i = 1; i < points.length; i++) {
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    const mx = (x0 + x1) / 2;
    const my = (y0 + y1) / 2;
    let nx = mx - center[0];
    let ny = my - center[1];
    const len = Math.hypot(nx, ny) || 1;
    nx /= len;
    ny /= len;
    const a = amount * (rng ? rng.range(0.7, 1.3) : 1);
    if (style === 'spiky') d += `L${pt(mx + nx * a, my + ny * a)}L${pt(x1, y1)}`;
    else d += `Q${pt(mx + nx * a * 1.6, my + ny * a * 1.6)} ${pt(x1, y1)}`;
  }
  return d;
}

/** Wrap content so it is drawn mirrored around the vertical centre line. */
export const mirrored = (cx, content) =>
  `<g transform="translate(${cx * 2},0) scale(-1,1)">${content}</g>`;

/**
 * Compute face anchor points for a face-shape definition. Everything else
 * (eyes, ears, hair, beard...) is positioned relative to this.
 */
export function faceGeometry(shape) {
  const g = {
    cx: CX,
    w: shape.w,
    top: shape.top,
    bottom: shape.bottom,
    jawW: shape.jawW,
    jawY: shape.jawY,
    chinW: shape.chinW,
    cheekW: shape.cheekW ?? shape.w,
    forehead: shape.forehead ?? 0.6,
  };
  g.eyeY = g.top + (g.bottom - g.top) * 0.5;
  g.browY = g.eyeY - 22;
  g.noseY = g.eyeY + (g.bottom - g.eyeY) * 0.4;
  g.mouthY = g.eyeY + (g.bottom - g.eyeY) * 0.64;
  g.eyeDX = g.w * 0.42;
  g.hairY = g.top + (g.eyeY - g.top) * 0.3; // natural hairline
  g.neckW = Math.min(36, g.jawW * 0.55);
  g.shoulderY = 404;
  return g;
}

/**
 * Geometry for the realistic style: proportions nudged towards life (sturdier
 * neck, broader chin), shaped by presentation (masculine: wider jaw, squarer
 * chin, heavier brow; feminine: narrower jaw and chin, finer neck), plus the
 * slight asymmetry every real face has. `rng` drives the asymmetry.
 */
export function realisticGeometry(g, presentation, rng) {
  const k = presentation === 'masculine' ? 1 : presentation === 'feminine' ? -1 : 0;
  // Masculine: broad, square jaw and wide chin. Feminine: tapered jaw to a narrow, rounded chin.
  // Capped below the cheekbones: presentation, build and a square face shape would otherwise stack into a box.
  // Cartoon face shapes are more extreme than real faces: pull the jaw halfway to a typical 0.78 of the cheekbones.
  const baseJaw = (g.jawW + g.cheekW * 0.78) / 2;
  const jawW = Math.min(g.cheekW * 0.9, baseJaw * (1 + (k > 0 ? 0.1 : 0.03) * k));
  const chinW = k > 0
    ? Math.min(jawW * 0.62, Math.max(g.chinW * 1.4 + 10, jawW * 0.42))
    : k < 0
      ? Math.min(jawW * 0.48, Math.max(23, g.chinW * 0.75 + 12))
      : Math.min(jawW * 0.5, Math.max(14, g.chinW + 6));
  const side = () => rng.range(-1, 1);
  return {
    ...g,
    real: true,
    masc: k,
    jawW,
    chinW,
    cheekW: g.cheekW * (1 - 0.01 * k),
    jawY: g.jawY - 4 + 4 * k,
    // How sharply the jaw turns at its angle: crisp when masculine, smooth when feminine.
    jawSmooth: k > 0 ? 0.2 : k < 0 ? 1 : 0.6,
    neckW: Math.min(k > 0 ? 72 : 64, jawW * (0.74 + 0.1 * k)),
    // Interpupillary distance ~46% of face width: the proportion rated most attractive.
    eyeDX: g.w * 0.45,
    browY: g.browY + 3.5 * k,
    // Per-side offsets (R = image right, +x). Small: a few pixels at most.
    asym: {
      eyeR: side() * 0.5, eyeL: side() * 0.5,
      browR: side() * 1, browL: side() * 1,
      mouthTilt: side() * 0.8, mouthDX: side() * 0.5, noseDX: side() * 0.6,
    },
  };
}

/**
 * Anatomical head outline (right half; mirrored): cranium, widest at the
 * cheekbones, a fairly straight jawline to a defined jaw angle at mouth level,
 * then a rounded-square chin.
 */
function realSegments(g) {
  const { w, top, bottom, eyeY, jawW, jawY, chinW, cheekW } = g;
  const H = bottom - top;
  const chinY = bottom - (bottom - jawY) * 0.14;
  // Handles either side of the jaw angle, pulled towards a shared tangent by `jawSmooth`.
  let jIn = [jawW + (cheekW - jawW) * 0.3, jawY - H * 0.09];
  let jOut = [jawW - (jawW - chinW) * 0.25, jawY + (bottom - jawY) * 0.3];
  const s = g.jawSmooth ?? 0;
  if (s) {
    const a = [jawW - jIn[0], jawY - jIn[1]], b = [jOut[0] - jawW, jOut[1] - jawY];
    const la = Math.hypot(...a), lb = Math.hypot(...b);
    const t = [a[0] / la + b[0] / lb, a[1] / la + b[1] / lb];
    const lt = Math.hypot(...t);
    const sIn = [jawW - (t[0] / lt) * la, jawY - (t[1] / lt) * la], sOut = [jawW + (t[0] / lt) * lb, jawY + (t[1] / lt) * lb];
    jIn = [jIn[0] + (sIn[0] - jIn[0]) * s, jIn[1] + (sIn[1] - jIn[1]) * s];
    jOut = [jOut[0] + (sOut[0] - jOut[0]) * s, jOut[1] + (sOut[1] - jOut[1]) * s];
  }
  return [
    [[w * 0.6, top], [w * 0.96, top + H * 0.12], [w * 0.99, top + H * 0.3]],
    [[w * 1.0, top + H * 0.4], [cheekW * 0.98, eyeY - H * 0.04], [cheekW * 0.99, eyeY + H * 0.05]],
    [[cheekW * 0.99 - (cheekW - jawW) * 0.2, eyeY + H * 0.15], jIn, [jawW, jawY]],
    [jOut, [chinW + (jawW - chinW) * 0.22, chinY - (bottom - jawY) * 0.12], [chinW, chinY]],
    [[chinW * 0.92, bottom - 1.5], [chinW * 0.5, bottom], [0, bottom]],
  ];
}

export function faceSegments(g) {
  const { w, top, eyeY, jawW, jawY, chinW, bottom, cheekW, forehead } = g;
  return [
    [[w * forehead, top], [w, top + (eyeY - top) * 0.38], [w, eyeY]],
    [[w, eyeY + (jawY - eyeY) * 0.45], [cheekW + (jawW - cheekW) * 0.4, jawY - (jawY - eyeY) * 0.18], [jawW, jawY]],
    [[jawW - (jawW - chinW) * 0.25, jawY + (bottom - jawY) * 0.55], [chinW + 6, bottom], [0, bottom]],
  ];
}

export const facePath = (g) => mirrorPath(g.cx, [0, g.top], g.real ? realSegments(g) : faceSegments(g));

/**
 * Gaussian blur filter with a fixed user-space region covering the canvas.
 * (Bounding-box relative regions break on thin or mirrored shapes in some renderers.)
 */
export const blurFilter = (id, sd) =>
  `<filter id="${id}" filterUnits="userSpaceOnUse" x="-64" y="-64" width="${SIZE + 128}" height="${SIZE + 128}"><feGaussianBlur stdDeviation="${sd}"/></filter>`;

/** Catmull-Rom control points for the span points[i] -> points[i + 1]. */
function catmullRom(points, i) {
  const p0 = points[Math.max(0, i - 1)], p1 = points[i], p2 = points[i + 1], p3 = points[Math.min(points.length - 1, i + 2)];
  return [p1, [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6], p2];
}

/** Smooth curve through points, as path commands continuing from points[0] (no leading M). */
export function splineThrough(points) {
  let d = '';
  for (let i = 0; i < points.length - 1; i++) {
    const [, c1, c2, e] = catmullRom(points, i);
    d += `C${pt(...c1)} ${pt(...c2)} ${pt(...e)}`;
  }
  return d;
}

/** Points along the same curve, `perSegment` per span. */
export function sampleSpline(points, perSegment = 6) {
  const out = [points[0]];
  for (let i = 0; i < points.length - 1; i++) {
    const [p1, c1, c2, p2] = catmullRom(points, i);
    for (let k = 1; k <= perSegment; k++) out.push(cubicPoint(p1, c1, c2, p2, k / perSegment));
  }
  return out;
}
