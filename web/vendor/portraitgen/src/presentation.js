// Gender presentation: a trait that steers which features are likely, so faces
// read as coherent people. It multiplies the theme/archetype weights rather
// than replacing them (factors not listed are 1; '*' sets the default factor).

export const PRESENTATIONS = {
  masculine: {
    label: 'Masculine',
    weights: {
      face: { square: 1.8, angular: 1.6, long: 1.2, heart: 0.35, round: 0.9, diamond: 0.8 },
      eyes: { lashes: 0.05, large: 0.5, cat: 0.6 },
      brows: { thick: 1.6, bushy: 1.8, straight: 1.4, natural: 1.2, thin: 0.3, arched: 0.35 },
      nose: { button: 0.6, small: 0.4, wide: 1.3, hooked: 1.3, straight: 1.2 },
      mouth: { full: 0.4, pursed: 0.3 },
      hair: {
        long: 0.35, longSwept: 0.35, curlyLong: 0.3, bob: 0.12, bun: 0.3, ponytail: 0.4, braids: 0.4,
        buzz: 2, short: 1.6, receding: 2, bald: 2, sidepart: 1.4, undercut: 1.4, pompadour: 1.4,
        wavy: 0.3, pixie: 0.15, spaceBuns: 0.05, slickedBack: 1.6, manBun: 1.6,
      },
      facialHair: { none: 0.6 },
    },
    accessories: { earrings: 0.25, blush: 0.15, noseRing: 0.6 },
  },
  feminine: {
    label: 'Feminine',
    weights: {
      face: { heart: 1.8, oval: 1.5, round: 1.1, diamond: 1.1, long: 0.8, square: 0.35, angular: 0.35 },
      eyes: { lashes: 2.5, large: 1.3, narrow: 0.6 },
      brows: { bushy: 0.05, thick: 0.5, arched: 1.8, thin: 1.6, angry: 0.5 },
      nose: { wide: 0.6, hooked: 0.4, small: 1.8, button: 1.6 },
      mouth: { full: 2 },
      hair: {
        bald: 0.05, buzz: 0.15, receding: 0.02, short: 0.5, mohawk: 0.5, spiky: 0.5,
        long: 1.8, longSwept: 1.8, curlyLong: 1.6, bob: 1.8, bun: 1.6, ponytail: 1.6, braids: 1.5,
        wavy: 2, pixie: 1.6, spaceBuns: 1.6, manBun: 0.1, slickedBack: 0.4,
      },
      facialHair: { '*': 0, none: 1 },
    },
    accessories: { earrings: 2.2, blush: 2, freckles: 1.2, wrinkles: 0.8 },
  },
  androgynous: {
    label: 'Androgynous',
    weights: {
      face: { oval: 1.4, diamond: 1.3, long: 1.2 },
      eyes: { lashes: 0.6 },
      brows: { bushy: 0.3, natural: 1.4, straight: 1.3 },
      hair: { short: 1.4, bob: 1.3, sidepart: 1.3, undercut: 1.3, receding: 0.4 },
      facialHair: { '*': 0.15, none: 4, stubble: 0.4 },
    },
    accessories: {},
  },
};

export const DEFAULT_PRESENTATION_WEIGHTS = { masculine: 1, feminine: 1, androgynous: 0.25 };

/** Apply a presentation's factors to a { id: weight } map; falls back to the input if nothing survives. */
export function applyPresentation(weights, presentation, category) {
  const factors = PRESENTATIONS[presentation]?.weights?.[category];
  if (!factors) return weights;
  const def = factors['*'] ?? 1;
  const out = Object.fromEntries(Object.entries(weights).map(([id, w]) => [id, w * (factors[id] ?? def)]));
  return Object.values(out).some((w) => w > 0) ? out : weights;
}

/** Scale accessory probabilities for a presentation. */
export function presentationChances(chances, presentation) {
  const f = PRESENTATIONS[presentation]?.accessories ?? {};
  return Object.fromEntries(Object.entries(chances).map(([id, p]) => [id, Math.min(1, p * (f[id] ?? 1))]));
}
