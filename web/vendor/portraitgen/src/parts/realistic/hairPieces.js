// Realistic hair pieces built from strands: coiled buns, a gathered ponytail,
// plaited braids, rope dreadlocks and cornrow rows.
import { pt, mirrored } from '../../geometry.js';
import { darken, lighten } from '../../color.js';
import { blur, blob } from '../../realism.js';

const f = (n) => +n.toFixed(2);
const WIDTHS = [0.6, 0.9, 1.3];
const OPAC = [0.35, 0.55, 0.75];

/** Groups strokes by look into a few compound paths. */
function buckets() {
  const m = new Map();
  return {
    add(c, w, o, d) { const k = `${c}|${w}|${o}`; m.set(k, (m.get(k) ?? '') + d); },
    toString() { let s = ''; for (const [k, d] of m) { const [c, w, o] = k.split('|'); s += `<path d="${d}" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" opacity="${o}"/>`; } return s; },
  };
}
const shade = (pal, light, rng) => pal[Math.max(0, Math.min(pal.length - 1, Math.round(rng.range(-0.6, 1.6) + light * (pal.length - 2.5))))];

/** A bun coiled from strands, lit from the upper left, with a contact shadow and a hair tie. */
export function bun(ctx, pal, hair, cx, cy, r) {
  const { uid, rng } = ctx;
  const grad = uid('bun');
  const b = buckets();
  for (let i = 0; i < Math.round(r * 2.4); i++) {
    const rr = rng.range(r * 0.15, r * 0.95);
    const a0 = rng.range(0, Math.PI * 2), span = rng.range(0.9, 2.2);
    const x0 = cx + Math.cos(a0) * rr, y0 = cy + Math.sin(a0) * rr * 0.9;
    const x1 = cx + Math.cos(a0 + span) * rr, y1 = cy + Math.sin(a0 + span) * rr * 0.9;
    const mid = a0 + span / 2;
    const light = 0.5 - Math.cos(mid) * 0.3 - Math.sin(mid) * 0.3;
    b.add(shade(pal, light, rng), rng.pick(WIDTHS), rng.pick(OPAC), `M${pt(x0, y0)}A${f(rr)},${f(rr * 0.9)} 0 0,1 ${pt(x1, y1)}`);
  }
  const b2 = uid('b2');
  return {
    defs: `<radialGradient id="${grad}" cx="0.35" cy="0.3" r="0.75"><stop offset="0" stop-color="${lighten(hair, 0.15)}"/><stop offset="0.6" stop-color="${darken(hair, 0.15)}"/><stop offset="1" stop-color="${darken(hair, 0.5)}"/></radialGradient>${blur(b2, 3)}`,
    markup: `<g filter="url(#${b2})">${blob(cx + 3, cy + r * 0.75, r * 0.9, r * 0.35, '#120a06', 0.45)}</g>` +
      `<ellipse cx="${f(cx)}" cy="${f(cy)}" rx="${f(r)}" ry="${f(r * 0.92)}" fill="url(#${grad})"/>${b}` +
      `<path d="M${pt(cx - r * 0.7, cy + r * 0.72)}Q${pt(cx, cy + r * 0.98)} ${pt(cx + r * 0.7, cy + r * 0.72)}" fill="none" stroke="${darken(hair, 0.65)}" stroke-width="4" stroke-linecap="round"/>`,
  };
}

/** Strands laid along a spine (array of points), spread across `width(t)`. */
function ropeStrands(rng, pal, spine, width, n, b, lightBias = 0) {
  for (let i = 0; i < n; i++) {
    const t = rng.next() * 0.96;
    const k = t * (spine.length - 1), j = Math.floor(k), u = k - j;
    const [x0, y0] = spine[j], [x1, y1] = spine[Math.min(j + 1, spine.length - 1)];
    const x = x0 + (x1 - x0) * u, y = y0 + (y1 - y0) * u;
    let tx = x1 - x0, ty = y1 - y0;
    const l = Math.hypot(tx, ty) || 1;
    tx /= l; ty /= l;
    const off = rng.range(-1, 1) * width(t);
    const sx = x - ty * off, sy = y + tx * off;
    const len = rng.range(10, 22);
    const light = 0.5 - (off / (width(t) || 1)) * 0.35 + lightBias;
    b.add(shade(pal, light, rng), rng.pick(WIDTHS), rng.pick(OPAC), `M${pt(sx, sy)}l${f(tx * len)},${f(ty * len)}`);
  }
}

/** A ponytail gathered at a tie behind the head, falling behind the shoulder. */
export function ponytail(ctx, pal, hair) {
  const { g, uid, rng } = ctx;
  const { cx, w, top, eyeY } = g;
  const spine = [[cx + w - 4, top + 26], [cx + w + 22, top + 60], [cx + w + 34, eyeY + 40], [cx + w + 32, eyeY + 120], [cx + w + 22, eyeY + 190]];
  const width = (t) => 13 * (1 - t * 0.55) + 3 * Math.sin(t * Math.PI);
  // Outline: offset the spine both ways and taper to a point.
  const side = (s) => spine.map(([x, y], i) => {
    const t = i / (spine.length - 1);
    const [nx, ny] = i < spine.length - 1 ? [spine[i + 1][1] - y, x - spine[i + 1][0]] : [y - spine[i - 1][1], spine[i - 1][0] - x];
    const l = Math.hypot(nx, ny) || 1;
    return [x + (nx / l) * width(t) * s, y + (ny / l) * width(t) * s];
  });
  const L = side(1), R = side(-1).reverse();
  const d = `M${pt(...L[0])}` + L.slice(1).map((p) => `L${pt(...p)}`).join('') + `L${pt(...spine[spine.length - 1])}` + R.map((p) => `L${pt(...p)}`).join('') + 'Z';
  const clip = uid('pony');
  const b = buckets();
  ropeStrands(rng, pal, spine, width, 160, b);
  return {
    defs: `<clipPath id="${clip}"><path d="${d}"/></clipPath>`,
    markup: `<path d="${d}" fill="${darken(hair, 0.25)}"/><g clip-path="url(#${clip})">${b}</g>` +
      `<ellipse cx="${f(cx + w + 2)}" cy="${f(top + 30)}" rx="8" ry="10" fill="${darken(hair, 0.65)}" transform="rotate(35 ${f(cx + w + 2)} ${f(top + 30)})"/>`,
  };
}

/** A three-strand plait: alternating lobes down a spine, tie and tuft at the end. */
export function plait(ctx, pal, hair, x0, y0, len, n = 9) {
  const { uid, rng } = ctx;
  const grad = uid('lobe');
  const b1 = uid('b1');
  let lobes = '';
  const strands = buckets();
  const step = len / n;
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const x = x0 + t * 10, y = y0 + i * step;
    const rx = 9.5 - t * 3, ry = step * 0.75;
    const k = i % 2 ? 1 : -1;
    lobes += `<ellipse cx="${f(x + k * 3)}" cy="${f(y)}" rx="${f(rx)}" ry="${f(ry)}" fill="url(#${grad})" transform="rotate(${k * 32} ${f(x + k * 3)} ${f(y)})"/>`;
    for (let j = -2; j <= 2; j++) {
      const ox = x + k * 3 + j * 2.2;
      strands.add(shade(pal, 0.5 - j * 0.12, rng), 0.7, 0.6, `M${pt(ox - k * rx * 0.6, y - ry * 0.7)}Q${pt(ox, y)} ${pt(ox + k * rx * 0.6, y + ry * 0.7)}`);
    }
  }
  const end = y0 + len;
  return {
    defs: `<radialGradient id="${grad}" cx="0.35" cy="0.3" r="0.8"><stop offset="0" stop-color="${lighten(hair, 0.22)}"/><stop offset="0.6" stop-color="${hair}"/><stop offset="1" stop-color="${darken(hair, 0.5)}"/></radialGradient>${blur(b1, 0.8)}`,
    markup: `<g filter="url(#${b1})">${lobes}</g>${strands}` +
      `<rect x="${f(x0 + 4)}" y="${f(end - 4)}" width="14" height="6" rx="2.5" fill="${darken(hair, 0.65)}"/>` +
      `<path d="M${pt(x0 + 7, end + 2)}l-4,16M${pt(x0 + 11, end + 2)}l0,18M${pt(x0 + 15, end + 2)}l4,16" stroke="${hair}" stroke-width="2.4" stroke-linecap="round"/>`,
  };
}

/** Rope-like dreadlocks hanging from around the head (both sides). */
export function dreads(ctx, pal, hair) {
  const { g, uid, rng } = ctx;
  const { cx, w, eyeY } = g;
  const grad = uid('dread');
  let one = '';
  for (let i = 0; i < 5; i++) {
    const xa = cx + w - 8 + i * 6, ya = eyeY - 16 + i * 6;
    const xb = cx + w + 6 + i * 9 + rng.range(-3, 3), yb = eyeY + 150 + (i % 2) * 40 + i * 8;
    const d = `M${pt(xa, ya)}Q${pt(xa + 12, eyeY + 60)} ${pt(xb, yb)}`;
    // Tube: a dark edge, a body with a lit side, and knotted texture along it.
    one += `<path d="${d}" fill="none" stroke="${darken(hair, 0.55)}" stroke-width="12" stroke-linecap="round"/>` +
      `<path d="${d}" fill="none" stroke="url(#${grad})" stroke-width="9" stroke-linecap="round"/>` +
      `<path d="${d}" fill="none" stroke="${darken(hair, 0.4)}" stroke-width="9" stroke-dasharray="1.5 4" opacity="0.6"/>` +
      `<path d="${d}" fill="none" stroke="${lighten(hair, 0.25)}" stroke-width="2" opacity="0.4" transform="translate(-2.5,0)"/>`;
  }
  return {
    defs: `<linearGradient id="${grad}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${lighten(hair, 0.1)}"/><stop offset="1" stop-color="${darken(hair, 0.3)}"/></linearGradient>`,
    markup: one + mirrored(cx, one),
  };
}

/** Cornrows: tight braided rows from the hairline back over the crown, on a visible scalp. */
export function cornrows(ctx, pal, hair) {
  const { g } = ctx;
  const { cx, w, top } = g;
  let s = '';
  for (let i = -3; i <= 3; i++) {
    const x0 = cx + i * w * 0.24, x1 = cx + i * w * 0.34;
    const d = `M${pt(x0, g.hairY + 4 - Math.abs(i) * 2)}Q${pt(x0 + i * 3, top + 14)} ${pt(x1 * 0.6 + cx * 0.4, top - 2 + Math.abs(i) * 3)}`;
    s += `<path d="${d}" fill="none" stroke="${darken(hair, 0.5)}" stroke-width="9" stroke-linecap="round"/>` +
      `<path d="${d}" fill="none" stroke="${hair}" stroke-width="6.5" stroke-linecap="round" stroke-dasharray="3 1.6"/>` +
      `<path d="${d}" fill="none" stroke="${lighten(hair, 0.3)}" stroke-width="1.4" opacity="0.5" transform="translate(-1.5,0)"/>`;
  }
  return { defs: '', markup: s };
}
