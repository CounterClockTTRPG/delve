// Engraving: the realistic portrait printed as ink lines on paper. Line
// thickness follows the tone (thin in the light, thick in shadow) and a second
// set of lines cross-hatches the darkest areas.
//
// How: the portrait's luminance goes into the red channel; two triangle-wave
// line patterns go into green and blue (combined with mix-blend-mode: lighten,
// i.e. a per-channel max). One filter then thresholds tone + pattern per pixel.
import { registerRenderStyle } from '../registry.js';
import { SIZE } from '../geometry.js';
import { maskCopy } from '../realism.js';
import { hexToRgb } from '../color.js';

const INK = '#2a1c14';
const PAPER = '#efe4c9';
const region = `filterUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}" color-interpolation-filters="sRGB"`;

/**
 * Engraved lines as a repeating triangle wave (0 on the line, 1 between lines) in
 * one channel. Rings centred far off the canvas give gently curved hatching.
 */
function rings(id, channel, period, cx, cy) {
  const c = { g: '#00ff00', b: '#0000ff' }[channel];
  return `<radialGradient id="${id}" gradientUnits="userSpaceOnUse" cx="${cx}" cy="${cy}" r="${period}" spreadMethod="repeat">` +
    `<stop offset="0" stop-color="#000"/><stop offset="0.5" stop-color="${c}"/><stop offset="1" stop-color="#000"/></radialGradient>`;
}

/** Straight engraved lines (see rings). */
function lines(id, channel, period, dir) {
  const c = { g: '#00ff00', b: '#0000ff' }[channel];
  const [x2, y2] = { main: [period / 2, period / 2], cross: [period / 2, -period / 2], horizontal: [0, period] }[dir];
  return `<linearGradient id="${id}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="${x2}" y2="${y2}" spreadMethod="repeat">` +
    `<stop offset="0" stop-color="#000"/><stop offset="0.5" stop-color="${c}"/><stop offset="1" stop-color="#000"/></linearGradient>`;
}

registerRenderStyle({
  id: 'engraving',
  label: 'Engraving',
  base: 'realistic',
  finish: false, // no photographic grade: vignette and grain would print as ink
  post({ content, ctx, figure }) {
    const { uid, rng } = ctx;
    const tone = uid('tone');
    const hatchA = uid('hatchA');
    const hatchB = uid('hatchB');
    const hatchH = uid('hatchH');
    const silhouette = uid('silhouette');
    const figMask = uid('figMask');
    const engrave = uid('engrave');
    const [ir, ig, ib] = hexToRgb(INK).map((v) => v / 255);
    const [pr, pg, pb] = hexToRgb(PAPER).map((v) => v / 255);
    const f = (n) => +n.toFixed(4);
    const defs =
      // Luminance (with a little contrast) into red; green and blue cleared.
      `<filter id="${tone}" ${region}>` +
      `<feColorMatrix type="matrix" values="0.2126 0.7152 0.0722 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1"/>` +
      // Brightened, and kept off solid black so even the darkest areas show some paper between the lines.
      `<feComponentTransfer><feFuncR type="table" tableValues="0.04 0.12 0.28 0.52 0.82 0.98 1"/></feComponentTransfer></filter>` +
      rings(hatchA, 'g', 5.4, -260, -180) + rings(hatchB, 'b', 5.4, 820, -220) + lines(hatchH, 'g', 6.5, 'horizontal') +
      // The figure's silhouette (white wherever it has any opacity), to give it its own line direction.
      `<filter id="${silhouette}" ${region}><feColorMatrix type="matrix" values="0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 1 0"/></filter>` +
      `<mask id="${figMask}" maskUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}"><g filter="url(#${silhouette})">${maskCopy(figure)}</g></mask>` +
      `<filter id="${engrave}" ${region}>` +
      // A little noise in the tone makes the lines waver like a hand-cut plate.
      `<feTurbulence type="fractalNoise" baseFrequency="0.06" numOctaves="2" seed="${rng.int(1, 9999)}" result="n"/>` +
      `<feComposite in="SourceGraphic" in2="n" operator="arithmetic" k2="1" k3="0.08" k4="-0.04" result="src"/>` +
      // Paper where tone + pattern clears the threshold: main lines everywhere, cross lines in shadow.
      `<feColorMatrix in="src" type="matrix" values="0.5 0.5 0 0 0  0.5 0 0.5 0 0.2  0 0 0 0 0  0 0 0 0 1" result="v"/>` +
      `<feComponentTransfer in="v" result="t"><feFuncR type="linear" slope="14" intercept="-6"/><feFuncG type="linear" slope="14" intercept="-6"/></feComponentTransfer>` +
      `<feColorMatrix in="t" type="matrix" values="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 0 0 0 0 1" result="r"/>` +
      `<feColorMatrix in="t" type="matrix" values="0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 0 0 0 1" result="g"/>` +
      `<feComposite in="r" in2="g" operator="arithmetic" k1="1" result="p0"/>` +
      // Contours: where the tone changes sharply (local max - local min), cut a line.
      `<feColorMatrix in="SourceGraphic" type="matrix" values="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 0 0 0 0 1" result="L"/>` +
      `<feMorphology in="L" operator="dilate" radius="1.4" result="hi"/><feMorphology in="L" operator="erode" radius="1.4" result="lo"/>` +
      `<feComposite in="hi" in2="lo" operator="arithmetic" k2="1" k3="-1" result="grad"/>` +
      `<feComponentTransfer in="grad" result="e"><feFuncR type="linear" slope="12" intercept="-1"/><feFuncG type="linear" slope="12" intercept="-1"/><feFuncB type="linear" slope="12" intercept="-1"/></feComponentTransfer>` +
      `<feComposite in="p0" in2="e" operator="arithmetic" k1="-1" k2="1" result="p"/>` +
      // Map 0 -> ink, 1 -> paper.
      `<feColorMatrix in="p" type="matrix" values="${f(pr - ir)} 0 0 0 ${f(ir)} ${f(pg - ig)} 0 0 0 ${f(ig)} ${f(pb - ib)} 0 0 0 ${f(ib)} 0 0 0 0 1"/>` +
      `</filter>`;
    const markup = `<g filter="url(#${engrave})" style="isolation:isolate">` +
      `<g filter="url(#${tone})"><rect width="${SIZE}" height="${SIZE}" fill="#fff"/>${content}</g>` +
      // Green: horizontal lines in the backdrop, diagonal lines on the figure.
      `<g style="mix-blend-mode:lighten"><rect width="${SIZE}" height="${SIZE}" fill="url(#${hatchH})"/>` +
      `<rect width="${SIZE}" height="${SIZE}" fill="url(#${hatchA})" mask="url(#${figMask})"/></g>` +
      `<rect width="${SIZE}" height="${SIZE}" fill="url(#${hatchB})" style="mix-blend-mode:lighten"/>` +
      `</g>`;
    return { defs, markup };
  },
});
