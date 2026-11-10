// Age: young / adult / middle-aged / elder. Each maps to a continuous value 0..1
// (which a fine-tune can override) that greys the hair, adds wrinkles, folds and
// jowls, and nudges hairstyles and beards.
import { pt, blurFilter } from './geometry.js';
import { darken, lighten, mix, luminance } from './color.js';

export const AGES = {
  young: { label: 'Young adult', value: 0.12 },
  adult: { label: 'Adult', value: 0.35 },
  middle: { label: 'Middle-aged', value: 0.62 },
  elder: { label: 'Elder', value: 0.9 },
};
export const AGE_WEIGHTS = { young: 2, adult: 3, middle: 2, elder: 1.2 };

/** Feature likelihoods by age (factors, like presentation's). */
const AGE_FACTORS = {
  young: { hair: { receding: 0.2, bald: 0.4 }, facialHair: { longBeard: 0.3 } },
  middle: { hair: { receding: 1.8, bald: 1.4 }, facialHair: { fullBeard: 1.2 } },
  elder: { hair: { receding: 2.6, bald: 2, buzz: 1.3, mohawk: 0.2, spiky: 0.3 }, facialHair: { longBeard: 2.5, fullBeard: 1.4 } },
};

export function applyAge(weights, age, category) {
  const f = AGE_FACTORS[age]?.[category];
  if (!f) return weights;
  const out = Object.fromEntries(Object.entries(weights).map(([id, w]) => [id, w * (f[id] ?? 1)]));
  return Object.values(out).some((w) => w > 0) ? out : weights;
}

/** Continuous age 0..1 for a portrait (a fine-tune overrides the age group). */
export const ageValue = (traits) => traits.tweaks?.age ?? AGES[traits.age]?.value ?? AGES.adult.value;

/** Greying hair: from about middle age, mixing towards silver and then white. */
export function agedHair(hair, a) {
  const grey = Math.max(0, (a - 0.45) / 0.55);
  if (!grey) return hair;
  return mix(hair, luminance(hair) > 0.6 ? '#e8e6e2' : '#b8b6b2', Math.min(0.85, grey * 0.9));
}

/**
 * Lines and folds of age, drawn on the face ('marks' layer) and neck ('shade').
 * `soft` renders them blurred for the realistic-based styles.
 */
export function ageModelling({ g, colors, uid, rng }, a, soft) {
  const k = Math.max(0, (a - 0.4) / 0.6); // nothing before ~40
  if (!k) return { defs: '', marks: '', shade: '' };
  const { cx, eyeY, eyeDX, browY, noseY, mouthY, bottom, jawW, top } = g;
  const sh = mix(darken(colors.skin, 0.4), '#4a1e14', 0.15);
  const hi = lighten(colors.skin, 0.25);
  const w0 = soft ? 1.6 : 1.4;
  const line = (d, o, w = w0, c = sh) => `<path d="${d}" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" opacity="${+o.toFixed(2)}"/>`;
  let m = '';
  // Forehead lines.
  const fy = browY - 18;
  for (let i = 0; i < 1 + Math.round(k * 2.4); i++) {
    const y = fy - i * 8, half = 22 + i * 4;
    m += line(`M${pt(cx - half, y + 2)}Q${pt(cx, y - 3 + rng.range(-1, 1))} ${pt(cx + half, y + 2)}`, 0.28 + k * 0.25);
  }
  // Crow's feet and under-eye bags.
  const side = (s) => {
    const ox = cx + s * (eyeDX + 24);
    let d = '';
    for (let i = -1; i <= 1; i++) d += `M${pt(ox, eyeY + i * 4)}l${s * (6 + k * 4)},${i * 3}`;
    return line(d, 0.25 + k * 0.3) +
      line(`M${pt(cx + s * (eyeDX - 14), eyeY + 14)}Q${pt(cx + s * eyeDX, eyeY + 20 + k * 3)} ${pt(cx + s * (eyeDX + 16), eyeY + 12)}`, 0.2 + k * 0.3) +
      (soft ? line(`M${pt(cx + s * (eyeDX - 12), eyeY + 17)}Q${pt(cx + s * eyeDX, eyeY + 23 + k * 3)} ${pt(cx + s * (eyeDX + 14), eyeY + 15)}`, 0.18, 3, hi) : '');
  };
  m += side(1) + side(-1);
  // Deeper nasolabial folds, marionette lines and jowls.
  for (const s of [1, -1]) {
    m += line(`M${pt(cx + s * 20, noseY + 4)}Q${pt(cx + s * 33, mouthY - 6)} ${pt(cx + s * 31, mouthY + 10)}`, 0.25 + k * 0.35, w0 + 0.6);
    if (k > 0.45) m += line(`M${pt(cx + s * 26, mouthY + 10)}Q${pt(cx + s * 28, mouthY + 22)} ${pt(cx + s * 24, bottom - 10)}`, (k - 0.45) * 0.8);
    if (k > 0.55) m += line(`M${pt(cx + s * (jawW - 12), g.jawY - 8)}Q${pt(cx + s * (jawW - 4), g.jawY + 8)} ${pt(cx + s * (jawW - 18), g.jawY + 16)}`, (k - 0.55) * 0.9, w0 + 1.4);
  }
  // A few age spots (realistic only).
  if (soft && k > 0.6) {
    for (let i = 0; i < 4; i++) m += `<circle cx="${(cx + rng.range(-g.w * 0.7, g.w * 0.7)).toFixed(1)}" cy="${(top + rng.range(20, 60)).toFixed(1)}" r="${rng.range(1.5, 3).toFixed(1)}" fill="${darken(colors.skin, 0.25)}" opacity="0.35"/>`;
  }
  // Neck: horizontal lines and a softer jaw-neck angle.
  const shade = line(`M${pt(cx - g.neckW * 0.6, bottom + 30)}Q${pt(cx, bottom + 36)} ${pt(cx + g.neckW * 0.6, bottom + 30)}`, 0.2 + k * 0.3) +
    (k > 0.5 ? line(`M${pt(cx - g.neckW * 0.5, bottom + 46)}Q${pt(cx, bottom + 52)} ${pt(cx + g.neckW * 0.5, bottom + 46)}`, (k - 0.5) * 0.6) : '');
  if (!soft) return { defs: '', marks: m, shade };
  const id = uid('age');
  return { defs: blurFilter(id, 0.9), marks: `<g filter="url(#${id})">${m}</g>`, shade: `<g filter="url(#${id})">${shade}</g>` };
}

