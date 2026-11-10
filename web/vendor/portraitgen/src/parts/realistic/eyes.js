// Realistic eyes and eyebrows.
import { registerStyle } from '../../registry.js';
import { mirrored, pt } from '../../geometry.js';
import { darken, lighten, mix, luminance } from '../../color.js';
import { blur, blob } from '../../realism.js';
import { eyeTypes, scleraPath, lidCover, posedEye, gazeShift, shifted, browTypes } from '../eyes.js';
import { shadowTone, lightTone, flush } from './face.js';

const f = (n) => +n.toFixed(2);
/** Realistic eyes are drawn a little larger: cartoon features sit too small on the head. */
// Sized so the gap between the eyes is about one eye width.
const SCALE = 1.26;
const EYE_BOX = [-40, -40, 80, 70];

/** Height of the upper lid's control points; `closing` (0 open, 1 shut) lowers them past the lower lid, as lidEdge does. */
const lidCtl = (e, closing) => {
  const y = -e.top * 1.33 + (e.bot * 1.33 + 0.5 + e.top * 1.33) * closing;
  return [y, y - e.lift * (1 - closing)];
};

/** Upper lid curve (inner corner -> outer corner), optionally shifted down by `dy` at its middle. */
const lidCurve = (e, dy = 0, closing = 0) => {
  const [y1, y2] = lidCtl(e, closing);
  return `M${pt(-e.ew - 1, 0.5)}C${pt(-e.ew * 0.5, y1 + dy)} ${pt(e.ew * 0.45, y2 + dy)} ${pt(e.ew + 1.5, -e.lift - 0.5)}`;
};

/** Point on the upper lid at parameter t (0 = inner corner). */
function lidPoint(e, t, closing = 0) {
  const [y1, y2] = lidCtl(e, closing);
  const p = [[-e.ew - 1, 0.5], [-e.ew * 0.5, y1], [e.ew * 0.45, y2], [e.ew + 1.5, -e.lift - 0.5]];
  const u = 1 - t;
  const b = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t];
  return [0, 1].map((k) => b.reduce((s, w, i) => s + w * p[i][k], 0));
}

function eye(e, ctx, ids, side) {
  const { colors, rng, g } = ctx;
  const closing = ctx.pose?.eyes?.lid ?? 0; // blinking: 0 open, 1 shut
  const fem = -(g.masc ?? 0); // 1 feminine, -1 masculine
  const skin = colors.skin;
  const iris = colors.eyes;
  const sclera = scleraPath(e);
  const line = mix(darken(colors.hair, 0.55), '#140c0a', 0.6);
  const sh = shadowTone(skin, 0.4);
  let inner;
  if (e.glow || e.blank) {
    const c = e.blank ? '#f4f8ff' : lighten(iris, 0.45);
    inner = `<path d="${sclera}" fill="${e.blank ? '#bcd4ff' : iris}" filter="url(#${ids.glow})" opacity="${f(0.95 * (1 - closing))}" transform="scale(1.5)"/>` +
      `<path d="${sclera}" fill="${e.blank ? '#e8f0ff' : iris}"/>` +
      `<g clip-path="url(#${ids.clip})">${blob(0, 0, e.ew * 0.7, e.top * 0.7, c, 0.9)}</g>`;
  } else {
    const r = e.r;
    const iy = -e.top * 0.22;
    let fibers = '';
    for (let i = 0; i < 28; i++) {
      const a = (i / 28) * Math.PI * 2 + rng.range(-0.08, 0.08);
      const r0 = r * 0.42, r1 = r * rng.range(0.75, 0.95);
      const c = rng.chance(0.55) ? lighten(iris, 0.4) : darken(iris, 0.35);
      fibers += `<path d="M${pt(Math.cos(a) * r0, iy + Math.sin(a) * r0)}L${pt(Math.cos(a) * r1, iy + Math.sin(a) * r1)}" stroke="${c}" stroke-width="${f(rng.range(0.35, 0.7))}" opacity="${f(rng.range(0.3, 0.6))}"/>`;
    }
    const pupil = e.slit
      ? `<ellipse cx="0" cy="${iy}" rx="1.4" ry="${f(r * 0.85)}" fill="#070505"/>`
      : `<circle cx="0" cy="${iy}" r="${f(r * 0.36 * (e.pupil ?? 1))}" fill="#070505"/>`;
    // Gaze: the iris shifts inside the opening (mirrored for the left eye, which is drawn flipped).
    const [gdx, gdy] = gazeShift(e, side ? 1 : -1);
    inner = `<path d="${sclera}" fill="url(#${ids.sclera})"/>` +
      `<g clip-path="url(#${ids.clip})">` +
      shifted(`<circle cx="0" cy="${iy}" r="${f(r)}" fill="url(#${ids.iris})"/>${fibers}` +
        `<circle cx="0" cy="${iy}" r="${f(r * 0.5)}" fill="none" stroke="${lighten(iris, 0.3)}" stroke-width="1.2" opacity="0.35"/>` + // collarette
        pupil, f(gdx), f(gdy)) +
      // Shadow cast by the upper lid and lashes onto the eyeball.
      `<g filter="url(#${ids.b15})"><path d="${lidCurve(e, 0, closing)}L${pt(e.ew + 4, -e.top * 3)}L${pt(-e.ew - 4, -e.top * 3)}Z" fill="#2a1612" opacity="${f(0.5 - (e.dark ?? 0) * 0.22)}" transform="translate(0,${f(e.top * 0.42)})"/></g>` +
      `</g>`;
  }
  // Caruncle (tear duct) at the inner corner.
  const caruncle = blob(-e.ew + 2.4, 0.6, 2.6, 1.8, mix(flush(skin), '#e88a8a', 0.4), 0.85);
  // Lash line, thickening towards the outer corner.
  const lid0 = mix(line, darken(skin, 0.5), 0.35 - fem * 0.15);
  const lp = (t) => pt(...lidPoint(e, t, closing));
  const lashLine = `<path d="M${lp(0.04)}C${lp(0.3)} ${lp(0.65)} ${lp(0.97)}" fill="none" stroke="${lid0}" stroke-width="${f(1 + fem * 0.25)}" stroke-linecap="round"/>` +
    `<path d="M${lp(0.45)}C${lp(0.65)} ${lp(0.82)} ${lp(0.97)}" fill="none" stroke="${line}" stroke-width="${f(1.5 + fem * 0.5)}" stroke-linecap="round" opacity="0.85"/>`;
  // Individual lashes, curving up and outward, longer towards the outer corner.
  let lashes = '';
  const n = Math.round((e.lashes ? 14 : 9) * (1 + fem * 0.35));
  for (let i = 0; i < n; i++) {
    const t = 0.3 + 0.68 * Math.sqrt((i + rng.range(0, 0.8)) / n);
    const [x, y] = lidPoint(e, t, closing);
    const len = (e.lashes ? 4.2 : 2.6) * (1 + fem * 0.35) * (0.5 + t * 0.6) * rng.range(0.7, 1.15);
    // A closing lid tips its lashes down.
    const dx = (t - 0.3) * 1.3 + 0.2 + rng.range(-0.25, 0.25), dy = closing > 0.6 ? 0.8 : -1;
    const k = Math.hypot(dx, dy);
    const ex = x + (dx / k) * len, ey = y + (dy / k) * len;
    lashes += `<path d="M${pt(x, y)}Q${pt(x + (dx / k) * len * 0.3, ey + 0.6)} ${pt(ex + 0.8, ey + 0.2)}" fill="none" stroke="${line}" stroke-width="${f(rng.range(0.4, 0.65))}" stroke-linecap="round" opacity="${f(rng.range(0.45, 0.8))}"/>`;
  }
  // Lower lid: soft rim, a wet line highlight and a few short lower lashes.
  const lower = `M${pt(-e.ew + 1, 1.2)}C${pt(-e.ew * 0.5, e.bot * 1.33 + 0.8)} ${pt(e.ew * 0.5, e.bot * 1.33 - e.lift * 0.5 + 0.8)} ${pt(e.ew + 0.5, -e.lift + 0.6)}`;
  let lowerLashes = '';
  for (let i = 0; i < 6; i++) {
    const t = 0.45 + i * 0.09;
    const x = -e.ew + 2 * e.ew * t;
    const y = e.bot * 1.0 * Math.sin(Math.PI * t) + 1.2 - e.lift * t * 0.5;
    lowerLashes += `<path d="M${pt(x, y)}l${f(0.6 + t)},${f(1.6 + t)}" stroke="${line}" stroke-width="0.4" opacity="0.12"/>`;
  }
  const lowerLid = `<path d="${lower}" fill="none" stroke="${lightTone(skin, 0.2)}" stroke-width="1.2" opacity="0.2" transform="translate(0,1)"/>` +
    `<path d="${lower}" fill="none" stroke="${darken(skin, 0.4)}" stroke-width="0.8" opacity="0.5"/>` + lowerLashes;
  // Lid fold and the skin around the eye.
  const creaseY = e.hooded ? -e.top - 1 : -e.top - 6;
  const crease = `M${pt(-e.ew * 0.85, creaseY + 2)}Q${pt(0, creaseY * 1.45 - 4)} ${pt(e.ew * 0.95, creaseY - e.lift + 1)}`;
  let lid = `<g filter="url(#${ids.b1})"><path d="${crease}" fill="none" stroke="${sh}" stroke-width="2.4" opacity="${side ? 0.7 : 0.55}"/></g>` +
    `<g filter="url(#${ids.b3})">${blob(-1, -e.top - 2, e.ew * 0.85, 3.5, lightTone(skin, 0.35), 0.35)}${blob(-e.ew - 1, -2, 4, 5, sh, 0.35)}${blob(0, e.bot * 1.5 + 3, e.ew * 0.9, 3.5, sh, 0.25)}</g>`;
  if (e.hooded && !closing) {
    lid += `<path d="${lidCurve(e)}L${pt(e.ew + 1, -e.lift + 1.5)}Q0,${f(-e.top * 0.4)} ${pt(-e.ew - 1, 1.5)}Z" fill="${darken(skin, 0.04)}"/>`;
  }
  // Blinking: the lid's skin, lit from above and shaded towards its rim, covers the eye.
  if (closing) {
    inner += `<g clip-path="url(#${ids.clip})"><path d="${lidCover(e, closing)}" fill="${mix(skin, sh, 0.3)}"/>` +
      `<g filter="url(#${ids.b15})"><path d="${lidCurve(e, 0, closing)}" fill="none" stroke="${sh}" stroke-width="2.5" opacity="0.4"/>${blob(-1, -e.top * 0.6, e.ew * 0.6, 2.5, lightTone(skin, 0.3), 0.3)}</g></g>`;
  }
  return `<g filter="url(#${ids.b05})">${caruncle}</g>${inner}${lid}${lowerLid}${lashLine}${lashes}`;
}

/** The eye's opening shaped by expression: a smile squints, surprise opens wide, sadness droops. */
function expressionEye(e, expression) {
  switch (expression) {
    case 'smile': return { ...e, top: e.top * 0.9, bot: e.bot * 0.62, lift: e.lift + 1 };
    case 'surprised': return { ...e, top: e.top * 1.3, bot: e.bot * 1.2 };
    case 'tired': return { ...e, top: e.top * 0.72, hooded: true };
    case 'stern': return { ...e, top: e.top * 0.85, bot: e.bot * 0.9 };
    case 'sad': return { ...e, lift: e.lift - 2 };
    case 'smug': return { ...e, top: e.top * 0.8 };
    default: return e;
  }
}

for (const [id, base] of Object.entries(eyeTypes)) {
  // Real eyes open less than cartoon ones: the upper lid covers the top of the iris.
  const e0 = { ...base, top: base.top * 0.8, bot: base.bot * 0.85 };
  registerStyle('eyes', id, 'realistic', (ctx) => {
    // Narrow, hooded and tired eyes keep a minimum opening, wider on dark skin where the
    // lids and sockets otherwise swallow the eye at small sizes.
    const lum = luminance(ctx.colors.skin);
    const ex0 = expressionEye(e0, ctx.traits.expression);
    const minTop = 5.2 + (1 - Math.min(1, lum * 2.5)) * 1.6;
    const e = posedEye({ ...ex0, top: Math.max(ex0.top, minTop), bot: Math.max(ex0.bot, minTop * 0.7), dark: 1 - Math.min(1, lum * 2.5) }, ctx.pose?.eyes);
    const { g, colors, uid } = ctx;
    const iris = colors.eyes;
    const ids = {
      clip: uid('eyeClip'), sclera: uid('sclera'), iris: uid('iris'), glow: uid('eyeGlow'),
      b05: uid('b05'), b1: uid('b1'), b15: uid('b15'), b3: uid('b3'),
    };
    const corner = mix(colors.skin, '#c8a8a0', 0.45 + e.dark * 0.3);
    const defs = `<clipPath id="${ids.clip}"><path d="${scleraPath(e)}"/></clipPath>` +
      `<radialGradient id="${ids.sclera}" cx="0.5" cy="0.6" r="0.55"><stop offset="0" stop-color="#f3efea"/><stop offset="0.65" stop-color="#e2d9d2"/><stop offset="1" stop-color="${corner}"/></radialGradient>` +
      `<radialGradient id="${ids.iris}"><stop offset="0.3" stop-color="${darken(iris, 0.3)}"/><stop offset="0.5" stop-color="${iris}"/><stop offset="0.78" stop-color="${lighten(iris, 0.12)}"/><stop offset="0.86" stop-color="${darken(iris, 0.3)}"/><stop offset="0.94" stop-color="${darken(iris, 0.7)}"/><stop offset="1" stop-color="${darken(iris, 0.8)}"/></radialGradient>` +
      blur(ids.glow, 3.5, EYE_BOX) + blur(ids.b05, 0.6, EYE_BOX) + blur(ids.b1, 1, EYE_BOX) + blur(ids.b15, 1.5, EYE_BOX) + blur(ids.b3, 2.5, EYE_BOX);
    const ex = g.cx + g.eyeDX;
    const ey = g.eyeY;
    const dyR = g.asym?.eyeR ?? 0, dyL = g.asym?.eyeL ?? 0;
    // Feminine presentation: very slightly larger eyes.
    const sc = SCALE * (1 - (g.masc ?? 0) * 0.04) * (g.eyeScale ?? 1);
    const right = `<g transform="translate(${pt(ex, ey + dyR)}) scale(${sc})">${eye(e, ctx, ids, true)}</g>`;
    const left = mirrored(g.cx, `<g transform="translate(${pt(ex, ey + dyL)}) scale(${sc})">${eye(e, ctx, ids, false)}</g>`);
    // Catchlights share one light source (upper left), so they are not mirrored.
    // Catchlights share one light source (upper left), so they are not mirrored. Each is clipped
    // to its eye's visible white and kept below a hooded lid, so it never sits on the eyelid.
    const lidY = e.hooded ? -e.top * 0.4 + 1.2 : -Infinity;
    const [gdx, gdy] = gazeShift(e).map((v) => f(v * sc)); // catchlights follow the gaze
    const hl = e.glow || e.blank || (ctx.pose?.eyes?.lid ?? 0) >= 0.5 ? '' : [[ex, ey + dyR, 1], [g.cx * 2 - ex, ey + dyL, -1]].map(([x, y, k]) => {
      const clipId = uid('catch');
      const hy = Math.max(-e.top * 0.22 - e.r * 0.32, lidY + e.r * 0.2);
      return `<clipPath id="${clipId}"><path d="${scleraPath(e)}" transform="translate(${pt(x, y)}) scale(${f(k * sc)},${f(sc)})"/></clipPath>` +
        `<g clip-path="url(#${clipId})">${shifted(`<circle cx="${f(x - e.r * 0.38 * sc)}" cy="${f(y + hy * sc)}" r="${f(Math.max(1.1, e.r * 0.17 * sc))}" fill="#fff" opacity="0.92"/>` +
        `<circle cx="${f(x + e.r * 0.4 * sc)}" cy="${f(y + (-e.top * 0.22 + e.r * 0.45) * sc)}" r="${f(e.r * 0.12 * sc)}" fill="#fff" opacity="0.25"/>`, gdx, gdy)}</g>`;
    }).join('');
    return { defs, eyes: right + left + hl };
  });
}

// ---------------------------------------------------------------- eyebrows
/** Parse an illustrated brow centre-line ("M x,y Q cx,cy x,y" or "M x,y L x,y") into a quadratic. */
function browCurve(d) {
  const n = d.match(/-?[\d.]+/g).map(Number);
  return n.length >= 6 ? [[n[0], n[1]], [n[2], n[3]], [n[4], n[5]]] : [[n[0], n[1]], [(n[0] + n[2]) / 2, (n[1] + n[3]) / 2], [n[2], n[3]]];
}

function browHairs(b, color, rng, k = 0) {
  // k: 1 masculine (thicker, flatter), -1 feminine (finer, more arched).
  const [p0, p1raw, p2] = browCurve(b.d);
  const p1 = [p1raw[0], p1raw[1] + k * 2.5];
  b = { ...b, w: b.w * (1 + k * 0.3) };
  const at = (t) => {
    const u = 1 - t;
    return [u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0], u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]];
  };
  const tan = (t) => {
    const x = 2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0]);
    const y = 2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1]);
    const k = Math.hypot(x, y) || 1;
    return [x / k, y / k];
  };
  const dark = darken(color, 0.25);
  const light = lighten(color, 0.15);
  let s = '';
  const n = Math.round(b.w * 14 * (b.bushy ? 1.4 : 1));
  for (let i = 0; i < n; i++) {
    const t = rng.next() ** 0.9;
    const [x, y] = at(t);
    const [tx, ty] = tan(t);
    const thick = b.w * (1.15 - 0.8 * t ** 1.2) * (b.bushy ? 1.25 : 1);
    const off = rng.range(-0.5, 0.5) * thick;
    const sx = x - ty * off, sy = y + tx * off;
    // Hairs at the inner head grow upward; along the tail they lie with the curve.
    const up = Math.max(0, 0.9 - t * 1.6);
    let dx = tx * (1 - up) + 0.25 * up, dy = ty * (1 - up) - up;
    const k = Math.hypot(dx, dy);
    dx /= k; dy /= k;
    const len = rng.range(3.5, 7) * (b.bushy ? 1.3 : 1);
    const bend = rng.range(-1, 1.2);
    s += `<path d="M${pt(sx, sy)}q${f(dx * len * 0.5 - dy * bend)},${f(dy * len * 0.5 + dx * bend)} ${f(dx * len)},${f(dy * len)}" stroke="${rng.chance(0.3) ? light : dark}" stroke-width="${f(rng.range(0.55, 1.05))}" stroke-linecap="round" fill="none" opacity="${f(rng.range(0.55, 0.95))}"/>`;
  }
  return s;
}

for (const [id, b] of Object.entries(browTypes)) {
  registerStyle('brows', id, 'realistic', ({ g, colors, uid, rng }) => {
    if (!b.d) return {};
    const c = darken(colors.hair, 0.12);
    const soft = uid('browSoft');
    const x = g.cx + g.eyeDX - 2;
    const k = g.masc ?? 0;
    const [q0, q1, q2] = browCurve(b.d);
    const arch = [q1[0], q1[1] + k * 2.5];
    const baseD = `M${pt(...q0)}Q${pt(...arch)} ${pt(...q2)}`;
    const base = `<path d="${baseD}" fill="none" stroke="${c}" stroke-width="${f(b.w * (0.9 + k * 0.3))}" stroke-linecap="round" opacity="0.5" filter="url(#${soft})"/>`;
    // Each side gets its own hairs, so the brows are not perfect mirror images.
    const side = (dy) => `<g transform="translate(${pt(x, g.browY + dy)}) scale(1.28,1.1)">${base}${browHairs(b, c, rng, k)}</g>`;
    return { defs: blur(soft, 1.6, [-30, -30, 60, 50]), brows: side(g.asym?.browR ?? 0) + mirrored(g.cx, side(g.asym?.browL ?? 0)) };
  });
}
