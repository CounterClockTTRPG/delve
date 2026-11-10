// Realistic renderers for accessories that the generic lighting pass can't save.
import { registerStyle } from '../../registry.js';
import { pt, facePath, mirrored } from '../../geometry.js';
import { darken, lighten, mix } from '../../color.js';
import { blur, grainFilter } from '../../realism.js';

// ---------------------------------------------------------------- hood
// Draped fabric lit from the upper left, with soft folds, and the deep shadow
// it casts over the forehead and the sides of the face.
registerStyle('accessories', 'hood', 'realistic', ({ g, colors, uid, rng }) => {
  const c = darken(colors.clothing, 0.1);
  const { cx, w, top, jawY, shoulderY: sY } = g;
  const backD = `M${pt(cx - w - 60, sY + 40)}C${pt(cx - w - 70, top - 30)} ${pt(cx - 30, top - 66)} ${pt(cx, top - 66)}C${pt(cx + 30, top - 66)} ${pt(cx + w + 70, top - 30)} ${pt(cx + w + 60, sY + 40)}Z`;
  const opening = `M${pt(cx + g.neckW + 30, sY + 4)}C${pt(cx + w + 10, jawY)} ${pt(cx + w + 22, top - 4)} ${pt(cx, top - 22)}C${pt(cx - w - 22, top - 4)} ${pt(cx - w - 10, jawY)} ${pt(cx - g.neckW - 30, sY + 4)}`;
  const rim = `M${pt(cx - w - 46, sY + 10)}C${pt(cx - w - 54, top - 20)} ${pt(cx - 30, top - 52)} ${pt(cx, top - 52)}C${pt(cx + 30, top - 52)} ${pt(cx + w + 54, top - 20)} ${pt(cx + w + 46, sY + 10)}` +
    `L${opening.slice(1)}Z`;
  const grad = uid('hood');
  const clip = uid('hoodClip');
  const fclip = uid('hoodFace');
  const weave = uid('weave');
  const b4 = uid('b4');
  const b10 = uid('b10');
  const defs = `<linearGradient id="${grad}" x1="0" y1="0" x2="1" y2="0.4"><stop offset="0" stop-color="${lighten(c, 0.12)}"/><stop offset="0.45" stop-color="${c}"/><stop offset="1" stop-color="${darken(c, 0.45)}"/></linearGradient>` +
    `<clipPath id="${clip}"><path d="${rim}"/></clipPath><clipPath id="${fclip}"><path d="${facePath(g)}"/></clipPath>` +
    grainFilter(weave, { fx: 1.1, fy: 0.5, octaves: 2, strength: 0.5, rng }) + blur(b4, 4) + blur(b10, 10);
  const folds = [-1, 1].map((k) =>
    `<path d="M${pt(cx + k * (w + 26), top + 30)}Q${pt(cx + k * (w + 40), jawY - 30)} ${pt(cx + k * (w + 34), sY - 10)}" fill="none" stroke="${darken(c, 0.5)}" stroke-width="7" opacity="0.5"/>` +
    `<path d="M${pt(cx + k * (w + 34), top + 10)}Q${pt(cx + k * (w + 48), jawY - 40)} ${pt(cx + k * (w + 44), sY)}" fill="none" stroke="${lighten(c, 0.25)}" stroke-width="5" opacity="${k < 0 ? 0.4 : 0.15}"/>`).join('') +
    `<path d="${opening}" fill="none" stroke="${darken(c, 0.6)}" stroke-width="9" opacity="0.6"/>`;
  return {
    defs,
    accBack: `<path d="${backD}" fill="${mix(darken(c, 0.55), '#0a0604', 0.3)}"/>`,
    accHead: `<path d="${rim}" fill="url(#${grad})"/>` +
      `<g clip-path="url(#${clip})"><g filter="url(#${b4})">${folds}</g><rect width="512" height="512" fill="#808080" filter="url(#${weave})" opacity="0.12"/></g>` +
      // The hood's shadow on the face: deepest at the top, falling off towards the chin.
      `<g clip-path="url(#${fclip})"><g filter="url(#${b10})"><path d="${opening}" fill="none" stroke="#0e0806" stroke-width="34" opacity="0.6"/>` +
      `<ellipse cx="${cx}" cy="${top + 4}" rx="${w + 10}" ry="38" fill="#0e0806" opacity="0.55"/></g></g>`,
  };
});

// ---------------------------------------------------------------- beanie
// A knit cap that hugs the skull, with a folded ribbed cuff, knit texture and a
// soft shadow on the forehead. The colour is muted from the accent.
registerStyle('accessories', 'beanie', 'realistic', ({ g, colors, uid, rng }) => {
  const c = mix(colors.accent, '#5a5650', 0.35);
  const { cx, w, top } = g;
  const y = g.hairY + 14;
  const ww = w + 12;
  const crown = `M${pt(cx - ww, y)}C${pt(cx - ww - 2, top - 30)} ${pt(cx - w * 0.45, top - 40)} ${pt(cx, top - 40)}C${pt(cx + w * 0.45, top - 40)} ${pt(cx + ww + 2, top - 30)} ${pt(cx + ww, y)}Z`;
  const cuff = `M${pt(cx - ww - 3, y - 14)}Q${pt(cx, y - 24)} ${pt(cx + ww + 3, y - 14)}L${pt(cx + ww + 2, y + 10)}Q${pt(cx, y + 2)} ${pt(cx - ww - 2, y + 10)}Z`;
  const grad = uid('beanie');
  const knit = uid('knit');
  const clip = uid('beanieClip');
  const fclip = uid('beanieFace');
  const b3 = uid('b3');
  const b6 = uid('b6');
  let ribs = '';
  for (let i = -9; i <= 9; i++) ribs += `M${pt(cx + i * 9, y - 22)}l0,34`;
  const defs = `<linearGradient id="${grad}" x1="0" y1="0" x2="1" y2="0.3"><stop offset="0" stop-color="${lighten(c, 0.15)}"/><stop offset="0.5" stop-color="${c}"/><stop offset="1" stop-color="${darken(c, 0.4)}"/></linearGradient>` +
    `<clipPath id="${clip}"><path d="${crown}"/><path d="${cuff}"/></clipPath><clipPath id="${fclip}"><path d="${facePath(g)}"/></clipPath>` +
    grainFilter(knit, { fx: 0.5, fy: 1.4, octaves: 2, strength: 0.7, rng }) + blur(b3, 3) + blur(b6, 6);
  return {
    defs,
    accHead:
      `<g clip-path="url(#${fclip})"><g filter="url(#${b6})"><path d="M${pt(cx - ww, y + 10)}Q${pt(cx, y + 4)} ${pt(cx + ww, y + 10)}" stroke="#120a06" stroke-width="12" opacity="0.4" fill="none"/></g></g>` +
      `<path d="${crown}" fill="url(#${grad})"/><path d="${cuff}" fill="url(#${grad})"/>` +
      `<g clip-path="url(#${clip})"><rect width="512" height="512" fill="#808080" filter="url(#${knit})" opacity="0.25"/>` +
      `<path d="${ribs}" stroke="${darken(c, 0.3)}" stroke-width="2.2" opacity="0.5"/>` +
      `<g filter="url(#${b3})"><path d="M${pt(cx - ww - 3, y - 14)}Q${pt(cx, y - 24)} ${pt(cx + ww + 3, y - 14)}" stroke="#120a06" stroke-width="6" opacity="0.35" fill="none"/>` +
      `<ellipse cx="${cx - w * 0.35}" cy="${top - 18}" rx="${w * 0.35}" ry="14" fill="${lighten(c, 0.3)}" opacity="0.35"/></g></g>`,
  };
});

// ---------------------------------------------------------------- headband
// A cloth band following the curve of the forehead, knotted at the side.
registerStyle('accessories', 'headband', 'realistic', ({ g, colors, uid, rng }) => {
  const c = mix(colors.accent, '#6a6058', 0.45);
  const { cx, w } = g;
  const y = g.hairY + 12;
  const band = `M${pt(cx - w - 8, y + 14)}Q${pt(cx, y - 18)} ${pt(cx + w + 8, y + 14)}L${pt(cx + w + 8, y + 30)}Q${pt(cx, y)} ${pt(cx - w - 8, y + 30)}Z`;
  const tails = `M${pt(cx + w + 4, y + 16)}C${pt(cx + w + 22, y + 22)} ${pt(cx + w + 30, y + 40)} ${pt(cx + w + 30, y + 62)}L${pt(cx + w + 22, y + 60)}C${pt(cx + w + 20, y + 42)} ${pt(cx + w + 12, y + 30)} ${pt(cx + w + 2, y + 26)}Z` +
    `M${pt(cx + w + 4, y + 20)}C${pt(cx + w + 14, y + 34)} ${pt(cx + w + 16, y + 52)} ${pt(cx + w + 10, y + 70)}L${pt(cx + w + 4, y + 66)}C${pt(cx + w + 8, y + 50)} ${pt(cx + w + 6, y + 36)} ${pt(cx + w, y + 26)}Z`;
  const grad = uid('band');
  const weave = uid('weave');
  const clip = uid('bandClip');
  const fclip = uid('bandFace');
  const b3 = uid('b3');
  return {
    defs: `<linearGradient id="${grad}" x1="0" y1="0" x2="1" y2="0.6"><stop offset="0" stop-color="${lighten(c, 0.2)}"/><stop offset="0.5" stop-color="${c}"/><stop offset="1" stop-color="${darken(c, 0.4)}"/></linearGradient>` +
      `<clipPath id="${clip}"><path d="${band}"/><path d="${tails}"/></clipPath><clipPath id="${fclip}"><path d="${facePath(g)}"/></clipPath>` +
      grainFilter(weave, { fx: 1.2, fy: 0.6, octaves: 2, strength: 0.6, rng }) + blur(b3, 3),
    accHead: `<g clip-path="url(#${fclip})"><g filter="url(#${b3})"><path d="M${pt(cx - w - 8, y + 28)}Q${pt(cx, y - 2)} ${pt(cx + w + 8, y + 28)}" stroke="#120a06" stroke-width="5" opacity="0.35" fill="none"/></g></g>` +
      `<path d="${tails}" fill="${darken(c, 0.2)}"/><path d="${band}" fill="url(#${grad})"/>` +
      `<g clip-path="url(#${clip})"><rect width="512" height="512" fill="#808080" filter="url(#${weave})" opacity="0.2"/>` +
      `<g filter="url(#${b3})"><path d="M${pt(cx - w * 0.7, y + 2)}Q${pt(cx - w * 0.2, y - 9)} ${pt(cx + w * 0.2, y - 5)}" stroke="${lighten(c, 0.4)}" stroke-width="3" opacity="0.5" fill="none"/></g></g>` +
      `<ellipse cx="${cx + w + 6}" cy="${y + 20}" rx="7" ry="8" fill="${darken(c, 0.25)}"/>`,
  };
});

// ---------------------------------------------------------------- visor
// A wraparound holo visor: tinted glass over the eyes (they stay faintly visible),
// a dark frame, a glowing edge and reflections of the scene in the glass.
registerStyle('accessories', 'visor', 'realistic', ({ g, colors, uid }) => {
  const { cx, w, eyeY } = g;
  const c = colors.accent;
  const d = `M${pt(cx - w - 10, eyeY - 14)}Q${pt(cx, eyeY - 26)} ${pt(cx + w + 10, eyeY - 14)}L${pt(cx + w + 6, eyeY + 12)}Q${pt(cx, eyeY + 22)} ${pt(cx - w - 6, eyeY + 12)}Z`;
  const tint = uid('visorTint');
  const clip = uid('visorClip');
  const glow = uid('visorGlow');
  return {
    defs: `<linearGradient id="${tint}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${darken(c, 0.55)}" stop-opacity="0.85"/><stop offset="0.55" stop-color="${c}" stop-opacity="0.45"/><stop offset="1" stop-color="${darken(c, 0.4)}" stop-opacity="0.75"/></linearGradient>` +
      `<clipPath id="${clip}"><path d="${d}"/></clipPath>${blur(glow, 3)}`,
    accFace: `<path d="${d}" fill="${c}" opacity="0.35" filter="url(#${glow})"/>` +
      `<path d="${d}" fill="url(#${tint})"/>` +
      `<g clip-path="url(#${clip})"><path d="M${pt(cx - w - 10, eyeY - 6)}L${pt(cx + w + 10, eyeY - 12)}L${pt(cx + w + 10, eyeY - 8)}L${pt(cx - w - 10, eyeY - 2)}Z" fill="#fff" opacity="0.35"/>` +
      `<path d="M${pt(cx - w * 0.2, eyeY - 30)}L${pt(cx + w * 0.05, eyeY - 30)}L${pt(cx - w * 0.25, eyeY + 30)}L${pt(cx - w * 0.5, eyeY + 30)}Z" fill="#fff" opacity="0.14"/></g>` +
      `<path d="${d}" fill="none" stroke="#1a1d24" stroke-width="3.5" stroke-linejoin="round"/>` +
      `<path d="M${pt(cx - w - 6, eyeY + 12)}Q${pt(cx, eyeY + 22)} ${pt(cx + w + 6, eyeY + 12)}" fill="none" stroke="${lighten(c, 0.5)}" stroke-width="1.6" opacity="0.8"/>`,
  };
});

// ---------------------------------------------------------------- sunglasses
// Dark glass that still shows a hint of the eyes, with a sky reflection and a glint.
registerStyle('accessories', 'sunglasses', 'realistic', ({ g, uid }) => {
  const ex = g.cx + g.eyeDX;
  const lensD = (x) => `M${pt(x - 24, g.eyeY - 14)}L${pt(x + 26, g.eyeY - 16)}Q${pt(x + 26, g.eyeY + 18)} ${pt(x + 2, g.eyeY + 18)}Q${pt(x - 22, g.eyeY + 16)} ${pt(x - 24, g.eyeY - 14)}Z`;
  const glass = uid('sunGlass');
  const lens = `<path d="${lensD(ex)}" fill="url(#${glass})" stroke="#15161a" stroke-width="3"/>` +
    `<path d="M${pt(ex - 18, g.eyeY - 8)}L${pt(ex + 4, g.eyeY - 10)}" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity="0.35"/>` +
    `<path d="M${pt(ex + 26, g.eyeY - 14)}L${pt(g.cx + g.w + 4, g.eyeY - 12)}" stroke="#15161a" stroke-width="3.5"/>`;
  return {
    defs: `<linearGradient id="${glass}" x1="0" y1="0" x2="0.3" y2="1"><stop offset="0" stop-color="#5a6a80" stop-opacity="0.95"/><stop offset="0.45" stop-color="#14171c" stop-opacity="0.88"/><stop offset="1" stop-color="#3a3028" stop-opacity="0.9"/></linearGradient>`,
    accFace: lens + mirrored(g.cx, lens) + `<path d="M${pt(g.cx - g.eyeDX + 24, g.eyeY - 14)}Q${pt(g.cx, g.eyeY - 18)} ${pt(ex - 24, g.eyeY - 14)}" fill="none" stroke="#15161a" stroke-width="4"/>`,
  };
});
