// WCAG contrast, for the looks' tests: is text readable on its real background?

export type Rgb = [number, number, number];

/** The brightest pixel (by luminance) of each texture in ./textures/. */
export const TEXTURE_MAX: Record<"wood" | "rock", Rgb> = { wood: [93, 80, 72], rock: [176, 173, 166] };

function rgb(hex: string): Rgb {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
  if (!/^[0-9a-f]{6}$/i.test(full)) throw new Error(`not a hex colour: ${hex}`);
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16)) as Rgb;
}

function hex([r, g, b]: Rgb): string {
  return "#" + [r, g, b].map((c) => Math.round(c).toString(16).padStart(2, "0")).join("");
}

function luminance(colour: string): number {
  const [r, g, b] = rgb(colour).map((c) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** The WCAG contrast ratio of two hex colours, from 1 to 21. */
export function ratio(fg: string, bg: string): number {
  const [a, b] = [luminance(fg), luminance(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}

/** The colour of `wash` laid at `alpha` over the pixel `below`, as hex. */
export function over(wash: string, alpha: number, below: Rgb): string {
  const top = rgb(wash);
  return hex(top.map((c, i) => c * alpha + below[i] * (1 - alpha)) as Rgb);
}
