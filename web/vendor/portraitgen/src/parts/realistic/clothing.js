// Realistic clothing: every garment is the illustrated cut, repainted with the
// surface of its material (knit ribs, cotton weave, wool fuzz, leather grain and
// sheen, polished steel reflections, satin synthetics, hard plastic), plus
// details such as stitching.
import { registerStyle, listParts } from '../../registry.js';
import { SIZE, pt } from '../../geometry.js';
import { darken, lighten } from '../../color.js';
import { softenOutlines } from '../../realism.js';

const region = `filterUnits="userSpaceOnUse" x="-64" y="-64" width="${SIZE + 128}" height="${SIZE + 360}" color-interpolation-filters="sRGB"`;
const light = '<feDistantLight azimuth="225" elevation="48"/>';

/**
 * Material surface as one filter. relief/shine/gloss shape the lighting; tex is
 * an optional [baseFrequency, strength] noise multiplied in (weave, ribs, grain).
 */
const MATERIALS = {
  knit: { depth: 9, relief: 6, shine: 0.1, gloss: 8, tex: ['0.08 1.1', 0.55] },
  cotton: { depth: 10, relief: 6, shine: 0.14, gloss: 10, tex: ['0.9 0.6', 0.3] },
  wool: { depth: 11, relief: 5, shine: 0.06, gloss: 6, tex: ['0.6 0.6', 0.4], fuzz: true },
  leather: { depth: 6, relief: 5, shine: 0.55, gloss: 26, tex: ['0.35 0.35', 0.28] },
  satin: { depth: 9, relief: 7, shine: 0.6, gloss: 12, tex: ['1.2 0.2', 0.12] },
  plastic: { depth: 4, relief: 5, shine: 0.8, gloss: 30 },
  steel: { depth: 4, relief: 6, shine: 1.1, gloss: 40, metal: true },
};

function materialFilter(id, m, seed) {
  const tex = m.tex
    ? `<feTurbulence type="fractalNoise" baseFrequency="${m.tex[0]}" numOctaves="2" seed="${seed}" result="n"/>` +
      `<feColorMatrix in="n" type="matrix" values="${m.tex[1]} 0 0 0 ${1 - m.tex[1] / 2} ${m.tex[1]} 0 0 0 ${1 - m.tex[1] / 2} ${m.tex[1]} 0 0 0 ${1 - m.tex[1] / 2} 0 0 0 0 1" result="t"/>` +
      `<feBlend in="lit" in2="t" mode="multiply" result="lit"/>`
    : '';
  // Polished metal: remap brightness to bands of sky and ground reflection, keeping the hue.
  const metal = m.metal
    ? `<feColorMatrix in="SourceGraphic" type="matrix" values="0.3 0.6 0.1 0 0 0.3 0.6 0.1 0 0 0.3 0.6 0.1 0 0 0 0 0 1 0" result="lum"/>` +
      `<feComponentTransfer in="lum" result="bands"><feFuncR type="table" tableValues="0.15 0.55 0.3 0.85 1 0.6 0.9"/><feFuncG type="table" tableValues="0.15 0.55 0.3 0.85 1 0.6 0.9"/><feFuncB type="table" tableValues="0.18 0.6 0.34 0.88 1 0.64 0.92"/></feComponentTransfer>` +
      `<feBlend in="bands" in2="SourceGraphic" mode="multiply" result="src"/>`
    : '';
  const src = m.metal ? 'src' : 'SourceGraphic';
  const fuzz = m.fuzz
    ? `<feTurbulence type="fractalNoise" baseFrequency="0.5" numOctaves="1" seed="${seed + 1}" result="fz"/>` +
      `<feDisplacementMap in="final0" in2="fz" scale="2.5" xChannelSelector="R" yChannelSelector="G" result="final"/>`
    : '';
  return `<filter id="${id}" ${region}>` + metal +
    `<feGaussianBlur in="SourceAlpha" stdDeviation="${m.depth}" result="h"/>` +
    `<feDiffuseLighting in="h" surfaceScale="${m.relief}" diffuseConstant="1.3" lighting-color="#ffffff" result="d">${light}</feDiffuseLighting>` +
    `<feBlend in="${src}" in2="d" mode="multiply" result="m"/>` +
    `<feSpecularLighting in="h" surfaceScale="${m.relief}" specularConstant="${m.shine}" specularExponent="${m.gloss}" lighting-color="#fff6e8" result="s">${light}</feSpecularLighting>` +
    `<feComposite in="m" in2="s" operator="arithmetic" k2="1" k3="1" result="lit"/>` + tex +
    `<feComposite in="lit" in2="SourceAlpha" operator="in" result="${m.fuzz ? 'final0' : 'final'}"/>` + fuzz +
    `</filter>`;
}

/** Garment -> material, and optional details drawn over it (stitching, seams, sheen). */
const GARMENTS = {
  tshirt: { material: 'cotton' },
  hoodie: { material: 'cotton', detail: 'hem' },
  suit: { material: 'wool', detail: 'lapelSheen' },
  sweater: { material: 'knit' },
  turtleneck: { material: 'knit' },
  jacket: { material: 'leather', detail: 'stitch' },
  tunic: { material: 'cotton', detail: 'stitch' },
  robe: { material: 'wool' },
  armor: { material: 'steel' },
  leather: { material: 'leather', detail: 'stitch' },
  cloak: { material: 'wool' },
  jumpsuit: { material: 'satin', detail: 'seams' },
  exosuit: { material: 'plastic', detail: 'seams' },
  highCollar: { material: 'satin', detail: 'seams' },
  monkRobe: { material: 'wool' },
  tabard: { material: 'cotton', detail: 'stitch' },
  gambeson: { material: 'cotton' },
};

function details(kind, g, c) {
  const { cx, shoulderY: sY, neckW } = g;
  const thread = lighten(c, 0.28);
  const dashed = (d, color = thread, w = 1.4) => `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w}" stroke-dasharray="3 3" opacity="0.6"/>`;
  switch (kind) {
    case 'stitch':
      return [-1, 1].map((k) => dashed(`M${pt(cx + k * (neckW + 18), sY + 2)}Q${pt(cx + k * 110, sY + 12)} ${pt(cx + k * 165, sY + 44)}`) +
        dashed(`M${pt(cx + k * 170, sY + 60)}L${pt(cx + k * 182, 520)}`)).join('');
    case 'seams':
      return [-1, 1].map((k) => `<path d="M${pt(cx + k * (neckW + 24), sY)}Q${pt(cx + k * 120, sY + 16)} ${pt(cx + k * 170, sY + 62)}" fill="none" stroke="${darken(c, 0.45)}" stroke-width="1.6" opacity="0.6"/>` +
        `<path d="M${pt(cx + k * (neckW + 24), sY + 3)}Q${pt(cx + k * 120, sY + 19)} ${pt(cx + k * 170, sY + 65)}" fill="none" stroke="${lighten(c, 0.35)}" stroke-width="1" opacity="0.4"/>`).join('');
    case 'hem':
      return `<path d="M${pt(cx - 210, 502)}L${pt(cx + 210, 502)}" stroke="${darken(c, 0.35)}" stroke-width="10" opacity="0.4"/>`;
    case 'lapelSheen':
      return [-1, 1].map((k) => `<path d="M${pt(cx + k * (neckW + 12), sY + 4)}L${pt(cx + k * (neckW + 20), sY + 34)}" stroke="${lighten(c, 0.4)}" stroke-width="2.5" opacity="${k < 0 ? 0.45 : 0.2}"/>`).join('');
    default:
      return '';
  }
}

for (const part of listParts('clothing')) {
  const spec = GARMENTS[part.id];
  if (!spec) continue;
  const illustrated = part.render;
  registerStyle('clothing', part.id, 'realistic', (ctx) => {
    const { uid, rng, g, colors } = ctx;
    const out = illustrated(ctx);
    const m = MATERIALS[spec.material];
    const id = uid(`mat-${spec.material}`);
    const body = softenOutlines(out.body, { width: 0.35, opacity: 0.3 }) + details(spec.detail, g, colors.clothing);
    return { ...out, defs: (out.defs ?? '') + materialFilter(id, m, rng.int(1, 9999)), body: `<g filter="url(#${id})">${body}</g>` };
  });
}
