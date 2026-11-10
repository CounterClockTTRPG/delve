import { registerPart } from '../registry.js';
import { pt } from '../geometry.js';
import { darken, mix, lighten } from '../color.js';

// Mouths are drawn around (0,0) = mouth centre.
function lipColor(skin) {
  return mix(skin, '#b5545a', 0.42);
}

const mouths = {
  neutral: { label: 'Neutral', render: (L, line) => `<path d="M-12,4Q0,12 12,4Q0,7 -12,4Z" fill="${L}" opacity="0.8"/><path d="M-18,0Q0,4 18,0" ${line()}/>` },
  smile: { label: 'Smile', render: (L, line) => `<path d="M-14,7Q0,16 14,7Q0,11 -14,7Z" fill="${L}" opacity="0.8"/><path d="M-20,-3Q0,12 20,-3" ${line()}/><path d="M-22,-5l3,3M22,-5l-3,3" ${line(2)}/>` },
  grin: {
    label: 'Grin',
    render: (L, line, c) => `<path d="M-22,-4Q0,0 22,-4Q16,22 0,22Q-16,22 -22,-4Z" fill="${darken(c.lip, 0.6)}"/>` +
      `<path d="M-20,-3Q0,1 20,-3L18,4Q0,7 -18,4Z" fill="#f6f1e6"/>` +
      `<path d="M-12,16Q0,20 12,16Q0,12 -12,16Z" fill="${lighten(c.lip, 0.1)}"/>` +
      `<path d="M-22,-4Q0,0 22,-4Q16,22 0,22Q-16,22 -22,-4Z" ${line()}/>`,
  },
  smirk: { label: 'Smirk', render: (L, line) => `<path d="M-10,5Q2,11 12,3Q2,7 -10,5Z" fill="${L}" opacity="0.8"/><path d="M-17,2Q2,6 19,-6" ${line()}/><path d="M19,-6l2,4" ${line(2)}/>` },
  frown: { label: 'Frown', render: (L, line) => `<path d="M-12,7Q0,10 12,7Q0,6 -12,7Z" fill="${L}" opacity="0.8"/><path d="M-18,6Q0,-4 18,6" ${line()}/>` },
  open: { label: 'Surprised', render: (L, line, c) => `<ellipse cx="0" cy="4" rx="9" ry="11" fill="${darken(c.lip, 0.6)}" stroke="${c.lineColor}" stroke-width="2.6"/><path d="M-6,10Q0,14 6,10" stroke="${lighten(c.lip, 0.1)}" stroke-width="3" fill="none"/>` },
  full: {
    label: 'Full lips',
    render: (L, line, c) => `<path d="M-19,1Q-10,-8 -3,-5Q0,-3 3,-5Q10,-8 19,1Q0,4 -19,1Z" fill="${darken(L, 0.08)}"/>` +
      `<path d="M-19,1Q0,4 19,1Q12,14 0,14Q-12,14 -19,1Z" fill="${L}"/><path d="M-6,8Q0,10 6,8" stroke="#fff" stroke-width="2" opacity="0.35" fill="none"/>` +
      `<path d="M-19,1Q0,4 19,1" ${line(2.4)}/>`,
  },
  pursed: { label: 'Pursed', render: (L, line) => `<path d="M-9,1Q0,-6 9,1Q0,10 -9,1Z" fill="${L}"/><path d="M-9,1Q0,3 9,1" ${line(2.2)}/>` },
  fangs: {
    label: 'Fangs',
    render: (L, line) => `<path d="M-12,5Q0,11 12,5Q0,8 -12,5Z" fill="${L}" opacity="0.8"/><path d="M-11,1L-8,11L-5,2Z M11,1L8,11L5,2Z" fill="#fbf8f0" stroke="#7a6a5a" stroke-width="1"/><path d="M-19,0Q0,5 19,0" ${line()}/>`,
  },
  tusks: {
    label: 'Tusks',
    render: (L, line) => `<path d="M-14,6Q0,13 14,6Q0,9 -14,6Z" fill="${L}" opacity="0.8"/><path d="M-21,1Q0,7 21,1" ${line()}/>` +
      `<path d="M-16,5Q-20,-8 -13,-16Q-12,-6 -10,4Z M16,5Q20,-8 13,-16Q12,-6 10,4Z" fill="#f2ead2" stroke="#6b5d45" stroke-width="1.8" stroke-linejoin="round"/>`,
  },
};

for (const [id, m] of Object.entries(mouths)) {
  registerPart('mouth', {
    id,
    label: m.label,
    render({ g, colors }) {
      const lip = lipColor(colors.skin);
      const lineColor = darken(lip, 0.55);
      const line = (w = 3) => `fill="none" stroke="${lineColor}" stroke-width="${w}" stroke-linecap="round"`;
      return { mouth: `<g transform="translate(${pt(g.cx, g.mouthY)})">${m.render(lip, line, { lip, lineColor })}</g>` };
    },
  });
}
