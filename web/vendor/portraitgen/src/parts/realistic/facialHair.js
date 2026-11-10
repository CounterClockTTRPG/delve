// Realistic facial hair: frayed masses filled with directional strands, and
// stubble as a speckle texture on the skin.
import { registerStyle } from '../../registry.js';
import { pt, mirrorPath, mirrored } from '../../geometry.js';
import { darken, lighten, mix, luminance } from '../../color.js';
import { blur, blob, speckleFilter, frayFilter } from '../../realism.js';
import { fullBeard, mustache, mouthHole } from '../facialHair.js';
import { strokeBuckets, strandPalette } from './hair.js';
import { lipOffset } from './mouth.js';

// The realistic mouth is wider than the illustrated one, so the beard's opening is too.
const hole = (g) => mouthHole(g, 28, 10);

function goatee(g) {
  const { mouthY: m, bottom: b } = g;
  return mirrorPath(g.cx, [0, m - 13], [
    [[14, m - 15], [24, m - 9], [31, m + 4]],
    [[33, m + 16], [24, b - 4], [12, b + 8]],
    [[8, b + 12], [4, b + 14], [0, b + 14]],
  ]);
}

function muttonChop(g) {
  const { cx, w, eyeY, jawY, jawW, mouthY: m } = g;
  return `M${pt(cx + w - 1, eyeY)}C${pt(cx + w + 3, jawY - 20)} ${pt(cx + jawW + 6, jawY + 4)} ${pt(cx + jawW - 10, jawY + 18)}` +
    `C${pt(cx + w * 0.6, jawY + 10)} ${pt(cx + 34, m + 14)} ${pt(cx + 33, m - 4)}C${pt(cx + w * 0.5, m - 14)} ${pt(cx + w - 16, eyeY + 30)} ${pt(cx + w - 12, eyeY + 4)}Z`;
}

function longBeard(g) {
  const { w, eyeY, noseY, jawY, jawW, mouthY: m } = g;
  return mirrorPath(g.cx, [0, m - 13], [
    [[w * 0.3, m - 14], [w * 0.6, m - 4], [w * 0.8, noseY + 10]],
    [[w * 0.92, noseY - 4], [w - 3, eyeY + 22], [w - 1, eyeY + 4]],
    [[w + 4, jawY - 10], [jawW + 16, jawY + 60], [jawW - 6, 440]],
    [[jawW * 0.5, 486], [20, 500], [0, 506]],
  ]);
}

/** Realistic moustaches are wider to match the realistic mouth. */
const widen = (g, d) => ({ d, transform: `translate(${g.cx},${g.mouthY}) scale(1.3,1.1) translate(${-g.cx},${-g.mouthY})` });

/** Strands for a beard (falling, flaring outwards) or a moustache (out and down from the centre). */
function strands(rng, pal, g, box, n, kind) {
  const b = strokeBuckets();
  const [x0, y0, x1, y1] = box;
  for (let k = 0; k < n; k++) {
    const x = rng.range(x0, x1), y = rng.range(y0, y1);
    const side = Math.sign(x - g.cx) || 1;
    const spread = (x - g.cx) / (x1 - x0);
    let dx, dy, len;
    if (kind === 'stache') {
      dx = side * 0.75; dy = 0.65; len = rng.range(5, 10);
    } else {
      dx = spread * 0.8; dy = 1; len = rng.range(8, 20);
    }
    const k2 = Math.hypot(dx, dy);
    dx /= k2; dy /= k2;
    const light = 0.5 - spread * 0.9 - ((y - y0) / (y1 - y0) - 0.4) * 0.5;
    const i = Math.max(0, Math.min(pal.length - 1, Math.round(rng.range(-0.6, 1.6) + light * (pal.length - 2.5))));
    const bend = rng.range(-2, 2);
    b.add(pal[i], rng.pick([0.6, 0.9, 1.3]), rng.pick([0.35, 0.55, 0.75]),
      `M${pt(x, y)}q${(dx * len * 0.5 - dy * bend).toFixed(2)},${(dy * len * 0.5 + dx * bend).toFixed(2)} ${(dx * len).toFixed(2)},${(dy * len).toFixed(2)}`);
  }
  return b.toString();
}

/**
 * Paint one hair mass. `shape` is path data (or { d, transform }) and `box`
 * [x0, y0, x1, y1] bounds the strands; they are clipped to the shape anyway.
 */
function hairMass(ctx, shape, box, n, kind, evenodd = false) {
  const { g, colors, uid, rng } = ctx;
  const hair = colors.hair;
  const clip = uid('fhClip');
  const fray = uid('fhFray');
  const b4 = uid('b12');
  const rule = evenodd ? ' fill-rule="evenodd" clip-rule="evenodd"' : '';
  const { d, transform } = typeof shape === 'string' ? { d: shape } : shape;
  const el = (attrs) => `<path d="${d}"${transform ? ` transform="${transform}"` : ''}${attrs}/>`;
  const defs = `<clipPath id="${clip}">${el(rule)}</clipPath>${frayFilter(fray, { scale: kind === 'stache' ? 4 : 7, rng })}${blur(b4, 12)}`;
  const [x0, y0, x1, y1] = box;
  const markup = `<g filter="url(#${fray})">${el(`${rule} fill="${darken(hair, 0.15)}" opacity="0.9"`)}</g>` +
    `<g clip-path="url(#${clip})">${strands(rng, strandPalette(hair), g, box, n, kind)}` +
    `<g filter="url(#${b4})">${blob(x1, (y0 + y1) / 2, (x1 - x0) * 0.45, (y1 - y0) * 0.7, '#120a06', 0.3)}` +
    blob(x0 + (x1 - x0) * 0.3, y0 + (y1 - y0) * 0.35, (x1 - x0) * 0.18, (y1 - y0) * 0.2, lighten(hair, 0.35), 0.25) + `</g></g>`;
  return { defs, markup };
}

/** Stubble: dense speckle of short hairs plus a faint tint, on the skin. */
function stubble(ctx, d, density = 0.5) {
  const { colors, uid, rng } = ctx;
  const sp = uid('stubble');
  const b3 = uid('b3');
  // Stubble shows as shadow only when the hair is darker than the skin; light or
  // white stubble is barely visible in life, and drawn at full strength it reads as fuzz.
  const contrast = luminance(colors.skin) - luminance(colors.hair);
  const k = Math.max(0.15, Math.min(1, 0.35 + contrast * 2.2));
  return {
    defs: speckleFilter(sp, darken(colors.hair, 0.2), { freq: 1.5, density, rng }) + blur(b3, 3),
    markup: `<g filter="url(#${b3})"><path d="${d}" fill="${mix(colors.skin, colors.hair, 0.5)}" opacity="${+(0.22 * k).toFixed(3)}"/></g>` +
      `<path d="${d}" fill="#000" filter="url(#${sp})" opacity="${+(0.8 * k).toFixed(3)}"/>`,
  };
}

function combine(parts) {
  const out = { defs: '' };
  for (const [layer, p] of parts) {
    out.defs += p.defs;
    out[layer] = (out[layer] ?? '') + p.markup;
  }
  return out;
}

const beardBox = (g, drop = 26) => [g.cx - g.w - 6, g.noseY, g.cx + g.w + 6, g.bottom + drop + 6];
const stacheBox = (g) => [g.cx - 48, g.mouthY - 28, g.cx + 48, g.mouthY + 4];

const styles = {
  none: () => ({}),
  stubble: (ctx) => combine([['facialHair', stubble(ctx, fullBeard(ctx.g, 2), 0.55)]]),
  mustache: (ctx) => combine([['facialHair', stubble(ctx, fullBeard(ctx.g, 2), 0.12)], ['mustache', hairMass(ctx, widen(ctx.g, mustache(ctx.g)), stacheBox(ctx.g), 90, 'stache')]]),
  handlebar: (ctx) => combine([['facialHair', stubble(ctx, fullBeard(ctx.g, 2), 0.1)], ['mustache', hairMass(ctx, widen(ctx.g, mustache(ctx.g, true)), stacheBox(ctx.g), 100, 'stache')]]),
  goatee: (ctx) => combine([
    ['facialHair', stubble(ctx, fullBeard(ctx.g, 2), 0.12)],
    ['facialHair', hairMass(ctx, `${goatee(ctx.g)}${hole(ctx.g)}`, [ctx.g.cx - 34, ctx.g.mouthY - 14, ctx.g.cx + 34, ctx.g.bottom + 16], 110, 'beard', true)],
    ['mustache', hairMass(ctx, widen(ctx.g, mustache(ctx.g)), stacheBox(ctx.g), 90, 'stache')],
  ]),
  soulPatch: (ctx) => {
    const { g } = ctx;
    const d = `M${pt(g.cx - 7, g.mouthY + 17)}L${pt(g.cx + 7, g.mouthY + 17)}L${pt(g.cx, g.mouthY + 32)}Z`;
    return combine([['mustache', hairMass(ctx, d, [g.cx - 8, g.mouthY + 15, g.cx + 8, g.mouthY + 33], 25, 'beard')]]);
  },
  muttonChops: (ctx) => {
    const { g } = ctx;
    const right = hairMass(ctx, muttonChop(g), [g.cx + 26, g.eyeY, g.cx + g.w + 10, g.jawY + 20], 120, 'beard');
    const left = hairMass(ctx, muttonChop(g), [g.cx + 26, g.eyeY, g.cx + g.w + 10, g.jawY + 20], 120, 'beard');
    return combine([
      ['facialHair', stubble(ctx, fullBeard(g, 2), 0.12)],
      ['facialHair', { defs: right.defs + left.defs, markup: right.markup + mirrored(g.cx, left.markup) }],
      ['mustache', hairMass(ctx, widen(g, mustache(g)), stacheBox(g), 90, 'stache')],
    ]);
  },
  fullBeard: (ctx) => combine([
    ['facialHair', stubble(ctx, fullBeard(ctx.g, 6), 0.45)],
    ['facialHair', hairMass(ctx, `${fullBeard(ctx.g)}${hole(ctx.g)}`, beardBox(ctx.g), 320, 'beard', true)],
    ['mustache', hairMass(ctx, widen(ctx.g, mustache(ctx.g)), stacheBox(ctx.g), 90, 'stache')],
  ]),
  longBeard: (ctx) => combine([
    ['facialHair', stubble(ctx, fullBeard(ctx.g, 6), 0.45)],
    ['facialHair', hairMass(ctx, `${longBeard(ctx.g)}${hole(ctx.g)}`, [ctx.g.cx - ctx.g.w - 20, ctx.g.noseY, ctx.g.cx + ctx.g.w + 20, 506], 520, 'beard', true)],
    ['mustache', hairMass(ctx, widen(ctx.g, mustache(ctx.g)), stacheBox(ctx.g), 90, 'stache')],
  ]),
  braidedBeard: (ctx) => {
    const { g, colors, uid } = ctx;
    const seg = uid('beardBraid');
    let braid = `<radialGradient id="${seg}" cx="0.35" cy="0.3" r="0.8"><stop offset="0" stop-color="${lighten(colors.hair, 0.25)}"/><stop offset="0.6" stop-color="${colors.hair}"/><stop offset="1" stop-color="${darken(colors.hair, 0.5)}"/></radialGradient>`;
    for (let i = 0; i < 5; i++) {
      const y = g.bottom + 30 + i * 18;
      braid += blob(g.cx, y + 2, 15 - i, 11, '#120a06', 0.35) + `<ellipse cx="${g.cx}" cy="${y}" rx="${14 - i}" ry="10.5" fill="url(#${seg})"/>`;
    }
    const beadG = uid('bead');
    braid += `<linearGradient id="${beadG}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${lighten(colors.accent, 0.4)}"/><stop offset="1" stop-color="${darken(colors.accent, 0.45)}"/></linearGradient>` +
      `<rect x="${g.cx - 10}" y="${g.bottom + 108}" width="20" height="10" rx="3" fill="url(#${beadG})"/>`;
    return combine([
      ['facialHair', { defs: '', markup: braid }],
      ['facialHair', stubble(ctx, fullBeard(g, 6), 0.45)],
      ['facialHair', hairMass(ctx, `${fullBeard(g)}${hole(g)}`, beardBox(g), 320, 'beard', true)],
      ['mustache', hairMass(ctx, widen(g, mustache(g, true)), stacheBox(g), 100, 'stache')],
    ]);
  },
};

// Moustache and the beard's mouth opening follow the lips (a smile lifts them).
for (const [id, render] of Object.entries(styles)) {
  registerStyle('facialHair', id, 'realistic', (ctx) => {
    const dy = lipOffset(ctx.g, ctx.traits);
    return render(dy ? { ...ctx, g: { ...ctx.g, mouthY: ctx.g.mouthY + dy } } : ctx);
  });
}
