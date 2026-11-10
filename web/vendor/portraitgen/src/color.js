// Minimal colour utilities working on #rrggbb strings.

export function hexToRgb(hex) {
  let h = hex.replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function rgbToHex([r, g, b]) {
  const c = (v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0');
  return `#${c(r)}${c(g)}${c(b)}`;
}

export function mix(a, b, t) {
  const A = hexToRgb(a);
  const B = hexToRgb(b);
  return rgbToHex(A.map((v, i) => v + (B[i] - v) * t));
}

export const darken = (c, t) => mix(c, '#000000', t);
export const lighten = (c, t) => mix(c, '#ffffff', t);

export function luminance(c) {
  const [r, g, b] = hexToRgb(c).map((v) => v / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Outline colour for a fill: a darker, slightly desaturated version. */
export const outline = (c) => mix(darken(c, 0.55), '#2a1e1a', 0.25);

/** Scale saturation around the colour's own luminance (0 = grey, 1 = unchanged). */
export function saturate(c, s) {
  const l = luminance(c) * 255;
  return rgbToHex(hexToRgb(c).map((v) => l + (v - l) * s));
}
