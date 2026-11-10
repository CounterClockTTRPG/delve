// Shoulder gear (behind the head and shoulders) and shoulder companions.
import { registerPart } from '../registry.js';
import { pt } from '../geometry.js';
import { darken, lighten, mix } from '../color.js';

const f = (n) => +n.toFixed(2);
const L = (c, w = 2.6) => `stroke="${darken(c, 0.55)}" stroke-width="${w}" stroke-linejoin="round"`;
const WOOD = '#7a5434';
const STEEL = '#b6bec8';
const LEATHER = '#6a4428';

/** A strap across the chest, from one shoulder towards the opposite hip. */
const chestStrap = (g, side, c = LEATHER) =>
  `<path d="M${pt(g.cx + side * 120, g.shoulderY + 6)}L${pt(g.cx - side * 70, 520)}" stroke="${darken(c, 0.4)}" stroke-width="15"/>` +
  `<path d="M${pt(g.cx + side * 120, g.shoulderY + 6)}L${pt(g.cx - side * 70, 520)}" stroke="${c}" stroke-width="11"/>` +
  `<path d="M${pt(g.cx + side * 120, g.shoulderY + 6)}L${pt(g.cx - side * 70, 520)}" stroke="${lighten(c, 0.3)}" stroke-width="1.2" stroke-dasharray="3 3" opacity="0.7"/>`;

const defs = [
  // ------------------------------------------------------------ gear
  {
    id: 'quiver', label: 'Quiver & arrows', group: 'gear', layer: 'accBack',
    render({ g, colors }) {
      const { cx, top, shoulderY: sY } = g;
      // Rises behind the left shoulder, beside (not behind) the head so the fletchings show.
      const x0 = cx - 120, y0 = sY + 70, x1 = cx - g.w - 34, y1 = top + 6;
      const ang = (Math.atan2(y1 - y0, x1 - x0) * 180) / Math.PI;
      const len = Math.hypot(x1 - x0, y1 - y0);
      let arrows = '';
      for (let i = 0; i < 5; i++) {
        const o = -10 + i * 5;
        arrows += `<path d="M${f(len - 6)},${o}l26,${o * 0.3}" stroke="${WOOD}" stroke-width="2.4"/>` +
          `<path d="M${f(len + 12)},${o + o * 0.2}l16,-5l-4,5l4,5Z" fill="${i % 2 ? colors.accent : '#ece6da'}" ${L('#ece6da', 1)}/>`;
      }
      const body = `<g transform="translate(${pt(x0, y0)}) rotate(${f(ang)})">${arrows}` +
        `<rect x="0" y="-15" width="${f(len)}" height="30" rx="9" fill="${LEATHER}" ${L(LEATHER)}/>` +
        `<rect x="${f(len - 16)}" y="-16" width="14" height="32" rx="4" fill="${darken(LEATHER, 0.3)}"/>` +
        `<path d="M8,-9H${f(len - 20)}" stroke="${lighten(LEATHER, 0.3)}" stroke-width="2" opacity="0.6"/></g>`;
      return { accBack: body, accNeck: chestStrap(g, -1) };
    },
  },
  {
    id: 'swordHilt', label: 'Sword over shoulder', group: 'gear', layer: 'accBack',
    render({ g, colors }) {
      const { cx, top, shoulderY: sY } = g;
      // Blade behind the back, hilt rising above the right shoulder.
      const hx = cx + 118, hy = top + 30;
      const blade = `<path d="M${pt(hx - 4, hy + 40)}L${pt(cx + 30, sY + 120)}L${pt(cx + 40, sY + 124)}L${pt(hx + 6, hy + 44)}Z" fill="${STEEL}" ${L(STEEL)}/>`;
      const hilt = `<g transform="rotate(28 ${hx} ${hy})">` +
        `<rect x="${hx - 4}" y="${hy - 6}" width="8" height="44" rx="3" fill="${LEATHER}" ${L(LEATHER, 2)}/>` +
        `<path d="M${pt(hx - 4, hy + 4)}l8,6M${pt(hx - 4, hy + 14)}l8,6M${pt(hx - 4, hy + 24)}l8,6" stroke="${darken(LEATHER, 0.4)}" stroke-width="1.6"/>` +
        `<rect x="${hx - 26}" y="${hy + 36}" width="52" height="8" rx="3" fill="${colors.accent}" ${L(colors.accent, 2)}/>` +
        `<circle cx="${hx}" cy="${hy - 10}" r="8" fill="${colors.accent}" ${L(colors.accent, 2)}/></g>`;
      return { accBack: blade + hilt, accNeck: chestStrap(g, 1) };
    },
  },
  {
    id: 'spear', label: 'Spear', group: 'gear', layer: 'accBack',
    render({ g }) {
      const { cx, top } = g;
      const x = cx + 175;
      return {
        accBack: `<path d="M${pt(x + 20, 520)}L${pt(x - 6, top - 70)}" stroke="${WOOD}" stroke-width="8" stroke-linecap="round"/>` +
          `<path d="M${pt(x + 20, 520)}L${pt(x - 6, top - 70)}" stroke="${lighten(WOOD, 0.3)}" stroke-width="2" opacity="0.6" transform="translate(-2,0)"/>` +
          `<path d="M${pt(x - 6, top - 70)}C${pt(x - 20, top - 100)} ${pt(x - 14, top - 130)} ${pt(x - 12, top - 150)}C${pt(x + 2, top - 130)} ${pt(x + 8, top - 100)} ${pt(x - 6, top - 70)}Z" fill="${STEEL}" ${L(STEEL)}/>` +
          `<rect x="${x - 12}" y="${top - 72}" width="12" height="14" rx="2" fill="${darken(STEEL, 0.3)}" transform="rotate(-4 ${x - 6} ${top - 65})"/>`,
      };
    },
  },
  {
    id: 'staff', label: 'Wizard staff', group: 'gear', layer: 'accBack',
    render({ g, colors, uid }) {
      const { cx, top } = g;
      const x = cx - 172;
      const glow = uid('crystal');
      return {
        defs: `<radialGradient id="${glow}"><stop offset="0" stop-color="#fff"/><stop offset="0.4" stop-color="${lighten(colors.accent, 0.4)}"/><stop offset="1" stop-color="${colors.accent}" stop-opacity="0"/></radialGradient>`,
        accBack: `<path d="M${pt(x - 10, 520)}C${pt(x + 6, 380)} ${pt(x - 12, 200)} ${pt(x + 4, top - 50)}" fill="none" stroke="${darken(WOOD, 0.1)}" stroke-width="11" stroke-linecap="round"/>` +
          `<path d="M${pt(x + 4, top - 50)}C${pt(x - 22, top - 70)} ${pt(x - 18, top - 110)} ${pt(x + 4, top - 120)}M${pt(x + 4, top - 50)}C${pt(x + 26, top - 70)} ${pt(x + 22, top - 110)} ${pt(x + 4, top - 120)}" fill="none" stroke="${darken(WOOD, 0.1)}" stroke-width="6" stroke-linecap="round"/>` +
          `<circle cx="${x + 4}" cy="${top - 86}" r="34" fill="url(#${glow})"/>` +
          `<path d="M${pt(x + 4, top - 104)}L${pt(x + 15, top - 86)}L${pt(x + 4, top - 66)}L${pt(x - 7, top - 86)}Z" fill="${lighten(colors.accent, 0.3)}" ${L(colors.accent, 1.6)}/>`,
      };
    },
  },
  {
    id: 'lute', label: 'Lute on back', group: 'gear', layer: 'accBack',
    render({ g }) {
      const { cx, top, shoulderY: sY } = g;
      const wood = '#a8743c';
      const nx = cx - g.w - 44, ny = top - 4; // neck end beside the head
      // Body behind the back, neck and bent pegbox rising above the left shoulder.
      return {
        accBack: `<ellipse cx="${cx + 60}" cy="${sY + 90}" rx="70" ry="56" fill="${wood}" ${L(wood)} transform="rotate(-30 ${cx + 60} ${sY + 90})"/>` +
          `<path d="M${pt(cx + 20, sY + 40)}L${pt(nx, ny)}" stroke="${darken(wood, 0.3)}" stroke-width="16" stroke-linecap="round"/>` +
          `<path d="M${pt(cx + 20, sY + 40)}L${pt(nx, ny)}" stroke="${darken(wood, 0.6)}" stroke-width="1" stroke-dasharray="1 6"/>` +
          `<path d="M${pt(nx, ny)}l-14,22l12,6l10,-20Z" fill="${darken(wood, 0.35)}" ${L(wood, 2)}/>` +
          [0, 1, 2].map((i) => `<circle cx="${nx - 6 - i * 3}" cy="${ny + 8 + i * 6}" r="2.2" fill="#e8dcc0"/>`).join(''),
        accNeck: chestStrap(g, 1, '#5a3a24'),
      };
    },
  },
  // ------------------------------------------------------------ companions
  {
    id: 'shoulderCat', label: 'Cat on shoulder', group: 'companion', layer: 'accHead',
    render({ g, rng }) {
      const fur = rng.pick(['#d08a3a', '#3a3430', '#8a8a8a', '#e8e0d4', '#b06a2a']);
      const x = 0, y = 0;
      const dk = darken(fur, 0.35);
      return {
        accHead: `<path d="M${pt(x + 40, y + 10)}C${pt(x + 80, y - 10)} ${pt(x + 70, y - 60)} ${pt(x + 52, y - 66)}" fill="none" stroke="${fur}" stroke-width="9" stroke-linecap="round"/>` +
          `<ellipse cx="${x + 10}" cy="${y - 14}" rx="38" ry="24" fill="${fur}" ${L(fur)}/>` +
          `<circle cx="${x - 22}" cy="${y - 38}" r="20" fill="${fur}" ${L(fur)}/>` +
          `<path d="M${pt(x - 38, y - 48)}l2,-22l12,14ZM${pt(x - 16, y - 54)}l10,-18l4,18Z" fill="${fur}" ${L(fur, 2)}/>` +
          `<ellipse cx="${x - 30}" cy="${y - 40}" rx="3" ry="4" fill="#d8c040"/><ellipse cx="${x - 16}" cy="${y - 40}" rx="3" ry="4" fill="#d8c040"/>` +
          `<ellipse cx="${x - 30}" cy="${y - 40}" rx="1" ry="3.2" fill="#111"/><ellipse cx="${x - 16}" cy="${y - 40}" rx="1" ry="3.2" fill="#111"/>` +
          `<path d="M${pt(x - 25, y - 33)}l2,2l2,-2" fill="none" stroke="#c07070" stroke-width="1.6"/>` +
          `<path d="M${pt(x - 36, y - 31)}l-12,-2M${pt(x - 36, y - 29)}l-12,3M${pt(x - 12, y - 31)}l12,-2M${pt(x - 12, y - 29)}l12,3" stroke="${lighten(fur, 0.5)}" stroke-width="0.8"/>` +
          `<path d="M${pt(x - 8, y - 6)}q8,6 18,2M${pt(x + 20, y - 4)}q8,6 16,0" fill="none" stroke="${dk}" stroke-width="2"/>`,
      };
    },
  },
  {
    id: 'shoulderDragon', label: 'Small dragon', group: 'companion', layer: 'accHead',
    render({ g, colors }) {
      const sc = mix(colors.accent, '#3a8a4a', 0.5);
      const x = 0, y = 0;
      const wing = `<path d="M${pt(x + 10, y - 30)}L${pt(x + 40, y - 86)}L${pt(x + 46, y - 60)}L${pt(x + 62, y - 70)}L${pt(x + 58, y - 44)}L${pt(x + 74, y - 46)}L${pt(x + 30, y - 22)}Z" fill="${lighten(sc, 0.2)}" ${L(sc, 2)} opacity="0.95"/>`;
      return {
        accHead: wing +
          `<path d="M${pt(x + 30, y)}C${pt(x + 80, y + 4)} ${pt(x + 70, y + 40)} ${pt(x + 96, y + 30)}" fill="none" stroke="${sc}" stroke-width="8" stroke-linecap="round"/>` +
          `<ellipse cx="${x + 12}" cy="${y - 12}" rx="30" ry="17" fill="${sc}" ${L(sc)}/>` +
          `<path d="M${pt(x - 10, y - 20)}C${pt(x - 22, y - 34)} ${pt(x - 22, y - 46)} ${pt(x - 30, y - 50)}" fill="none" stroke="${sc}" stroke-width="12" stroke-linecap="round"/>` +
          `<path d="M${pt(x - 30, y - 50)}l-24,4l4,8l22,0Z" fill="${sc}" ${L(sc, 2)}/>` +
          `<path d="M${pt(x - 28, y - 56)}l6,-16l2,14ZM${pt(x - 36, y - 56)}l-2,-16l8,12Z" fill="${lighten(sc, 0.5)}"/>` +
          `<circle cx="${x - 36}" cy="${y - 50}" r="2.4" fill="#ffd040"/>` +
          `<path d="M${pt(x - 4, y - 10)}h20M${pt(x - 2, y - 4)}h20" stroke="${lighten(sc, 0.4)}" stroke-width="1.4" stroke-dasharray="3 3"/>`,
      };
    },
  },
  {
    id: 'raven', label: 'Raven', group: 'companion', layer: 'accHead',
    render({ g }) {
      const x = 0, y = 0;
      const ink = '#1c1c22';
      return {
        accHead: `<path d="M${pt(x + 26, y - 6)}L${pt(x + 70, y + 14)}L${pt(x + 30, y + 4)}Z" fill="${ink}"/>` +
          `<ellipse cx="${x + 4}" cy="${y - 20}" rx="30" ry="19" fill="${ink}" transform="rotate(-15 ${x + 4} ${y - 20})"/>` +
          `<path d="M${pt(x - 2, y - 26)}C${pt(x + 20, y - 34)} ${pt(x + 34, y - 18)} ${pt(x + 38, y - 4)}" fill="none" stroke="#3a3a48" stroke-width="3"/>` +
          `<circle cx="${x - 24}" cy="${y - 40}" r="14" fill="${ink}"/>` +
          `<path d="M${pt(x - 36, y - 44)}l-20,5l20,4Z" fill="#2a2a2a" stroke="#4a4a50" stroke-width="1"/>` +
          `<circle cx="${x - 28}" cy="${y - 44}" r="2.4" fill="#e8e0c0"/>` +
          `<path d="M${pt(x - 8, y - 2)}l-2,10M${pt(x + 4, y)}l0,10" stroke="#3a3a3a" stroke-width="2.4"/>`,
      };
    },
  },
];

// Companions are drawn around (0,0) and placed on the right shoulder, larger than life-size
// drawings would suggest so they read at portrait scale.
for (const d of defs) {
  if (d.group !== 'companion') { registerPart('accessories', d); continue; }
  const draw = d.render;
  registerPart('accessories', {
    ...d,
    render(ctx) {
      const out = draw(ctx);
      const { g } = ctx;
      return { ...out, accHead: `<g transform="translate(${pt(g.cx + 128, g.shoulderY + 6)}) scale(1.55)">${out.accHead}</g>` };
    },
  });
}

