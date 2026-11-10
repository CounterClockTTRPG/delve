// Anime: clean thin line art, two-tone cel shading, large expressive eyes set
// low under a big forehead, a tapered chin, a tiny nose and a small mouth,
// glossy hair with an "angel ring" highlight, and a soft bloom.
import { registerRenderStyle, registerStyle, listParts, getPart } from '../registry.js';
import { SIZE, facePath, mirrored, pt, blurFilter } from '../geometry.js';
import { darken, lighten, mix } from '../color.js';
import { eyeTypes, browTypes, shifted } from '../parts/eyes.js';

const f = (n) => +n.toFixed(2);
const ink = (c) => mix(darken(c, 0.6), '#2a1418', 0.4);

/** Anime proportions on top of the face geometry. */
function animeGeometry(g, traits) {
  const fem = traits.presentation === 'feminine' ? 1 : traits.presentation === 'masculine' ? -1 : 0;
  const eyeY = g.eyeY + 12;
  return {
    ...g,
    anime: true,
    fem,
    eyeY,
    browY: eyeY - 27,
    eyeDX: g.w * 0.47,
    noseY: eyeY + (g.bottom - eyeY) * 0.42,
    mouthY: eyeY + (g.bottom - eyeY) * 0.66,
    jawW: g.jawW * (0.82 + 0.08 * Math.max(0, -fem)),
    chinW: g.chinW * (fem > 0 ? 0.35 : 0.6),
    jawY: g.jawY - 6,
  };
}

/** Thinner, uniform line art for parts drawn by the illustrated renderers. */
const thinLines = (markup) => markup.replace(/\sstroke-width="([\d.]+)"/g, (m, w) => ` stroke-width="${f(Math.max(1.2, Number(w) * 0.62))}"`);

registerRenderStyle({
  id: 'anime',
  label: 'Anime',
  base: 'illustrated',
  geometry: animeGeometry,
  prepareGeneric: thinLines,
  post({ content, ctx }) {
    // Soft bloom: a blurred, brightened copy screened over the image, and a touch more saturation.
    const id = ctx.uid('bloom');
    const defs = `<filter id="${id}" filterUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}" color-interpolation-filters="sRGB">` +
      `<feColorMatrix in="SourceGraphic" type="saturate" values="1.12" result="sat"/>` +
      `<feGaussianBlur in="sat" stdDeviation="6" result="b"/>` +
      `<feComponentTransfer in="b" result="glow"><feFuncR type="linear" slope="0.35"/><feFuncG type="linear" slope="0.35"/><feFuncB type="linear" slope="0.38"/></feComponentTransfer>` +
      `<feBlend in="sat" in2="glow" mode="screen"/></filter>`;
    return { defs, markup: `<g filter="url(#${id})">${content}</g>` };
  },
});

// ---------------------------------------------------------------- face: flat skin, crisp cel shadow, thin line
for (const part of listParts('face')) {
  registerStyle('face', part.id, 'anime', ({ g, colors, uid }) => {
    const skin = colors.skin;
    const d = facePath(g);
    const clip = uid('animeFace');
    const shadow = mix(darken(skin, 0.14), '#c05060', 0.12);
    // Shadow side and the shade cast under the hair, as hard-edged shapes.
    const cel = `<clipPath id="${clip}"><path d="${d}"/></clipPath><g clip-path="url(#${clip})">` +
      `<path d="M${pt(g.cx + g.w * 0.78, g.top)}C${pt(g.cx + g.w * 0.68, g.eyeY - 20)} ${pt(g.cx + g.w * 0.8, g.eyeY + 40)} ${pt(g.cx + g.jawW * 0.6, g.bottom)}L${pt(g.cx + g.w + 30, g.bottom + 20)}L${pt(g.cx + g.w + 30, g.top)}Z" fill="${shadow}"/>` +
      `<ellipse cx="${g.cx}" cy="${g.bottom + 10}" rx="${g.jawW * 0.9}" ry="16" fill="${shadow}"/>` +
      (g.fem >= 0 ? [-1, 1].map((k) => `<ellipse cx="${g.cx + k * (g.eyeDX + 4)}" cy="${g.noseY + 4}" rx="17" ry="8" fill="#ff8a9a" opacity="0.32"/>` +
        `<path d="M${pt(g.cx + k * (g.eyeDX - 6), g.noseY + 6)}l3,-5M${pt(g.cx + k * g.eyeDX, g.noseY + 6)}l3,-5M${pt(g.cx + k * (g.eyeDX + 6), g.noseY + 6)}l3,-5" stroke="#e86a7a" stroke-width="1.2" stroke-linecap="round" opacity="0.6"/>`).join('') : '') +
      `</g>`;
    return { face: `<path d="${d}" fill="${skin}"/>${cel}<path d="${d}" fill="none" stroke="${ink(skin)}" stroke-width="2" stroke-linejoin="round"/>` };
  });
}

// ---------------------------------------------------------------- eyes: big, tall irises, bold upper lash line
for (const [id, e] of Object.entries(eyeTypes)) {
  registerStyle('eyes', id, 'anime', ({ g, colors, uid, pose }) => {
    const { lid = 0, top: kTop = 1, bot: kBot = 1, pupil: kPupil = 1, gx = 0, gy = 0 } = pose?.eyes ?? {};
    const iris = colors.eyes;
    const fem = g.fem ?? 0;
    // Anime eyes are large and tall; the type only nudges the shape.
    const es = g.eyeScale ?? 1;
    const ew = (22 + fem * 2) * es;
    const h = 34 * es * ((e.top + e.bot) / 15) ** 0.5 * (1 + fem * 0.15) * (e.hooded ? 0.8 : 1) * (id === 'narrow' ? 0.65 : 1);
    const lift = e.lift * 0.8 + 1;
    const top = -h * 0.62 * kTop, bot = h * 0.42 * kBot;
    const lash = '#1c1216';
    const clip = uid('animeEye');
    const grad = uid('animeIris');
    const sclera = `M${pt(-ew, 1)}C${pt(-ew * 0.6, top * 1.15)} ${pt(ew * 0.55, top * 1.2 - lift)} ${pt(ew, -lift)}C${pt(ew * 0.7, bot)} ${pt(-ew * 0.6, bot * 1.1)} ${pt(-ew, 1)}Z`;
    const ir = { rx: ew * 0.54, ry: h * 0.64 };
    // Gaze: the big irises shift inside the opening (dx is mirrored for the left eye below).
    const gdx = f(gx * ew * 0.35), gdy = f(gy * h * 0.15);
    let inner;
    if (e.glow || e.blank) {
      inner = () => `<path d="${sclera}" fill="${e.blank ? '#f2f6ff' : lighten(iris, 0.5)}"/><g clip-path="url(#${clip})"><ellipse cx="0" cy="${f(top * 0.1)}" rx="${f(ir.rx * 1.2)}" ry="${f(ir.ry)}" fill="${e.blank ? '#ffffff' : iris}" opacity="0.6"/></g>`;
    } else {
      const pupil = e.slit ? `<ellipse cx="0" cy="0" rx="1.6" ry="${f(ir.ry * 0.75)}" fill="#120a0c"/>` : `<ellipse cx="0" cy="${f(ir.ry * 0.05)}" rx="${f(ir.rx * 0.45 * kPupil)}" ry="${f(ir.ry * 0.5 * kPupil)}" fill="${darken(iris, 0.7)}"/>`;
      inner = (dx) => `<path d="${sclera}" fill="#fdfcff"/><g clip-path="url(#${clip})">` +
        shifted(`<ellipse cx="0" cy="${f(top * 0.05)}" rx="${f(ir.rx)}" ry="${f(ir.ry)}" fill="url(#${grad})"/>` + pupil +
          `<ellipse cx="0" cy="${f(top * 0.05)}" rx="${f(ir.rx)}" ry="${f(ir.ry)}" fill="none" stroke="${darken(iris, 0.6)}" stroke-width="1"/>`, dx, gdy) +
        `<path d="M${pt(-ew, top * 1.3)}L${pt(ew, top * 1.3)}L${pt(ew, top * 0.35)}Q0,${f(top * 0.1)} ${pt(-ew, top * 0.35)}Z" fill="#9aa8d8" opacity="0.35"/>` + // lid shade on the white
        `</g>`;
    }
    // Blinking lowers the lash line to just past the lower rim; skin covers the eye above it.
    const shut = (y) => y + (bot * 1.15 - y) * lid;
    const upper = `M${pt(-ew - 1.5, 2)}C${pt(-ew * 0.6, shut(top * 1.2))} ${pt(ew * 0.55, shut(top * 1.25 - lift))} ${pt(ew + 3, -lift - 1)}`;
    const cover = lid > 0 ? `<g clip-path="url(#${clip})"><path d="${upper}L${pt(ew + 4, top * 1.6)}L${pt(-ew - 4, top * 1.6)}Z" fill="${colors.skin}"/></g>` : '';
    const lashes = `<path d="${upper}" fill="none" stroke="${lash}" stroke-width="${f(3.4 + fem * 0.8)}" stroke-linecap="round"/>` +
      `<path d="M${pt(ew + 1, -lift - 1)}l${f(4 + fem * 2)},${f(-3 - fem)}" stroke="${lash}" stroke-width="${f(2.2 + fem * 0.6)}" stroke-linecap="round"/>` + // outer flick
      ((fem > 0 || e.lashes) && !lid ? `<path d="M${pt(ew * 0.55, top * 1.1 - lift * 0.8)}l2.5,-3.5M${pt(ew * 0.8, top * 0.7 - lift)}l3.5,-2.5" stroke="${lash}" stroke-width="1.6" stroke-linecap="round"/>` : '') +
      `<path d="M${pt(ew * 0.1, bot * 1.05)}Q${pt(ew * 0.6, bot * 0.95)} ${pt(ew - 1, bot * 0.2)}" fill="none" stroke="${lash}" stroke-width="1.2" stroke-linecap="round" opacity="0.7"/>` +
      `<path d="M${pt(-ew * 0.7, top * 1.35 - 3)}Q${pt(0, top * 1.6 - 4)} ${pt(ew * 0.7, top * 1.35 - lift - 3)}" fill="none" stroke="${ink(colors.skin)}" stroke-width="1" opacity="0.6"/>`; // lid crease
    const one = (dx) => `<g transform="translate(${pt(g.cx + g.eyeDX, g.eyeY)})">${inner(dx)}${cover}${lashes}</g>`;
    // Highlights share one light source, so they are not mirrored; they follow the gaze.
    const hl = e.glow || e.blank || lid >= 0.5 ? '' : [g.cx + g.eyeDX, g.cx - g.eyeDX].map((x) => shifted(
      `<ellipse cx="${f(x - ir.rx * 0.38)}" cy="${f(g.eyeY + top * 0.42)}" rx="${f(ir.rx * 0.34)}" ry="${f(ir.ry * 0.28)}" fill="#fff"/>` +
      `<circle cx="${f(x + ir.rx * 0.4)}" cy="${f(g.eyeY + ir.ry * 0.35)}" r="${f(ir.rx * 0.16)}" fill="#fff" opacity="0.9"/>`, gdx, gdy)).join('');
    const defs = `<clipPath id="${clip}"><path d="${sclera}"/></clipPath>` +
      `<linearGradient id="${grad}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${darken(iris, 0.45)}"/><stop offset="0.55" stop-color="${iris}"/><stop offset="1" stop-color="${lighten(iris, 0.45)}"/></linearGradient>`;
    return { defs, eyes: one(gdx) + mirrored(g.cx, one(-gdx)) + hl };
  });
}

// ---------------------------------------------------------------- brows: thin tapered strokes
for (const [id, b] of Object.entries(browTypes)) {
  registerStyle('brows', id, 'anime', ({ g, colors }) => {
    if (!b.d) return {};
    const c = darken(colors.hair, 0.3);
    const one = `<g transform="translate(${pt(g.cx + g.eyeDX - 1, g.browY)}) scale(1.1,0.9)"><path d="${b.d}" fill="none" stroke="${c}" stroke-width="${f(Math.min(3.4, b.w * 0.5) + 0.6)}" stroke-linecap="round"/></g>`;
    return { brows: one + mirrored(g.cx, one) };
  });
}

// ---------------------------------------------------------------- nose: a small stroke, sometimes a glint
for (const part of listParts('nose')) {
  if (part.keepsShape) continue; // a race's own shape, such as the minotaur's muzzle
  registerStyle('nose', part.id, 'anime', ({ g, colors }) => {
    const c = ink(colors.skin);
    const big = ['wide', 'hooked', 'flat'].includes(part.id) ? 1.4 : 1;
    return {
      nose: `<g transform="translate(${pt(g.cx, g.noseY)})"><path d="M${f(1.5 * big)},${f(-3 * big)}L${f(3 * big)},${f(2 * big)}L0,${f(2.6 * big)}" fill="none" stroke="${c}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>` +
        `<path d="M-2,-8l1,4" stroke="#fff" stroke-width="1.4" stroke-linecap="round" opacity="0.7"/></g>`,
    };
  });
}

// ---------------------------------------------------------------- mouth: small and simple
const mouths = {
  neutral: (c) => `<path d="M-7,0Q0,1.5 7,0" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`,
  smile: (c) => `<path d="M-9,-2Q0,6 9,-2" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`,
  grin: (c) => `<path d="M-10,-2Q0,-1 10,-2Q8,12 0,12Q-8,12 -10,-2Z" fill="${c.cavity}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/><path d="M-6,8Q0,5 6,8Q4,11 0,11Q-4,11 -6,8Z" fill="${c.tongue}"/><path d="M-9,-1.5L9,-1.5L8,1.5Q0,2.5 -8,1.5Z" fill="#fff"/>`,
  smirk: (c) => `<path d="M-6,1Q2,2 9,-3" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`,
  frown: (c) => `<path d="M-7,2Q0,-3 7,2" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`,
  open: (c) => `<ellipse cx="0" cy="2" rx="5" ry="6" fill="${c.cavity}" stroke="${c.line}" stroke-width="1.5"/><ellipse cx="0" cy="5.5" rx="3.2" ry="2" fill="${c.tongue}"/>`,
  full: (c) => `<path d="M-8,0Q0,2 8,0" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/><path d="M-4,4Q0,5.5 4,4" fill="none" stroke="${c.lip}" stroke-width="1.6" stroke-linecap="round"/>`,
  pursed: (c) => `<path d="M-3,0Q0,-2 3,0Q0,3 -3,0Z" fill="${c.lip}" stroke="${c.line}" stroke-width="1.2"/>`,
  fangs: (c) => `<path d="M-8,-1Q0,4 8,-1" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/><path d="M3,1L5,5.5L6.5,0.6Z" fill="#fff" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>`,
};
for (const part of listParts('mouth')) {
  const draw = mouths[part.id];
  if (!draw) continue; // e.g. tusks keep the illustrated drawing
  registerStyle('mouth', part.id, 'anime', ({ g, colors }) => {
    const c = { line: ink(colors.skin), cavity: '#7a2a34', tongue: '#e8707a', lip: mix(colors.skin, '#d06070', 0.45) };
    return { mouth: `<g transform="translate(${pt(g.cx, g.mouthY)})">${draw(c)}</g>` };
  });
}

// ---------------------------------------------------------------- hair: cel shading and the "angel ring"
for (const part of listParts('hair')) {
  const illustrated = part.render;
  registerStyle('hair', part.id, 'anime', (ctx) => {
    const out = illustrated(ctx);
    const { g, colors, uid } = ctx;
    const hair = colors.hair;
    const line = ink(hair);
    const recolor = (m) => thinLines(m.replace(/stroke="#[0-9a-f]{6}"/g, `stroke="${line}"`));
    for (const k of ['hairBack', 'hairLocks', 'hairFront']) if (out[k]) out[k] = recolor(out[k]);
    const front = out.hairFront?.match(/<path d="([^"]+)"/)?.[1];
    if (front && !part.style?.blend) {
      const clip = uid('animeHair');
      const shade = darken(hair, 0.22);
      const gloss = lighten(hair, 0.45);
      const soft = uid('gloss');
      // Ring of gloss across the crown, broken into a jagged band, plus a shadow band near the hairline.
      // A band following the crown: smooth upper edge, jagged lower edge of strand tips.
      const n = 12;
      const at = (t, dy) => [g.cx - g.w * 0.8 + t * g.w * 1.5, g.top + 4 + Math.pow((t - 0.42) * 2, 2) * 20 + dy];
      let ring = `M${pt(...at(0, 0))}`;
      for (let i = 1; i <= n; i++) ring += `L${pt(...at(i / n, 0))}`;
      for (let i = n; i >= 0; i--) ring += `L${pt(...at(i / n, i % 2 ? 4 : 10 - Math.abs(i / n - 0.42) * 8))}`;
      ring = `<path d="${ring}Z"/>`;
      out.defs = (out.defs ?? '') + `<clipPath id="${clip}"><path d="${front}"/></clipPath>${blurFilter(soft, 0.6)}`;
      out.hairFront = out.hairFront.replace(/(<path d="[^"]+"[^>]*\/>)/, `$1<g clip-path="url(#${clip})">` +
        `<path d="M${pt(g.cx - g.w - 30, g.hairY + 4)}Q${pt(g.cx, g.hairY - 18)} ${pt(g.cx + g.w + 30, g.hairY + 4)}L${pt(g.cx + g.w + 30, g.eyeY + 60)}L${pt(g.cx - g.w - 30, g.eyeY + 60)}Z" fill="${shade}"/>` +
        `<path d="M${pt(g.cx + g.w * 0.3, g.top - 60)}L${pt(g.cx + g.w + 60, g.top - 60)}L${pt(g.cx + g.w + 60, g.eyeY + 60)}L${pt(g.cx + g.w * 0.75, g.eyeY + 60)}Z" fill="${shade}" opacity="0.6"/>` +
        `<g fill="${gloss}" opacity="0.75" filter="url(#${soft})">${ring}</g></g>`);
    }
    return out;
  });
}

// Accessories, clothing, ears and facial hair keep the illustrated drawings with thinner lines.
export { getPart };
