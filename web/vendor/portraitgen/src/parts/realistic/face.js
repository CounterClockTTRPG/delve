// Realistic renderers for face shapes, ears and the neck: no outlines, the form
// is built from soft light and shadow (key light from the upper left).
import { registerStyle, listParts } from '../../registry.js';
import { facePath, mirrorPath, mirrored, pt } from '../../geometry.js';
import { darken, lighten, mix, luminance } from '../../color.js';
import { blur, grainFilter, blob } from '../../realism.js';
import { neckStyles } from '../face.js';

/** Warm, blood-flushed variant of a skin tone (cheeks, nose, ears, lips). */
export const flush = (skin) => mix(skin, '#c8504a', 0.38);
/** Shadow tone: darker, warmer and a little more saturated than the skin. */
// Scaled by luminance: on dark skin, full-strength shadows go to black and the features vanish.
export const shadowTone = (skin, t = 0.35) => {
  const l = luminance(skin);
  return mix(darken(skin, t * (0.5 + 0.6 * Math.min(1, l * 1.4))), '#5a1e14', 0.12 - (1 - Math.min(1, l * 2)) * 0.06);
};
/** Highlight tone. Darker skin gets a warmer, less whitened highlight so it doesn't turn ashy. */
export const lightTone = (skin, t = 0.3) => {
  const l = luminance(skin);
  return mix(skin, mix('#fff4e6', '#d9a888', 1 - Math.min(1, l * 1.6)), t * (0.5 + 0.6 * l));
};

function renderFace(ctx) {
  const { g, colors, uid, rng } = ctx;
  const skin = colors.skin;
  const d = facePath(g);
  const grad = uid('skin');
  const clip = uid('faceClip');
  const b14 = uid('b14');
  const b8 = uid('b8');
  const b4 = uid('b4');
  const pores = uid('pores');
  const sh = shadowTone(skin);
  const hi = lightTone(skin);
  const red = flush(skin);
  const glint = mix(lighten(skin, 0.55), '#ffffff', 0.4);
  const { cx, w, top, bottom, eyeY, browY, noseY, mouthY, jawY, jawW, eyeDX } = g;
  const h = bottom - top;
  const box = [cx - w - 50, top - 50, 2 * w + 100, h + 110];

  const defs = `<radialGradient id="${grad}" cx="0.4" cy="0.38" r="0.7">` +
    `<stop offset="0" stop-color="${lighten(skin, 0.08)}"/><stop offset="0.6" stop-color="${skin}"/><stop offset="1" stop-color="${darken(skin, 0.2)}"/></radialGradient>` +
    `<clipPath id="${clip}"><path d="${d}"/></clipPath>` +
    blur(b14, 14, box) + blur(b8, 7, box) + blur(b4, 3.5, box) +
    grainFilter(pores, { fx: 1.4, octaves: 2, strength: 0.5, rng });

  const { cheekW, chinW } = g;
  const masc = g.masc ?? 0;
  // Side plane of the head: the boundary where the front of the face turns away,
  // running from the temple over the cheekbone and down the jaw to the chin.
  const sidePlane = (k) => `M${pt(cx + k * w * 0.78, top + h * 0.2)}C${pt(cx + k * w * 0.7, browY)} ${pt(cx + k * cheekW * 0.72, eyeY + h * 0.02)} ${pt(cx + k * cheekW * 0.74, eyeY + h * 0.1)}` +
    `C${pt(cx + k * cheekW * 0.72, eyeY + h * 0.22)} ${pt(cx + k * jawW * 0.78, jawY - h * 0.06)} ${pt(cx + k * jawW * 0.66, jawY + h * 0.03)}` +
    `C${pt(cx + k * chinW * 1.3, bottom - h * 0.04)} ${pt(cx + k * chinW * 0.9, bottom - 4)} ${pt(cx + k * chinW * 0.6, bottom + 6)}` +
    `L${pt(cx + k * (w + 40), bottom + 30)}L${pt(cx + k * (w + 40), top - 20)}Z`;

  // Broad planes of the head.
  const falloff = `<rect x="${cx}" y="${top - 20}" width="${w + 40}" height="${h + 40}" fill="${sh}" opacity="0.22"/>`; // key light
  const planes =
    `<path d="${sidePlane(1)}" fill="${sh}" opacity="0.5"/>` + `<path d="${sidePlane(-1)}" fill="${sh}" opacity="0.2"/>` +
    blob(cx, bottom + 6, jawW * 0.9, 20, sh, 0.7) + // under the chin
    blob(cx + w * 0.86, browY - 12, 18, 30, sh, 0.3) + blob(cx - w * 0.86, browY - 12, 16, 28, sh, 0.15); // temples

  // Presentation-specific modelling.
  let dimorphic = '';
  if (masc > 0) {
    const beard = mix(skin, '#3a4250', 0.35);
    dimorphic =
      blob(cx + eyeDX, browY + 4, 24, 5, sh, 0.35) + blob(cx - eyeDX, browY + 4, 22, 5, sh, 0.25) + // shelf under a heavy brow ridge
      blob(cx, browY - 4, 12, 6, hi, 0.25) + // glabella
      `<path d="M${pt(cx + cheekW * 0.92, eyeY + h * 0.2)}L${pt(cx + jawW * 0.95, jawY)}L${pt(cx + chinW, bottom - 6)}" fill="none" stroke="${sh}" stroke-width="7" opacity="0.35"/>` + // jawline
      (ctx.traits.facialHair === 'none' ? blob(cx, mouthY + 10, jawW * 0.85, (bottom - mouthY) * 0.75, beard, 0.16) + blob(cx, mouthY - 13, 24, 6, beard, 0.18) : ''); // beard shadow
  } else if (masc < 0) {
    dimorphic =
      blob(cx - cheekW * 0.55, eyeY + h * 0.06, 20, 10, hi, 0.3, -12) + // high, full cheeks
      blob(cx + cheekW * 0.55, eyeY + h * 0.06, 16, 8, hi, 0.12, 12) +
      blob(cx - eyeDX - 2, noseY + 2, 20, 12, red, 0.16) + blob(cx + eyeDX + 2, noseY + 2, 19, 11, red, 0.16) + // natural colour
      blob(cx + eyeDX + 4, eyeY - 10, 18, 6, mix(red, sh, 0.5), 0.12) + blob(cx - eyeDX - 4, eyeY - 10, 18, 6, mix(red, sh, 0.5), 0.1); // soft lid colour
  }

  // Features of the skull and soft tissue.
  const forms =
    blob(cx + eyeDX + 1, eyeY - 4, 28, 17, sh, 0.6) + blob(cx - eyeDX, eyeY - 4, 27, 16, sh, 0.45) + // eye sockets
    blob(cx + 3, eyeY - 8, 7, 18, sh, 0.25) + // root of the nose, shadow side
    blob(cx + eyeDX + 2, eyeY + 16, 18, 5, sh, 0.25) + blob(cx - eyeDX, eyeY + 16, 17, 5, sh, 0.2) + // tear troughs
    blob(cx - w * 0.2, top + (eyeY - top) * 0.42, w * 0.5, 28, hi, 0.5) + // forehead
    blob(cx - eyeDX - 2, browY - 13, 21, 7 + masc * 1.5, hi, 0.3 + masc * 0.12) + blob(cx + eyeDX, browY - 13, 18, 6, hi, 0.12) + // brow ridge
    // Under the cheekbones: a diagonal hollow from below the cheekbone towards the mouth corner.
    `<path d="M${pt(cx + cheekW * 0.8, eyeY + h * 0.12)}Q${pt(cx + cheekW * 0.55, noseY + 14)} ${pt(cx + 34, mouthY - 4)}" fill="none" stroke="${sh}" stroke-width="12" opacity="${0.35 + masc * 0.08}"/>` +
    `<path d="M${pt(cx - cheekW * 0.8, eyeY + h * 0.12)}Q${pt(cx - cheekW * 0.55, noseY + 14)} ${pt(cx - 34, mouthY - 4)}" fill="none" stroke="${sh}" stroke-width="10" opacity="${0.16 + masc * 0.05}"/>` +
    blob(cx - cheekW * 0.6, eyeY + h * 0.09, 22, 10, hi, 0.55, -12) + blob(cx + cheekW * 0.6, eyeY + h * 0.09, 17, 8, hi, 0.16, 12) + // cheekbones
    blob(cx - 6, bottom - 15, chinW * 0.7 + 6, 9, hi, 0.4) + // chin ball
    blob(cx + chinW * 0.7, bottom - 10, 9, 10, sh, 0.25) + // chin, shadow side
    blob(cx - eyeDX - 6, noseY + 8, 22, 16, red, 0.26) + blob(cx + eyeDX + 6, noseY + 8, 21, 15, red, 0.28) + // cheeks
    blob(cx, bottom - 14, 18, 10, red, 0.12) + // chin warmth
    blob(cx, mouthY + 17, 22, 6, sh, 0.25) + // mentolabial groove
    // Nasolabial folds.
    `<path d="M${pt(cx - 24, noseY + 2)}Q${pt(cx - 34, mouthY - 8)} ${pt(cx - 33, mouthY + 6)}M${pt(cx + 24, noseY + 2)}Q${pt(cx + 34, mouthY - 8)} ${pt(cx + 33, mouthY + 6)}" fill="none" stroke="${sh}" stroke-width="4" opacity="0.38"/>`;

  return {
    defs,
    face: `<path d="${d}" fill="url(#${grad})"/>` +
      `<g clip-path="url(#${clip})">` +
      `<g filter="url(#${b14})">${falloff}</g><g filter="url(#${b8})">${planes}</g>` +
      `<g filter="url(#${b8})">${forms}</g>` +
      `<g filter="url(#${b8})">${dimorphic}</g>` +
      // Healthy sheen: soft specular glints where the skin faces the light.
      `<g filter="url(#${b4})">${blob(cx - w * 0.15, top + (eyeY - top) * 0.45, 14, 7, glint, 0.22)}${blob(cx - cheekW * 0.55, eyeY + h * 0.07, 9, 4, glint, 0.28, -15)}` +
      `${blob(cx + cheekW * 0.55, eyeY + h * 0.07, 6, 3, glint, 0.12, 15)}${blob(cx - 4, bottom - 18, 6, 3.5, glint, 0.2)}</g>` +
      // Rim: the head turning away from the viewer at its contour.
      `<path d="${d}" fill="none" stroke="${darken(skin, 0.45)}" stroke-width="12" opacity="0.4" filter="url(#${b4})"/>` +
      `<rect width="512" height="512" fill="#808080" filter="url(#${pores})" opacity="0.045"/>` +
      `</g>` +
      `<path d="${d}" fill="none" stroke="${darken(skin, 0.5)}" stroke-width="1" opacity="0.35"/>`,
  };
}

for (const part of listParts('face')) registerStyle('face', part.id, 'realistic', renderFace);

// ---------------------------------------------------------------- ears
for (const part of listParts('ears')) {
  const illustrated = part.render;
  registerStyle('ears', part.id, 'realistic', (ctx) => {
    const { g, colors, uid } = ctx;
    // Reuse the illustrated silhouette, then repaint it softly.
    const src = illustrated(ctx).ears;
    if (!src) return {};
    const shape = src.match(/<path d="([^"]+)"/)?.[1];
    const inner = src.match(/<path d="([^"]+)" fill="none"/)?.[1];
    const skin = colors.skin;
    const grad = uid('ear');
    const b2 = uid('b2');
    // Real ears run from the brow line to the base of the nose.
    const x = g.cx + g.w - 6;
    const y = g.eyeY - 3;
    const defs = `<linearGradient id="${grad}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${shadowTone(skin, 0.3)}"/><stop offset="0.45" stop-color="${mix(skin, flush(skin), 0.35)}"/><stop offset="1" stop-color="${darken(skin, 0.08)}"/></linearGradient>` +
      blur(b2, 2.2, [-20, -100, 110, 150]);
    // Taller and narrower than the cartoon ear: seen from the front, an ear is mostly edge-on.
    const sx = part.id === 'pointed' || part.id === 'elven' || part.id === 'fin' ? 1.05 : 0.82;
    const one = (dark) => `<g transform="translate(${x},${y}) scale(${sx},1.22)"><path d="${shape}" fill="url(#${grad})"/>` +
      (inner ? `<path d="${inner}" fill="none" stroke="${shadowTone(skin, 0.45)}" stroke-width="4" opacity="${dark ? 0.6 : 0.45}" filter="url(#${b2})"/>` +
        `<path d="${inner}" fill="none" stroke="${lightTone(skin, 0.3)}" stroke-width="1.3" opacity="0.35" transform="translate(2,-1.5)"/>` : '') +
      `<path d="${shape}" fill="none" stroke="${darken(skin, 0.5)}" stroke-width="0.8" opacity="0.35"/></g>`;
    return { defs, ears: one(true) + mirrored(g.cx, one(false)) };
  });
}

// ---------------------------------------------------------------- neck
neckStyles.realistic = function renderNeckRealistic({ g, colors, uid }) {
  const skin = colors.skin;
  const nw = g.neckW;
  const d = mirrorPath(g.cx, [0, g.jawY - 30], [
    // Narrower just under the jaw, flaring into the trapezius towards the shoulders.
    [[nw * 0.55, g.jawY - 30], [nw * 0.86, g.jawY - 20], [nw * 0.86, g.jawY]],
    [[nw * 0.9, g.shoulderY - 40], [nw + 2, g.shoulderY - 6], [nw + 18, g.shoulderY + 20]],
    [[nw * 0.5, g.shoulderY + 40], [nw * 0.2, g.shoulderY + 40], [0, g.shoulderY + 40]],
  ]);
  const clip = uid('neckClip');
  const grad = uid('neck');
  const b8 = uid('b8');
  const b16 = uid('b16');
  const sh = shadowTone(skin, 0.45);
  const defs = `<clipPath id="${clip}"><path d="${d}"/></clipPath>` +
    `<linearGradient id="${grad}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${darken(skin, 0.12)}"/><stop offset="0.35" stop-color="${darken(skin, 0.04)}"/><stop offset="1" stop-color="${darken(skin, 0.3)}"/></linearGradient>` +
    blur(b8, 7, [g.cx - 130, g.jawY - 70, 260, 240]) + blur(b16, 14, [g.cx - 160, g.shoulderY - 50, 320, 140]);
  const neck = `<path d="${d}" fill="url(#${grad})"/>` +
    `<g clip-path="url(#${clip})"><g filter="url(#${b8})">` +
    blob(g.cx + 6, g.bottom + 8, g.jawW * 0.95, 34, sh, 0.85) + // cast shadow of the jaw
    blob(g.cx + 4, g.bottom + 26, nw * 0.9, 18, sh, 0.35) +
    `<path d="M${pt(g.cx - nw + 4, g.bottom + 30)}L${pt(g.cx - 8, g.shoulderY + 14)}M${pt(g.cx + nw - 4, g.bottom + 30)}L${pt(g.cx + 8, g.shoulderY + 14)}" stroke="${sh}" stroke-width="5" opacity="0.25"/>` + // sternocleidomastoid
    blob(g.cx - 4, g.shoulderY + 6, 9, 6, sh, 0.3) + // jugular notch
    `</g></g>`;
  // Soft shadow the head and neck cast onto the clothing.
  const shade = `<g filter="url(#${b16})">${blob(g.cx + 14, g.shoulderY + 20, nw + 46, 26, '#120a08', 0.4)}</g>`;
  return { defs, neck, shade };
};

// ---------------------------------------------------------------- blush
// A diffuse flush across the cheeks and nose, rather than two pink discs.
registerStyle('accessories', 'blush', 'realistic', ({ g, colors, uid }) => {
  const b = uid('blush');
  const c = mix(flush(colors.skin), '#e0606a', 0.4);
  const box = [g.cx - g.w - 30, g.eyeY - 20, 2 * g.w + 60, g.mouthY - g.eyeY + 40];
  return {
    defs: blur(b, 9, box),
    marks: `<g filter="url(#${b})">${blob(g.cx - g.eyeDX - 4, g.noseY, 24, 15, c, 0.32)}${blob(g.cx + g.eyeDX + 4, g.noseY, 24, 15, c, 0.32)}${blob(g.cx, g.noseY - 4, 12, 8, c, 0.18)}</g>`,
  };
});
