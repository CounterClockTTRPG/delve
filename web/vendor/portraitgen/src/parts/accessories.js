import { registerPart } from '../registry.js';
import { pt, mirrored, blurFilter } from '../geometry.js';
import { darken, lighten, mix } from '../color.js';

// Layers accessories can draw into:
//   accBack  - behind everything except background (hoods, halos)
//   accNeck  - over clothing (necklaces)
//   marks    - painted on the skin (scars, freckles, tattoos)
//   accFace  - over the face & hair (glasses, earrings)
//   accHead  - topmost (hats, crowns, horns)
// `group` makes accessories mutually exclusive (e.g. only one eyewear item).

const GOLD = '#d4af37';
const STEEL = '#9aa3ad';
const glowFilter = (id, sd = 2.5) => blurFilter(id, sd);

const defs = [
  // ------------------------------------------------------------ eyewear
  {
    id: 'glassesRound', label: 'Round glasses', group: 'eyewear',
    render({ g, colors }) {
      const fr = darken(colors.accent, 0.5), r = 21, ex = g.cx + g.eyeDX;
      const lens = `<circle cx="${ex}" cy="${g.eyeY}" r="${r}" fill="#dff1ff" fill-opacity="0.18" stroke="${fr}" stroke-width="3.5"/>` +
        `<path d="M${pt(ex + r, g.eyeY - 4)}L${pt(g.cx + g.w + 4, g.eyeY - 8)}" stroke="${fr}" stroke-width="3"/>` +
        `<path d="M${pt(ex - 10, g.eyeY - 12)}l8,-4" stroke="#fff" stroke-width="2.5" stroke-linecap="round" opacity="0.6"/>`;
      return { accFace: lens + mirrored(g.cx, lens) + `<path d="M${pt(g.cx - g.eyeDX + r, g.eyeY - 3)}Q${pt(g.cx, g.eyeY - 12)} ${pt(ex - r, g.eyeY - 3)}" stroke="${fr}" stroke-width="3" fill="none"/>` };
    },
  },
  {
    id: 'glassesSquare', label: 'Square glasses', group: 'eyewear',
    render({ g }) {
      const fr = '#2a2420', ex = g.cx + g.eyeDX;
      const lens = `<rect x="${ex - 23}" y="${g.eyeY - 16}" width="46" height="31" rx="6" fill="#dff1ff" fill-opacity="0.18" stroke="${fr}" stroke-width="5"/>` +
        `<path d="M${pt(ex + 23, g.eyeY - 8)}L${pt(g.cx + g.w + 4, g.eyeY - 10)}" stroke="${fr}" stroke-width="4"/>`;
      return { accFace: lens + mirrored(g.cx, lens) + `<path d="M${pt(g.cx - g.eyeDX + 23, g.eyeY - 6)}Q${pt(g.cx, g.eyeY - 12)} ${pt(ex - 23, g.eyeY - 6)}" stroke="${fr}" stroke-width="4" fill="none"/>` };
    },
  },
  {
    id: 'sunglasses', label: 'Sunglasses', group: 'eyewear',
    render({ g, uid }) {
      const id = uid('shade'), ex = g.cx + g.eyeDX;
      const lens = `<path d="M${pt(ex - 24, g.eyeY - 14)}L${pt(ex + 26, g.eyeY - 16)}Q${pt(ex + 26, g.eyeY + 18)} ${pt(ex + 2, g.eyeY + 18)}Q${pt(ex - 22, g.eyeY + 16)} ${pt(ex - 24, g.eyeY - 14)}Z" fill="url(#${id})" stroke="#111" stroke-width="3.5"/>` +
        `<path d="M${pt(ex + 26, g.eyeY - 14)}L${pt(g.cx + g.w + 4, g.eyeY - 12)}" stroke="#111" stroke-width="4"/>`;
      return {
        defs: `<linearGradient id="${id}" x1="0" y1="0" x2="0.4" y2="1"><stop offset="0" stop-color="#3b4452"/><stop offset="0.5" stop-color="#14171c"/><stop offset="1" stop-color="#2c3440"/></linearGradient>`,
        accFace: lens + mirrored(g.cx, lens) + `<path d="M${pt(g.cx - g.eyeDX + 24, g.eyeY - 14)}L${pt(ex - 24, g.eyeY - 14)}" stroke="#111" stroke-width="5"/>`,
      };
    },
  },
  {
    id: 'monocle', label: 'Monocle', group: 'eyewear',
    render({ g }) {
      const ex = g.cx + g.eyeDX;
      return { accFace: `<circle cx="${ex}" cy="${g.eyeY}" r="20" fill="#e8f6ff" fill-opacity="0.2" stroke="${GOLD}" stroke-width="4"/><path d="M${pt(ex + 14, g.eyeY + 15)}Q${pt(ex + 50, g.eyeY + 90)} ${pt(ex + 30, 430)}" stroke="${GOLD}" stroke-width="2" fill="none" stroke-dasharray="3 2"/>` };
    },
  },
  {
    id: 'eyepatch', label: 'Eye patch', group: 'eyewear',
    render({ g }) {
      const ex = g.cx - g.eyeDX;
      // One strap: from the patch's inner top corner diagonally up across the forehead to the far
      // temple, and from its outer edge back to the near ear.
      return { accFace: `<path d="M${pt(ex + 18, g.eyeY - 15)}Q${pt(g.cx + g.w * 0.3, g.browY - 16)} ${pt(g.cx + g.w + 2, g.hairY + 12)}" fill="none" stroke="#1d1a18" stroke-width="4.5" stroke-linecap="round"/>` +
        `<path d="M${pt(ex - 21, g.eyeY - 4)}Q${pt(g.cx - g.w + 6, g.eyeY - 8)} ${pt(g.cx - g.w - 2, g.eyeY - 10)}" fill="none" stroke="#1d1a18" stroke-width="4" stroke-linecap="round"/>` +
        `<path d="M${pt(ex - 22, g.eyeY - 12)}Q${pt(ex, g.eyeY - 24)} ${pt(ex + 22, g.eyeY - 12)}Q${pt(ex + 22, g.eyeY + 22)} ${pt(ex, g.eyeY + 22)}Q${pt(ex - 22, g.eyeY + 20)} ${pt(ex - 22, g.eyeY - 12)}Z" fill="#26211e" stroke="#0e0c0b" stroke-width="3"/>` };
    },
  },
  {
    id: 'goggles', label: 'Brass goggles', group: 'eyewear',
    render({ g }) {
      const ex = g.cx + g.eyeDX, brass = '#b5833a';
      const lens = `<circle cx="${ex}" cy="${g.eyeY}" r="24" fill="${darken(brass, 0.3)}" stroke="${darken(brass, 0.6)}" stroke-width="3"/><circle cx="${ex}" cy="${g.eyeY}" r="17" fill="#9fd3c7" fill-opacity="0.45" stroke="${lighten(brass, 0.3)}" stroke-width="3"/>` +
        `<path d="M${pt(ex - 8, g.eyeY - 8)}l7,-3" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity="0.7"/>`;
      return { accFace: `<rect x="${g.cx - g.w - 10}" y="${g.eyeY - 7}" width="${g.w * 2 + 20}" height="14" fill="#4a3424"/>` + lens + mirrored(g.cx, lens) };
    },
  },
  {
    id: 'visor', label: 'Holo visor', group: 'eyewear',
    render({ g, colors, uid }) {
      const id = uid('visor'), glow = uid('glow');
      const d = `M${pt(g.cx - g.w - 10, g.eyeY - 14)}Q${pt(g.cx, g.eyeY - 26)} ${pt(g.cx + g.w + 10, g.eyeY - 14)}L${pt(g.cx + g.w + 6, g.eyeY + 12)}Q${pt(g.cx, g.eyeY + 22)} ${pt(g.cx - g.w - 6, g.eyeY + 12)}Z`;
      return {
        defs: `<linearGradient id="${id}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${colors.accent}" stop-opacity="0.85"/><stop offset="0.5" stop-color="${lighten(colors.accent, 0.5)}" stop-opacity="0.55"/><stop offset="1" stop-color="${colors.accent}" stop-opacity="0.85"/></linearGradient>${glowFilter(glow, 4)}`,
        accFace: `<path d="${d}" fill="${colors.accent}" opacity="0.5" filter="url(#${glow})"/><path d="${d}" fill="url(#${id})" stroke="${darken(colors.accent, 0.5)}" stroke-width="3"/>` +
          `<path d="M${pt(g.cx - g.w + 6, g.eyeY - 4)}L${pt(g.cx + g.w - 6, g.eyeY - 4)}" stroke="#fff" stroke-width="1.5" opacity="0.6" stroke-dasharray="6 4"/>`,
      };
    },
  },
  {
    id: 'cyberEye', label: 'Cybernetic eye', group: 'eyewear',
    render({ g, colors, uid }) {
      const ex = g.cx - g.eyeDX, glow = uid('glow'), c = colors.accent;
      return {
        defs: glowFilter(glow, 3),
        accFace: `<path d="M${pt(ex - 26, g.eyeY - 22)}L${pt(ex + 18, g.eyeY - 26)}L${pt(ex + 24, g.eyeY + 4)}L${pt(ex + 10, g.eyeY + 26)}L${pt(ex - 22, g.eyeY + 20)}Z" fill="${STEEL}" stroke="#3d434a" stroke-width="3" stroke-linejoin="round"/>` +
          `<circle cx="${ex}" cy="${g.eyeY}" r="12" fill="#111"/><circle cx="${ex}" cy="${g.eyeY}" r="8" fill="${c}" filter="url(#${glow})"/><circle cx="${ex}" cy="${g.eyeY}" r="4" fill="${lighten(c, 0.7)}"/>` +
          `<circle cx="${ex - 19}" cy="${g.eyeY - 15}" r="2.2" fill="#3d434a"/><circle cx="${ex + 16}" cy="${g.eyeY + 16}" r="2.2" fill="#3d434a"/>`,
      };
    },
  },
  // ------------------------------------------------------------ marks on skin
  {
    id: 'scarEye', label: 'Scar over eye', layer: 'marks',
    render({ g, colors }) {
      const c = mix(colors.skin, '#b0605a', 0.45), x = g.cx - g.eyeDX + 4;
      return { marks: `<path d="M${pt(x - 8, g.browY - 20)}L${pt(x + 6, g.eyeY + 30)}" stroke="${c}" stroke-width="5" stroke-linecap="round"/><path d="M${pt(x - 8, g.browY - 20)}L${pt(x + 6, g.eyeY + 30)}" stroke="${lighten(c, 0.3)}" stroke-width="1.5" stroke-linecap="round"/>` +
        `<path d="M${pt(x - 10, g.browY - 8)}l10,-2M${pt(x - 6, g.eyeY + 14)}l10,-2M${pt(x - 4, g.eyeY + 24)}l10,-2" stroke="${c}" stroke-width="2" stroke-linecap="round"/>` };
    },
  },
  {
    id: 'scarCheek', label: 'Cheek scar', layer: 'marks',
    render({ g, colors }) {
      const c = mix(colors.skin, '#b0605a', 0.45), x = g.cx + g.eyeDX + 6;
      return { marks: `<path d="M${pt(x + 18, g.eyeY + 18)}Q${pt(x + 4, g.noseY + 4)} ${pt(x - 14, g.noseY + 26)}" stroke="${c}" stroke-width="4.5" fill="none" stroke-linecap="round"/><path d="M${pt(x + 18, g.eyeY + 18)}Q${pt(x + 4, g.noseY + 4)} ${pt(x - 14, g.noseY + 26)}" stroke="${lighten(c, 0.35)}" stroke-width="1.2" fill="none"/>` };
    },
  },
  {
    id: 'scarNose', label: 'Nose scar', layer: 'marks',
    render({ g, colors }) {
      const c = mix(colors.skin, '#b0605a', 0.45);
      return { marks: `<path d="M${pt(g.cx - 26, g.noseY - 26)}L${pt(g.cx + 22, g.noseY - 8)}" stroke="${c}" stroke-width="4" stroke-linecap="round"/>` };
    },
  },
  {
    id: 'freckles', label: 'Freckles', layer: 'marks',
    render({ g, colors, rng }) {
      const c = darken(colors.skin, 0.32);
      let s = '';
      for (const side of [-1, 1]) {
        for (let i = 0; i < 9; i++) {
          s += `<circle cx="${(g.cx + side * rng.range(16, g.eyeDX + 18)).toFixed(1)}" cy="${(g.eyeY + rng.range(16, 36)).toFixed(1)}" r="${rng.range(1.1, 2).toFixed(1)}" fill="${c}" opacity="0.7"/>`;
        }
      }
      return { marks: s };
    },
  },
  {
    id: 'blush', label: 'Blush', layer: 'marks',
    render({ g, uid }) {
      const b = uid('blur');
      return { marks: `${blurFilter(b, 5)}<g filter="url(#${b})" fill="#ff6f7d" opacity="0.35"><ellipse cx="${g.cx - g.eyeDX - 6}" cy="${g.noseY + 2}" rx="17" ry="9"/><ellipse cx="${g.cx + g.eyeDX + 6}" cy="${g.noseY + 2}" rx="17" ry="9"/></g>` };
    },
  },
  {
    id: 'mole', label: 'Beauty mark', layer: 'marks',
    render: ({ g, colors }) => ({ marks: `<circle cx="${g.cx + 26}" cy="${g.mouthY - 12}" r="2.6" fill="${darken(colors.skin, 0.6)}"/>` }),
  },
  {
    id: 'wrinkles', label: 'Wrinkles (age)', layer: 'marks',
    render({ g, colors }) {
      const c = darken(colors.skin, 0.3);
      const side = `<path d="M${pt(g.cx + g.eyeDX + 22, g.eyeY - 4)}l8,-4M${pt(g.cx + g.eyeDX + 22, g.eyeY + 2)}l9,1M${pt(g.cx + 20, g.noseY - 4)}Q${pt(g.cx + 32, g.mouthY - 12)} ${pt(g.cx + 28, g.mouthY + 6)}M${pt(g.cx + g.eyeDX - 12, g.eyeY + 14)}q10,5 20,0" stroke="${c}" stroke-width="2" fill="none" stroke-linecap="round" opacity="0.7"/>`;
      return { marks: side + mirrored(g.cx, side) + `<path d="M${pt(g.cx - 30, g.browY - 20)}q30,-6 60,0M${pt(g.cx - 24, g.browY - 30)}q24,-5 48,0" stroke="${c}" stroke-width="2" fill="none" stroke-linecap="round" opacity="0.6"/>` };
    },
  },
  {
    id: 'warPaint', label: 'War paint', layer: 'marks',
    render({ g, colors }) {
      const c = colors.accent;
      const one = `<path d="M${pt(g.cx + g.eyeDX - 14, g.eyeY + 14)}l-2,30M${pt(g.cx + g.eyeDX - 2, g.eyeY + 14)}l-1,34M${pt(g.cx + g.eyeDX + 10, g.eyeY + 12)}l0,28" stroke="${c}" stroke-width="5" stroke-linecap="round" opacity="0.85"/>`;
      return { marks: one + mirrored(g.cx, one) };
    },
  },
  {
    id: 'tattooRunes', label: 'Rune tattoo', layer: 'marks',
    render({ g, colors }) {
      const c = mix(colors.accent, '#1a3a6a', 0.4);
      return { marks: `<g stroke="${c}" stroke-width="2.6" fill="none" stroke-linecap="round" opacity="0.85">` +
        `<path d="M${pt(g.cx, g.browY - 34)}l0,22M${pt(g.cx - 8, g.browY - 30)}l8,6l8,-6M${pt(g.cx - 7, g.browY - 16)}l14,0"/>` +
        `<path d="M${pt(g.cx + g.eyeDX + 18, g.noseY - 8)}l6,10l-6,10M${pt(g.cx + g.eyeDX + 30, g.noseY - 6)}l0,20M${pt(g.cx + g.eyeDX + 26, g.noseY + 2)}l8,0"/></g>` };
    },
  },
  {
    id: 'tattooCircuit', label: 'Circuit tattoo', layer: 'marks',
    render({ g, colors, uid }) {
      const glow = uid('glow'), c = colors.accent;
      const x = g.cx + g.w - 10;
      const lines = `<path d="M${pt(x, g.browY - 20)}l-14,14l0,30l-12,12M${pt(x, g.eyeY + 30)}l-18,0l-10,10M${pt(x - 2, g.noseY + 10)}l-16,16" fill="none" stroke="${c}" stroke-width="2.2"/>` +
        `<circle cx="${x - 26}" cy="${g.browY + 36}" r="3" fill="${c}"/><circle cx="${x - 28}" cy="${g.eyeY + 40}" r="3" fill="${c}"/><circle cx="${x - 18}" cy="${g.noseY + 26}" r="3" fill="${c}"/>`;
      return { defs: glowFilter(glow, 2), marks: `<g filter="url(#${glow})" opacity="0.9">${lines}</g>${lines}` };
    },
  },
  {
    id: 'cyberImplant', label: 'Temple implant', layer: 'marks',
    render({ g, colors, uid }) {
      const glow = uid('glow'), x = g.cx - g.w + 4, y = g.browY - 6;
      return {
        defs: glowFilter(glow, 2),
        marks: `<path d="M${pt(x - 6, y - 26)}L${pt(x + 22, y - 18)}L${pt(x + 24, y + 22)}L${pt(x - 4, y + 34)}Z" fill="${STEEL}" stroke="#3d434a" stroke-width="2.5" stroke-linejoin="round"/>` +
          [0, 1, 2].map((i) => `<circle cx="${x + 9}" cy="${y - 10 + i * 14}" r="3.5" fill="${colors.accent}" filter="url(#${glow})"/><circle cx="${x + 9}" cy="${y - 10 + i * 14}" r="2" fill="#fff"/>`).join(''),
      };
    },
  },
  // ------------------------------------------------------------ jewelry
  {
    id: 'earrings', label: 'Hoop earrings', group: 'earwear',
    render({ g }) {
      const one = `<circle cx="${g.cx + g.w + 10}" cy="${g.eyeY + 48}" r="9" fill="none" stroke="${GOLD}" stroke-width="3"/>`;
      return { accFace: one + mirrored(g.cx, one) };
    },
  },
  {
    id: 'earStuds', label: 'Ear studs', group: 'earwear',
    render({ g, colors }) {
      const one = `<circle cx="${g.cx + g.w + 9}" cy="${g.eyeY + 34}" r="4" fill="${lighten(colors.accent, 0.3)}" stroke="${darken(colors.accent, 0.4)}" stroke-width="1.5"/>`;
      return { accFace: one + mirrored(g.cx, one) };
    },
  },
  {
    id: 'noseRing', label: 'Nose ring',
    render: ({ g }) => ({ accFace: `<path d="M${pt(g.cx + 8, g.noseY + 2)}a5,5 0 1,1 -4,6" fill="none" stroke="${GOLD}" stroke-width="2.6"/>` }),
  },
  {
    id: 'pendant', label: 'Pendant', group: 'neck', layer: 'accNeck',
    render({ g, colors }) {
      const y = g.shoulderY;
      return { accNeck: `<path d="M${pt(g.cx - g.neckW - 4, y - 6)}Q${pt(g.cx, y + 70)} ${pt(g.cx + g.neckW + 4, y - 6)}" fill="none" stroke="${GOLD}" stroke-width="2.5"/>` +
        `<path d="M${pt(g.cx, y + 24)}l10,14l-10,16l-10,-16Z" fill="${colors.accent}" stroke="${darken(GOLD, 0.4)}" stroke-width="2.5"/>` };
    },
  },
  // ------------------------------------------------------------ headwear
  {
    id: 'circlet', label: 'Circlet', group: 'head', layer: 'accHead',
    render({ g, colors }) {
      const y = g.hairY + 20;
      return { accHead: `<path d="M${pt(g.cx - g.w - 2, y + 18)}Q${pt(g.cx, y - 12)} ${pt(g.cx + g.w + 2, y + 18)}" fill="none" stroke="#6e5418" stroke-width="7"/><path d="M${pt(g.cx - g.w - 2, y + 18)}Q${pt(g.cx, y - 12)} ${pt(g.cx + g.w + 2, y + 18)}" fill="none" stroke="${GOLD}" stroke-width="4"/>` +
        `<path d="M${pt(g.cx, y - 8)}l9,11l-9,12l-9,-12Z" fill="${colors.accent}" stroke="#6e5418" stroke-width="2.5"/>` };
    },
  },
  {
    id: 'crown', label: 'Crown', group: 'head', layer: 'accHead',
    render({ g, colors }) {
      const y = g.top - 4, w = g.w * 0.72, cx = g.cx;
      const d = `M${pt(cx - w, y + 20)}L${pt(cx - w - 6, y - 26)}L${pt(cx - w * 0.5, y - 4)}L${pt(cx, y - 40)}L${pt(cx + w * 0.5, y - 4)}L${pt(cx + w + 6, y - 26)}L${pt(cx + w, y + 20)}Q${pt(cx, y + 30)} ${pt(cx - w, y + 20)}Z`;
      return { accHead: `<path d="${d}" fill="${GOLD}" stroke="#6e5418" stroke-width="3" stroke-linejoin="round"/>` +
        `<circle cx="${cx}" cy="${y + 10}" r="6" fill="${colors.accent}" stroke="#6e5418" stroke-width="2"/><circle cx="${cx - w * 0.6}" cy="${y + 12}" r="4" fill="#c22"/><circle cx="${cx + w * 0.6}" cy="${y + 12}" r="4" fill="#c22"/>` };
    },
  },
  {
    id: 'headband', label: 'Headband', group: 'head', layer: 'accHead',
    render({ g, colors }) {
      const y = g.hairY + 14, c = colors.accent;
      return { accHead: `<path d="M${pt(g.cx - g.w - 8, y + 20)}Q${pt(g.cx, y - 12)} ${pt(g.cx + g.w + 8, y + 20)}" fill="none" stroke="${darken(c, 0.4)}" stroke-width="17"/><path d="M${pt(g.cx - g.w - 8, y + 20)}Q${pt(g.cx, y - 12)} ${pt(g.cx + g.w + 8, y + 20)}" fill="none" stroke="${c}" stroke-width="12"/>` +
        `<path d="M${pt(g.cx + g.w + 6, y + 18)}q22,10 30,40M${pt(g.cx + g.w + 6, y + 18)}q14,16 12,48" stroke="${c}" stroke-width="7" fill="none" stroke-linecap="round"/>` };
    },
  },
  {
    id: 'beanie', label: 'Beanie', group: 'head', layer: 'accHead',
    hidesHairAbove: (g) => g.hairY + 6,
    render({ g, colors }) {
      const c = colors.accent, y = g.hairY + 18, w = g.w + 14;
      let ribs = '';
      for (let i = -6; i <= 6; i++) ribs += `<path d="M${pt(g.cx + i * 14, y - 8)}l0,22" stroke="${darken(c, 0.3)}" stroke-width="2"/>`;
      return { accHead: `<path d="M${pt(g.cx - w, y)}C${pt(g.cx - w - 4, g.top - 60)} ${pt(g.cx + w + 4, g.top - 60)} ${pt(g.cx + w, y)}Z" fill="${c}" stroke="${darken(c, 0.5)}" stroke-width="3"/>` +
        `<rect x="${g.cx - w - 4}" y="${y - 10}" width="${w * 2 + 8}" height="26" rx="10" fill="${darken(c, 0.1)}" stroke="${darken(c, 0.5)}" stroke-width="3"/>${ribs}` };
    },
  },
  {
    id: 'headphones', label: 'Headphones', group: 'head', layer: 'accHead',
    render({ g, colors }) {
      const c = colors.accent;
      const cup = `<rect x="${g.cx + g.w - 2}" y="${g.eyeY - 14}" width="24" height="52" rx="10" fill="${c}" stroke="${darken(c, 0.55)}" stroke-width="3"/>`;
      return { accHead: `<path d="M${pt(g.cx - g.w - 4, g.eyeY - 6)}C${pt(g.cx - g.w - 8, g.top - 70)} ${pt(g.cx + g.w + 8, g.top - 70)} ${pt(g.cx + g.w + 4, g.eyeY - 6)}" fill="none" stroke="#2b2b30" stroke-width="10"/>` + cup + mirrored(g.cx, cup) };
    },
  },
  {
    id: 'headset', label: 'Comms headset', group: 'head', layer: 'accHead',
    render({ g, colors, uid }) {
      const glow = uid('glow'), x = g.cx + g.w + 4;
      return {
        defs: glowFilter(glow, 2.5),
        accHead: `<path d="M${pt(x + 6, g.eyeY + 20)}Q${pt(x - 10, g.mouthY + 10)} ${pt(g.cx + 34, g.mouthY + 2)}" stroke="#2f3338" stroke-width="5" fill="none" stroke-linecap="round"/>` +
          `<rect x="${x - 8}" y="${g.eyeY - 8}" width="22" height="40" rx="6" fill="#3a4047" stroke="#16191c" stroke-width="3"/><circle cx="${x + 3}" cy="${g.eyeY + 4}" r="4" fill="${colors.accent}" filter="url(#${glow})"/><circle cx="${x + 3}" cy="${g.eyeY + 4}" r="2" fill="#fff"/>`,
      };
    },
  },
  {
    id: 'hood', label: 'Hood', group: 'head', layer: 'accHead',
    render({ g, colors }) {
      const c = darken(colors.clothing, 0.1), L = darken(c, 0.5);
      const { cx, w, top, jawY, shoulderY: sY } = g;
      const backD = `M${pt(cx - w - 60, sY + 40)}C${pt(cx - w - 70, top - 30)} ${pt(cx - 30, top - 66)} ${pt(cx, top - 66)}C${pt(cx + 30, top - 66)} ${pt(cx + w + 70, top - 30)} ${pt(cx + w + 60, sY + 40)}Z`;
      const rim = `M${pt(cx - w - 46, sY + 10)}C${pt(cx - w - 54, top - 20)} ${pt(cx - 30, top - 52)} ${pt(cx, top - 52)}C${pt(cx + 30, top - 52)} ${pt(cx + w + 54, top - 20)} ${pt(cx + w + 46, sY + 10)}` +
        `L${pt(cx + g.neckW + 30, sY + 4)}C${pt(cx + w + 10, jawY)} ${pt(cx + w + 22, top - 4)} ${pt(cx, top - 22)}C${pt(cx - w - 22, top - 4)} ${pt(cx - w - 10, jawY)} ${pt(cx - g.neckW - 30, sY + 4)}Z`;
      return {
        accBack: `<path d="${backD}" fill="${darken(c, 0.35)}" stroke="${L}" stroke-width="3"/>`,
        accHead: `<path d="${rim}" fill="${c}" stroke="${L}" stroke-width="3" stroke-linejoin="round"/><path d="M${pt(cx + w + 16, top + 40)}Q${pt(cx + w + 30, jawY - 40)} ${pt(cx + w + 30, sY - 20)}" stroke="${L}" stroke-width="2" fill="none" opacity="0.5"/>`,
      };
    },
  },
  {
    id: 'horns', label: 'Horns', group: 'horns', layer: 'accHead',
    render({ g }) {
      const bone = '#e9dcc0', L = '#6b5d45', { cx, w, top } = g;
      const one = `<path d="M${pt(cx + w * 0.3, top + 14)}C${pt(cx + w * 0.4, top - 30)} ${pt(cx + w + 10, top - 60)} ${pt(cx + w + 46, top - 52)}C${pt(cx + w + 6, top - 34)} ${pt(cx + w * 0.75, top - 6)} ${pt(cx + w * 0.72, top + 24)}Z" fill="${bone}" stroke="${L}" stroke-width="3" stroke-linejoin="round"/>` +
        `<path d="M${pt(cx + w * 0.42, top - 6)}l16,6M${pt(cx + w * 0.55, top - 24)}l14,10M${pt(cx + w * 0.8, top - 38)}l10,12" stroke="${L}" stroke-width="2" opacity="0.6"/>`;
      return { accHead: one + mirrored(cx, one) };
    },
  },
  {
    id: 'halo', label: 'Halo', group: 'halo', layer: 'accBack',
    render({ g, uid }) {
      const glow = uid('glow');
      return { defs: glowFilter(glow, 5), accBack: `<ellipse cx="${g.cx}" cy="${g.top - 44}" rx="74" ry="16" fill="none" stroke="#ffe27a" stroke-width="10" filter="url(#${glow})"/><ellipse cx="${g.cx}" cy="${g.top - 44}" rx="74" ry="16" fill="none" stroke="#fff6c8" stroke-width="4"/>` };
    },
  },
  {
    id: 'antennae', label: 'Antennae', group: 'horns', layer: 'accHead',
    render({ g, colors, uid }) {
      const glow = uid('glow');
      const one = `<path d="M${pt(g.cx + 22, g.top + 4)}Q${pt(g.cx + 40, g.top - 60)} ${pt(g.cx + 64, g.top - 86)}" stroke="${darken(colors.skin, 0.25)}" stroke-width="5" fill="none" stroke-linecap="round"/>` +
        `<circle cx="${g.cx + 64}" cy="${g.top - 88}" r="8" fill="${colors.accent}" filter="url(#${glow})"/><circle cx="${g.cx + 64}" cy="${g.top - 88}" r="5" fill="${lighten(colors.accent, 0.5)}"/>`;
      return { defs: glowFilter(glow, 3), accHead: one + mirrored(g.cx, one) };
    },
  },
];

for (const d of defs) registerPart('accessories', { layer: 'accFace', ...d });
