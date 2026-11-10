import { registerPart } from '../registry.js';
import { facePath, mirrorPath, mirrored, pt } from '../geometry.js';
import { darken, lighten, outline } from '../color.js';

// ---------------------------------------------------------------- face shapes
const shapes = {
  oval: { label: 'Oval', w: 92, top: 128, bottom: 372, jawW: 72, jawY: 322, chinW: 24 },
  round: { label: 'Round', w: 100, top: 134, bottom: 362, jawW: 88, jawY: 316, chinW: 38, forehead: 0.7 },
  square: { label: 'Square', w: 96, top: 130, bottom: 364, jawW: 94, jawY: 334, chinW: 52, forehead: 0.78 },
  heart: { label: 'Heart', w: 100, top: 128, bottom: 368, jawW: 60, jawY: 320, chinW: 12, forehead: 0.72 },
  long: { label: 'Long', w: 84, top: 118, bottom: 382, jawW: 70, jawY: 332, chinW: 28 },
  diamond: { label: 'Diamond', w: 88, top: 132, bottom: 372, jawW: 66, jawY: 322, chinW: 16, cheekW: 102, forehead: 0.45 },
  angular: { label: 'Angular', w: 90, top: 128, bottom: 372, jawW: 84, jawY: 340, chinW: 30, forehead: 0.66 },
};

for (const [id, shape] of Object.entries(shapes)) {
  registerPart('face', {
    id,
    label: shape.label,
    shape,
    render({ g, colors, uid }) {
      const grad = uid('skinGrad');
      const skin = colors.skin;
      const defs = `<radialGradient id="${grad}" cx="0.45" cy="0.42" r="0.65">
        <stop offset="0" stop-color="${lighten(skin, 0.1)}"/>
        <stop offset="0.75" stop-color="${skin}"/>
        <stop offset="1" stop-color="${darken(skin, 0.14)}"/></radialGradient>`;
      // Cheek contour shading.
      const cheek = (s) =>
        `<path d="M${pt(g.cx + s * (g.w - 4), g.eyeY + 18)}Q${pt(g.cx + s * (g.w - 18), g.noseY + 14)} ${pt(g.cx + s * (g.jawW - 14), g.jawY - 6)}" fill="none" stroke="${darken(skin, 0.18)}" stroke-width="5" stroke-linecap="round" opacity="0.35"/>`;
      return {
        defs,
        face: `<path d="${facePath(g)}" fill="url(#${grad})" stroke="${outline(skin)}" stroke-width="3.2" stroke-linejoin="round"/>${cheek(1)}${cheek(-1)}`,
      };
    },
  });
}

// ---------------------------------------------------------------- neck (drawn as part of the face option set)
export function renderNeck({ g, colors, uid }) {
  const skin = colors.skin;
  const nw = g.neckW;
  const d = mirrorPath(g.cx, [0, g.jawY - 30], [
    [[nw * 0.6, g.jawY - 30], [nw, g.jawY - 20], [nw, g.jawY]],
    [[nw, g.shoulderY - 30], [nw + 4, g.shoulderY], [nw + 14, g.shoulderY + 20]],
    [[nw * 0.5, g.shoulderY + 40], [nw * 0.2, g.shoulderY + 40], [0, g.shoulderY + 40]],
  ]);
  const clip = uid('neckClip');
  return `<clipPath id="${clip}"><path d="${d}"/></clipPath>
    <path d="${d}" fill="${darken(skin, 0.06)}" stroke="${outline(skin)}" stroke-width="3"/>
    <g clip-path="url(#${clip})"><ellipse cx="${g.cx}" cy="${g.bottom + 4}" rx="${g.jawW}" ry="30" fill="${darken(skin, 0.35)}" opacity="0.35"/></g>`;
}

/** Neck renderer per render style (other styles register theirs here). */
export const neckStyles = { illustrated: renderNeck };

// ---------------------------------------------------------------- ears
const earShapes = {
  round: { label: 'Round', d: 'M0,-14C14,-26 28,-10 24,8C21,24 12,34 0,32', inner: 'M4,-6C14,-12 18,0 14,10C12,16 8,20 4,20' },
  small: { label: 'Small', d: 'M0,-8C10,-18 22,-6 19,6C17,18 9,24 0,22', inner: 'M3,-2C10,-6 13,2 10,8' },
  pointed: { label: 'Pointed', d: 'M0,-12C14,-22 30,-40 40,-52C36,-28 32,-2 24,12C20,24 12,32 0,30', inner: 'M5,-4C14,-12 24,-26 30,-36C26,-18 22,-2 16,10' },
  elven: { label: 'Long elven', d: 'M0,-12C18,-24 46,-58 66,-82C56,-46 40,-8 26,12C20,24 12,32 0,30', inner: 'M5,-4C18,-16 36,-40 52,-62C44,-34 30,-6 16,10' },
  // A bull's ear: out to the side, a little down, under the horns (the minotaur's).
  bovine: { label: 'Bovine', d: 'M0,-12C18,-26 50,-26 66,-12C60,2 32,12 0,14', inner: 'M8,-5C24,-15 42,-16 56,-11C46,-3 26,3 8,5', dy: -34 },
  fin: { label: 'Fin', d: 'M0,-18C14,-30 30,-34 40,-34C34,-22 38,-12 30,-4C36,4 32,14 24,16C22,26 12,32 0,30', inner: 'M6,-12L28,-26M6,-2L26,-6M6,10L22,10' },
  none: { label: 'Hidden', d: null },
};

for (const [id, ear] of Object.entries(earShapes)) {
  registerPart('ears', {
    id,
    label: ear.label,
    render({ g, colors }) {
      if (!ear.d) return {};
      const skin = colors.skin;
      const x = g.cx + g.w - 5;
      const y = g.eyeY + 6 + (ear.dy ?? 0);
      const one = `<g transform="translate(${x},${y})"><path d="${ear.d}Z" fill="${skin}" stroke="${outline(skin)}" stroke-width="3" stroke-linejoin="round"/><path d="${ear.inner}" fill="none" stroke="${darken(skin, 0.3)}" stroke-width="2.5" stroke-linecap="round" opacity="0.7"/></g>`;
      return { ears: one + mirrored(g.cx, one) };
    },
  });
}
