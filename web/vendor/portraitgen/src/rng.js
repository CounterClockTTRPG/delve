// Small, fast, deterministic PRNG (mulberry32) seeded from any string/number.

export function hashSeed(seed) {
  const s = String(seed);
  let h = 1779033703 ^ s.length;
  for (let i = 0; i < s.length; i++) {
    h = Math.imul(h ^ s.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  h = Math.imul(h ^ (h >>> 16), 2246822507);
  h = Math.imul(h ^ (h >>> 13), 3266489909);
  return (h ^= h >>> 16) >>> 0;
}

export function createRng(seed, state) {
  let a = state ?? hashSeed(seed);
  const next = () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const rng = {
    next,
    range: (min, max) => min + next() * (max - min),
    int: (min, max) => Math.floor(min + next() * (max - min + 1)),
    chance: (p) => next() < p,
    pick: (arr) => arr[Math.floor(next() * arr.length)],
    /** Pick a key from a { key: weight } map. */
    weighted(map) {
      const entries = Object.entries(map).filter(([, w]) => w > 0);
      if (!entries.length) return undefined;
      const total = entries.reduce((s, [, w]) => s + w, 0);
      let r = next() * total;
      for (const [k, w] of entries) {
        if ((r -= w) <= 0) return k;
      }
      return entries[entries.length - 1][0];
    },
    /** Derive an independent child generator (keeps streams stable per category). */
    fork: (label) => createRng(`${seed}::${label}`),
    /** A copy that continues from the current state (replays the same draws). */
    snapshot: () => createRng(seed, a),
  };
  return rng;
}

export function randomSeed() {
  return Math.random().toString(36).slice(2, 10);
}
