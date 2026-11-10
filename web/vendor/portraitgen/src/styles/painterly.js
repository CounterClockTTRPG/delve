// Painterly oil: the realistic portrait repainted. Fine detail merges into
// paint patches, colour is smeared along brush strokes, and the strokes catch
// the light as raised paint on a canvas weave.
import { registerRenderStyle } from '../registry.js';
import { SIZE, pt } from '../geometry.js';
import { createRng } from '../rng.js';

// Exactly the canvas: displacement filters misbehave in resvg when their region overhangs it.
const region = `filterUnits="userSpaceOnUse" primitiveUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}" color-interpolation-filters="sRGB"`;

/**
 * Brush strokes that follow the form of the portrait, as grey marks for a height
 * map: around the face, along the hair's flow from the crown, down the neck,
 * along the slope of the shoulders, and loose crossing strokes in the backdrop.
 * Contrast (and so relief) is gentler on the face than on the backdrop.
 */
function brushField({ g, traits }) {
  const rng = createRng(`${traits.seed}:brush`);
  const { cx, w, top, bottom, eyeY, neckW, shoulderY, jawY } = g;
  const fcy = (top + bottom) / 2 + 6, frx = w * 1.02, fry = (bottom - top) / 2 + 4;
  const longHair = ['long', 'longSwept', 'curlyLong', 'braids', 'bob'].includes(traits.hair);
  const buckets = new Map();
  const add = (grey, width, d) => {
    const k = `${grey}|${width}`;
    buckets.set(k, (buckets.get(k) ?? '') + d);
  };
  for (let i = 0; i < 2600; i++) {
    const x = rng.range(-10, SIZE + 10), y = rng.range(-10, SIZE + 10);
    const dx = x - cx;
    const inFace = (dx / frx) ** 2 + ((y - fcy) / fry) ** 2 < 1;
    const inHair = !inFace && ((dx / (w + 40)) ** 2 + ((y - fcy + 10) / (fry + 40)) ** 2 < 1 && y < eyeY + 10 ||
      longHair && Math.abs(dx) > w * 0.85 && Math.abs(dx) < w + 50 && y > eyeY - 20 && y < 470);
    const inNeck = !inFace && Math.abs(dx) < neckW && y > jawY && y < shoulderY + 12;
    const inBody = !inFace && !inNeck && !inHair && y > shoulderY - 6 + Math.max(0, Math.abs(dx) - neckW - 20) * 0.12 && Math.abs(dx) < 230;
    let a, len, width, spread;
    if (inFace) {
      // Around the face, like a painter modelling the planes with curved strokes.
      a = Math.atan2(y - fcy, dx) + Math.PI / 2 + rng.range(-0.25, 0.25);
      len = rng.range(9, 16); width = rng.pick([6, 8]); spread = 0.06;
    } else if (inHair) {
      // Along the hair's flow from the crown.
      a = Math.atan2(y - (top - 60), dx) + rng.range(-0.12, 0.12);
      len = rng.range(16, 28); width = rng.pick([4, 6]); spread = 0.07;
    } else if (inNeck) {
      a = Math.PI / 2 + Math.sign(dx) * 0.15 + rng.range(-0.15, 0.15);
      len = rng.range(10, 18); width = 7; spread = 0.04;
    } else if (inBody) {
      // Along the slope of the shoulders; folds run down near the centre.
      a = Math.abs(dx) < 50 ? Math.PI / 2 + rng.range(-0.3, 0.3) : Math.atan2(0.4, Math.sign(dx)) + rng.range(-0.2, 0.2);
      len = rng.range(18, 30); width = rng.pick([8, 11]); spread = 0.07;
    } else {
      // Loose, crossing strokes in the backdrop.
      a = (rng.chance(0.5) ? -0.6 : 0.65) + rng.range(-0.3, 0.3);
      len = rng.range(24, 40); width = rng.pick([11, 15]); spread = 0.06;
    }
    const ex = Math.cos(a) * len / 2, ey = Math.sin(a) * len / 2, bend = rng.range(-2.5, 2.5);
    const grey = Math.round((0.5 + rng.range(-1, 1) * spread) * 40) / 40;
    add(grey, width, `M${pt(x - ex, y - ey)}q${(ex - ey * bend * 0.1).toFixed(2)},${(ey + ex * bend * 0.1).toFixed(2)} ${(2 * ex).toFixed(2)},${(2 * ey).toFixed(2)}`);
  }
  let out = '';
  for (const [k, d] of buckets) {
    const [grey, width] = k.split('|').map(Number);
    const c = Math.round(grey * 255).toString(16).padStart(2, '0');
    out += `<path d="${d}" fill="none" stroke="#${c}${c}${c}" stroke-width="${width}" stroke-linecap="round"/>`;
  }
  return out;
}

registerRenderStyle({
  id: 'painterly',
  label: 'Painterly oil',
  base: 'realistic',
  post({ content, ctx, clip }) {
    const { uid, rng } = ctx;
    const id = uid('paint');
    const seed = rng.int(1, 9999);
    const light = '<feDistantLight azimuth="225" elevation="50"/>';
    const paint = `<filter id="${id}" ${region}>` +
      // Paint dabs: a light closing then opening merges small details into flat patches.
      `<feMorphology in="SourceGraphic" operator="dilate" radius="0.5" result="d1"/>` +
      `<feMorphology in="d1" operator="erode" radius="0.5" result="closed"/>` +
      `<feMorphology in="closed" operator="erode" radius="0.5" result="e1"/>` +
      `<feMorphology in="e1" operator="dilate" radius="0.5" result="dabs"/>` +
      // Smear the paint along low-frequency stroke directions.
      `<feTurbulence type="fractalNoise" baseFrequency="0.03 0.05" numOctaves="2" seed="${seed}" result="flow"/>` +
      `<feDisplacementMap in="dabs" in2="flow" scale="4" xChannelSelector="R" yChannelSelector="G" result="smear"/>` +
      // Keep the edges filled (the smear pulls in transparency there) and features legible.
      `<feMerge result="paint0"><feMergeNode in="SourceGraphic"/><feMergeNode in="smear"/></feMerge>` +
      `<feComposite in="paint0" in2="SourceGraphic" operator="arithmetic" k2="0.5" k3="0.5" result="mixed"/>` +
      `<feColorMatrix in="mixed" type="saturate" values="1.2" result="sat"/>` +
      // Old-master tone: an S-curve with warm glaze (deeper, browner shadows; creamy highlights).
      `<feComponentTransfer in="sat" result="rich"><feFuncR type="table" tableValues="0.03 0.15 0.39 0.65 0.85 0.95"/><feFuncG type="table" tableValues="0.02 0.12 0.33 0.59 0.8 0.91"/><feFuncB type="table" tableValues="0.02 0.09 0.26 0.49 0.71 0.82"/></feComponentTransfer>` +
      // Canvas weave.
      `<feTurbulence type="turbulence" baseFrequency="0.9 0.9" numOctaves="1" seed="${seed + 2}" result="weave"/>` +
      `<feColorMatrix in="weave" type="matrix" values="0.14 0 0 0 0.91 0.14 0 0 0 0.91 0.14 0 0 0 0.91 0 0 0 0 1" result="w"/>` +
      `<feBlend in="rich" in2="w" mode="multiply"/>` +
      `</filter>`;
    // Brush relief: grey strokes that follow the form, used as a height map and lit from the upper left.
    const brush = uid('brush');
    const fall = uid('fall');
    const defs = paint +
      `<filter id="${brush}" ${region}>` +
      `<feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.2126 0.7152 0.0722 0 0" result="h0"/>` +
      `<feGaussianBlur in="h0" stdDeviation="1.1" result="h"/>` +
      `<feDiffuseLighting in="h" surfaceScale="2.6" diffuseConstant="1.3" lighting-color="#fff" result="d">${light}</feDiffuseLighting>` +
      `<feSpecularLighting in="h" surfaceScale="2.6" specularConstant="0.35" specularExponent="18" lighting-color="#fff" result="s">${light}</feSpecularLighting>` +
      `<feComposite in="d" in2="s" operator="arithmetic" k2="1" k3="0.35"/></filter>` +
      // Rembrandt light: the darkness closes in around the lit head.
      `<radialGradient id="${fall}" cx="0.42" cy="0.38" r="0.7"><stop offset="0.35" stop-color="#140a04" stop-opacity="0"/><stop offset="1" stop-color="#140a04" stop-opacity="0.55"/></radialGradient>`;
    // Overlays follow the frame's clip (e.g. the circle avatar). A masked group is
    // composited on its own, so the multiply blend sits on that outer group.
    const relief = `<g filter="url(#${brush})"><rect width="${SIZE}" height="${SIZE}" fill="#808080"/>${brushField(ctx)}</g>`;
    const overlays = `<g style="mix-blend-mode:multiply">${clip(relief)}</g>` + clip(`<rect width="${SIZE}" height="${SIZE}" fill="url(#${fall})"/>`);
    // Clip the painted result too: the smear drags colour past a circular frame's edge.
    const markup = `<g style="isolation:isolate">${clip(`<g filter="url(#${id})">${content}</g>`)}${overlays}</g>`;
    return { defs, markup };
  },
});
