// Ink & wash: the look of an illustrated RPG character portrait. Pen line work
// traced from the portrait's tones, watercolour washes that granulate and pool at
// their edges, sparse hatching in the deepest shadows, on aged cream paper whose
// backdrop wash fades out at ragged edges.
import { registerRenderStyle } from '../registry.js';
import { SIZE } from '../geometry.js';
import { maskCopy } from '../realism.js';

const region = `filterUnits="userSpaceOnUse" primitiveUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}" color-interpolation-filters="sRGB"`;
const PAPER = '#efe5cf';
const INK = [0.16, 0.1, 0.06];

/** Watercolour: softened, slightly desaturated colour, lifted towards the paper, with pigment granulation. */
function washFilter(id, seed, strength) {
  return `<filter id="${id}" ${region}>` +
    `<feGaussianBlur in="SourceGraphic" stdDeviation="0.8" result="soft"/>` +
    `<feColorMatrix in="soft" type="saturate" values="0.95" result="sat"/>` +
    // Lift towards white so the paper glows through, more so for the backdrop.
    `<feComponentTransfer in="sat" result="lift"><feFuncR type="linear" slope="${strength}" intercept="${1 - strength}"/><feFuncG type="linear" slope="${strength}" intercept="${1 - strength}"/><feFuncB type="linear" slope="${strength}" intercept="${1 - strength}"/></feComponentTransfer>` +
    // Granulation: pigment settling in the paper's tooth.
    `<feTurbulence type="fractalNoise" baseFrequency="0.22" numOctaves="2" seed="${seed}" result="n"/>` +
    `<feColorMatrix in="n" type="matrix" values="0.12 0 0 0 0.93 0.12 0 0 0 0.93 0.12 0 0 0 0.93 0 0 0 0 1" result="gran"/>` +
    `<feBlend in="lift" in2="gran" mode="multiply" result="w"/>` +
    `<feComposite in="w" in2="SourceAlpha" operator="in"/></filter>`;
}

/**
 * Sketch lines by difference of Gaussians: ink where a pixel is darker than its
 * surroundings (eyes, lids, nostrils, lip parting, strands, folds), as on a pen drawing.
 */
function sketchFilter(id, fine, wide, gain, cut) {
  return `<filter id="${id}" ${region}>` +
    `<feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.3 0.6 0.1 0 0" result="L"/>` +
    `<feGaussianBlur in="L" stdDeviation="${fine}" result="b1"/><feGaussianBlur in="L" stdDeviation="${wide}" result="b2"/>` +
    `<feComposite in="b2" in2="b1" operator="arithmetic" k2="1" k3="-1" result="d"/>` +
    `<feColorMatrix in="d" type="matrix" values="0 0 0 0 ${INK[0]} 0 0 0 0 ${INK[1]} 0 0 0 0 ${INK[2]} 0 0 0 ${gain} ${-cut}" result="ink"/>` +
    `<feComposite in="ink" in2="SourceAlpha" operator="in"/></filter>`;
}

/** Pen lines where the tone changes sharply, as ink on a transparent layer. */
function inkFilter(id, radius, gain, cut) {
  return `<filter id="${id}" ${region}>` +
    `<feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.3 0.6 0.1 0 0" result="L"/>` +
    `<feMorphology in="L" operator="dilate" radius="${radius}" result="hi"/><feMorphology in="L" operator="erode" radius="${radius}" result="lo"/>` +
    `<feComposite in="hi" in2="lo" operator="arithmetic" k2="1" k3="-1" result="g"/>` +
    `<feColorMatrix in="g" type="matrix" values="0 0 0 0 ${INK[0]} 0 0 0 0 ${INK[1]} 0 0 0 0 ${INK[2]} 0 0 0 ${gain} ${-cut}"/></filter>`;
}

/** Mask source: white where the figure's tone is darker than `below` (0..1.5 scale), fading in. */
const shadeFilter = (id, below) => `<filter id="${id}" ${region}><feColorMatrix type="matrix" values="0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 -1.8 -3.6 -0.45 0 ${below * 1.6}" result="d"/><feComposite in="d" in2="SourceAlpha" operator="in"/></filter>`;
const inkRGB = `rgb(${INK.map((v) => Math.round(v * 255)).join(',')})`;
const hatchPattern = (id, angle) => `<pattern id="${id}" width="4.5" height="4.5" patternUnits="userSpaceOnUse" patternTransform="rotate(${angle})"><path d="M0,2.25H4.5" stroke="${inkRGB}" stroke-width="0.7" opacity="0.5"/></pattern>`;

registerRenderStyle({
  id: 'inkwash',
  label: 'Ink & wash',
  base: 'realistic',
  finish: false, // no photographic grade: the paper and washes carry the light
  post({ ctx, background, figure, clip, frame }) {
    const { uid, rng } = ctx;
    const seed = rng.int(1, 9999);
    const washBg = uid('washBg');
    const washFig = uid('washFig');
    const inkBold = uid('inkBold');
    const inkFine = uid('inkFine');
    const dark = uid('dark');
    const shadowMask = uid('shadowMask');
    const hatch = uid('hatch');
    const cross = uid('cross');
    const deep = uid('deep');
    const deepMask = uid('deepMask');
    const ragged = uid('ragged');
    const raggedMask = uid('raggedMask');
    const paper = uid('paper');
    const defs = washFilter(washBg, seed, 0.42) + washFilter(washFig, seed + 1, 0.95) +
      inkFilter(inkBold, 1.2, 9, 0.5) + sketchFilter(inkFine, 0.6, 2.4, 22, 0.25) +
      // Deep shadows (dark tones of the figure) select where hatching goes.
      // Shadows select where hatching goes: one direction in the half-tones, crossed in the deepest darks.
      shadeFilter(dark, 1.1) + shadeFilter(deep, 0.75) +
      `<mask id="${shadowMask}" maskUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}"><g filter="url(#${dark})">${maskCopy(figure)}</g></mask>` +
      `<mask id="${deepMask}" maskUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}"><g filter="url(#${deep})">${maskCopy(figure)}</g></mask>` +
      hatchPattern(hatch, -35) + hatchPattern(cross, 40) +
      // A ragged, irregular vignette for the backdrop wash.
      `<filter id="${ragged}" ${region}><feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="3" seed="${seed + 2}" result="n"/>` +
      `<feDisplacementMap in="SourceGraphic" in2="n" scale="46" xChannelSelector="R" yChannelSelector="G" result="d"/><feGaussianBlur in="d" stdDeviation="5"/></filter>` +
      `<mask id="${raggedMask}" maskUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}"><rect x="40" y="36" width="${SIZE - 80}" height="${SIZE - 72}" rx="40" fill="#fff" filter="url(#${ragged})"/></mask>` +
      `<filter id="${paper}" ${region}><feTurbulence type="fractalNoise" baseFrequency="0.6 0.5" numOctaves="3" seed="${seed + 3}" result="n"/>` +
      `<feColorMatrix in="n" type="matrix" values="0.12 0 0 0 0.9 0.12 0 0 0 0.88 0.12 0 0 0 0.84 0 0 0 0 1"/></filter>`;
    const markup = clip(
      `<rect width="${SIZE}" height="${SIZE}" fill="${PAPER}"/>` +
      `<rect width="${SIZE}" height="${SIZE}" fill="#fff" filter="url(#${paper})" style="mix-blend-mode:multiply"/>` +
      `<g mask="url(#${raggedMask})" style="mix-blend-mode:multiply"><g filter="url(#${washBg})">${background}</g></g>` +
      `<g filter="url(#${washFig})" style="mix-blend-mode:multiply">${figure}</g>` +
      `<rect width="${SIZE}" height="${SIZE}" fill="url(#${hatch})" mask="url(#${shadowMask})"/>` +
      `<rect width="${SIZE}" height="${SIZE}" fill="url(#${cross})" mask="url(#${deepMask})"/>` +
      `<g mask="url(#${raggedMask})" opacity="0.5"><g filter="url(#${inkFine})">${maskCopy(background)}</g></g>` +
      `<g filter="url(#${inkFine})" opacity="0.75">${maskCopy(figure)}</g>` +
      // Bold contours: the backdrop's only inside its ragged wash.
      `<g mask="url(#${raggedMask})"><g filter="url(#${inkBold})">${maskCopy(background)}</g></g>` +
      `<g filter="url(#${inkBold})">${maskCopy(figure)}</g>`,
    ) + frame;
    return { defs, markup };
  },
});
