import { registerPart } from '../registry.js';
import { pt } from '../geometry.js';
import { darken } from '../color.js';

// Noses are drawn in local coordinates around the tip (0,0).
const noses = {
  button: { label: 'Button', line: 'M-8,-2Q-10,6 -3,6M8,-2Q10,6 3,6', bridge: null, shade: 9 },
  straight: { label: 'Straight', line: 'M-10,0Q-11,8 -3,7Q0,9 3,7Q11,8 10,0', bridge: 'M3,-36Q6,-16 8,-4', shade: 11 },
  wide: { label: 'Wide', line: 'M-14,-2Q-18,8 -6,8Q0,11 6,8Q18,8 14,-2', bridge: 'M4,-30Q8,-14 11,-4', shade: 14 },
  pointed: { label: 'Pointed', line: 'M-7,2L-2,7L2,7L7,2', bridge: 'M2,-36L9,0L3,7', shade: 9 },
  hooked: { label: 'Hooked', line: 'M-9,1Q-10,8 -3,7Q1,10 4,7', bridge: 'M2,-36Q14,-22 9,-6Q8,4 4,7', shade: 11 },
  small: { label: 'Small', line: 'M-5,3Q0,6 5,3', bridge: null, shade: 7 },
  snub: { label: 'Snub', line: 'M-9,0Q-9,7 -3,6M9,0Q9,7 3,6M-3,6Q0,4 3,6', bridge: 'M3,-20Q6,-10 8,-4', shade: 10, nostrils: true },
  flat: { label: 'Flat (beast)', line: 'M-12,-4Q-14,6 -5,6Q0,2 5,6Q14,6 12,-4', bridge: null, shade: 13, nostrils: true },
};

for (const [id, n] of Object.entries(noses)) {
  registerPart('nose', {
    id,
    label: n.label,
    render({ g, colors }) {
      const c = darken(colors.skin, 0.38);
      let s = `<ellipse cx="0" cy="3" rx="${n.shade}" ry="${n.shade * 0.6}" fill="${darken(colors.skin, 0.3)}" opacity="0.18"/>`;
      if (n.bridge) s += `<path d="${n.bridge}" fill="none" stroke="${c}" stroke-width="2.4" stroke-linecap="round" opacity="0.6"/>`;
      s += `<path d="${n.line}" fill="none" stroke="${c}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>`;
      if (n.nostrils) s += `<ellipse cx="-5" cy="3" rx="2.4" ry="1.6" fill="${darken(colors.skin, 0.55)}"/><ellipse cx="5" cy="3" rx="2.4" ry="1.6" fill="${darken(colors.skin, 0.55)}"/>`;
      return { nose: `<g transform="translate(${pt(g.cx, g.noseY)})">${s}</g>` };
    },
  });
}
