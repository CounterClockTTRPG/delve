// Layered fantasy pieces worn over any clothing: a wrapped scarf, a fur collar,
// a cloak brooch, and a chainmail coif framing the face.
import { registerPart } from '../registry.js';
import { pt } from '../geometry.js';
import { darken, lighten, mix } from '../color.js';

const L = (c, w = 2.6) => `stroke="${darken(c, 0.55)}" stroke-width="${w}" stroke-linejoin="round"`;

const defs = [
  {
    id: 'scarf', label: 'Wrapped scarf', group: 'neckwrap', layer: 'accNeck',
    render({ g, colors }) {
      const c = mix(colors.accent, colors.clothing, 0.4);
      const { cx, neckW: nw, shoulderY: sY, bottom } = g;
      // Two wraps around the neck and a loose end hanging over the chest.
      const wrap = (y, h, k) => `<path d="M${pt(cx - nw - 22, y)}Q${pt(cx, y + h * 0.7)} ${pt(cx + nw + 22, y)}L${pt(cx + nw + 26, y + h)}Q${pt(cx, y + h * 1.8)} ${pt(cx - nw - 26, y + h)}Z" fill="${k}" ${L(c)}/>` +
        `<path d="M${pt(cx - nw - 14, y + h * 0.55)}Q${pt(cx, y + h * 1.25)} ${pt(cx + nw + 14, y + h * 0.55)}" fill="none" stroke="${darken(c, 0.3)}" stroke-width="2" opacity="0.6"/>`;
      const end = `<path d="M${pt(cx + 10, sY + 20)}C${pt(cx + 36, sY + 60)} ${pt(cx + 24, sY + 110)} ${pt(cx + 40, sY + 150)}L${pt(cx + 6, sY + 156)}C${pt(cx - 2, sY + 110)} ${pt(cx + 4, sY + 60)} ${pt(cx - 10, sY + 26)}Z" fill="${darken(c, 0.08)}" ${L(c)}/>` +
        `<path d="M${pt(cx + 8, sY + 156)}l-3,10M${pt(cx + 18, sY + 155)}l0,10M${pt(cx + 30, sY + 153)}l3,10" stroke="${c}" stroke-width="2.4"/>`;
      return { accNeck: end + wrap(bottom + 14, 22, c) + wrap(bottom + 34, 26, lighten(c, 0.06)) };
    },
  },
  {
    id: 'furCollar', label: 'Fur collar', group: 'neckwrap', layer: 'accNeck',
    render({ g, rng }) {
      const fur = rng.pick(['#8a6a4a', '#b8a890', '#4a3a2e', '#d8d0c4']);
      const { cx, shoulderY: sY, neckW: nw } = g;
      // A thick ruff of tufts over the shoulders: three overlapping rows following the shoulder line.
      let tufts = '';
      for (let row = 0; row < 3; row++) {
        for (let i = 0; i <= 22; i++) {
          const t = i / 22, k = t * 2 - 1; // -1 .. 1 across the shoulders
          const x = cx + k * (nw + 150 - row * 22);
          const y = sY + 8 + row * 14 + Math.abs(k) ** 1.6 * 34 - (1 - Math.abs(k)) * 6;
          const r = rng.range(15, 22) - row * 2;
          tufts += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}" fill="${mix(fur, '#000', rng.range(0, 0.22) + (2 - row) * 0.04)}"/>` +
            `<path d="M${pt(x - r * 0.5, y - r * 0.1)}q${(r * 0.3).toFixed(1)},-${(r * 0.6).toFixed(1)} ${(r * 0.9).toFixed(1)},-${(r * 0.3).toFixed(1)}" fill="none" stroke="${lighten(fur, 0.3)}" stroke-width="1.6" opacity="0.7"/>`;
        }
      }
      return { accNeck: `<g stroke="${darken(fur, 0.45)}" stroke-width="1.2">${tufts}</g>` };
    },
  },
  {
    id: 'brooch', label: 'Cloak brooch', group: 'brooch', layer: 'accNeck',
    render({ g, colors }) {
      const x = g.cx - 64, y = g.shoulderY + 34;
      const gold = '#c9a443';
      let petals = '';
      for (let i = 0; i < 8; i++) {
        const a = (i / 8) * Math.PI * 2;
        petals += `<circle cx="${(x + Math.cos(a) * 11).toFixed(1)}" cy="${(y + Math.sin(a) * 11).toFixed(1)}" r="4.5" fill="${gold}" ${L(gold, 1.2)}/>`;
      }
      return {
        accNeck: petals + `<circle cx="${x}" cy="${y}" r="9" fill="${colors.accent}" ${L(colors.accent, 1.6)}/>` +
          `<circle cx="${x - 3}" cy="${y - 3}" r="2.6" fill="#fff" opacity="0.7"/>` +
          `<path d="M${pt(x - 26, y + 14)}L${pt(x + 26, y - 14)}" stroke="${gold}" stroke-width="3" stroke-linecap="round"/>`,
      };
    },
  },
  {
    id: 'mailCoif', label: 'Chainmail coif', group: 'head', layer: 'accHead',
    hidesHairAbove: (g) => g.bottom,
    render({ g, uid }) {
      const { cx, w, top, jawY, bottom, shoulderY: sY, neckW } = g;
      const mail = '#8a9098';
      const ring = uid('mail');
      // A hood of mail over the head and neck, with an opening around the face.
      const hood = `M${pt(cx - w - 22, sY + 30)}C${pt(cx - w - 30, jawY)} ${pt(cx - w - 26, top - 20)} ${pt(cx, top - 26)}` +
        `C${pt(cx + w + 26, top - 20)} ${pt(cx + w + 30, jawY)} ${pt(cx + w + 22, sY + 30)}Q${pt(cx, sY + 56)} ${pt(cx - w - 22, sY + 30)}Z`;
      const opening = `M${pt(cx - w + 2, g.eyeY - 10)}C${pt(cx - w + 2, top + 12)} ${pt(cx + w - 2, top + 12)} ${pt(cx + w - 2, g.eyeY - 10)}` +
        `C${pt(cx + w, jawY)} ${pt(cx + g.chinW + 14, bottom + 2)} ${pt(cx, bottom + 4)}C${pt(cx - g.chinW - 14, bottom + 2)} ${pt(cx - w, jawY)} ${pt(cx - w + 2, g.eyeY - 10)}Z`;
      return {
        defs: `<pattern id="${ring}" width="6" height="5" patternUnits="userSpaceOnUse"><circle cx="3" cy="2.5" r="2.2" fill="none" stroke="${lighten(mail, 0.3)}" stroke-width="0.9"/><circle cx="0" cy="0" r="2.2" fill="none" stroke="${darken(mail, 0.2)}" stroke-width="0.9"/><circle cx="6" cy="0" r="2.2" fill="none" stroke="${darken(mail, 0.2)}" stroke-width="0.9"/></pattern>`,
        accHead: `<path d="${hood}${opening}" fill-rule="evenodd" fill="${darken(mail, 0.35)}" ${L(mail)}/>` +
          `<path d="${hood}${opening}" fill-rule="evenodd" fill="url(#${ring})"/>` +
          `<path d="${opening}" fill="none" stroke="${darken(mail, 0.5)}" stroke-width="5"/>`,
      };
    },
  },
];

for (const d of defs) registerPart('accessories', d);

