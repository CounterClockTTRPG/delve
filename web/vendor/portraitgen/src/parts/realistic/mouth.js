// Realistic mouths: shaded lip volumes, a soft parting line and the shadows
// around the mouth (philtrum, corners, under the lower lip).
import { registerStyle } from '../../registry.js';
import { pt } from '../../geometry.js';
import { darken, lighten, mix, luminance } from '../../color.js';
import { blur, blob } from '../../realism.js';
import { shadowTone, lightTone } from './face.js';

// hw: half width; curve: corner height (negative = up); smirk: extra lift of the
// right corner; upper/lower: lip thickness; open: gap between the lips.
const mouths = {
  neutral: { hw: 19, curve: 0.5, upper: 5, lower: 6.5 },
  smile: { hw: 22, curve: -6, upper: 4, lower: 5.5, cheeks: true },
  grin: { hw: 21, curve: -6, upper: 3.8, lower: 5, open: 8, teeth: true, cheeks: true },
  smirk: { hw: 20, curve: 0, smirk: -4.5, upper: 4.2, lower: 5.6 },
  frown: { hw: 19, curve: 4, upper: 4.2, lower: 5.8 },
  open: { hw: 11, curve: 0, upper: 3.6, lower: 5, open: 13, round: true },
  full: { hw: 21, curve: 0, upper: 7, lower: 9 },
  pursed: { hw: 10.5, curve: 0, upper: 5, lower: 6 },
  fangs: { hw: 19, curve: 0, upper: 4.2, lower: 5.6, fangs: true },
  tusks: { hw: 21, curve: 1, upper: 4.8, lower: 6.5, tusks: true },
};

function shapes(m) {
  const lY = m.curve;
  const rY = m.curve + (m.smirk ?? 0);
  const L = [-m.hw, lY];
  const R = [m.hw, rY];
  const gap = m.open ?? 0;
  const midY = (lY + rY) / 2;
  const top = midY - (m.curve < 0 ? m.curve * 0.25 : 0) + 1 - gap * 0.35; // centre of the upper lip's lower edge
  const bot = top + gap;
  const u = m.upper;
  const lo = m.lower;
  // Lower edge of the upper lip / upper edge of the lower lip (identical when closed).
  const upperEdge = `C${pt(-m.hw * 0.5, top + (lY - top) * 0.1)} ${pt(m.hw * 0.5, top + (rY - top) * 0.1)} ${pt(...R)}`;
  const lowerEdgeBack = `C${pt(m.hw * 0.5, bot + (rY - bot) * 0.1)} ${pt(-m.hw * 0.5, bot + (lY - bot) * 0.1)} ${pt(...L)}`;
  const upperLip = `M${pt(...L)}C${pt(-m.hw * 0.7, lY - u * 0.7)} ${pt(-m.hw * 0.35, top - u * 1.15)} ${pt(-m.hw * 0.14, top - u * 1.05)}` +
    `Q${pt(0, top - u * 0.6)} ${pt(m.hw * 0.14, top - u * 1.05)}C${pt(m.hw * 0.35, top - u * 1.15)} ${pt(m.hw * 0.7, rY - u * 0.7)} ${pt(...R)}` +
    `C${pt(m.hw * 0.5, top + (rY - top) * 0.1)} ${pt(-m.hw * 0.5, top + (lY - top) * 0.1)} ${pt(...L)}Z`;
  const lowerLip = `M${pt(...L)}C${pt(-m.hw * 0.5, bot + (lY - bot) * 0.1)} ${pt(m.hw * 0.5, bot + (rY - bot) * 0.1)} ${pt(...R)}` +
    `C${pt(m.hw * 0.7, rY + lo * 0.9)} ${pt(m.hw * 0.4, bot + lo * 1.3)} ${pt(0, bot + lo * 1.3)}` +
    `C${pt(-m.hw * 0.4, bot + lo * 1.3)} ${pt(-m.hw * 0.7, lY + lo * 0.9)} ${pt(...L)}Z`;
  const parting = `M${pt(...L)}${upperEdge}`;
  const cavity = gap ? `M${pt(...L)}${upperEdge}${lowerEdgeBack}Z` : null;
  return { L, R, top, bot, upperLip, lowerLip, parting, cavity, gap };
}

const BOX = [-70, -50, 140, 90];

/** The mouth's shape for a portrait: presentation, age and expression applied. */
function mouthParams(id, g, traits) {
  const base = mouths[id] ?? mouths.neutral;
  // Scaled up from the cartoon proportions: a mouth is about as wide as the distance between the pupils.
  // Lower lip about 1.6x the upper.
  const scaled = { ...base, hw: base.hw * 1.4, upper: base.upper * 1.3, lower: base.lower * 1.6, curve: base.curve * 1.2, smirk: (base.smirk ?? 0) * 1.2, open: base.open && base.open * 1.2 };
  // Feminine presentation: fuller lips; masculine: slightly thinner, wider mouth.
  const k = g.masc ?? 0;
  // Lips thin with age.
  const thin = 1 - Math.max(0, ((g.age ?? 0.35) - 0.45) / 0.55) * 0.35;
  const m = { ...scaled, hw: scaled.hw * (1 + k * 0.04), upper: scaled.upper * (1 - k * 0.25) * thin, lower: scaled.lower * (1 - k * 0.15) * thin };
  // Expression pushes the mouth further than the cartoon shapes do.
  const ex = traits?.expression;
  if (ex === 'smile') { m.curve = Math.min(m.curve, 0) * 1.5 - 3; m.hw *= 1.06; m.cheeks = true; }
  if (ex === 'sad') m.curve += 3;
  if (ex === 'stern') { m.upper *= 0.82; m.lower *= 0.88; m.curve += 1; }
  if (ex === 'smug') m.smirk = (m.smirk || -3) * 1.5;
  return m;
}

/**
 * How far (px, + = down) the parting of the lips sits from g.mouthY for a portrait,
 * relative to a neutral mouth. Facial hair uses it to stay around the lips.
 */
export function lipOffset(g, traits) {
  const at = (id, t) => shapes(mouthParams(id, g, t)).top;
  return at(traits.mouth, traits) - at('neutral', { expression: 'neutral' });
}

for (const id of Object.keys(mouths)) {
  registerStyle('mouth', id, 'realistic', ({ g, colors, uid, traits }) => {
    const m = mouthParams(id, g, traits);
    const skin = colors.skin;
    // Lip/skin contrast is a strong attractiveness cue, stronger in feminine faces.
    // Lips relative to the skin: rosy on light skin, deeper and browner/berry on dark skin (pink reads as lipstick there).
    const l = luminance(skin);
    const lip = mix(skin, mix('#a23a48', '#4a2228', 1 - Math.min(1, l * 2)), (0.48 - (g.masc ?? 0) * 0.16) * (0.75 + 0.25 * Math.min(1, l * 2)));
    const sh = shadowTone(skin, 0.4);
    const s = shapes(m);
    const up = uid('upLip');
    const lo = uid('loLip');
    const clip = uid('mouthClip');
    const b4 = uid('b4');
    const b15 = uid('b15');
    const b07 = uid('b07');
    const defs = `<linearGradient id="${up}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${darken(lip, 0.1)}"/><stop offset="1" stop-color="${darken(lip, 0.35)}"/></linearGradient>` +
      `<linearGradient id="${lo}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${darken(lip, 0.18)}"/><stop offset="0.45" stop-color="${lip}"/><stop offset="1" stop-color="${mix(lip, skin, 0.5)}"/></linearGradient>` +
      (s.cavity ? `<clipPath id="${clip}"><path d="${s.cavity}"/></clipPath>` : '') +
      blur(b4, 3.5, BOX) + blur(b15, 1.5, BOX) + blur(b07, 0.7, BOX);
    // Surrounding soft tissue.
    let around = blob(0, s.bot + m.lower * 1.3 + 5, m.hw * 0.65, 4, sh, 0.6) + // under the lower lip
      blob(-1, s.top - m.upper - 9, 5, 7, sh, 0.18) + // philtrum
      blob(s.L[0] - 2, s.L[1], 3.5, 4, sh, 0.45) + blob(s.R[0] + 2, s.R[1], 3.5, 4, sh, 0.5); // corners
    if (m.cheeks) around += blob(s.L[0] - 9, s.L[1] - 4, 4, 10, sh, 0.3, 25) + blob(s.R[0] + 9, s.R[1] - 4, 4, 10, sh, 0.35, -25);
    let lips = `<path d="${s.lowerLip}" fill="url(#${lo})"/><path d="${s.upperLip}" fill="url(#${up})"/>`;
    if (s.cavity) {
      lips += `<path d="${s.cavity}" fill="#2a1212"/>`;
      if (m.teeth) {
        lips += `<g clip-path="url(#${clip})"><path d="M${pt(-m.hw, s.top - 2)}L${pt(m.hw, s.top - 2)}L${pt(m.hw * 0.85, s.top + s.gap * 0.6)}Q0,${(s.top + s.gap * 0.72).toFixed(2)} ${pt(-m.hw * 0.85, s.top + s.gap * 0.6)}Z" fill="#ece4d6"/>` +
          `<g filter="url(#${b07})">${[-0.62, -0.34, -0.08, 0.08, 0.34, 0.62].map((t) => `<path d="M${pt(m.hw * t, s.top)}l0,${(s.gap * 0.6).toFixed(2)}" stroke="#b8ab98" stroke-width="0.8" opacity="0.7"/>`).join('')}` +
          blob(0, s.top, m.hw, 2.5, '#2a1212', 0.45) + `</g></g>`;
      }
      lips += `<g filter="url(#${b15})"><path d="${s.cavity}" fill="none" stroke="${darken(lip, 0.5)}" stroke-width="1.5" opacity="0.6"/></g>`;
    }
    const parting = s.cavity ? '' :
      `<g filter="url(#${b15})"><path d="${s.parting}" fill="none" stroke="${darken(lip, 0.65)}" stroke-width="2.6" opacity="0.6"/></g>` +
      `<path d="${s.parting}" fill="none" stroke="${darken(lip, 0.7)}" stroke-width="0.9" stroke-linecap="round" opacity="0.75"/>`;
    const sheen = `<g filter="url(#${b15})">${blob(-m.hw * 0.25, s.bot + m.lower * 0.6, m.hw * 0.22, m.lower * 0.18, lighten(lip, 0.4), 0.4)}` +
      blob(-m.hw * 0.3, s.top - m.upper * 0.55, m.hw * 0.18, 1.2, lighten(lip, 0.4), 0.3) + `</g>` +
      // Vermilion border catching the light on the upper lip.
      `<path d="M${pt(-m.hw * 0.6, s.top - m.upper * 0.95)}Q${pt(-m.hw * 0.3, s.top - m.upper * 1.3)} ${pt(-m.hw * 0.12, s.top - m.upper * 1.15)}" fill="none" stroke="${lightTone(skin, 0.3)}" stroke-width="1" opacity="0.35"/>`;
    let extra = '';
    if (m.fangs) {
      extra = `<path d="M-10,${(s.top - 0.5).toFixed(2)}Q-9,${(s.top + 8).toFixed(2)} -7.5,${(s.top + 10).toFixed(2)}Q-6.5,${(s.top + 6).toFixed(2)} -5.5,${(s.top - 0.5).toFixed(2)}ZM10,${(s.top - 0.5).toFixed(2)}Q9,${(s.top + 8).toFixed(2)} 7.5,${(s.top + 10).toFixed(2)}Q6.5,${(s.top + 6).toFixed(2)} 5.5,${(s.top - 0.5).toFixed(2)}Z" fill="#efe8da"/>` +
        `<g filter="url(#${b07})"><path d="M-9,${(s.top + 1).toFixed(2)}l1.2,7M9,${(s.top + 1).toFixed(2)}l-1.2,7" stroke="#a89880" stroke-width="1" opacity="0.6"/></g>`;
    }
    if (m.tusks) {
      const tg = uid('tusk');
      const tusk = (k) => `<path d="M${pt(k * 16, s.bot + 5)}Q${pt(k * 21, -8)} ${pt(k * 13, -17)}Q${pt(k * 12, -6)} ${pt(k * 10, s.bot + 4)}Z" fill="url(#${tg})"/>`;
      extra = `<linearGradient id="${tg}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#f6efdc"/><stop offset="1" stop-color="#b8a682"/></linearGradient>` +
        tusk(-1) + tusk(1) +
        `<g filter="url(#${b15})">${blob(-13, s.bot + 5, 5, 2, sh, 0.5)}${blob(13, s.bot + 5, 5, 2, sh, 0.5)}</g>`;
    }
    return {
      defs,
      mouth: `<g transform="translate(${pt(g.cx + (g.asym?.mouthDX ?? 0), g.mouthY)}) rotate(${(g.asym?.mouthTilt ?? 0).toFixed(2)})"><g filter="url(#${b4})">${around}</g>${lips}${parting}${sheen}${extra}</g>`,
    };
  });
}
