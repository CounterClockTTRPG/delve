// Shared building blocks for the 'realistic' render style: soft shading,
// procedural textures, volume lighting and a final photographic grade.
// The light comes from the upper left, matching the illustrated eye highlights.
import { SIZE, CX, blurFilter, pt } from './geometry.js';
import { hexToRgb, darken, lighten, mix } from './color.js';

/** Filter region covering the whole canvas (bbox-relative regions misbehave in some renderers). */
const region = `filterUnits="userSpaceOnUse" x="-64" y="-64" width="${SIZE + 128}" height="${SIZE + 128}"`;
const rgb01 = (c) => hexToRgb(c).map((v) => +(v / 255).toFixed(3));
const seedOf = (rng) => rng.int(1, 9999);

/**
 * Gaussian blur. Without `box` the filter covers the whole canvas; pass a
 * [x, y, w, h] box (in the user space of the blurred element) for small local
 * features - filters are rasterised over their whole region, so this is much faster.
 */
export const blur = (id, sd, box) => box
  ? `<filter id="${id}" filterUnits="userSpaceOnUse" x="${box[0]}" y="${box[1]}" width="${box[2]}" height="${box[3]}"><feGaussianBlur stdDeviation="${sd}"/></filter>`
  : blurFilter(id, sd);

/**
 * Coloured speckle texture (stubble, buzzed hair, pores). Apply the filter to a
 * filled shape: the speckles are clipped to that shape's alpha.
 * `density` 0..1 controls coverage, `freq` the grain size (higher = finer).
 */
export function speckleFilter(id, color, { freq = 0.8, density = 0.45, octaves = 2, rng } = {}) {
  const [r, g, b] = rgb01(color);
  const gain = 5;
  const offset = -gain * (1 - density * 0.6) + 0.4;
  return `<filter id="${id}" ${region} color-interpolation-filters="sRGB">` +
    `<feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="${octaves}" seed="${rng ? seedOf(rng) : 1}" result="n"/>` +
    `<feColorMatrix in="n" type="matrix" values="0 0 0 0 ${r} 0 0 0 0 ${g} 0 0 0 0 ${b} ${gain} 0 0 0 ${offset.toFixed(3)}" result="c"/>` +
    `<feComposite in="c" in2="SourceAlpha" operator="in"/></filter>`;
}

/**
 * Luminance noise that darkens and lightens a surface around mid grey
 * (skin pores, fabric weave, painted backdrops). Clipped to the source alpha.
 * `fx`/`fy` allow stretched noise (e.g. woven or brushed textures).
 */
export function grainFilter(id, { fx = 0.7, fy = fx, octaves = 3, strength = 0.5, rng } = {}) {
  const k = strength * 2;
  return `<filter id="${id}" ${region} color-interpolation-filters="sRGB">` +
    `<feTurbulence type="fractalNoise" baseFrequency="${fx} ${fy}" numOctaves="${octaves}" seed="${rng ? seedOf(rng) : 1}" result="n"/>` +
    `<feColorMatrix in="n" type="matrix" values="${k} 0 0 0 ${(0.5 - k / 2).toFixed(3)} ${k} 0 0 0 ${(0.5 - k / 2).toFixed(3)} ${k} 0 0 0 ${(0.5 - k / 2).toFixed(3)} 0 0 0 0 1" result="c"/>` +
    `<feComposite in="c" in2="SourceAlpha" operator="in"/></filter>`;
}

/**
 * Frays a shape's edge: the blurred silhouette is perturbed with noise and
 * re-thresholded, giving a ragged, hairy contour. (No feDisplacementMap: resvg
 * can panic on it when the canvas is scaled.) `scale` is the fray depth in px.
 */
export function frayFilter(id, { scale = 5, freq = 0.7, rng, box } = {}) {
  const r = box ? `filterUnits="userSpaceOnUse" x="${box[0]}" y="${box[1]}" width="${box[2]}" height="${box[3]}"` : region;
  return `<filter id="${id}" ${r}>` +
    `<feGaussianBlur in="SourceAlpha" stdDeviation="${+(scale * 0.3).toFixed(2)}" result="b"/>` +
    `<feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="2" seed="${rng ? seedOf(rng) : 1}" result="n"/>` +
    `<feComposite in="b" in2="n" operator="arithmetic" k2="1" k3="0.6" k4="-0.3" result="m"/>` +
    `<feComponentTransfer in="m" result="t"><feFuncA type="linear" slope="5" intercept="-2"/></feComponentTransfer>` +
    `<feComposite in="SourceGraphic" in2="t" operator="in"/></filter>`;
}

/**
 * Gives flat shapes volume: the blurred silhouette is used as a height map,
 * lit by a distant light from the upper left (diffuse multiply + soft specular).
 * `depth` is the blur radius of the bevel, `shine` the specular strength.
 */
export function volumeFilter(id, { depth = 8, relief = 5, shine = 0.35, gloss = 14, weave = 0, tall = false } = {}) {
  const light = '<feDistantLight azimuth="225" elevation="48"/>';
  // Optional fabric weave: fine stretched noise multiplied into the lit result.
  const tex = weave
    ? `<feTurbulence type="fractalNoise" baseFrequency="0.9 0.25" numOctaves="2" seed="7" result="wn"/>` +
      `<feColorMatrix in="wn" type="matrix" values="${weave} 0 0 0 ${1 - weave / 2} ${weave} 0 0 0 ${1 - weave / 2} ${weave} 0 0 0 ${1 - weave / 2} 0 0 0 0 1" result="w"/>` +
      `<feBlend in="lit" in2="w" mode="multiply" result="lit"/>`
    : '';
  return `<filter id="${id}" ${tall ? `filterUnits="userSpaceOnUse" x="-64" y="-64" width="${SIZE + 128}" height="${SIZE + 360}"` : region} color-interpolation-filters="sRGB">` +
    `<feGaussianBlur in="SourceAlpha" stdDeviation="${depth}" result="h"/>` +
    `<feDiffuseLighting in="h" surfaceScale="${relief}" diffuseConstant="1.3" lighting-color="#ffffff" result="d">${light}</feDiffuseLighting>` +
    `<feBlend in="SourceGraphic" in2="d" mode="multiply" result="m"/>` +
    `<feSpecularLighting in="h" surfaceScale="${relief}" specularConstant="${shine}" specularExponent="${gloss}" lighting-color="#fff6e8" result="s">${light}</feSpecularLighting>` +
    `<feComposite in="m" in2="s" operator="arithmetic" k2="1" k3="1" result="lit"/>${tex}` +
    `<feComposite in="lit" in2="SourceAlpha" operator="in"/></filter>`;
}

/**
 * Soften cartoon outlines in markup that has no realistic renderer of its own:
 * strokes on filled shapes are thinned and made translucent; strokes that ARE
 * the shape (fill="none", lines) are left alone.
 */
export function softenOutlines(markup, { width = 0.45, opacity = 0.4 } = {}) {
  return markup.replace(/<(path|circle|ellipse|rect|polygon)\b([^>]*?)(\/?)>/g, (tag, name, attrs, close) => {
    const fill = attrs.match(/\sfill="([^"]*)"/);
    const sw = attrs.match(/\sstroke-width="([\d.]+)"/);
    if (!fill || fill[1] === 'none' || !sw || !/\sstroke="(?!none)/.test(attrs)) return tag;
    let a = attrs.replace(sw[0], ` stroke-width="${+(Number(sw[1]) * width).toFixed(2)}"`);
    const so = a.match(/\sstroke-opacity="([\d.]+)"/);
    a = so ? a.replace(so[0], ` stroke-opacity="${+(Number(so[1]) * opacity).toFixed(3)}"`) : `${a} stroke-opacity="${opacity}"`;
    return `<${name}${a}${close}>`;
  });
}

/** Photographic finish over the whole portrait: key light falloff, vignette and film grain. */
export function grade({ uid, rng }) {
  const key = uid('key');
  const vig = uid('vig');
  const grain = uid('grain');
  const defs = `<radialGradient id="${key}" cx="0.3" cy="0.22" r="0.95"><stop offset="0" stop-color="#fff3df" stop-opacity="0.10"/><stop offset="0.5" stop-color="#fff3df" stop-opacity="0"/><stop offset="1" stop-color="#0b0a14" stop-opacity="0.28"/></radialGradient>` +
    `<radialGradient id="${vig}" cx="0.5" cy="0.45" r="0.72"><stop offset="0.55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.5"/></radialGradient>` +
    grainFilter(grain, { fx: 0.9, octaves: 2, strength: 0.5, rng });
  const markup = `<rect width="${SIZE}" height="${SIZE}" fill="url(#${key})"/><rect width="${SIZE}" height="${SIZE}" fill="url(#${vig})"/>` +
    `<rect width="${SIZE}" height="${SIZE}" fill="#808080" filter="url(#${grain})" opacity="0.07"/>`;
  return { defs, markup };
}

/**
 * Soft fabric folds for any clothing, clipped to the torso silhouette `torso`:
 * creases from the shoulders towards the chest, a shadow down the sternum, and
 * light on the shoulder tops (stronger on the lit, left side).
 */
export function clothFolds({ g, colors, uid }, torso) {
  const { cx, shoulderY: sY } = g;
  const clip = uid('folds');
  const b5 = uid('b5');
  const sh = mix(darken(colors.clothing, 0.5), '#0a0604', 0.3);
  const hi = lighten(colors.clothing, 0.3);
  let m = '';
  for (const k of [-1, 1]) {
    const o = k < 0 ? 0.32 : 0.45; // the shadow side carries deeper creases
    m += `<path d="M${pt(cx + k * 150, sY + 34)}Q${pt(cx + k * 110, sY + 60)} ${pt(cx + k * 70, sY + 104)}" fill="none" stroke="${sh}" stroke-width="7" opacity="${o}"/>` +
      `<path d="M${pt(cx + k * 175, sY + 70)}Q${pt(cx + k * 150, sY + 90)} ${pt(cx + k * 128, sY + 118)}" fill="none" stroke="${sh}" stroke-width="6" opacity="${o * 0.8}"/>` +
      `<path d="M${pt(cx + k * (g.neckW + 40), sY + 8)}Q${pt(cx + k * 110, sY + 10)} ${pt(cx + k * 160, sY + 30)}" fill="none" stroke="${hi}" stroke-width="8" opacity="${k < 0 ? 0.3 : 0.1}"/>`;
  }
  m += `<path d="M${pt(cx + 3, sY + 50)}L${pt(cx + 3, 520)}" stroke="${sh}" stroke-width="10" opacity="0.15"/>`;
  return {
    defs: `<clipPath id="${clip}"><path d="${torso}"/></clipPath>${blurFilter(b5, 5)}`,
    markup: `<g clip-path="url(#${clip})"><g filter="url(#${b5})">${m}</g></g>`,
  };
}

/** Depth of field for backdrops: blurred over a solid backing so the edges don't fade out. */
export function depthOfField(markup, { uid, colors }, sd = 3) {
  const id = uid('dof');
  return {
    defs: blurFilter(id, sd),
    markup: `<rect width="${SIZE}" height="${SIZE}" fill="${darken(colors.background, 0.3)}"/><g filter="url(#${id})">${markup}</g>`,
  };
}

/** Soft elliptical shadow/highlight blob, meant to be drawn inside a blurred group. */
export const blob = (cx, cy, rx, ry, fill, opacity, rot = 0) =>
  `<ellipse cx="${+cx.toFixed(2)}" cy="${+cy.toFixed(2)}" rx="${+rx.toFixed(2)}" ry="${+ry.toFixed(2)}" fill="${fill}" opacity="${opacity}"${rot ? ` transform="rotate(${rot} ${+cx.toFixed(2)} ${+cy.toFixed(2)})"` : ''}/>`;

export { CX };

/**
 * A copy of some markup for use inside a mask: ids are removed (the copy's
 * references still resolve to the originals), so the document keeps unique ids.
 */
export const maskCopy = (markup) => markup.replace(/\sid="[^"]*"/g, '');
