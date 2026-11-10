// Realistic hair: the illustrated silhouettes filled with strand flow fields,
// a soft sheen, and the shadow the hair casts on the forehead.
import { registerStyle } from '../../registry.js';
import { pt, mirrored, facePath } from '../../geometry.js';
import { darken, lighten, mix } from '../../color.js';
import { blur, blob, speckleFilter, frayFilter } from '../../realism.js';
import { styles, back } from '../hair.js';
import { SHAPES, hairShape, backShape, topShape } from './hairShapes.js';
import * as pieces from './hairPieces.js';

const f = (n) => +n.toFixed(2);

/**
 * Collects many thin strokes and emits them as a handful of compound paths,
 * grouped by colour/width/opacity: far smaller and faster than one element each.
 */
export function strokeBuckets() {
  const map = new Map();
  return {
    add(color, width, opacity, d) {
      const key = `${color}|${width}|${opacity}`;
      map.set(key, (map.get(key) ?? '') + d);
    },
    toString() {
      let s = '';
      for (const [key, d] of map) {
        const [c, w, o] = key.split('|');
        s += `<path d="${d}" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" opacity="${o}"/>`;
      }
      return s;
    },
  };
}

/** Strand palette for a hair colour, darkest first. */
export function strandPalette(hair) {
  return [darken(hair, 0.45), darken(hair, 0.25), darken(hair, 0.08), lighten(hair, 0.18), lighten(hair, 0.38)];
}

const WIDTHS = [0.6, 1, 1.6];
const OPACITIES = [0.3, 0.5, 0.7];

function strand(b, rng, pal, x0, y0, x1, y1, bend, light = 0.5) {
  const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
  const len = Math.hypot(x1 - x0, y1 - y0) || 1;
  const nx = -(y1 - y0) / len, ny = (x1 - x0) / len;
  // `light` biases the colour towards the lighter end of the palette.
  const i = Math.max(0, Math.min(pal.length - 1, Math.round(rng.range(-0.6, 1.6) + light * (pal.length - 2.5))));
  b.add(pal[i], rng.pick(WIDTHS), rng.pick(OPACITIES), `M${pt(x0, y0)}Q${pt(mx + nx * bend, my + ny * bend)} ${pt(x1, y1)}`);
}

/** Strands radiating from a crown point, with light falling from the upper left. */
function radialFlow(rng, pal, O, R, n, minR = 0, up = false) {
  const b = strokeBuckets();
  for (let k = 0; k < n; k++) {
    // Origins above the hair point downward only; a crown inside the hair radiates all round.
    // `up`: an origin below the hair, strands rising (brushed up); otherwise falling from above.
    const a = up ? rng.range(Math.PI * 1.08, Math.PI * 1.92) : minR ? rng.range(Math.PI * 0.05, Math.PI * 0.95) : rng.range(0, Math.PI * 2);
    const dx = Math.cos(a), dy = Math.sin(a);
    const r0 = rng.range(R * minR, R * 0.6);
    const len = rng.range(R * 0.3, R * 0.85);
    const light = 0.5 - dx * 0.25 - dy * 0.2;
    strand(b, rng, pal, O[0] + dx * r0, O[1] + dy * r0, O[0] + dx * (r0 + len), O[1] + dy * (r0 + len), rng.range(-1, 1) * len * 0.1, light);
  }
  return b.toString();
}

/** Strands falling downwards through a box, swaying slightly. */
function fallFlow(rng, pal, x0, x1, y0, y1, n, flare = 0) {
  const b = strokeBuckets();
  const mid = (x0 + x1) / 2;
  for (let k = 0; k < n; k++) {
    const x = rng.range(x0, x1);
    const y = rng.range(y0 - 20, y1);
    const len = rng.range(40, 140);
    const drift = ((x - mid) / ((x1 - x0) / 2 || 1)) * flare * len;
    const light = 0.55 - ((x - mid) / ((x1 - x0) || 1)) * 0.6;
    strand(b, rng, pal, x, y, x + drift + rng.range(-3, 3), y + len, rng.range(-1, 1) * 5, light);
  }
  return b.toString();
}

/** Small curls scattered over an area (curly hair, afros). */
function curlFlow(rng, pal, x0, x1, y0, y1, n, size = 6) {
  const b = strokeBuckets();
  for (let k = 0; k < n; k++) {
    const x = rng.range(x0, x1), y = rng.range(y0, y1);
    const r = size * rng.range(0.6, 1.3);
    const a = rng.range(0, Math.PI * 2);
    const ex = x + Math.cos(a) * r * 1.6, ey = y + Math.sin(a) * r * 1.6;
    const light = 0.5 - ((x - x0) / (x1 - x0) - 0.5) * 0.6 - ((y - y0) / (y1 - y0) - 0.5) * 0.4;
    const i = Math.max(0, Math.min(pal.length - 1, Math.round(rng.range(-0.6, 1.6) + light * (pal.length - 2.5))));
    b.add(pal[i], rng.pick(WIDTHS), rng.pick(OPACITIES), `M${pt(x, y)}A${f(r)},${f(r * 0.8)} ${f(a * 57.3)} 0,${rng.chance(0.5) ? 1 : 0} ${pt(ex, ey)}`);
  }
  return b.toString();
}

/**
 * Stray hairs breaking the silhouette, and fine baby hairs along the hairline:
 * the details that stop hair reading as a solid shape.
 */
function flyaways(rng, hair, outer, inner, center, shape) {
  const b = strokeBuckets();
  const c = lighten(hair, 0.12);
  const n = shape.curls ? 26 : 18;
  for (let k = 0; k < n; k++) {
    const [x, y] = outer[rng.int(2, outer.length - 3)];
    let nx = x - center[0], ny = y - center[1];
    const l = Math.hypot(nx, ny) || 1;
    nx /= l; ny /= l;
    const len = rng.range(5, shape.curls ? 12 : 16);
    const bend = rng.range(-6, 6);
    b.add(c, rng.pick([0.45, 0.65]), rng.pick([0.35, 0.55]),
      `M${pt(x - nx * 3, y - ny * 3)}q${(nx * len * 0.5 - ny * bend).toFixed(2)},${(ny * len * 0.5 + nx * bend).toFixed(2)} ${(nx * len + ny * bend * 0.5).toFixed(2)},${(ny * len - nx * bend * 0.5).toFixed(2)}`);
  }
  if (!['bangs', 'curly'].includes(shape.line)) {
    for (let k = 0; k < 16; k++) {
      const [x, y] = inner[rng.int(1, inner.length - 2)];
      if (y > center[1] - 20) continue; // only along the forehead
      b.add(darken(hair, 0.05), 0.45, rng.pick([0.3, 0.5]), `M${pt(x, y - 2)}q${rng.range(-1.5, 1.5).toFixed(2)},2 ${rng.range(-2.5, 2.5).toFixed(2)},${rng.range(3, 6).toFixed(2)}`);
    }
  }
  return b.toString();
}

/** A shaded hair mass: soft-edged fill, strands clipped to the shape, sheen and depth. */
function mass(ctx, d, fill, flow, { sheen = null, shadow = true, fray = 6 } = {}) {
  const { uid, rng } = ctx;
  const clip = uid('hairClip');
  const soft = uid('fray');
  const b6 = uid('b6');
  const shade = shadow ? `<path d="${d}" fill="none" stroke="#120a06" stroke-width="10" opacity="0.35"/>` : '';
  return {
    defs: `<clipPath id="${clip}"><path d="${d}"/></clipPath>${frayFilter(soft, { scale: fray, rng })}${blur(b6, 6)}`,
    markup: `<path d="${d}" fill="${fill}" filter="url(#${soft})"/>` +
      `<g clip-path="url(#${clip})">${flow}<g filter="url(#${b6})">${shade}${sheen ?? ''}</g></g>`,
  };
}

for (const [id, s] of Object.entries(styles)) {
  registerStyle('hair', id, 'realistic', (ctx) => {
    const { g, colors, rng, uid } = ctx;
    const hair = colors.hair;
    const pal = strandPalette(hair);
    const out = { defs: '' };
    const { cx, w, top, eyeY } = g;

    const shape = SHAPES[id];
    // ------------------------------------------------ hair behind the head
    // Buns, top knots and ponytails are built from strands rather than filled outlines.
    const BUNS = { bun: [[0, -26, 34]], topknot: [[0, -20, 22]], spaceBuns: [[-0.6, -26, 25], [0.6, -26, 25]] };
    const buns = id === 'manBun' ? [[0, -22, 26]] : BUNS[s.back];
    if (buns) {
      out.hairBack = '';
      for (const [dx, dy, r] of buns) {
        const p = pieces.bun(ctx, pal, hair, cx + dx * w, top + dy, r);
        out.defs += p.defs;
        out.hairBack += p.markup;
      }
    } else if (s.back === 'ponytail') {
      const p = pieces.ponytail(ctx, pal, hair);
      out.defs += p.defs;
      out.hairBack = p.markup;
    }
    const b = buns || s.back === 'ponytail' ? null : backShape(g, shape ?? {}, rng) ?? (['long', 'curlyLong', 'wavyLong'].includes(s.back) ? null : back(g, s.back, rng));
    if (b) {
      const flow = s.back === 'bun' || s.back === 'topknot'
        ? curlFlow(rng, pal.slice(0, 4), cx - 40, cx + 40, top - 64, top + 10, 70, 9)
        : shape?.curls
          ? curlFlow(rng, pal.slice(0, 4), cx - w - 50, cx + w + 50, top - 50, 490, 300, shape.curls)
          : fallFlow(rng, pal.slice(0, 4), cx - w - 50, cx + w + 50, top - 30, 480, 220, 0.15);
      const m = mass(ctx, b, darken(hair, 0.32), flow, {
        sheen: blob(cx - w * 0.6, top + 20, 26, 60, lighten(hair, 0.35), 0.3),
      });
      out.defs += m.defs;
      out.hairBack = m.markup;
    }

    // ------------------------------------------------ locks over the shoulders
    if (s.locks === 'braids') {
      const one = () => {
        const p = pieces.plait(ctx, pal, hair, cx + w + 2, eyeY + 30, 200);
        out.defs += p.defs;
        return p.markup;
      };
      out.hairLocks = one() + mirrored(cx, one());
    } else if (s.locks === 'dreads') {
      const p = pieces.dreads(ctx, pal, hair);
      out.defs += p.defs;
      out.hairLocks = p.markup;
    }

    // ------------------------------------------------ hair on top of the head
    if (shape) {
      const { d, outer, inner, part } = hairShape(g, shape, rng);
      let front;
      if (shape.buzz) {
        // Buzzed / shaved: scalp showing through a dense speckle of short hairs.
        const sp = uid('buzz');
        const soft = uid('b1');
        out.defs += speckleFilter(sp, darken(hair, 0.1), { freq: 1.8, density: 0.15 + shape.buzz * 0.45, rng }) + blur(soft, 0.6);
        // Opaque and only lightly softened: a translucent, blurred scalp layer reads as a ghostly cap.
        front = `<path d="${d}" fill="${mix(colors.skin, hair, shape.buzz * 0.5)}" opacity="0.9" filter="url(#${soft})"/>` +
          `<path d="${d}" fill="#000" filter="url(#${sp})"/>`;
        if (shape.rows) {
          const p = pieces.cornrows(ctx, pal, hair);
          out.defs += p.defs;
          front += p.markup;
        }
      } else {
        const grad = uid('hairTop');
        out.defs += `<linearGradient id="${grad}" x1="0.2" y1="0" x2="0.8" y2="1"><stop offset="0" stop-color="${lighten(hair, 0.06)}"/><stop offset="0.5" stop-color="${hair}"/><stop offset="1" stop-color="${darken(hair, 0.3)}"/></linearGradient>`;
        const long = shape.side === 'long' || shape.side === 'bob';
        const flow = shape.curls
          ? curlFlow(rng, pal, cx - w - 70, cx + w + 70, top - shape.vol - 30, long ? 480 : g.jawY, long ? 520 : shape.side === 'afro' ? 460 : 260, shape.curls)
          : shape.up
            ? radialFlow(rng, pal, [cx, g.eyeY + 40], g.eyeY + 40 - (top - shape.vol - (shape.quiff ?? 0)) + 10, 340, 0.5, true)
            : radialFlow(rng, pal, [cx + (part ?? 0), top - 70 - (shape.quiff ?? 0)], long ? (shape.side === 'long' ? 470 : 300) : w * 2.1, long ? 560 : 320, 0.35);
        const sheen = `<path d="M${pt(cx - w * 0.8, top + 14)}Q${pt(cx - w * 0.15, top - shape.vol - 22)} ${pt(cx + w * 0.55, top - 2)}" fill="none" stroke="${lighten(hair, 0.5)}" stroke-width="14" opacity="0.3"/>` +
          (shape.side === 'long' ? blob(cx - w - 4, g.jawY, 6, 70, lighten(hair, 0.4), 0.3) : '');
        // Slicked-back hair: tight, glossy, with long highlights combed back.
        const sleek = shape.sleek ? [-0.45, -0.15, 0.2].map((t) => `<path d="M${pt(cx + w * t, g.hairY + 4)}Q${pt(cx + w * t * 1.3, top - 4)} ${pt(cx + w * t * 1.6, top - 20)}" fill="none" stroke="${lighten(hair, 0.55)}" stroke-width="5" opacity="0.45"/>`).join('') : '';
        const m = mass(ctx, d, `url(#${grad})`, flow, { sheen: sheen + sleek, fray: shape.curls ? 12 : shape.sleek ? 2 : 6 });
        out.defs += m.defs;
        front = m.markup;
        // Parting: a thin line of shadow where the hair divides.
        if (part !== null) {
          const b15 = uid('b15');
          out.defs += blur(b15, 1.5);
          front += `<path d="M${pt(cx + part, g.hairY - 4)}Q${pt(cx + part * 0.8, top + 4)} ${pt(cx + part * 0.4, top - shape.vol + 8)}" fill="none" stroke="${darken(hair, 0.6)}" stroke-width="2.2" opacity="0.55" filter="url(#${b15})"/>`;
        }
        front += flyaways(rng, hair, outer, inner, [cx, g.eyeY], shape);
      }
      const tp = topShape(g, shape, rng);
      if (tp) {
        const m = mass(ctx, tp.d, hair, radialFlow(rng, pal, tp.origin, 150, 220), {
          sheen: blob(cx - 10, top - 14, 26, 14, lighten(hair, 0.4), 0.3),
        });
        out.defs += m.defs;
        front += m.markup + flyaways(rng, hair, tp.outer, tp.inner, [cx, g.eyeY], { curls: 0, line: 'bangs' });
      }
      out.hairFront = front;

      // Shadow the hair casts on the forehead, temples and cheeks.
      const fclip = uid('foreheadClip');
      const b5 = uid('b5');
      out.defs += `<clipPath id="${fclip}"><path d="${facePath(g)}"/></clipPath>${blur(b5, 5, [cx - w - 40, top - 40, 2 * w + 80, g.bottom - top + 60])}`;
      out.marks = `<g clip-path="url(#${fclip})"><g filter="url(#${b5})"><path d="${d}" fill="#1a0e08" opacity="${shape.buzz ? 0.12 : 0.45}" transform="translate(3,6)"/></g></g>`;
    }
    return out;
  });
}
