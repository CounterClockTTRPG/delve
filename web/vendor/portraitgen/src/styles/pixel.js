// Pixel art: the illustrated portrait with chunkier outlines, snapped to a
// coarse pixel grid and reduced to a small palette, entirely with SVG filters.
import { registerRenderStyle, registerStyle, listParts } from '../registry.js';
import { SIZE, facePath } from '../geometry.js';
import { darken, lighten } from '../color.js';

/** Pixels across the portrait. */
export const GRID = 72;

/** Thicker outlines survive the downsampling as clean one-pixel contours. */
function thicken(markup) {
  return markup.replace(/\sstroke-width="([\d.]+)"/g, (m, w) => ` stroke-width="${+Math.max(Number(w) * 2, 4).toFixed(2)}"`);
}

/** Levels per channel: a retro palette without a fixed colour table. */
const levels = (n) => Array.from({ length: n }, (_, i) => +(i / (n - 1)).toFixed(3)).join(' ');

registerRenderStyle({
  id: 'pixel',
  label: 'Pixel art',
  base: 'illustrated',
  prepare: thicken,
  post({ content, ctx }) {
    const id = ctx.uid('pixelate');
    const c = SIZE / GRID;
    // Sample one point per cell (a small flood tile repeated over the canvas),
    // keep the source only there, then grow each sample to fill its cell.
    const defs = `<filter id="${id}" filterUnits="userSpaceOnUse" primitiveUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}" color-interpolation-filters="sRGB">` +
      `<feFlood x="${c / 2 - 0.5}" y="${c / 2 - 0.5}" width="1" height="1" flood-color="#fff" result="dot"/>` +
      `<feComposite in="dot" in2="dot" operator="over" x="0" y="0" width="${c}" height="${c}" result="cell"/>` +
      `<feTile in="cell" x="0" y="0" width="${SIZE}" height="${SIZE}" result="grid"/>` +
      `<feComposite in="SourceGraphic" in2="grid" operator="in" result="samples"/>` +
      `<feMorphology in="samples" operator="dilate" radius="${c / 2}" result="pixels"/>` +
      `<feComponentTransfer in="pixels"><feFuncR type="discrete" tableValues="${levels(8)}"/><feFuncG type="discrete" tableValues="${levels(8)}"/><feFuncB type="discrete" tableValues="${levels(7)}"/><feFuncA type="discrete" tableValues="0 1"/></feComponentTransfer>` +
      `</filter>`;
    return { defs, markup: `<g filter="url(#${id})">${content}</g>` };
  },
});

// Faces: pixel artists shade with flat tones, not gradients (which would
// quantise into concentric bands). Base tone, a hard shadow on the side away
// from the light, and a small highlight.
for (const part of listParts('face')) {
  const illustrated = part.render;
  registerStyle('face', part.id, 'pixel', (ctx) => {
    const out = illustrated(ctx);
    const { g, colors, uid } = ctx;
    const skin = colors.skin;
    const clip = uid('celClip');
    const d = facePath(g);
    const cel = `<clipPath id="${clip}"><path d="${d}"/></clipPath><g clip-path="url(#${clip})">` +
      `<ellipse cx="${g.cx + g.w * 1.05}" cy="${g.eyeY + 20}" rx="${g.w * 0.55}" ry="${(g.bottom - g.top) * 0.75}" fill="${darken(skin, 0.16)}"/>` +
      `<ellipse cx="${g.cx}" cy="${g.bottom + 6}" rx="${g.jawW}" ry="18" fill="${darken(skin, 0.16)}"/>` +
      `<ellipse cx="${g.cx - g.w * 0.35}" cy="${g.top + (g.eyeY - g.top) * 0.4}" rx="${g.w * 0.28}" ry="14" fill="${lighten(skin, 0.12)}"/></g>`;
    return {
      ...out,
      defs: '',
      face: out.face.replace(/fill="url\(#[^)]+\)"/, `fill="${skin}"`).replace(/(<path d="[^"]+" fill="[^"]+"[^>]*\/>)/, `$1${cel}`),
    };
  });
}
