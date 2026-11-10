import { registerPart } from '../registry.js';
import { mirrored, pt, blurFilter } from '../geometry.js';
import { darken, lighten, outline, mix } from '../color.js';

// Eye shape parameters: half-width, upper/lower opening, outer-corner lift, iris radius.
export const eyeTypes = {
  almond: { label: 'Almond', ew: 16, top: 9, bot: 6, lift: 1, r: 7 },
  round: { label: 'Round', ew: 14, top: 11, bot: 10, lift: 0, r: 7.5 },
  narrow: { label: 'Narrow', ew: 16, top: 5, bot: 3.5, lift: 1, r: 6.5 },
  large: { label: 'Large', ew: 18, top: 13, bot: 11, lift: 1, r: 9.5 },
  cat: { label: 'Upturned', ew: 17, top: 8, bot: 6, lift: 6, r: 7 },
  sleepy: { label: 'Hooded', ew: 16, top: 8, bot: 6, lift: 0, r: 7, hooded: true },
  lashes: { label: 'Lashes', ew: 16, top: 10, bot: 7, lift: 3, r: 7.5, lashes: true },
  slit: { label: 'Slit pupil', ew: 16, top: 9, bot: 7, lift: 3, r: 8, slit: true },
  glow: { label: 'Glowing', ew: 16, top: 8, bot: 6, lift: 2, r: 0, glow: true },
  blank: { label: 'Blank (white)', ew: 16, top: 9, bot: 6, lift: 1, r: 0, blank: true },
};

export function scleraPath(e) {
  const { ew, top, bot, lift } = e;
  return `M${pt(-ew, 0)}C${pt(-ew * 0.5, -top * 1.33)} ${pt(ew * 0.45, -top * 1.33 - lift)} ${pt(ew, -lift)}` +
    `C${pt(ew * 0.5, bot * 1.33 - lift * 0.5)} ${pt(-ew * 0.5, bot * 1.33)} ${pt(-ew, 0)}Z`;
}

/**
 * Upper lid edge, inner corner -> outer corner. `lid` closes it: 0 is the open eye,
 * 1 lies just past the lower lid, so a closed eye leaves no sliver of white.
 */
export function lidEdge(e, lid = 0) {
  const { ew, top, bot, lift } = e;
  const cy = -top * 1.33 + (bot * 1.33 + 0.5 + top * 1.33) * lid;
  return `M${pt(-ew - 1, 0.5)}C${pt(-ew * 0.5, cy)} ${pt(ew * 0.45, cy - lift * (1 - lid))} ${pt(ew + 1.5, -lift - 0.5)}`;
}

/** An eye shape in an emote's pose ({ top, bot, pupil } scale the opening and the pupil; gx, gy gaze). */
export function posedEye(e, pose) {
  if (!pose) return e;
  return { ...e, top: e.top * (pose.top ?? 1), bot: e.bot * (pose.bot ?? 1), pupil: pose.pupil ?? 1, gx: pose.gx ?? 0, gy: pose.gy ?? 0 };
}

/** How far the iris moves for the eye's gaze, in the eye's own units: [dx, dy]. */
export const gazeShift = (e, k = 1) => [(e.gx ?? 0) * Math.max(2, e.ew - (e.r || e.ew * 0.45)) * 0.85 * k, (e.gy ?? 0) * e.top * 0.45 * k];

/** Markup moved by (dx, dy), untouched when there is no move. */
export const shifted = (markup, dx, dy) => (dx || dy ? `<g transform="translate(${pt(dx, dy)})">${markup}</g>` : markup);

/** Skin above the lid edge, drawn clipped to the eye opening. */
export const lidCover = (e, lid) => `${lidEdge(e, lid)}L${pt(e.ew + 4, -e.top * 2 - e.lift - 6)}L${pt(-e.ew - 4, -e.top * 2 - 6)}Z`;

/** The lower half of the eye outline, for an eye that is partly closed. */
export const lowerRim = (e) => `M${pt(e.ew, -e.lift)}C${pt(e.ew * 0.5, e.bot * 1.33 - e.lift * 0.5)} ${pt(-e.ew * 0.5, e.bot * 1.33)} ${pt(-e.ew, 0)}`;

for (const [id, e0] of Object.entries(eyeTypes)) {
  registerPart('eyes', {
    id,
    label: e0.label,
    render({ g, colors, uid, pose }) {
      const e = posedEye(e0, pose?.eyes);
      const lid = pose?.eyes?.lid ?? 0;
      const skin = colors.skin;
      const iris = colors.eyes;
      const line = darken(outline(skin), 0.3);
      const clip = uid('eyeClip');
      const glowF = uid('eyeGlow');
      const sclera = scleraPath(e);
      const ex = g.cx + g.eyeDX;
      const ey = g.eyeY;
      let defs = `<clipPath id="${clip}"><path d="${sclera}"/></clipPath>`;
      // Gaze: the iris shifts inside the opening (dx is mirrored for the left eye below).
      const [gdx, gdy] = gazeShift(e);
      let inner;
      if (e.glow || e.blank) {
        const c = e.blank ? '#f4f8ff' : lighten(iris, 0.35);
        defs += `${blurFilter(glowF, 3)}`;
        inner = () => `<path d="${sclera}" fill="${e.blank ? '#bcd4ff' : iris}" filter="url(#${glowF})" opacity="${+(0.9 * (1 - lid)).toFixed(2)}" transform="scale(1.35)"/>` +
          `<path d="${sclera}" fill="${c}"/>`;
      } else {
        const iy = 1;
        const pupil = e.slit
          ? `<ellipse cx="0" cy="${iy}" rx="1.8" ry="${e.r * 0.9}" fill="#120c0a"/>`
          : `<circle cx="0" cy="${iy}" r="${e.r * 0.45 * (e.pupil ?? 1)}" fill="#120c0a"/>`;
        const scleraFill = e.slit ? mix('#fff6d8', iris, 0.15) : '#fbf8f4';
        const irisMarkup = `<circle cx="0" cy="${iy}" r="${e.r}" fill="${iris}" stroke="${darken(iris, 0.45)}" stroke-width="1.5"/>` +
          `<circle cx="0" cy="${iy}" r="${e.r * 0.62}" fill="${lighten(iris, 0.18)}" opacity="0.45"/>${pupil}`;
        inner = (dx) => `<path d="${sclera}" fill="${scleraFill}"/>` +
          `<g clip-path="url(#${clip})">${shifted(irisMarkup, dx, gdy)}` +
          `<path d="M${pt(-e.ew, -e.top * 0.4)}Q0,${-e.top * 1.6} ${pt(e.ew, -e.top * 0.4)}" fill="none" stroke="#000" stroke-width="4" opacity="0.12"/></g>`;
      }
      // Blinking: skin covers the eye down to the lid edge.
      const cover = lid > 0 ? `<g clip-path="url(#${clip})"><path d="${lidCover(e, lid)}" fill="${darken(skin, 0.05)}"/></g>` : '';
      const upper = lidEdge(e, lid);
      let lids = `<path d="${upper}" fill="none" stroke="${line}" stroke-width="3.4" stroke-linecap="round"/>`;
      lids += `<path d="${lid > 0 ? lowerRim(e) : sclera}" fill="none" stroke="${line}" stroke-width="1.2" opacity="0.6"/>`;
      if (e.hooded && !lid) {
        lids = `<path d="${upper}L${pt(e.ew + 1, -e.lift + 2)}Q0,${-e.top * 0.25} ${pt(-e.ew - 1, 2)}Z" fill="${darken(skin, 0.05)}" stroke="${line}" stroke-width="2.6" stroke-linejoin="round"/>`;
      }
      if (e.lashes && !lid) {
        lids += `<path d="M${pt(e.ew * 0.55, -e.top - 1.5)}l3,-5M${pt(e.ew * 0.85, -e.top * 0.55 - e.lift)}l5,-4M${pt(e.ew + 1, -e.lift - 0.5)}l6,-2" stroke="${line}" stroke-width="2.2" stroke-linecap="round"/>`;
      }
      // Crease above the eye.
      const crease = `<path d="M${pt(-e.ew * 0.7, -e.top - 5)}Q${pt(0, -e.top * 1.5 - 7)} ${pt(e.ew * 0.85, -e.top - e.lift - 3)}" fill="none" stroke="${darken(skin, 0.25)}" stroke-width="1.6" stroke-linecap="round" opacity="0.55"/>`;
      const es = g.eyeScale ?? 1;
      const one = (dx) => `<g transform="translate(${pt(ex, ey)}) scale(${es})">${inner(dx)}${cover}${crease}${lids}</g>`;
      // Specular highlights are not mirrored so both eyes share a light source; they follow the gaze.
      const hl = e.glow || e.blank || lid >= 0.5 ? '' :
        [ex, g.cx * 2 - ex].map((x) => `<circle cx="${x + (gdx - e.r * 0.35) * es}" cy="${ey + (gdy - e.r * 0.3) * es}" r="${Math.max(1.6, e.r * 0.26 * es)}" fill="#fff" opacity="0.9"/>`).join('');
      return { defs, eyes: one(gdx) + mirrored(g.cx, one(-gdx)) + hl };
    },
  });
}

// ---------------------------------------------------------------- eyebrows
// Each brow: centre-line from inner (near nose) to outer end, plus stroke width.
export const browTypes = {
  natural: { label: 'Natural', d: 'M-14,2Q2,-6 18,-1', w: 5 },
  thin: { label: 'Thin', d: 'M-13,1Q2,-6 18,0', w: 3 },
  thick: { label: 'Thick', d: 'M-15,3Q0,-6 18,0', w: 8 },
  arched: { label: 'Arched', d: 'M-14,3Q4,-12 19,2', w: 5 },
  straight: { label: 'Straight', d: 'M-15,0L18,-2', w: 6 },
  angry: { label: 'Stern', d: 'M-15,6Q2,0 18,-4', w: 6 },
  worried: { label: 'Raised', d: 'M-14,-5Q2,-6 18,2', w: 5 },
  bushy: { label: 'Bushy', d: 'M-15,3Q0,-7 19,0', w: 9, bushy: true },
  none: { label: 'None', d: null },
};

for (const [id, b] of Object.entries(browTypes)) {
  registerPart('brows', {
    id,
    label: b.label,
    render({ g, colors }) {
      if (!b.d) return {};
      const c = darken(colors.hair, 0.15);
      const x = g.cx + g.eyeDX - 2;
      let s = `<path d="${b.d}" fill="none" stroke="${c}" stroke-width="${b.w}" stroke-linecap="round"/>`;
      if (b.bushy) {
        s += `<path d="M-12,-1l-3,-5M-4,-4l-2,-6M5,-5l1,-6M13,-3l3,-5" stroke="${c}" stroke-width="3" stroke-linecap="round"/>`;
      }
      const one = `<g transform="translate(${pt(x, g.browY)})">${s}</g>`;
      return { brows: one + mirrored(g.cx, one) };
    },
  });
}
