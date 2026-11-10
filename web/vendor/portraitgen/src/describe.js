// Plain-language requests: "a stout old male dwarf", "a beautiful young blonde
// elven woman with a flower crown". describe() turns the words it knows into
// generate() options; anything not mentioned is still rolled at random, and what
// is mentioned always wins over the random rolls.

/** Named colours for --color and descriptions. */
export const COLOR_NAMES = {
  hair: {
    blonde: '#e8d29a', blond: '#e8d29a', golden: '#d8b46a', platinum: '#ece6d8', strawberry: '#d89a6a',
    red: '#a0402a', redhead: '#a0402a', ginger: '#b0582a', auburn: '#8a3a22', copper: '#b06a3a',
    brown: '#6a4021', brunette: '#4a2e1a', chestnut: '#6a3a1e', black: '#1f1612', raven: '#141018', dark: '#2a1c14',
    grey: '#9c9c9c', gray: '#9c9c9c', silver: '#c8ccd0', white: '#ececec', snowy: '#f4f4f4',
    blue: '#4a7bd8', pink: '#e86aa8', purple: '#8a5ad0', green: '#4a9a5a', teal: '#3de0e8',
  },
  eyes: {
    blue: '#3d6fa8', green: '#4f8a4a', brown: '#5b3a1e', hazel: '#8a6d3b', grey: '#6f7d8a', gray: '#6f7d8a',
    amber: '#c99a2e', golden: '#d8b030', violet: '#8a4fbf', red: '#c0302a', black: '#1a1412',
  },
  skin: {
    pale: '#f7dccb', fair: '#f2d2bc', light: '#efc6a8', tan: '#c68b62', tanned: '#c68b62', olive: '#b08a5a',
    brown: '#8a5a38', dark: '#5e3a24', ebony: '#3e2416', green: '#6f8f5a', grey: '#9aa0a6', blue: '#7ab8d8',
    red: '#c96b5a', purple: '#8a5a9a', lavender: '#b7c6d9',
  },
};

/** Resolve a colour name (for a slot) or a hex value; undefined if unknown. */
export function resolveColor(slot, value) {
  const v = String(value).trim().toLowerCase();
  if (/^#[0-9a-f]{3}([0-9a-f]{3})?$/.test(v)) return v;
  return COLOR_NAMES[slot]?.[v];
}

// Word lists (matched as whole words, singular or plural).
const RACES = {
  dwarf: ['fantasy', 'dwarf'], dwarves: ['fantasy', 'dwarf'], dwarven: ['fantasy', 'dwarf'],
  elf: ['fantasy', 'elf'], elves: ['fantasy', 'elf'], elven: ['fantasy', 'elf'], elvish: ['fantasy', 'elf'],
  orc: ['fantasy', 'orc'], orcish: ['fantasy', 'orc'], 'half-orc': ['fantasy', 'orc'],
  tiefling: ['fantasy', 'tiefling'], tabaxi: ['fantasy', 'tabaxi'], catfolk: ['fantasy', 'tabaxi'], 'cat-folk': ['fantasy', 'tabaxi'],
  satyr: ['fantasy', 'satyr'], faun: ['fantasy', 'satyr'], lizardfolk: ['fantasy', 'lizardfolk'], lizardman: ['fantasy', 'lizardfolk'], minotaur: ['fantasy', 'minotaur'], 'bull-man': ['fantasy', 'minotaur'],
  centaur: ['fantasy', 'centaur'], human: [null, 'human'],
  android: ['scifi', 'android'], robot: ['scifi', 'android'], synth: ['scifi', 'android'], alien: ['scifi', 'alien'],
};
const THEMES = {
  fantasy: 'fantasy', medieval: 'fantasy', wizard: 'fantasy', knight: 'fantasy', ranger: 'fantasy', bard: 'fantasy', cleric: 'fantasy',
  modern: 'modern', contemporary: 'modern', 'present-day': 'modern', office: 'modern',
  scifi: 'scifi', 'sci-fi': 'scifi', space: 'scifi', cyberpunk: 'scifi', starship: 'scifi', pilot: 'scifi', futuristic: 'scifi',
};
const PRESENTATION = {
  male: 'masculine', man: 'masculine', men: 'masculine', boy: 'masculine', lad: 'masculine', gentleman: 'masculine', king: 'masculine', lord: 'masculine', prince: 'masculine', he: 'masculine', masculine: 'masculine', handsome: 'masculine',
  female: 'feminine', woman: 'feminine', women: 'feminine', girl: 'feminine', lass: 'feminine', lady: 'feminine', queen: 'feminine', princess: 'feminine', she: 'feminine', feminine: 'feminine', maiden: 'feminine',
  androgynous: 'androgynous', nonbinary: 'androgynous', 'non-binary': 'androgynous', enby: 'androgynous',
};
const AGE = {
  young: 'young', youthful: 'young', teen: 'young', teenage: 'young', youth: 'young', boy: 'young', girl: 'young', lad: 'young', lass: 'young', maiden: 'young',
  adult: 'adult', 'middle-aged': 'middle', middle: 'middle', mature: 'middle',
  old: 'elder', elderly: 'elder', aged: 'elder', ancient: 'elder', venerable: 'elder', grizzled: 'elder', elder: 'elder', wizened: 'elder', aging: 'middle',
};
const BUILD = {
  stout: 'heavy', heavy: 'heavy', fat: 'heavy', portly: 'heavy', rotund: 'heavy', plump: 'heavy', chubby: 'heavy', stocky: 'heavy',
  burly: 'muscular', brawny: 'muscular', muscular: 'muscular', strong: 'muscular', hulking: 'muscular', buff: 'muscular',
  athletic: 'athletic', fit: 'athletic', toned: 'athletic', sporty: 'athletic',
  slim: 'slender', slender: 'slender', thin: 'slender', lithe: 'slender', willowy: 'slender', skinny: 'slender', lean: 'slender', wiry: 'slender',
  curvy: 'curvy', voluptuous: 'curvy', buxom: 'curvy', average: 'average',
};
const EXPRESSION = {
  smiling: 'smile', smile: 'smile', happy: 'smile', cheerful: 'smile', friendly: 'smile', jolly: 'smile', warm: 'smile', kind: 'smile',
  stern: 'stern', grim: 'stern', angry: 'stern', serious: 'stern', fierce: 'stern', scowling: 'stern', menacing: 'stern',
  sad: 'sad', melancholy: 'sad', sorrowful: 'sad', mournful: 'sad', crying: 'sad',
  surprised: 'surprised', shocked: 'surprised', astonished: 'surprised',
  smug: 'smug', cocky: 'smug', sly: 'smug', smirking: 'smug', arrogant: 'smug', mischievous: 'smug',
  tired: 'tired', weary: 'tired', sleepy: 'tired', exhausted: 'tired',
  neutral: 'neutral', calm: 'neutral',
};
const STYLE = {
  realistic: 'realistic', photorealistic: 'realistic', illustrated: 'illustrated', cartoon: 'illustrated', pixel: 'pixel', 'pixel-art': 'pixel', '8-bit': 'pixel',
  anime: 'anime', manga: 'anime', painterly: 'painterly', painted: 'painterly', oil: 'painterly', engraving: 'engraving', engraved: 'engraving', etching: 'engraving',
  ink: 'inkwash', watercolor: 'inkwash', watercolour: 'inkwash', sketch: 'inkwash',
};
const LIGHTING = { candlelit: 'candle', candlelight: 'candle', neon: 'neon', backlit: 'rim', 'rim-lit': 'rim', studio: 'studio', dramatic: 'rembrandt' };
const FRAMING = { 'close-up': 'head', closeup: 'head', headshot: 'head', bust: 'bust', 'half-body': 'bust' };
const HAIR = {
  bald: 'bald', 'shaved-head': 'bald', braided: 'braids', braids: 'braids', 'long-haired': 'long', 'short-haired': 'short', curly: 'curly', 'curly-haired': 'curly',
  ponytail: 'ponytail', bun: 'bun', mohawk: 'mohawk', dreadlocks: 'dreadlocks', dreads: 'dreadlocks', afro: 'afro', cornrows: 'cornrows', wavy: 'wavy', pixie: 'pixie', 'slicked-back': 'slickedBack',
};
const BEARD = {
  bearded: 'fullBeard', beard: 'fullBeard', 'long-bearded': 'longBeard', 'braided-beard': 'braidedBeard', mustache: 'mustache', moustache: 'mustache', moustached: 'mustache',
  goatee: 'goatee', stubble: 'stubble', unshaven: 'stubble', 'clean-shaven': 'none', beardless: 'none',
};
// Decorations by the words people use for them.
const THINGS = {
  hood: 'hood', hooded: 'hood', crown: 'crown', crowned: 'crown', circlet: 'circlet', tiara: 'circlet', glasses: 'glassesRound', spectacles: 'glassesRound',
  sunglasses: 'sunglasses', monocle: 'monocle', eyepatch: 'eyepatch', 'eye-patch': 'eyepatch', goggles: 'goggles', visor: 'visor',
  scar: 'scarCheek', scarred: 'scarCheek', freckles: 'freckles', freckled: 'freckles', freckly: 'freckles', earrings: 'earrings', pendant: 'pendant', necklace: 'pendant',
  helmet: 'helmetNasal', helm: 'helmetNasal', 'wizard-hat': 'wizardHat', 'top-hat': 'topHat', hat: 'wideBrimHat', bandana: 'bandana', 'flower-crown': 'flowerCrown',
  horns: 'horns', halo: 'halo', tattoo: 'tattooRunes', tattooed: 'tattooRunes', 'war-paint': 'warPaint', warpaint: 'warPaint',
  quiver: 'quiver', bow: 'quiver', archer: 'quiver', sword: 'swordHilt', spear: 'spear', staff: 'staff', lute: 'lute', cat: 'shoulderCat', dragon: 'shoulderDragon', raven: 'raven',
  scarf: 'scarf', fur: 'furCollar', brooch: 'brooch', coif: 'mailCoif', chainmail: 'mailCoif', candle: 'handCandle', book: 'handBook', tankard: 'handMug', mug: 'handMug', pipe: 'pipe',
  headphones: 'headphones', headset: 'headset', mask: 'faceMask', beanie: 'beanie', piercings: 'piercings',
};
const CLOTHING = {
  armor: 'armor', armour: 'armor', armored: 'armor', robe: 'robe', robed: 'robe', cloak: 'cloak', cloaked: 'cloak', leather: 'leather', tunic: 'tunic',
  monk: 'monkRobe', priest: 'monkRobe', cleric: 'monkRobe', tabard: 'tabard', paladin: 'tabard', gambeson: 'gambeson',
  suit: 'suit', hoodie: 'hoodie', sweater: 'sweater', jacket: 'jacket', 't-shirt': 'tshirt', turtleneck: 'turtleneck', jumpsuit: 'jumpsuit',
};
/** Decorations that work against "beautiful" (injuries, paint, coverings that hide the face). */
const NOT_BEAUTIFUL = ['scarEye', 'scarCheek', 'scarNose', 'warPaint', 'blackEye', 'bandage', 'eyepatch', 'faceMask', 'acne', 'helmetNasal', 'helmetPlumed', 'helmetSpectacle', 'helmetCombat', 'mailCoif', 'goggles', 'visor', 'wrinkles'];
const BEAUTY = ['beautiful', 'pretty', 'lovely', 'gorgeous', 'attractive', 'handsome', 'stunning', 'elegant', 'fair'];
const COLOUR_TARGETS = { hair: ['hair', 'haired', 'bearded', 'maned'], eyes: ['eyes', 'eyed'], skin: ['skin', 'skinned'] };

/**
 * Parse a description into generate() options.
 * Returns { options, matched, unknown } where `matched` lists what was understood.
 */
export function describe(text) {
  const src = String(text ?? '').toLowerCase().replace(/[.,;:!?()"]/g, ' ');
  // Join hyphenated phrases people write with spaces ("middle aged", "clean shaven", "wizard hat").
  const joined = src.replace(/\b(middle|clean|long|short|curly|blue|green|brown|grey|gray|red|black|white|blonde|dark|pale|close|half|eye|war|wizard|top|flower|pixel|slicked|rim|shaved|non|braided)\s+(aged|shaven|haired|bearded|eyed|skinned|up|body|patch|paint|hat|crown|art|back|lit|head|binary|beard)\b/g, '$1-$2');
  const words = joined.split(/\s+/).filter(Boolean);
  const o = { colors: {}, include: [], avoid: [] };
  const matched = [];
  const hit = (label) => matched.push(label);
  const set = (k, v, w) => { if (v !== undefined && o[k] === undefined) { o[k] = v; hit(`${k}=${v} (${w})`); } };
  const singular = (w) => (w.endsWith('s') && !w.endsWith('ss') ? w.slice(0, -1) : w);
  for (let i = 0; i < words.length; i++) {
    const w = words[i], s = singular(w);
    const race = RACES[w] ?? RACES[s];
    if (race) { if (race[0]) set('theme', race[0], w); set('archetype', race[1], w); }
    if (THEMES[w]) set('theme', THEMES[w], w);
    set('presentation', PRESENTATION[w], w);
    set('age', AGE[w], w);
    set('build', BUILD[w], w);
    set('expression', EXPRESSION[w], w);
    set('style', STYLE[w], w);
    set('lighting', LIGHTING[w], w);
    set('framing', FRAMING[w], w);
    set('hair', HAIR[w], w);
    set('facialHair', BEARD[w], w);
    set('clothing', CLOTHING[w] ?? CLOTHING[s], w);
    const thing = THINGS[w] ?? THINGS[s];
    if (thing && !o.include.includes(thing)) { o.include.push(thing); hit(`+${thing} (${w})`); }
    // Colours: "blonde", "red-haired", "blue-eyed", "green skin", "white-bearded".
    const [base, suffix] = w.split('-');
    for (const [slot, cues] of Object.entries(COLOUR_TARGETS)) {
      const next = words[i + 1];
      const explicit = (suffix && cues.includes(suffix)) || (next && cues.includes(next.replace(/s$/, '')));
      const name = explicit ? (suffix ? base : w) : null;
      if (name && COLOR_NAMES[slot][name] && !o.colors[slot]) { o.colors[slot] = COLOR_NAMES[slot][name]; hit(`${slot} colour=${name}`); }
    }
    if (['blonde', 'blond', 'redhead', 'ginger', 'brunette', 'auburn', 'platinum'].includes(w) && !o.colors.hair) { o.colors.hair = COLOR_NAMES.hair[w]; hit(`hair colour=${w}`); }
    if (suffix === 'bearded' && BEARD[w] === undefined) set('facialHair', 'fullBeard', w);
    if (['pale', 'fair', 'tanned', 'olive', 'freckled'].includes(w) && w !== 'freckled' && !o.colors.skin) { o.colors.skin = COLOR_NAMES.skin[w]; hit(`skin colour=${w}`); }
    if (BEAUTY.includes(w)) {
      o.beautiful = true;
      hit(`beautiful (${w})`);
    }
  }
  if (o.beautiful) {
    o.avoid.push(...NOT_BEAUTIFUL.filter((id) => !o.include.includes(id)));
    if (!o.expression) set('expression', 'smile', 'beautiful');
    // Natural skin tones unless a colour was asked for (no lavender elves by surprise).
    o.naturalSkin = true;
    o.tweaks = { eyeSize: 1.06 };
  }
  // A beard implies a masculine presentation unless one was given.
  if (o.facialHair && o.facialHair !== 'none' && !o.presentation) set('presentation', 'masculine', 'beard');
  if (!Object.keys(o.colors).length) delete o.colors;
  if (!o.include.length) delete o.include;
  if (!o.avoid.length) delete o.avoid;
  delete o.beautiful;
  return { options: o, matched };
}
