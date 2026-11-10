import { registerTheme, getTheme } from './registry.js';

// Shared palettes ------------------------------------------------------------
const HUMAN_SKIN = { '#f7dccb': 2, '#efc6a8': 3, '#e0ac85': 3, '#c68b62': 2.5, '#a06a45': 2, '#7a4b30': 1.6, '#55331f': 1.2 };
const NATURAL_HAIR = { '#1f1612': 3, '#3b2516': 3, '#6a4021': 2.2, '#a0592a': 1.2, '#c99a5b': 1.2, '#e3cf9a': 1, '#8a2f1f': 0.8, '#9c9c9c': 0.8, '#ececec': 0.4 };
const NATURAL_EYES = { '#5b3a1e': 3, '#3d6fa8': 2, '#4f8a4a': 1.6, '#8a6d3b': 1.4, '#6f7d8a': 1 };

const fantasy = registerTheme({
  id: 'fantasy',
  label: 'Fantasy',
  maxAccessories: 3,
  weights: {
    face: { oval: 2, round: 1, square: 1.5, heart: 1, long: 1, diamond: 1, angular: 1 },
    ears: { round: 3, small: 1 },
    eyes: { almond: 3, round: 2, narrow: 1.5, large: 0.6, cat: 1, sleepy: 1.2, lashes: 1.5, slit: 0.2, glow: 0.1, blank: 0.1 },
    brows: { natural: 3, thin: 1, thick: 2, arched: 1.5, straight: 1, angry: 1.5, worried: 0.5, bushy: 1 },
    nose: { button: 1.5, straight: 3, wide: 2, pointed: 1.5, hooked: 1.5, small: 1, snub: 1 },
    mouth: { neutral: 3, smile: 2.5, grin: 0.8, smirk: 2, frown: 1.5, full: 1.5, pursed: 0.4, open: 0.2 },
    hair: { bald: 0.8, buzz: 0.3, short: 2, sidepart: 1, spiky: 0.3, curly: 1, afro: 0.2, receding: 0.8, bob: 0.8, long: 3, longSwept: 2, curlyLong: 1, ponytail: 1.5, bun: 1, topknot: 1, braids: 2, mohawk: 0.3, wavy: 1.5, dreadlocks: 0.4, manBun: 0.4, slickedBack: 0.3 },
    facialHair: { none: 6, stubble: 1, mustache: 0.5, handlebar: 0.3, goatee: 0.7, muttonChops: 0.3, fullBeard: 1.5, longBeard: 0.6, braidedBeard: 0.4 },
    clothing: { tunic: 3, robe: 2, armor: 2, leather: 2, cloak: 2, monkRobe: 1, tabard: 1.2, gambeson: 1.2 },
    background: { parchment: 3, forest: 2, dungeon: 2, sunburst: 0.8, archway: 1.5, ruins: 1.2, candlehall: 1, market: 1, birches: 1, mountains: 1.2 },
    frame: { ornate: 2, simple: 1, none: 2, circle: 0.4 },
  },
  accessories: {
    scarEye: 0.07, scarCheek: 0.1, scarNose: 0.05, freckles: 0.12, blush: 0.04, mole: 0.04, wrinkles: 0.1,
    warPaint: 0.06, tattooRunes: 0.06, eyepatch: 0.05, monocle: 0.02, goggles: 0.03, glassesRound: 0.03,
    earrings: 0.1, earStuds: 0.04, noseRing: 0.03, pendant: 0.15, circlet: 0.1, crown: 0.03, headband: 0.05, hood: 0.1, halo: 0.01,
    helmetNasal: 0.05, helmetPlumed: 0.025, helmetSpectacle: 0.03, wizardHat: 0.03, flowerCrown: 0.03, wideBrimHat: 0.02,
    acne: 0.03, birthmark: 0.02, vitiligo: 0.015, bandage: 0.03, blackEye: 0.03, choker: 0.02, piercings: 0.01,
    quiver: 0.05, swordHilt: 0.05, spear: 0.03, staff: 0.04, lute: 0.02, shoulderCat: 0.02, shoulderDragon: 0.015, raven: 0.015,
    scarf: 0.08, furCollar: 0.04, brooch: 0.06, mailCoif: 0.03,
    handCandle: 0.03, handBook: 0.03, handMug: 0.02, pipe: 0.03,
  },
  colors: {
    skin: HUMAN_SKIN,
    hair: { ...NATURAL_HAIR, '#e8e0cf': 0.6, '#b0382a': 0.6 },
    eyes: { ...NATURAL_EYES, '#c99a2e': 0.6, '#8a4fbf': 0.4 },
    clothing: ['#6b3e26', '#3f5e3a', '#2f4a6d', '#7a2e2e', '#5a4a6e', '#8a7a5a', '#3d3a36', '#4e6b6b'],
    accent: ['#d4af37', '#c0c0c0', '#b33a3a', '#3a7bd5', '#5fa35f', '#9b59b6'],
    background: ['#d8c08a', '#c9b07a', '#6f8a4f', '#7a746a', '#8a6a4a', '#5a6a8a'],
  },
  archetypes: {
    human: { label: 'Human', weight: 4 },
    elf: {
      label: 'Elf',
      weight: 2,
      weights: {
        ears: { pointed: 1, elven: 2 },
        face: { oval: 2, heart: 2, diamond: 1, long: 1 },
        eyes: { almond: 2, cat: 2, lashes: 1.5, glow: 0.1 },
        facialHair: { none: 1 },
        nose: { straight: 2, small: 2, pointed: 1 },
        hair: { long: 3, longSwept: 3, braids: 2, ponytail: 1.5, bun: 1, sidepart: 1, short: 0.5 },
      },
      colors: { skin: { '#f7e3d3': 3, '#e8c9ae': 2, '#c9966e': 1, '#b7c6d9': 0.6, '#9b8bb8': 0.4 }, hair: { '#ece3c8': 2, '#d8b46a': 2, '#2a1c14': 1.5, '#a7462a': 1, '#c8d3e0': 1 } },
    },
    dwarf: {
      label: 'Dwarf',
      weight: 1.5,
      weights: {
        face: { square: 2, round: 2, angular: 1 },
        nose: { wide: 2, hooked: 1.5, button: 1 },
        brows: { bushy: 3, thick: 2 },
        facialHair: { fullBeard: 2, longBeard: 2, braidedBeard: 3, none: 0.25 },
        hair: { bald: 1.5, receding: 1, braids: 1.5, long: 1, short: 1, topknot: 0.5 },
        clothing: { armor: 3, leather: 2, tunic: 1 },
      },
      colors: { hair: { '#a0592a': 2, '#6a4021': 2, '#3b2516': 2, '#8a2f1f': 2, '#9c9c9c': 1.5, '#e3cf9a': 1 } },
    },
    orc: {
      label: 'Orc',
      weight: 1.2,
      weights: {
        face: { square: 2, angular: 2, round: 1 },
        ears: { pointed: 2, round: 1 },
        nose: { flat: 2, wide: 2 },
        brows: { angry: 3, thick: 2 },
        mouth: { tusks: 4, grin: 0.5 },
        eyes: { narrow: 2, almond: 1, slit: 0.5 },
        facialHair: { none: 4, goatee: 1 },
        hair: { bald: 1.5, mohawk: 2, topknot: 1.5, braids: 1, buzz: 1 },
        clothing: { armor: 2, leather: 3 },
      },
      accessories: { scarEye: 0.25, scarCheek: 0.25, warPaint: 0.3, earrings: 0.2 },
      colors: { skin: { '#8fae74': 3, '#6f8f5a': 2, '#9a9a7a': 1, '#5e7a4a': 1 }, hair: { '#1f1612': 3, '#3b2516': 2 } },
    },
    tabaxi: {
      label: 'Tabaxi (cat folk)',
      weight: 0.6,
      weights: {
        ears: { none: 1 },
        eyes: { slit: 4, cat: 3 },
        nose: { small: 3, button: 1 },
        mouth: { neutral: 2, smirk: 2, smile: 1, fangs: 1 },
        brows: { thin: 2, none: 1 },
        facialHair: { none: 1 },
        hair: { short: 2, long: 1.5, ponytail: 1, braids: 1, curly: 1, spiky: 0.8 },
      },
      features: ['catEars', 'whiskers', 'felineMuzzle', 'felineFur'],
      accessories: { furMarkings: 0.75 },
      colors: { skin: { '#d08a3a': 2, '#c8a070': 2, '#e0c090': 1.5, '#8a7a6a': 1.5, '#6a5a4a': 1, '#e8e0d4': 0.8 }, eyes: { '#d8c040': 2, '#7ac050': 1.5, '#4ab0c8': 1 } },
    },
    satyr: {
      label: 'Satyr',
      weight: 0.5,
      weights: {
        ears: { pointed: 3 },
        hair: { curly: 3, curlyLong: 2, afro: 0.5, short: 0.5 },
        brows: { bushy: 2, arched: 1.5 },
        facialHair: { goatee: 2.5, none: 1.5, fullBeard: 0.5 },
        mouth: { smirk: 3, grin: 1.5, smile: 1 },
      },
      features: ['ramHorns'],
      accessories: { earrings: 0.3 },
      colors: { hair: { '#3b2516': 2, '#6a4021': 2, '#1f1612': 1.5, '#a0592a': 1 } },
    },
    lizardfolk: {
      label: 'Lizardfolk',
      weight: 0.5,
      weights: {
        ears: { none: 1 },
        eyes: { slit: 5, round: 1 },
        nose: { flat: 3, small: 1 },
        brows: { none: 1 },
        hair: { bald: 1 },
        facialHair: { none: 1 },
        mouth: { neutral: 2, fangs: 2, frown: 1 },
        face: { long: 2, diamond: 1.5, oval: 1 },
      },
      features: ['scales'],
      accessories: { lizardCrest: 0.8 },
      presentations: { masculine: 1, feminine: 1, androgynous: 1 },
      colors: { skin: { '#5e8a4a': 2, '#4a7a6a': 2, '#7a9a4a': 1.5, '#8a6a3a': 1, '#3a6a7a': 1 }, eyes: { '#d8b030': 3, '#e86a2a': 1 } },
    },
    minotaur: {
      label: 'Minotaur',
      // Only when asked for (an archetype or a description): a new archetype with a weight would
      // change which face every existing seed draws.
      weight: 0,
      weights: {
        ears: { bovine: 1 },
        nose: { bovine: 1 },
        eyes: { round: 2, narrow: 2, almond: 1, glow: 0.1 },
        brows: { thick: 3, angry: 2, bushy: 1 },
        mouth: { neutral: 3, frown: 2, grin: 0.5 },
        face: { long: 3, square: 2, angular: 1 },
        // A bull's head has no human hair, and no hat or hood goes over its horns.
        hair: { bald: 1 },
        facialHair: { none: 1 },
        clothing: { armor: 3, leather: 3, tunic: 1 },
      },
      features: ['bullHorns', 'felineFur'],
      accessories: {
        // Earrings hang where a human's ears are; a bull's are higher, so its ring is in its nose.
        noseRing: 0.6, earrings: 0, earStuds: 0, warPaint: 0.2, tattooRunes: 0.15, scarCheek: 0.2, scarEye: 0.1,
        freckles: 0, acne: 0, blush: 0, mole: 0, vitiligo: 0, glassesRound: 0, monocle: 0, goggles: 0,
        hood: 0, mailCoif: 0, helmetNasal: 0, helmetPlumed: 0, helmetSpectacle: 0, wizardHat: 0, wideBrimHat: 0,
        flowerCrown: 0, crown: 0, circlet: 0, headband: 0, halo: 0,
      },
      colors: {
        skin: { '#6b4226': 3, '#3a2a20': 2, '#8a5a34': 2, '#1f1a17': 1.5, '#b08a5a': 1, '#d8d0c4': 0.5 },
        hair: { '#1f1612': 2, '#3b2516': 2, '#6a4021': 1 },
        eyes: { '#2a1a10': 3, '#5b3a1e': 2, '#b03020': 0.4 },
      },
    },
    centaur: {
      label: 'Centaur',
      weight: 0.4,
      weights: {
        hair: { long: 3, braids: 2, wavy: 2, dreadlocks: 1 },
        facialHair: { fullBeard: 2, none: 2 },
        clothing: { leather: 3, tunic: 1 },
      },
      accessories: { quiver: 0.5, spear: 0.3, warPaint: 0.3, tattooRunes: 0.3 },
    },
    tiefling: {
      label: 'Tiefling',
      weight: 0.6,
      weights: {
        eyes: { glow: 1, blank: 0.5, slit: 1.5, almond: 1 },
        mouth: { smirk: 3, fangs: 1, neutral: 1 },
        ears: { pointed: 2 },
        facialHair: { none: 5, goatee: 1 },
      },
      accessories: { horns: 0.95 },
      colors: { skin: { '#c96b5a': 2, '#a04a5a': 1.5, '#8a5a9a': 1.5, '#d9a0a0': 1 }, eyes: { '#e8b030': 2, '#ff5040': 1 }, hair: { '#1f1612': 3, '#2a2240': 2, '#5a1a2a': 1 } },
    },
  },
});

const modern = registerTheme({
  id: 'modern',
  label: 'Present day',
  maxAccessories: 3,
  weights: {
    face: { oval: 2, round: 1.5, square: 1.5, heart: 1, long: 1, diamond: 1, angular: 0.6 },
    ears: { round: 3, small: 2 },
    eyes: { almond: 3, round: 2.5, narrow: 1.5, large: 1, cat: 1, sleepy: 1.5, lashes: 1.5 },
    brows: { natural: 4, thin: 1.5, thick: 2, arched: 1.5, straight: 1.5, angry: 0.6, worried: 0.8 },
    nose: { button: 2, straight: 3, wide: 2, pointed: 1, hooked: 0.8, small: 1.5, snub: 1 },
    mouth: { neutral: 3, smile: 3.5, grin: 1.5, smirk: 2, frown: 0.6, full: 1.5, pursed: 0.4, open: 0.3 },
    hair: { bald: 0.8, buzz: 1, short: 3, sidepart: 2, spiky: 0.6, curly: 1.5, afro: 0.8, pompadour: 0.8, receding: 0.8, bob: 1.5, long: 2, longSwept: 1.5, curlyLong: 1, ponytail: 1.5, bun: 1.2, braids: 0.8, mohawk: 0.2, undercut: 0.8, wavy: 1.5, pixie: 1, dreadlocks: 0.6, cornrows: 0.5, slickedBack: 0.8, manBun: 0.6, spaceBuns: 0.3 },
    facialHair: { none: 6, stubble: 2, mustache: 0.5, handlebar: 0.15, goatee: 0.8, soulPatch: 0.2, fullBeard: 1.2 },
    clothing: { tshirt: 3, hoodie: 2, suit: 1.5, sweater: 2, turtleneck: 1, jacket: 2 },
    background: { studio: 3, pastel: 2.5, solid: 1.5, urban: 1.5 },
    frame: { none: 4, circle: 1.5, simple: 1 },
  },
  accessories: {
    glassesRound: 0.1, glassesSquare: 0.14, sunglasses: 0.06, freckles: 0.12, blush: 0.06, mole: 0.05, wrinkles: 0.08,
    scarCheek: 0.02, earrings: 0.12, earStuds: 0.08, noseRing: 0.05, pendant: 0.08, beanie: 0.06, headphones: 0.06, headband: 0.02,
    acne: 0.06, birthmark: 0.02, vitiligo: 0.02, bandage: 0.02, blackEye: 0.01, piercings: 0.05, bindi: 0.02, choker: 0.03,
    faceMask: 0.02, bandana: 0.03, wideBrimHat: 0.03, topHat: 0.01, helmetCombat: 0.01, flowerCrown: 0.01,
    handBook: 0.02, handMug: 0.02, pipe: 0.01, scarf: 0.05,
  },
  colors: {
    skin: HUMAN_SKIN,
    hair: { ...NATURAL_HAIR, '#e86aa8': 0.2, '#4a7bd8': 0.15, '#8a5ad0': 0.15 },
    eyes: NATURAL_EYES,
    clothing: ['#2d3e50', '#c0392b', '#27ae60', '#f1c40f', '#ecf0f1', '#34495e', '#8e44ad', '#e67e22', '#1abc9c', '#2c2c2c', '#7f8c8d'],
    accent: ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#34495e'],
    background: ['#7fb3d5', '#f5b7b1', '#a9dfbf', '#f9e79f', '#d2b4de', '#aeb6bf', '#f0b27a'],
  },
});

const scifi = registerTheme({
  id: 'scifi',
  label: 'Sci-fi',
  maxAccessories: 3,
  weights: {
    face: { oval: 2, round: 1, square: 1.5, heart: 1, long: 1.2, diamond: 1, angular: 2 },
    ears: { round: 3, small: 2, pointed: 0.3, fin: 0.3, none: 0.3 },
    eyes: { almond: 3, round: 1.5, narrow: 2, large: 1, cat: 1, sleepy: 1, lashes: 1, glow: 0.6, blank: 0.2 },
    brows: { natural: 3, thin: 2, thick: 1, arched: 1, straight: 2, angry: 1, none: 0.6 },
    nose: { button: 1.5, straight: 3, wide: 1, pointed: 1.5, small: 2, snub: 1 },
    mouth: { neutral: 4, smile: 2, grin: 0.8, smirk: 2.5, frown: 1, full: 1.2, pursed: 0.4 },
    hair: { bald: 1.2, buzz: 1.5, short: 2, sidepart: 1.2, spiky: 1, curly: 0.6, afro: 0.3, bob: 1.5, long: 1, longSwept: 1, ponytail: 1.5, bun: 0.6, topknot: 0.5, braids: 0.4, mohawk: 1, undercut: 2.5, pixie: 1, slickedBack: 1, spaceBuns: 0.6, cornrows: 0.4 },
    facialHair: { none: 8, stubble: 1.5, goatee: 0.5, soulPatch: 0.2, fullBeard: 0.4 },
    clothing: { jumpsuit: 3, exosuit: 2, highCollar: 2.5 },
    background: { grid: 3, nebula: 2.5, hex: 2 },
    frame: { brackets: 3, none: 2, circle: 0.6 },
  },
  accessories: {
    visor: 0.08, cyberEye: 0.08, glassesSquare: 0.03, tattooCircuit: 0.12, cyberImplant: 0.12, scarCheek: 0.06, scarEye: 0.04,
    freckles: 0.06, earStuds: 0.1, headset: 0.15, pendant: 0.03, noseRing: 0.03,
    helmetSpace: 0.05, helmetCombat: 0.04, faceMask: 0.03, piercings: 0.05, acne: 0.03, bandage: 0.03, vitiligo: 0.015, birthmark: 0.015,
  },
  colors: {
    skin: { ...HUMAN_SKIN, '#a8c8e8': 0.3, '#c8b8e0': 0.2 },
    hair: { ...NATURAL_HAIR, '#3de0e8': 0.6, '#e83de0': 0.5, '#f4f4ff': 0.5, '#6a7dff': 0.3 },
    eyes: { ...NATURAL_EYES, '#3de0e8': 0.6, '#c0c8d0': 0.5 },
    clothing: ['#2a3140', '#3a4a5c', '#e8ecf0', '#5a2a3a', '#1c2a24', '#4a4f58', '#c84a2a'],
    accent: ['#3de0e8', '#ff3d7f', '#7dff6a', '#ffb43d', '#9d6aff', '#ff5040'],
    background: ['#1a2a5a', '#3a1a5a', '#0a3a4a', '#2a2a3a', '#4a1a2a'],
  },
  archetypes: {
    human: { label: 'Human', weight: 4 },
    android: {
      label: 'Android',
      weight: 1.2,
      weights: {
        eyes: { glow: 3, almond: 1, round: 1 },
        hair: { bald: 3, bob: 1, short: 1, undercut: 1 },
        facialHair: { none: 1 },
        brows: { none: 2, thin: 1 },
        mouth: { neutral: 4, smirk: 1 },
      },
      accessories: { cyberImplant: 0.5, tattooCircuit: 0.5, cyberEye: 0.15 },
      colors: { skin: { '#d8dde4': 2, '#b8c4d0': 2, '#e8e8f0': 1, '#9aa8b8': 1 } },
    },
    alien: {
      label: 'Alien',
      weight: 1,
      weights: {
        ears: { fin: 2, none: 2, pointed: 1 },
        eyes: { large: 3, blank: 1, glow: 1, slit: 1.5 },
        nose: { small: 3, flat: 1, button: 1 },
        hair: { bald: 4, mohawk: 1, long: 0.5, topknot: 0.5 },
        facialHair: { none: 1 },
        brows: { none: 3, thin: 1 },
        face: { heart: 2, diamond: 2, long: 1 },
      },
      accessories: { antennae: 0.3, tattooCircuit: 0.2 },
      colors: { skin: { '#7ab8d8': 2, '#8ad8a8': 2, '#b88ad8': 2, '#d88a8a': 1, '#5a8a9a': 1 } },
    },
  },
});

// Realistic style overrides ---------------------------------------------------
// When a portrait uses the realistic style, these weights/colours replace the
// theme's own: muted, natural palettes and photographic backdrops.
function realistic(base, overrides) {
  return registerTheme({ ...base, styles: { ...base.styles, realistic: overrides } });
}

realistic(fantasy, {
  weights: {
    eyes: { almond: 3, round: 2, narrow: 1.5, large: 0.4, cat: 1, sleepy: 1.2, lashes: 1.5 },
    background: { canvas: 3, hearth: 2.5, forest: 1.5, dungeon: 1.2, parchment: 0.4, archway: 1.5, ruins: 1.2, candlehall: 1.5, market: 1, birches: 1, mountains: 1.2 },
    frame: { none: 4, simple: 1, ornate: 1 },
  },
  colors: {
    clothing: ['#5a4632', '#4a5a3a', '#3a4a5e', '#6a3030', '#4e4258', '#7a6a4e', '#38342f', '#5a5248'],
    background: ['#6a5e4e', '#4e5a4a', '#5a5048', '#46505e', '#7a6a52'],
  },
});

realistic(modern, {
  weights: {
    background: { canvas: 3, studio: 2.5, urban: 2, solid: 0.4 },
    frame: { none: 5, circle: 1 },
  },
  colors: {
    hair: NATURAL_HAIR,
    clothing: ['#2d3a48', '#7a2e2a', '#3e5a44', '#c9b38a', '#e8e4dc', '#3a3a3e', '#5a4a6a', '#8a5a3a', '#486870', '#222224', '#6a6e72'],
    background: ['#5e6a72', '#8a7e70', '#4a5560', '#6e6258', '#a09a90', '#3e4a52'],
  },
});

realistic(scifi, {
  weights: {
    // Blank and glowing eyes stay with androids and aliens (their archetypes set their own eyes).
    eyes: { almond: 3, round: 1.5, narrow: 2, large: 0.6, cat: 1, sleepy: 1, lashes: 1, glow: 0.1 },
    background: { corridor: 3, nebula: 1.5, grid: 0.8, hex: 0.8, canvas: 1 },
    frame: { none: 3, brackets: 2 },
  },
  colors: {
    hair: { ...NATURAL_HAIR, '#3de0e8': 0.3, '#f4f4ff': 0.4 },
    clothing: ['#2a3140', '#3a4a5c', '#d8dce0', '#4a2a32', '#1c2a24', '#4a4f58', '#8a3a22'],
    background: ['#1a2a4a', '#2a2a3a', '#0a2a3a', '#3a2a3a'],
  },
});

// Engraving: light, plain backdrops and book-plate frames suit the line work.
for (const base of [fantasy, modern, scifi]) {
  const t = getTheme(base.id);
  registerTheme({
    ...t,
    styles: {
      ...t.styles,
      engraving: {
        ...t.styles?.realistic,
        weights: { ...t.styles?.realistic?.weights, background: { studio: 2, canvas: 2, solid: 1 }, frame: { circle: 2, ornate: 1.5, simple: 1.5, none: 1 } },
        colors: { ...t.styles?.realistic?.colors, background: ['#d8d0c0', '#c8c0b0', '#e0d8c8', '#bab2a2'] },
      },
    },
  });
}

// Ink & wash: warm, simple backdrops that read as a pale wash behind the figure.
for (const base of [fantasy, modern, scifi]) {
  const t = getTheme(base.id);
  registerTheme({
    ...t,
    styles: {
      ...t.styles,
      inkwash: {
        ...t.styles?.realistic,
        weights: { ...t.styles?.realistic?.weights, background: { parchment: 2, forest: 1.5, dungeon: 1.5, hearth: 1, canvas: 1, archway: 2, ruins: 1.5, candlehall: 1, market: 1.2, birches: 1.2, mountains: 1.5 }, frame: { none: 4, simple: 1 } },
        colors: { ...t.styles?.realistic?.colors, background: ['#c9b07a', '#a89a78', '#8a9a7a', '#b8a080', '#9aa0a8'] },
      },
    },
  });
}
