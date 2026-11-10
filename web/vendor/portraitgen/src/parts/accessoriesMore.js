// More decorations: helmets, hats, face coverings, skin conditions and adornments.
// Headwear may define hidesHairAbove(g): hair above that height is hidden, so
// big hairstyles don't poke through the top of a helmet.
import { registerPart } from '../registry.js';
import { pt, mirrored, mirrorPath, blurFilter } from '../geometry.js';
import { darken, lighten, mix } from '../color.js';

const STEEL = '#a3acb6';
const f = (n) => +n.toFixed(2);
const stroke = (c, w = 3) => `stroke="${darken(c, 0.55)}" stroke-width="${w}" stroke-linejoin="round"`;
const rivets = (pts, c) => pts.map(([x, y]) => `<circle cx="${f(x)}" cy="${f(y)}" r="2.6" fill="${lighten(c, 0.3)}" ${stroke(c, 1.2)}/>`).join('');

/** Top of a helmet dome: just clear of the skull and a short haircut, not a tall bucket. */
const domeTop = (g, extra) => g.top - 14 - extra * 0.5;

/** Dome of a helmet over the skull, from rim height `rimY`, `extra` px clear of the head. */
function dome(g, rimY, extra = 10) {
  const { cx, w, top } = g;
  const t = domeTop(g, extra);
  return `M${pt(cx - w - extra, rimY)}C${pt(cx - w - extra - 3, top + 12)} ${pt(cx - w * 0.55, t)} ${pt(cx, t)}` +
    `C${pt(cx + w * 0.55, t)} ${pt(cx + w + extra + 3, top + 12)} ${pt(cx + w + extra, rimY)}Z`;
}

/** Chainmail: a fine repeating pattern of rings. */
const mailPattern = (id, c) => `<pattern id="${id}" width="5" height="4" patternUnits="userSpaceOnUse">` +
  `<circle cx="0" cy="0" r="1.8" fill="none" stroke="${lighten(c, 0.35)}" stroke-width="0.8"/><circle cx="5" cy="0" r="1.8" fill="none" stroke="${lighten(c, 0.35)}" stroke-width="0.8"/>` +
  `<circle cx="2.5" cy="2" r="1.8" fill="none" stroke="${lighten(c, 0.2)}" stroke-width="0.8"/>` +
  `<circle cx="0" cy="4" r="1.8" fill="none" stroke="${lighten(c, 0.35)}" stroke-width="0.8"/><circle cx="5" cy="4" r="1.8" fill="none" stroke="${lighten(c, 0.35)}" stroke-width="0.8"/></pattern>`;

const defs = [
  // ------------------------------------------------------------ helmets
  {
    id: 'helmetNasal', label: 'Nasal helm', group: 'head', layer: 'accHead',
    hidesHairAbove: (g) => g.browY - 6,
    render({ g, uid }) {
      const { cx, w, browY, noseY } = g;
      const grad = uid('steel');
      const rim = browY - 8;
      const cone = `M${pt(cx - w - 10, rim)}C${pt(cx - w - 12, g.top - 20)} ${pt(cx - 18, g.top - 62)} ${pt(cx, g.top - 70)}C${pt(cx + 18, g.top - 62)} ${pt(cx + w + 12, g.top - 20)} ${pt(cx + w + 10, rim)}Z`;
      return {
        defs: `<linearGradient id="${grad}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${lighten(STEEL, 0.35)}"/><stop offset="0.45" stop-color="${STEEL}"/><stop offset="1" stop-color="${darken(STEEL, 0.4)}"/></linearGradient>`,
        accHead: `<path d="${cone}" fill="url(#${grad})" ${stroke(STEEL)}/>` +
          `<path d="M${pt(cx, g.top - 66)}L${pt(cx, rim)}" stroke="${darken(STEEL, 0.35)}" stroke-width="3"/>` +
          `<path d="M${pt(cx - w - 12, rim - 14)}Q${pt(cx, rim - 22)} ${pt(cx + w + 12, rim - 14)}L${pt(cx + w + 12, rim + 2)}Q${pt(cx, rim - 6)} ${pt(cx - w - 12, rim + 2)}Z" fill="${darken(STEEL, 0.1)}" ${stroke(STEEL)}/>` +
          `<path d="M${pt(cx - 5, rim - 6)}L${pt(cx + 5, rim - 6)}L${pt(cx + 4, noseY - 4)}L${pt(cx, noseY)}L${pt(cx - 4, noseY - 4)}Z" fill="url(#${grad})" ${stroke(STEEL, 2.4)}/>` +
          rivets([[cx - w * 0.7, rim - 7], [cx - w * 0.35, rim - 10], [cx + w * 0.35, rim - 10], [cx + w * 0.7, rim - 7]], STEEL),
      };
    },
  },
  {
    id: 'helmetPlumed', label: 'Plumed helm', group: 'head', layer: 'accHead',
    hidesHairAbove: (g) => g.browY - 4,
    render({ g, colors, uid }) {
      const { cx, w, browY, eyeY, jawY, top } = g;
      const metal = mix(STEEL, '#c9a443', 0.35);
      const grad = uid('helm');
      const plume = colors.accent;
      const guard = `<path d="M${pt(cx + w - 8, browY - 4)}L${pt(cx + w + 12, browY - 4)}L${pt(cx + w + 10, jawY - 10)}Q${pt(cx + w - 6, jawY + 4)} ${pt(cx + w - 18, jawY - 18)}L${pt(cx + w - 14, eyeY + 6)}Z" fill="url(#${grad})" ${stroke(metal, 2.6)}/>` +
        rivets([[cx + w + 2, eyeY + 4], [cx + w, jawY - 20]], metal);
      // A fan of plume strands rising from the crest holder and sweeping back.
      let crest = '';
      for (let i = 0; i < 11; i++) {
        const t = i / 10;
        const x = cx - 8 + t * 16, y = domeTop(g, 12) - 2;
        crest += `<path d="M${pt(x, y)}C${pt(x - 6 + t * 12, y - 40)} ${pt(cx - 60 + t * 120, y - 62)} ${pt(cx - 80 + t * 160, y - 36 - Math.sin(t * Math.PI) * 26)}" fill="none" stroke="${i % 2 ? darken(plume, 0.25) : plume}" stroke-width="6" stroke-linecap="round"/>`;
      }
      return {
        defs: `<linearGradient id="${grad}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${lighten(metal, 0.35)}"/><stop offset="0.5" stop-color="${metal}"/><stop offset="1" stop-color="${darken(metal, 0.4)}"/></linearGradient>`,
        accHead: `${crest}<path d="${dome(g, browY - 6, 12)}" fill="url(#${grad})" ${stroke(metal)}/>` +
          `<path d="M${pt(cx - w - 14, browY - 10)}Q${pt(cx, browY - 22)} ${pt(cx + w + 14, browY - 10)}" fill="none" stroke="${darken(metal, 0.3)}" stroke-width="7" stroke-linecap="round"/>` +
          `<rect x="${cx - 7}" y="${domeTop(g, 12) - 6}" width="14" height="14" rx="3" fill="${darken(metal, 0.2)}" ${stroke(metal, 2)}/>` +
          guard + mirrored(cx, guard),
      };
    },
  },
  {
    // Viking-age spectacle helm (after the Gjermundbu find): a low riveted dome on a
    // brow band, a guard plate around the eyes and nose, and a mail aventail.
    id: 'helmetSpectacle', label: 'Spectacle helm', group: 'head', alsoGroups: ['eyewear'], layer: 'accHead',
    hidesHairAbove: (g) => g.browY - 6,
    render({ g, uid }) {
      const { cx, w, top, eyeY, eyeDX, browY, noseY, jawY, jawW, cheekW, neckW, shoulderY } = g;
      const metal = mix(STEEL, '#6a6258', 0.3);
      const grad = uid('helm');
      const mail = uid('mail');
      const clip = uid('domeClip');
      const R = browY - 6; // brow band centre line
      const t = top - 16;
      const bandTop = `Q${pt(cx, R - 24)} `;
      const domeD = `M${pt(cx - w - 9, R + 4)}C${pt(cx - w - 12, top + 10)} ${pt(cx - w * 0.55, t)} ${pt(cx, t)}C${pt(cx + w * 0.55, t)} ${pt(cx + w + 12, top + 10)} ${pt(cx + w + 9, R + 4)}${bandTop}${pt(cx - w - 9, R + 4)}Z`;
      const band = `M${pt(cx - w - 9, R + 4)}Q${pt(cx, R - 24)} ${pt(cx + w + 9, R + 4)}L${pt(cx + w + 9, R + 14)}Q${pt(cx, R - 10)} ${pt(cx - w - 9, R + 14)}Z`;
      // Guard plate: from the band around both eyes and down into a nose guard, with eye openings.
      const plate = mirrorPath(cx, [0, R], [
        [[eyeDX * 0.5, R - 1], [eyeDX + 18, R + 1], [eyeDX + 27, R + 6]],
        [[eyeDX + 31, eyeY - 6], [eyeDX + 26, eyeY + 20], [eyeDX + 6, eyeY + 22]],
        [[eyeDX - 10, eyeY + 23], [16, eyeY + 18], [9, eyeY + 10]],
        [[7, noseY - 18], [7, noseY - 6], [0, noseY + 2]],
      ]);
      const hole = (x) => `M${pt(x - 21, eyeY + 1)}a21,12.5 0 1,0 42,0a21,12.5 0 1,0 -42,0Z`;
      const plateD = plate + hole(cx + eyeDX) + hole(cx - eyeDX);
      // Aventail: mail hanging from the sides over the ears and neck.
      const aventail = `M${pt(cx + cheekW * 0.94, R + 10)}L${pt(cx + w + 10, R + 10)}C${pt(cx + w + 18, jawY - 10)} ${pt(cx + w + 26, shoulderY - 20)} ${pt(cx + w + 42, shoulderY + 6)}` +
        `L${pt(cx + neckW + 10, shoulderY + 12)}C${pt(cx + neckW + 2, jawY + 40)} ${pt(cx + jawW + 4, jawY + 10)} ${pt(cx + cheekW * 0.93, eyeY + 10)}Z`;
      // Iron mail: dark, with the rings catching a little light.
      const side = `<path d="${aventail}" fill="${darken(metal, 0.6)}" ${stroke(metal, 2)}/><path d="${aventail}" fill="url(#${mail})" opacity="0.75"/>` +
        `<path d="M${pt(cx + w + 6, R + 14)}C${pt(cx + w + 14, jawY)} ${pt(cx + w + 22, shoulderY - 20)} ${pt(cx + w + 36, shoulderY + 4)}" fill="none" stroke="${darken(metal, 0.6)}" stroke-width="4" opacity="0.35"/>`;
      return {
        defs: `<linearGradient id="${grad}" x1="0" y1="0" x2="1" y2="0.2"><stop offset="0" stop-color="${lighten(metal, 0.4)}"/><stop offset="0.45" stop-color="${metal}"/><stop offset="1" stop-color="${darken(metal, 0.45)}"/></linearGradient>` +
          mailPattern(mail, darken(metal, 0.45)) + `<clipPath id="${clip}"><path d="${domeD}"/></clipPath>`,
        accHead: side + mirrored(cx, side) +
          `<path d="${domeD}" fill="url(#${grad})" ${stroke(metal)}/>` +
          `<g clip-path="url(#${clip})"><path d="M${pt(cx, R - 12)}L${pt(cx, t - 4)}" stroke="${darken(metal, 0.15)}" stroke-width="13"/>` +
          `<path d="M${pt(cx - 6.5, R - 12)}L${pt(cx - 6.5, t - 4)}M${pt(cx + 6.5, R - 12)}L${pt(cx + 6.5, t - 4)}" stroke="${darken(metal, 0.55)}" stroke-width="1.4"/>` +
          `<path d="M${pt(cx - w * 0.6, top + 4)}Q${pt(cx - w * 0.35, t + 8)} ${pt(cx - 12, t + 6)}" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity="0.35"/></g>` +
          `<path d="${band}" fill="url(#${grad})" ${stroke(metal, 2.4)}/>` +
          `<path d="${plateD}" fill="url(#${grad})" fill-rule="evenodd" ${stroke(metal, 2.2)}/>` +
          `<path d="M${pt(cx - eyeDX - 22, eyeY - 2)}Q${pt(cx - eyeDX, eyeY - 17)} ${pt(cx - 10, eyeY - 10)}" fill="none" stroke="#fff" stroke-width="1.6" opacity="0.45"/>` +
          rivets([[cx - w * 0.75, R + 6], [cx - w * 0.38, R + 1], [cx, t + 14], [cx, R - 4], [cx + w * 0.38, R + 1], [cx + w * 0.75, R + 6], [cx - eyeDX - 22, eyeY + 6], [cx + eyeDX + 22, eyeY + 6]], metal),
      };
    },
  },
  {
    id: 'helmetSpace', label: 'Space helmet', group: 'head', alsoGroups: ['mask'], layer: 'accHead',
    render({ g, colors, uid }) {
      const { cx } = g;
      // Sized so the bubble clears the crown and its neck ring sits below the chin.
      const ringY = g.bottom + 30;
      const r = Math.max(g.w + 60, (ringY - g.top + 52) / 1.78);
      const cy = g.top - 52 + r;
      const glass = uid('glass');
      return {
        defs: `<radialGradient id="${glass}" cx="0.35" cy="0.3" r="0.8"><stop offset="0" stop-color="#ffffff" stop-opacity="0.18"/><stop offset="0.7" stop-color="#bfe4ff" stop-opacity="0.06"/><stop offset="1" stop-color="#8ac8ff" stop-opacity="0.28"/></radialGradient>`,
        accHead: `<circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#${glass})" stroke="#d8eeff" stroke-width="3" stroke-opacity="0.7"/>` +
          `<path d="M${pt(cx - r * 0.75, cy - r * 0.35)}A${r * 0.85},${r * 0.85} 0 0,1 ${pt(cx - r * 0.1, cy - r * 0.86)}" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity="0.55"/>` +
          `<path d="M${pt(cx + r * 0.62, cy + r * 0.48)}A${r * 0.8},${r * 0.8} 0 0,0 ${pt(cx + r * 0.8, cy + r * 0.05)}" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity="0.4"/>` +
          // Neck ring.
          `<path d="M${pt(cx - r * 0.82, cy + r * 0.62)}Q${pt(cx, cy + r * 0.85)} ${pt(cx + r * 0.82, cy + r * 0.62)}L${pt(cx + r * 0.9, cy + r * 0.78)}Q${pt(cx, cy + r * 1.02)} ${pt(cx - r * 0.9, cy + r * 0.78)}Z" fill="#c8ced6" ${stroke('#c8ced6', 2.5)}/>` +
          `<rect x="${cx + r * 0.3}" y="${f(cy + r * 0.8)}" width="22" height="6" rx="2" fill="${colors.accent}"/>`,
      };
    },
  },
  {
    // Modern combat helmet: the shell sits just above the brows at the front and
    // drops over the ears at the sides; band around the shell, front mount, chinstrap.
    id: 'helmetCombat', label: 'Combat helmet', group: 'head', layer: 'accHead',
    hidesHairAbove: (g) => g.browY - 12,
    render({ g, uid }) {
      const { cx, w, top, browY, eyeY, bottom } = g;
      const c = '#4f5a3e';
      const grad = uid('kevlar');
      const clip = uid('shell');
      const t = top - 30;
      const front = browY - 13;
      const shell = `M${pt(cx - w - 16, eyeY - 4)}C${pt(cx - w - 24, top - 2)} ${pt(cx - w * 0.55, t)} ${pt(cx, t)}C${pt(cx + w * 0.55, t)} ${pt(cx + w + 24, top - 2)} ${pt(cx + w + 16, eyeY - 4)}` +
        `C${pt(cx + w + 6, browY + 2)} ${pt(cx + w * 0.5, front)} ${pt(cx, front)}C${pt(cx - w * 0.5, front)} ${pt(cx - w - 6, browY + 2)} ${pt(cx - w - 16, eyeY - 4)}Z`;
      const rim = `M${pt(cx + w + 16, eyeY - 4)}C${pt(cx + w + 6, browY + 2)} ${pt(cx + w * 0.5, front)} ${pt(cx, front)}C${pt(cx - w * 0.5, front)} ${pt(cx - w - 6, browY + 2)} ${pt(cx - w - 16, eyeY - 4)}`;
      const strap = `<path d="M${pt(cx + w + 10, eyeY - 6)}Q${pt(cx + w + 2, eyeY + 50)} ${pt(cx + g.chinW + 4, bottom + 4)}" fill="none" stroke="#2c2a24" stroke-width="4"/>`;
      return {
        defs: `<linearGradient id="${grad}" x1="0" y1="0" x2="1" y2="0.3"><stop offset="0" stop-color="${lighten(c, 0.25)}"/><stop offset="0.5" stop-color="${c}"/><stop offset="1" stop-color="${darken(c, 0.4)}"/></linearGradient>` +
          `<clipPath id="${clip}"><path d="${shell}"/></clipPath>`,
        accHead: strap + mirrored(cx, strap) +
          `<path d="${shell}" fill="url(#${grad})" ${stroke(c)}/>` +
          `<g clip-path="url(#${clip})"><path d="M${pt(cx - w - 30, browY - 30)}Q${pt(cx, browY - 52)} ${pt(cx + w + 30, browY - 30)}" fill="none" stroke="${darken(c, 0.3)}" stroke-width="9"/>` +
          `<path d="M${pt(cx - w * 0.62, top + 6)}Q${pt(cx - w * 0.35, t + 6)} ${pt(cx - 10, t + 4)}" fill="none" stroke="${lighten(c, 0.35)}" stroke-width="6" stroke-linecap="round" opacity="0.5"/></g>` +
          `<path d="${rim}" fill="none" stroke="${darken(c, 0.5)}" stroke-width="4" stroke-linecap="round"/>` +
          `<path d="M${pt(cx - 11, front - 20)}L${pt(cx + 11, front - 20)}L${pt(cx + 9, front - 4)}L${pt(cx - 9, front - 4)}Z" fill="#2c2e2a" ${stroke('#2c2e2a', 1.4)}/>`,
      };
    },
  },
  // ------------------------------------------------------------ hats
  {
    id: 'wizardHat', label: 'Wizard hat', group: 'head', layer: 'accHead',
    hidesHairAbove: (g) => g.browY - 10,
    render({ g, colors }) {
      const { cx, w, browY, top } = g;
      const c = darken(colors.clothing, 0.05);
      const rim = browY - 12;
      let stars = '';
      for (const [x, y, s] of [[cx - 20, top - 30, 6], [cx + 16, top - 70, 4], [cx - 2, top - 110, 3.5]]) {
        stars += `<path d="M${pt(x, y - s)}L${pt(x + s * 0.3, y - s * 0.3)}L${pt(x + s, y)}L${pt(x + s * 0.3, y + s * 0.3)}L${pt(x, y + s)}L${pt(x - s * 0.3, y + s * 0.3)}L${pt(x - s, y)}L${pt(x - s * 0.3, y - s * 0.3)}Z" fill="${colors.accent}"/>`;
      }
      return {
        accHead: `<path d="M${pt(cx - w - 8, rim)}C${pt(cx - w * 0.5, top - 60)} ${pt(cx - 10, top - 120)} ${pt(cx + 34, top - 160)}C${pt(cx + 20, top - 110)} ${pt(cx + w * 0.6, top - 50)} ${pt(cx + w + 8, rim)}Z" fill="${c}" ${stroke(c)}/>` +
          stars +
          `<path d="M${pt(cx - w - 8, rim - 4)}Q${pt(cx, rim - 18)} ${pt(cx + w + 8, rim - 4)}L${pt(cx + w + 8, rim + 6)}Q${pt(cx, rim - 8)} ${pt(cx - w - 8, rim + 6)}Z" fill="${colors.accent}" ${stroke(colors.accent, 2)}/>` +
          `<ellipse cx="${cx}" cy="${rim + 4}" rx="${w + 62}" ry="17" fill="${darken(c, 0.12)}" ${stroke(c)}/>` +
          `<path d="M${pt(cx - w - 8, rim + 4)}Q${pt(cx, rim - 10)} ${pt(cx + w + 8, rim + 4)}" fill="none" stroke="${darken(c, 0.45)}" stroke-width="3" opacity="0.7"/>`,
      };
    },
  },
  {
    id: 'topHat', label: 'Top hat', group: 'head', layer: 'accHead',
    hidesHairAbove: (g) => g.browY - 14,
    render({ g, colors }) {
      const { cx, w, browY } = g;
      const c = '#25222a';
      const rim = browY - 16;
      const tw = w * 0.82;
      return {
        accHead: `<path d="M${pt(cx - tw, rim)}L${pt(cx - tw - 6, rim - 96)}Q${pt(cx, rim - 104)} ${pt(cx + tw + 6, rim - 96)}L${pt(cx + tw, rim)}Z" fill="${c}" ${stroke('#4a4650')}/>` +
          `<path d="M${pt(cx - tw - 1, rim - 22)}L${pt(cx + tw + 1, rim - 22)}L${pt(cx + tw, rim - 4)}L${pt(cx - tw, rim - 4)}Z" fill="${colors.accent}"/>` +
          `<path d="M${pt(cx - tw * 0.7, rim - 90)}L${pt(cx - tw * 0.6, rim - 30)}" stroke="#6a6670" stroke-width="5" stroke-linecap="round" opacity="0.6"/>` +
          `<ellipse cx="${cx}" cy="${rim}" rx="${w + 30}" ry="11" fill="#1c1a20" ${stroke('#4a4650')}/>`,
      };
    },
  },
  {
    id: 'wideBrimHat', label: 'Wide-brim hat', group: 'head', layer: 'accHead',
    hidesHairAbove: (g) => g.browY - 10,
    render({ g, colors }) {
      // The crown fits over the whole skull (wider than the head, taller than its top) with
      // a pinched top, a band, and a brim that spans well past the face.
      const { cx, w, browY, top } = g;
      const c = mix(colors.clothing, '#8a6a44', 0.5);
      const rim = browY - 12;
      const cw = w + 8, ct = top - 30;
      return {
        accHead: `<path d="M${pt(cx - cw, rim)}C${pt(cx - cw - 4, ct + 30)} ${pt(cx - cw * 0.6, ct)} ${pt(cx - 10, ct + 4)}Q${pt(cx, ct + 12)} ${pt(cx + 10, ct + 4)}C${pt(cx + cw * 0.6, ct)} ${pt(cx + cw + 4, ct + 30)} ${pt(cx + cw, rim)}Z" fill="${c}" ${stroke(c)}/>` +
          `<path d="M${pt(cx, ct + 10)}Q${pt(cx - 6, (ct + rim) / 2)} ${pt(cx, rim - 22)}" fill="none" stroke="${darken(c, 0.4)}" stroke-width="3"/>` +
          `<path d="M${pt(cx - cw - 1, rim - 22)}Q${pt(cx, rim - 30)} ${pt(cx + cw + 1, rim - 22)}L${pt(cx + cw, rim - 4)}Q${pt(cx, rim - 12)} ${pt(cx - cw, rim - 4)}Z" fill="${darken(c, 0.45)}"/>` +
          `<path d="M${pt(cx - w - 92, rim + 10)}Q${pt(cx - w - 46, rim - 16)} ${pt(cx, rim - 12)}Q${pt(cx + w + 46, rim - 16)} ${pt(cx + w + 92, rim + 10)}Q${pt(cx, rim + 22)} ${pt(cx - w - 92, rim + 10)}Z" fill="${darken(c, 0.08)}" ${stroke(c)}/>`,
      };
    },
  },
  {
    id: 'bandana', label: 'Bandana', group: 'head', layer: 'accHead',
    hidesHairAbove: (g) => g.top + 4,
    render({ g, colors }) {
      const { cx, w, top } = g;
      const c = colors.accent;
      const y = g.hairY + 6;
      let dots = '';
      for (let i = -4; i <= 4; i++) dots += `<circle cx="${cx + i * 20}" cy="${y - 20 + Math.abs(i) * 1.5}" r="2.4" fill="${lighten(c, 0.6)}"/>`;
      return {
        accHead: `<path d="M${pt(cx - w - 6, y)}C${pt(cx - w - 8, top - 26)} ${pt(cx + w + 8, top - 26)} ${pt(cx + w + 6, y)}Q${pt(cx, y - 10)} ${pt(cx - w - 6, y)}Z" fill="${c}" ${stroke(c)}/>` + dots +
          `<path d="M${pt(cx + w + 2, y - 8)}l26,10l-6,24l-12,-20ZM${pt(cx + w + 2, y - 8)}l22,30l-12,8Z" fill="${darken(c, 0.1)}" ${stroke(c, 2.4)}/>` +
          `<circle cx="${cx + w + 4}" cy="${y - 8}" r="7" fill="${darken(c, 0.2)}" ${stroke(c, 2)}/>`,
      };
    },
  },
  {
    id: 'flowerCrown', label: 'Flower crown', group: 'head', layer: 'accHead',
    render({ g, colors, rng }) {
      const { cx, w } = g;
      const y0 = g.hairY - 4;
      const petals = ['#f2a7c0', '#fff1f4', colors.accent, '#f6d36b', '#c9a8f0'];
      let s = '';
      for (let i = 0; i <= 8; i++) {
        const t = i / 8;
        const x = cx - w - 4 + t * (2 * w + 8);
        const y = y0 - Math.sin(t * Math.PI) * 18 + 6;
        s += `<ellipse cx="${f(x + 8)}" cy="${f(y + 6)}" rx="9" ry="4" fill="#5f8a4a" transform="rotate(${f(rng.range(-40, 40))} ${f(x + 8)} ${f(y + 6)})"/>`;
      }
      for (let i = 0; i <= 7; i++) {
        const t = (i + 0.5) / 8;
        const x = cx - w + t * 2 * w;
        const y = y0 - Math.sin(t * Math.PI) * 18 + 4;
        const c = rng.pick(petals);
        let flower = '';
        for (let k = 0; k < 5; k++) {
          const a = (k / 5) * Math.PI * 2;
          flower += `<circle cx="${f(x + Math.cos(a) * 5)}" cy="${f(y + Math.sin(a) * 5)}" r="4.6" fill="${c}" stroke="${darken(c, 0.35)}" stroke-width="1"/>`;
        }
        s += flower + `<circle cx="${f(x)}" cy="${f(y)}" r="3" fill="#f2c94c"/>`;
      }
      return { accHead: s };
    },
  },
  // ------------------------------------------------------------ face coverings
  {
    id: 'faceMask', label: 'Face mask', group: 'mask', layer: 'accFace',
    render({ g, colors }) {
      const { cx, noseY, bottom, mouthY, w } = g;
      const c = mix(colors.clothing, '#d8dee6', 0.55);
      const top = noseY - 12;
      const half = g.jawW * 0.98;
      const d = mirrorPath(cx, [0, top - 4], [
        [[16, top - 6], [half * 0.7, top + 2], [half, top + 8]],
        [[half + 4, mouthY], [g.chinW + 22, bottom], [0, bottom + 6]],
      ]);
      const loop = `<path d="M${pt(cx + half, top + 10)}Q${pt(cx + w + 6, noseY)} ${pt(cx + w + 2, g.eyeY + 8)}M${pt(cx + half - 4, mouthY + 10)}Q${pt(cx + w + 4, mouthY)} ${pt(cx + w + 2, g.eyeY + 14)}" fill="none" stroke="${darken(c, 0.3)}" stroke-width="2"/>`;
      return {
        accFace: loop + mirrored(cx, loop) + `<path d="${d}" fill="${c}" ${stroke(c, 2.4)}/>` +
          `<path d="M${pt(cx - half * 0.8, mouthY - 10)}Q${pt(cx, mouthY - 16)} ${pt(cx + half * 0.8, mouthY - 10)}M${pt(cx - half * 0.75, mouthY + 4)}Q${pt(cx, mouthY - 2)} ${pt(cx + half * 0.75, mouthY + 4)}" fill="none" stroke="${darken(c, 0.25)}" stroke-width="2" opacity="0.6"/>`,
      };
    },
  },
  // ------------------------------------------------------------ skin
  {
    id: 'acne', label: 'Acne', layer: 'marks',
    render({ g, colors, rng }) {
      const red = mix(colors.skin, '#c0404a', 0.45);
      const zones = [[g.cx - g.eyeDX - 4, g.noseY + 6, 22, 14], [g.cx + g.eyeDX + 4, g.noseY + 6, 22, 14], [g.cx, g.top + (g.eyeY - g.top) * 0.45, g.w * 0.5, 14], [g.cx, g.bottom - 18, 16, 8]];
      let s = '';
      for (const [zx, zy, rx, ry] of zones) {
        for (let i = 0; i < 5; i++) {
          const x = zx + rng.range(-rx, rx), y = zy + rng.range(-ry, ry), r = rng.range(1.4, 2.8);
          s += `<circle cx="${f(x)}" cy="${f(y)}" r="${f(r + 1.2)}" fill="${red}" opacity="0.35"/><circle cx="${f(x)}" cy="${f(y)}" r="${f(r)}" fill="${red}" opacity="0.8"/>` +
            `<circle cx="${f(x - r * 0.3)}" cy="${f(y - r * 0.3)}" r="${f(r * 0.35)}" fill="${lighten(red, 0.5)}" opacity="0.7"/>`;
        }
      }
      return { marks: s };
    },
  },
  {
    id: 'birthmark', label: 'Birthmark', layer: 'marks',
    render({ g, colors, rng }) {
      const c = mix(colors.skin, '#9a3048', 0.4);
      const x = g.cx - g.eyeDX - 8, y = g.noseY + 4;
      let d = '';
      const n = 9;
      for (let i = 0; i <= n; i++) {
        const a = (i / n) * Math.PI * 2;
        const r = rng.range(12, 20);
        d += `${i ? 'L' : 'M'}${pt(x + Math.cos(a) * r, y + Math.sin(a) * r * 0.8)}`;
      }
      return { marks: `<path d="${d}Z" fill="${c}" opacity="0.5" stroke="${c}" stroke-width="4" stroke-opacity="0.25" stroke-linejoin="round"/>` };
    },
  },
  {
    id: 'vitiligo', label: 'Vitiligo', layer: 'marks',
    render({ g, colors, rng }) {
      const c = mix(lighten(colors.skin, 0.55), '#f6dcd0', 0.4);
      const spots = [[g.cx + g.eyeDX + 2, g.eyeY - 2, 16], [g.cx - 16, g.top + (g.eyeY - g.top) * 0.5, 14], [g.cx + 10, g.bottom - 14, 12], [g.cx - g.w * 0.75, g.mouthY - 8, 10]];
      let s = '';
      for (const [x, y, r0] of spots) {
        let d = '';
        for (let i = 0; i <= 10; i++) {
          const a = (i / 10) * Math.PI * 2;
          const r = r0 * rng.range(0.6, 1.2);
          d += `${i ? 'L' : 'M'}${pt(x + Math.cos(a) * r, y + Math.sin(a) * r)}`;
        }
        s += `<path d="${d}Z" fill="${c}" opacity="0.85" stroke="${c}" stroke-width="3" stroke-linejoin="round" stroke-opacity="0.5"/>`;
      }
      return { marks: s };
    },
  },
  {
    id: 'bandage', label: 'Bandage', layer: 'accFace',
    render({ g }) {
      const x = g.cx + g.eyeDX + 8, y = g.noseY + 2;
      const strip = (rot) => `<g transform="rotate(${rot} ${x} ${y})"><rect x="${x - 16}" y="${y - 5}" width="32" height="10" rx="4" fill="#ecc9a2" stroke="#b08a66" stroke-width="1.6"/>` +
        `<rect x="${x - 5}" y="${y - 4}" width="10" height="8" rx="1.5" fill="#f6e2c8"/>` +
        `<circle cx="${x - 10}" cy="${y}" r="0.9" fill="#b08a66"/><circle cx="${x + 10}" cy="${y}" r="0.9" fill="#b08a66"/></g>`;
      return { accFace: strip(35) + strip(-35) };
    },
  },
  {
    id: 'blackEye', label: 'Black eye', layer: 'marks',
    render({ g, colors, uid }) {
      const b = uid('bruise');
      const x = g.cx + g.eyeDX, y = g.eyeY + 2;
      return {
        defs: blurFilter(b, 4),
        marks: `<g filter="url(#${b})"><ellipse cx="${x}" cy="${y}" rx="26" ry="18" fill="${mix(colors.skin, '#4a1e4a', 0.6)}" opacity="0.85"/>` +
          `<ellipse cx="${x + 4}" cy="${y + 12}" rx="20" ry="8" fill="${mix(colors.skin, '#9a8a3a', 0.4)}" opacity="0.5"/></g>`,
      };
    },
  },
  // ------------------------------------------------------------ adornments
  {
    id: 'piercings', label: 'Brow & lip rings', group: 'piercing', layer: 'accFace',
    render({ g }) {
      const ring = (x, y, r) => `<circle cx="${f(x)}" cy="${f(y)}" r="${r}" fill="none" stroke="#c8ccd2" stroke-width="2.2"/><circle cx="${f(x - r * 0.5)}" cy="${f(y - r * 0.6)}" r="0.9" fill="#fff"/>`;
      return { accFace: ring(g.cx + g.eyeDX + 14, g.browY - 1, 4) + ring(g.cx + 12, g.mouthY + 7, 4.2) };
    },
  },
  {
    id: 'bindi', label: 'Bindi', group: 'forehead', layer: 'accFace',
    render({ g, colors }) {
      const y = g.browY - 4;
      return { accFace: `<circle cx="${g.cx}" cy="${y}" r="4.2" fill="#b3122e" stroke="#6e0a1c" stroke-width="1"/><circle cx="${g.cx - 1.2}" cy="${y - 1.4}" r="1.1" fill="#ff8a9a"/>` +
        `<circle cx="${g.cx}" cy="${y - 9}" r="1.6" fill="${colors.accent}"/>` };
    },
  },
  {
    id: 'choker', label: 'Choker', group: 'neck', layer: 'accNeck',
    render({ g, colors }) {
      const y = g.bottom + 22;
      const nw = g.neckW + 1;
      return { accNeck: `<path d="M${pt(g.cx - nw, y - 4)}Q${pt(g.cx, y + 6)} ${pt(g.cx + nw, y - 4)}" fill="none" stroke="#1e1a22" stroke-width="7"/>` +
        `<path d="M${pt(g.cx - nw, y - 6)}Q${pt(g.cx, y + 3)} ${pt(g.cx + nw, y - 6)}" fill="none" stroke="#5a5462" stroke-width="1.2" opacity="0.6"/>` +
        `<path d="M${pt(g.cx, y + 3)}l5,6l-5,6l-5,-6Z" fill="${colors.accent}" stroke="${darken(colors.accent, 0.5)}" stroke-width="1.2"/>` };
    },
  },
];

for (const d of defs) registerPart('accessories', { layer: 'accFace', ...d });
