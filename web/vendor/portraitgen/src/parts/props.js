// Hands and held props. A hand rises from the bottom edge (in the sleeve colour)
// gripping a candle, book or tankard; a pipe sits in the mouth. One at a time.
import { registerPart } from '../registry.js';
import { pt } from '../geometry.js';
import { darken, mix } from '../color.js';

const L = (c, w = 2.4) => `stroke="${darken(c, 0.55)}" stroke-width="${w}" stroke-linejoin="round"`;

/** A forearm in a sleeve and a gripping fist at (x, y), fingers towards the viewer. */
function fist(g, colors, x, y, k = 1) {
  const skin = colors.skin, cloth = colors.clothing;
  const sleeve = `<path d="M${pt(x - 26 * k, y + 14)}L${pt(x - 58 * k, 560)}L${pt(x + 30 * k, 560)}L${pt(x + 24 * k, y + 18)}Z" fill="${darken(cloth, 0.08)}" ${L(cloth)}/>` +
    `<path d="M${pt(x - 28 * k, y + 22)}Q${pt(x, y + 32)} ${pt(x + 26 * k, y + 24)}" fill="none" stroke="${darken(cloth, 0.4)}" stroke-width="5"/>`;
  let fingers = '';
  for (let i = 0; i < 4; i++) fingers += `<path d="M${pt(x - 20 * k + i * 12 * k, y - 8)}q${6 * k},-2 ${10 * k},4q0,8 -${10 * k},10" fill="${skin}" ${L(skin, 1.8)}/>`;
  const palm = `<path d="M${pt(x - 24 * k, y - 10)}Q${pt(x - 28 * k, y + 16)} ${pt(x - 8 * k, y + 20)}L${pt(x + 18 * k, y + 18)}Q${pt(x + 28 * k, y + 4)} ${pt(x + 24 * k, y - 10)}Z" fill="${skin}" ${L(skin)}/>`;
  const thumb = `<path d="M${pt(x - 24 * k, y - 8)}q${-2 * k},-14 ${12 * k},-16q${10 * k},0 ${12 * k},6" fill="${darken(skin, 0.04)}" ${L(skin, 1.8)}/>`;
  return { back: sleeve + palm, front: fingers + thumb };
}

const defs = [
  {
    id: 'handCandle', label: 'Holding a candle', group: 'held', layer: 'accHead',
    render({ g, colors, uid }) {
      const x = g.cx - 92, y = g.shoulderY + 64;
      const h = fist(g, colors, x, y, -1);
      const glow = uid('flame');
      return {
        defs: `<radialGradient id="${glow}"><stop offset="0" stop-color="#fff6d0" stop-opacity="0.95"/><stop offset="0.35" stop-color="#ffb84a" stop-opacity="0.5"/><stop offset="1" stop-color="#ff8a20" stop-opacity="0"/></radialGradient>`,
        accHead: h.back +
          `<rect x="${x - 9}" y="${y - 86}" width="18" height="84" rx="3" fill="#efe6d0" ${L('#efe6d0', 1.6)}/>` +
          `<path d="M${pt(x + 4, y - 86)}q2,10 0,16q-2,4 -1,8" fill="none" stroke="#e0d4b8" stroke-width="3"/>` +
          `<circle cx="${x}" cy="${y - 104}" r="44" fill="url(#${glow})"/>` +
          `<path d="M${pt(x, y - 124)}C${pt(x + 9, y - 108)} ${pt(x + 7, y - 92)} ${pt(x, y - 90)}C${pt(x - 7, y - 92)} ${pt(x - 9, y - 108)} ${pt(x, y - 124)}Z" fill="#ffd060"/>` +
          `<path d="M${pt(x, y - 112)}c3,6 2,12 0,16c-2,-4 -3,-10 0,-16Z" fill="#fff8e0"/>` +
          `<path d="M${pt(x, y - 90)}V${y - 86}" stroke="#2a1a10" stroke-width="1.6"/>` + h.front,
      };
    },
  },
  {
    id: 'handBook', label: 'Holding a book', group: 'held', layer: 'accHead',
    render({ g, colors }) {
      const x = g.cx + 70, y = g.shoulderY + 86;
      const h = fist(g, colors, x, y, 1);
      const cover = mix(colors.accent, '#5a2a1a', 0.5);
      return {
        accHead: `<g transform="rotate(-12 ${x} ${y - 30})">` +
          `<rect x="${x - 50}" y="${y - 96}" width="92" height="112" rx="5" fill="${cover}" ${L(cover)}/>` +
          `<rect x="${x + 38}" y="${y - 92}" width="7" height="104" fill="#efe6d0" ${L('#efe6d0', 1)}/>` +
          `<path d="M${pt(x - 44, y - 96)}V${y + 16}" stroke="${darken(cover, 0.35)}" stroke-width="6"/>` +
          `<rect x="${x - 30}" y="${y - 76}" width="54" height="34" rx="3" fill="none" stroke="#c9a443" stroke-width="2.2"/>` +
          `<circle cx="${x - 3}" cy="${y - 59}" r="6" fill="#c9a443"/></g>` + h.back + h.front,
      };
    },
  },
  {
    id: 'handMug', label: 'Holding a tankard', group: 'held', layer: 'accHead',
    render({ g, colors }) {
      const x = g.cx + 92, y = g.shoulderY + 70;
      const h = fist(g, colors, x, y, 1);
      const pewter = '#9aa0a6';
      return {
        accHead: h.back +
          `<path d="M${pt(x + 26, y - 50)}q30,4 28,30q-2,26 -28,26" fill="none" stroke="${darken(pewter, 0.3)}" stroke-width="8"/>` +
          `<rect x="${x - 30}" y="${y - 66}" width="58" height="82" rx="6" fill="${pewter}" ${L(pewter)}/>` +
          `<path d="M${pt(x - 30, y - 50)}H${x + 28}M${pt(x - 30, y)}H${x + 28}" stroke="${darken(pewter, 0.35)}" stroke-width="3"/>` +
          `<path d="M${pt(x - 18, y - 60)}V${y + 8}" stroke="#fff" stroke-width="4" opacity="0.35"/>` +
          `<path d="M${pt(x - 32, y - 64)}q8,-14 18,-6q8,-10 18,-2q10,-8 18,2q8,-2 6,8Z" fill="#f4eee0" ${L('#f4eee0', 1.4)}/>` + h.front,
      };
    },
  },
  {
    id: 'pipe', label: 'Smoking a pipe', group: 'held', layer: 'accFace',
    render({ g }) {
      const x = g.cx + 18, y = g.mouthY + 4;
      const wood = '#5a3a24';
      return {
        accFace: `<path d="M${pt(x, y)}Q${pt(x + 26, y + 10)} ${pt(x + 48, y + 18)}" fill="none" stroke="${darken(wood, 0.3)}" stroke-width="6" stroke-linecap="round"/>` +
          `<path d="M${pt(x + 40, y + 6)}L${pt(x + 66, y + 4)}L${pt(x + 62, y + 34)}Q${pt(x + 52, y + 40)} ${pt(x + 42, y + 30)}Z" fill="${wood}" ${L(wood, 2)}/>` +
          `<ellipse cx="${x + 53}" cy="${y + 5}" rx="12" ry="3.5" fill="#2a1a10"/><ellipse cx="${x + 53}" cy="${y + 4}" rx="6" ry="2" fill="#e86a2a" opacity="0.8"/>` +
          `<path d="M${pt(x + 54, y - 2)}c-8,-14 10,-20 2,-34c-6,-10 8,-18 4,-28" fill="none" stroke="#e8e4dc" stroke-width="4" stroke-linecap="round" opacity="0.45"/>`,
      };
    },
  },
];

for (const d of defs) registerPart('accessories', d);

