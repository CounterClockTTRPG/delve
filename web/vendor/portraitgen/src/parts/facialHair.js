import { registerPart } from '../registry.js';
import { pt, mirrorPath, mirrored } from '../geometry.js';
import { darken, lighten } from '../color.js';

export const mouthHole = (g, rx = 20, ry = 11) =>
  `M${pt(g.cx - rx, g.mouthY + 3)}a${rx},${ry} 0 1,0 ${rx * 2},0a${rx},${ry} 0 1,0 ${-rx * 2},0Z`;

export function fullBeard(g, drop = 26) {
  const { w, eyeY, noseY, jawY, jawW, chinW, mouthY: m, bottom: b } = g;
  return mirrorPath(g.cx, [0, m - 13], [
    [[w * 0.3, m - 14], [w * 0.6, m - 4], [w * 0.8, noseY + 10]],
    [[w * 0.92, noseY - 4], [w - 3, eyeY + 22], [w - 1, eyeY + 4]],
    [[w + 3, jawY - 24], [jawW + 9, jawY + 8], [jawW - 2, jawY + 24]],
    [[chinW + 24, b + drop * 0.7], [chinW + 6, b + drop], [0, b + drop + 2]],
  ]);
}

export function mustache(g, handlebar = false) {
  const m = g.mouthY;
  if (handlebar) {
    return mirrorPath(g.cx, [0, m - 13], [
      [[14, m - 17], [30, m - 10], [36, m - 10]],
      [[44, m - 12], [46, m - 24], [38, m - 26]],
      [[42, m - 18], [24, m - 3], [0, m - 5]],
    ]);
  }
  return mirrorPath(g.cx, [0, m - 13], [
    [[10, m - 16], [22, m - 11], [27, m + 2]],
    [[20, m - 1], [10, m - 5], [0, m - 4]],
  ]);
}

function texture(g, color, from, to) {
  let s = '';
  for (let i = 0; i < 7; i++) {
    const x = g.cx - 40 + i * 13;
    s += `<path d="M${pt(x, from)}q2,8 0,${to - from}" stroke="${color}" stroke-width="1.6" fill="none" opacity="0.35" stroke-linecap="round"/>`;
  }
  return s;
}

const styles = {
  none: { label: 'None', render: () => ({}) },
  stubble: {
    label: 'Stubble',
    render: (g, c) => ({ facialHair: `<path d="${fullBeard(g, 2)}" fill="${c.hair}" opacity="0.22"/>` }),
  },
  mustache: { label: 'Mustache', render: (g, c, s) => ({ mustache: `<path d="${mustache(g)}" fill="${c.hair}" ${s}/>` }) },
  handlebar: { label: 'Handlebar', render: (g, c, s) => ({ mustache: `<path d="${mustache(g, true)}" fill="${c.hair}" ${s}/>` }) },
  goatee: {
    label: 'Goatee',
    render(g, c, s) {
      const { mouthY: m, bottom: b } = g;
      const d = mirrorPath(g.cx, [0, m - 13], [
        [[14, m - 15], [24, m - 9], [25, m + 4]],
        [[27, m + 16], [22, b - 4], [12, b + 8]],
        [[8, b + 12], [4, b + 14], [0, b + 14]],
      ]);
      return {
        facialHair: `<path d="${d}${mouthHole(g, 17, 9)}" fill-rule="evenodd" fill="${c.hair}" ${s}/>`,
        mustache: `<path d="${mustache(g)}" fill="${c.hair}" ${s}/>`,
      };
    },
  },
  soulPatch: {
    label: 'Soul patch',
    render: (g, c, s) => ({ mustache: `<path d="M${pt(g.cx - 6, g.mouthY + 14)}L${pt(g.cx + 6, g.mouthY + 14)}L${pt(g.cx, g.mouthY + 28)}Z" fill="${c.hair}" ${s}/>` }),
  },
  muttonChops: {
    label: 'Mutton chops',
    render(g, c, s) {
      const { cx, w, eyeY, jawY, jawW, mouthY: m } = g;
      const one = `<path d="M${pt(cx + w - 1, eyeY)}C${pt(cx + w + 3, jawY - 20)} ${pt(cx + jawW + 6, jawY + 4)} ${pt(cx + jawW - 10, jawY + 18)}` +
        `C${pt(cx + w * 0.6, jawY + 10)} ${pt(cx + 28, m + 14)} ${pt(cx + 26, m - 4)}C${pt(cx + w * 0.5, m - 14)} ${pt(cx + w - 16, eyeY + 30)} ${pt(cx + w - 12, eyeY + 4)}Z" fill="${c.hair}" ${s}/>`;
      return { facialHair: one + mirrored(cx, one), mustache: `<path d="${mustache(g)}" fill="${c.hair}" ${s}/>` };
    },
  },
  fullBeard: {
    label: 'Full beard',
    render: (g, c, s) => ({
      facialHair: `<path d="${fullBeard(g)}${mouthHole(g)}" fill-rule="evenodd" fill="${c.hair}" ${s}/>${texture(g, darken(c.hair, 0.5), g.mouthY + 18, g.bottom + 14)}`,
      mustache: `<path d="${mustache(g)}" fill="${c.hair}" ${s}/>`,
    }),
  },
  longBeard: {
    label: 'Long beard',
    render(g, c, s) {
      const { w, eyeY, noseY, jawY, jawW, mouthY: m } = g;
      const d = mirrorPath(g.cx, [0, m - 13], [
        [[w * 0.3, m - 14], [w * 0.6, m - 4], [w * 0.8, noseY + 10]],
        [[w * 0.92, noseY - 4], [w - 3, eyeY + 22], [w - 1, eyeY + 4]],
        [[w + 4, jawY - 10], [jawW + 16, jawY + 60], [jawW - 6, 440]],
        [[jawW * 0.5, 486], [20, 500], [0, 506]],
      ]);
      return {
        facialHair: `<path d="${d}${mouthHole(g)}" fill-rule="evenodd" fill="${c.hair}" ${s}/>` +
          texture(g, darken(c.hair, 0.5), g.mouthY + 20, 470) +
          `<path d="M${pt(g.cx - 30, g.bottom + 40)}Q${pt(g.cx, g.bottom + 30)} ${pt(g.cx + 30, g.bottom + 40)}" stroke="${lighten(c.hair, 0.3)}" stroke-width="4" fill="none" opacity="0.4"/>`,
        mustache: `<path d="${mustache(g)}" fill="${c.hair}" ${s}/>`,
      };
    },
  },
  braidedBeard: {
    label: 'Braided beard',
    render(g, c, s) {
      let braid = '';
      for (let i = 0; i < 5; i++) {
        const y = g.bottom + 30 + i * 18;
        braid += `<ellipse cx="${g.cx}" cy="${y}" rx="${14 - i}" ry="11" fill="${c.hair}" ${s}/>`;
      }
      braid += `<rect x="${g.cx - 10}" y="${g.bottom + 108}" width="20" height="10" rx="3" fill="${c.accent}" stroke="${darken(c.accent, 0.5)}" stroke-width="2"/>`;
      return {
        facialHair: braid + `<path d="${fullBeard(g)}${mouthHole(g)}" fill-rule="evenodd" fill="${c.hair}" ${s}/>${texture(g, darken(c.hair, 0.5), g.mouthY + 18, g.bottom + 14)}`,
        mustache: `<path d="${mustache(g, true)}" fill="${c.hair}" ${s}/>`,
      };
    },
  },
};

for (const [id, f] of Object.entries(styles)) {
  registerPart('facialHair', {
    id,
    label: f.label,
    render({ g, colors }) {
      const s = `stroke="${darken(colors.hair, 0.55)}" stroke-width="2.6" stroke-linejoin="round"`;
      return f.render(g, colors, s);
    },
  });
}
