import {
  generate, render, catalog, themes, randomSeed, CATEGORIES, COLOR_SLOTS, STYLES, RENDER_STYLES,
  PRESENTATIONS, BUILDS, AGES, EXPRESSIONS, EMOTES, LIGHTS, FRAMINGS, getPart, describe,
} from '../src/index.js';
import { toPNGBlob, download } from '../src/png-browser.js';

const $ = (id) => document.getElementById(id);
const LABELS = {
  face: 'Face', ears: 'Ears', eyes: 'Eyes', brows: 'Eyebrows', nose: 'Nose', mouth: 'Mouth', hair: 'Hair',
  facialHair: 'Facial hair', clothing: 'Clothing', background: 'Backdrop', frame: 'Frame',
};
const COLOR_LABELS = { skin: 'Skin', hair: 'Hair', eyes: 'Eyes', clothing: 'Clothing', accent: 'Accent', background: 'Backdrop' };
const GROUP_LABELS = { eyewear: 'Eyewear (one)', head: 'Headwear (one)', earwear: 'Ears (one)', neck: 'Neck', horns: 'Horns / antennae', halo: 'Halo', mask: 'Face covering', piercing: 'Piercings', forehead: 'Forehead', gear: 'Gear (one)', companion: 'Companion (one)', neckwrap: 'Scarf / collar (one)', brooch: 'Brooch', held: 'Held / props (one)', marks: 'Skin marks', other: 'Other' };

/** Character traits shown as "Any (rolled value)" menus; picking a value pins it. */
const TRAIT_MENUS = [
  ['presentation', 'Presentation', PRESENTATIONS],
  ['build', 'Build', BUILDS],
  ['age', 'Age', AGES],
  ['expression', 'Expression', EXPRESSIONS],
  ['lighting', 'Lighting', LIGHTS],
  ['framing', 'Framing', FRAMINGS],
];

/** Fine-tune sliders. `auto` = no default value: the slider shows the portrait's own value. */
const TWEAKS = [
  { k: 'eyeSize', label: 'Eye size', min: 0.7, max: 1.4, step: 0.01, def: 1 },
  { k: 'jaw', label: 'Jaw width', min: 0.8, max: 1.2, step: 0.01, def: 1 },
  { k: 'hairLength', label: 'Hair length', min: 0.2, max: 1, step: 0.01, def: 1 },
  { k: 'saturation', label: 'Saturation', min: 0, max: 1.5, step: 0.01, def: 1 },
  { k: 'age', label: 'Age', min: 0, max: 1, step: 0.01, auto: (t) => AGES[t.age]?.value ?? 0.35 },
  { k: 'turn', label: 'Head turn', min: -1, max: 1, step: 0.01, auto: (t) => t.turn ?? 0 },
];

/** Feature shortcuts: the key rerolls that feature; Shift+key toggles its lock. */
const FEATURE_KEYS = { f: 'face', e: 'eyes', b: 'brows', n: 'nose', m: 'mouth', h: 'hair', j: 'facialHair', c: 'clothing', g: 'background' };
const TRAIT_KEYS = { a: 'age', x: 'expression', l: 'lighting' };

const state = {
  traits: null,
  locks: { parts: new Set(), colors: new Set(), accessories: false },
  pins: {},          // trait menu -> pinned value
  past: [], future: [], current: null, // undo / redo
  recent: [],        // recent portraits, newest first
  emote: { idle: new Set(), play: null }, // previewed emotes: idle ones (blinking) toggle, plus at most one other
};

/** Emote ids for the preview and the SVG export. */
const activeEmotes = () => [...state.emote.idle, ...(state.emote.play ? [state.emote.play] : [])];
/** Render options for the preview and the SVG export: transparency, emotes and the line to lip-sync. */
const viewOptions = () => ({ transparent: $('transparent').checked, emotes: activeEmotes(), say: $('say').value.trim() || undefined });
const showPreview = () => {
  $('preview').innerHTML = render(state.traits, { idPrefix: 'main', ...viewOptions() });
};

function buildEmotes() {
  const box = $('emotes');
  box.textContent = '';
  const all = Object.entries(EMOTES);
  for (const [title, list] of [['Idle', all.filter(([, e]) => e.idle)], ['Play', all.filter(([, e]) => !e.idle)]]) {
    const row = document.createElement('div');
    row.className = 'emote-group';
    const h = document.createElement('h3');
    h.textContent = title;
    const chips = document.createElement('div');
    chips.className = 'chips';
    chips.setAttribute('role', 'group');
    chips.setAttribute('aria-label', `${title} emotes`);
    for (const [id, e] of list) {
      const idle = !!e.idle;
      const on = idle ? state.emote.idle.has(id) : state.emote.play === id;
      const b = document.createElement('button');
      b.className = `chip${idle ? ' idle' : ''}`;
      b.textContent = e.label;
      b.setAttribute('aria-pressed', String(on));
      b.title = idle ? 'Toggle; carries on during other emotes' : e.visemes ? 'Play in a loop (lip-syncs the Say line); click again to stop' : 'Play in a loop; click again to stop';
      b.onclick = () => {
        if (idle) state.emote.idle[on ? 'delete' : 'add'](id);
        else state.emote.play = on ? null : id;
        buildEmotes();
        showPreview();
      };
      chips.append(b);
    }
    row.append(h, chips);
    box.append(row);
  }
}
const thumbs = new Map(); // traits JSON -> thumbnail SVG

// ------------------------------------------------------------------ generation
function lockedOptions() {
  const t = state.traits;
  const opts = { theme: $('theme').value, archetype: $('archetype').value || undefined, style: $('style').value, colors: {} };
  for (const [k] of TRAIT_MENUS) if (state.pins[k]) opts[k] = state.pins[k];
  // A description is a standing request: randomizing keeps to it.
  const text = $('describe').value.trim();
  if (text) opts.describe = text;
  if (!t) return opts;
  for (const c of state.locks.parts) opts[c] = t[c];
  for (const s of state.locks.colors) opts.colors[s] = t.colors[s];
  if (state.locks.accessories) opts.accessories = [...t.accessories];
  if (t.tweaks) opts.tweaks = { ...t.tweaks }; // fine-tunes are preferences: they carry over
  return opts;
}

function regenerate(seed = $('seed').value || randomSeed()) {
  state.traits = generate({ ...lockedOptions(), seed });
  refresh();
}

/** Reroll one feature (or trait), keeping everything else exactly as it is. */
function rerollOne(key) {
  const t = state.traits;
  const keep = { theme: t.theme, archetype: t.archetype, style: t.style, colors: { ...t.colors }, accessories: [...t.accessories], tweaks: t.tweaks };
  for (const [k] of TRAIT_MENUS) keep[k] = t[k];
  keep.turn = t.turn;
  for (const c of CATEGORIES) keep[c] = t[c];
  if (key === 'accessories') delete keep.accessories;
  else delete keep[key];
  const fresh = generate({ ...keep, seed: randomSeed() });
  state.traits = { ...t, [key]: fresh[key] };
  refresh();
}

function setTraits(traits) {
  state.traits = traits;
  if ($('theme').value !== traits.theme) {
    $('theme').value = traits.theme;
    fillArchetypes();
  }
  refresh();
}

// ------------------------------------------------------------------ undo / redo / recent
const keyOf = (t) => JSON.stringify(t);
function record() {
  const k = keyOf(state.traits);
  if (k === state.current) return;
  if (state.current) state.past.push(state.current);
  if (state.past.length > 100) state.past.shift();
  state.future = [];
  state.current = k;
  // Recent strip: newest first, distinct, capped.
  state.recent = [k, ...state.recent.filter((x) => x !== k)].slice(0, 12);
}
function undo() {
  if (!state.past.length) return status('Nothing to undo.');
  state.future.push(state.current);
  state.current = state.past.pop();
  setTraits(JSON.parse(state.current));
}
function redo() {
  if (!state.future.length) return status('Nothing to redo.');
  state.past.push(state.current);
  state.current = state.future.pop();
  setTraits(JSON.parse(state.current));
}

// ------------------------------------------------------------------ rendering
function refresh() {
  const t = state.traits;
  record();
  $('seed').value = t.seed;
  // "Any" keeps rolling and shows what was rolled; only an explicit pick pins.
  const arch = catalog(t.theme).archetypes.find((x) => x.id === t.archetype);
  if ($('archetype').options.length) $('archetype').options[0].text = arch ? `Any (${arch.label})` : 'Any';
  $('style').value = t.style ?? 'illustrated';
  showPreview();
  buildCharacter();
  buildTweaks();
  buildParts();
  buildColors();
  buildAccessories();
  renderVariations();
  renderRecent();
  $('undo').disabled = !state.past.length;
  $('redo').disabled = !state.future.length;
  history.replaceState(null, '', `#${encodeTraits(t)}`);
}

function renderVariations() {
  const box = $('variations');
  box.textContent = '';
  const opts = lockedOptions();
  for (let i = 0; i < 8; i++) {
    const tr = generate({ ...opts, seed: randomSeed() });
    const b = document.createElement('button');
    b.title = `${i + 1}: seed ${tr.seed}${tr.archetype ? ` · ${tr.archetype}` : ''}`;
    b.innerHTML = render(tr, { idPrefix: `v${i}` });
    b.onclick = () => setTraits(tr);
    box.append(b);
  }
}

function renderRecent() {
  const box = $('recent');
  box.textContent = '';
  state.recent.forEach((k, i) => {
    if (!thumbs.has(k)) thumbs.set(k, render(JSON.parse(k), { size: 96, idPrefix: `r${thumbs.size}` }));
    const b = document.createElement('button');
    b.innerHTML = thumbs.get(k);
    b.title = i === 0 ? 'Current portrait' : 'Go back to this portrait';
    if (k === state.current) b.setAttribute('aria-current', 'true');
    b.onclick = () => setTraits(JSON.parse(k));
    box.append(b);
  });
}

// ------------------------------------------------------------------ panels
function lockBox(checked, onChange, label) {
  const l = document.createElement('input');
  l.type = 'checkbox';
  l.className = 'lock';
  l.checked = checked;
  l.title = `Lock ${label} when randomizing`;
  l.setAttribute('aria-label', `Lock ${label}`);
  l.onchange = () => onChange(l.checked);
  return l;
}

function buildCharacter() {
  const box = $('character');
  box.textContent = '';
  for (const [k, label, table] of TRAIT_MENUS) {
    const row = document.createElement('div');
    row.className = 'row';
    const name = document.createElement('span');
    name.textContent = label;
    const sel = document.createElement('select');
    sel.setAttribute('aria-label', label);
    const rolled = table[state.traits[k]]?.label;
    sel.append(new Option(rolled ? `Any (${rolled})` : 'Any', ''));
    for (const [id, v] of Object.entries(table)) sel.append(new Option(v.label, id));
    sel.value = state.pins[k] ?? '';
    sel.onchange = () => {
      state.pins[k] = sel.value || undefined;
      // Apply the pick to this portrait (keep everything else); "Any" re-rolls just this trait.
      if (sel.value) {
        state.traits = { ...state.traits, [k]: sel.value };
        refresh();
      } else rerollOne(k);
    };
    const pin = document.createElement('span');
    pin.className = 'pin';
    pin.textContent = state.pins[k] ? '●' : '';
    pin.title = state.pins[k] ? 'Pinned: kept when randomizing' : '';
    row.append(name, sel, pin);
    box.append(row);
  }
}

function buildTweaks() {
  const box = $('tweaks');
  box.textContent = '';
  const t = state.traits;
  for (const tw of TWEAKS) {
    const row = document.createElement('div');
    row.className = 'slider-row';
    const name = document.createElement('span');
    name.textContent = tw.label;
    const input = document.createElement('input');
    input.type = 'range';
    input.min = tw.min;
    input.max = tw.max;
    input.step = tw.step;
    const set = t.tweaks?.[tw.k];
    input.value = set ?? (tw.auto ? tw.auto(t) : tw.def);
    input.setAttribute('aria-label', tw.label);
    const val = document.createElement('output');
    val.textContent = set === undefined ? 'auto' : Number(set).toFixed(2);
    const withValue = (v) => ({ ...t, tweaks: { ...t.tweaks, [tw.k]: v } });
    input.oninput = () => {
      val.textContent = Number(input.value).toFixed(2);
      $('preview').innerHTML = render(withValue(Number(input.value)), { idPrefix: 'main' });
    };
    input.onchange = () => {
      state.traits = withValue(Number(input.value));
      refresh();
    };
    // Double-click a slider to reset it.
    input.ondblclick = () => {
      const { [tw.k]: _, ...rest } = t.tweaks ?? {};
      state.traits = { ...t, tweaks: Object.keys(rest).length ? rest : undefined };
      if (!state.traits.tweaks) delete state.traits.tweaks;
      refresh();
    };
    row.append(name, input, val);
    box.append(row);
  }
}

function buildParts() {
  const cat = catalog(state.traits.theme, state.traits.archetype, state.traits.presentation, state.traits.style);
  const box = $('parts');
  box.textContent = '';
  const keyFor = Object.fromEntries(Object.entries(FEATURE_KEYS).map(([k, c]) => [c, k]));
  for (const c of CATEGORIES) {
    const row = document.createElement('div');
    row.className = 'row';
    const name = document.createElement('span');
    name.textContent = LABELS[c] ?? c;
    if (keyFor[c]) name.title = `Press ${keyFor[c].toUpperCase()} to reroll, Shift+${keyFor[c].toUpperCase()} to lock`;
    const sel = document.createElement('select');
    sel.setAttribute('aria-label', LABELS[c] ?? c);
    const native = cat.categories[c].filter((o) => o.weight > 0);
    const other = cat.categories[c].filter((o) => o.weight === 0);
    const addGroup = (label, list) => {
      if (!list.length) return;
      const g = document.createElement('optgroup');
      g.label = label;
      for (const o of list) g.append(new Option(o.label, o.id));
      sel.append(g);
    };
    addGroup(`${cat.theme.label}`, native);
    addGroup('Other themes', other);
    sel.value = state.traits[c];
    sel.onchange = () => {
      state.traits = { ...state.traits, [c]: sel.value };
      state.locks.parts.add(c); // a manual pick is kept when randomizing
      refresh();
    };
    const lock = lockBox(state.locks.parts.has(c), (on) => (on ? state.locks.parts.add(c) : state.locks.parts.delete(c)), LABELS[c]);
    row.append(name, sel, lock);
    box.append(row);
  }
}

function buildColors() {
  const cat = catalog(state.traits.theme, state.traits.archetype, state.traits.presentation, state.traits.style);
  const box = $('colors');
  box.textContent = '';
  for (const s of COLOR_SLOTS) {
    const row = document.createElement('div');
    row.className = 'color-row';
    const name = document.createElement('span');
    name.textContent = COLOR_LABELS[s];
    const input = document.createElement('input');
    input.type = 'color';
    input.value = state.traits.colors[s];
    input.setAttribute('aria-label', `${COLOR_LABELS[s]} colour`);
    const apply = (hex) => {
      state.traits = { ...state.traits, colors: { ...state.traits.colors, [s]: hex } };
      state.locks.colors.add(s);
      refresh();
    };
    input.onchange = () => apply(input.value);
    input.oninput = () => {
      // live preview while dragging, without rebuilding panels
      const t = { ...state.traits, colors: { ...state.traits.colors, [s]: input.value } };
      $('preview').innerHTML = render(t, { idPrefix: 'main' });
    };
    const sw = document.createElement('div');
    sw.className = 'swatches';
    for (const hex of cat.colors[s]) {
      const b = document.createElement('button');
      b.className = 'swatch';
      b.style.background = hex;
      b.title = hex;
      b.setAttribute('aria-pressed', String(hex.toLowerCase() === state.traits.colors[s].toLowerCase()));
      b.onclick = () => apply(hex);
      sw.append(b);
    }
    const lock = lockBox(state.locks.colors.has(s), (on) => (on ? state.locks.colors.add(s) : state.locks.colors.delete(s)), `${COLOR_LABELS[s]} colour`);
    row.append(name, input, sw, lock);
    box.append(row);
  }
}

function buildAccessories() {
  const cat = catalog(state.traits.theme, state.traits.archetype, state.traits.presentation, state.traits.style);
  const box = $('accessories');
  box.textContent = '';
  const groups = new Map();
  for (const a of cat.accessories) {
    const layer = getPart('accessories', a.id).layer;
    const key = a.group ?? (layer === 'marks' ? 'marks' : 'other');
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(a);
  }
  const order = ['marks', 'eyewear', 'head', 'mask', 'earwear', 'piercing', 'forehead', 'neck', 'neckwrap', 'brooch', 'gear', 'companion', 'held', 'horns', 'halo', 'other'];
  for (const key of [...groups.keys()].sort((x, y) => order.indexOf(x) - order.indexOf(y))) {
    const g = document.createElement('div');
    g.className = 'acc-group';
    const h = document.createElement('h3');
    h.textContent = GROUP_LABELS[key] ?? key;
    const chips = document.createElement('div');
    chips.className = 'chips';
    for (const a of groups.get(key)) {
      const on = state.traits.accessories.includes(a.id);
      const b = document.createElement('button');
      b.className = `chip${a.chance > 0 ? '' : ' off-theme'}`;
      b.textContent = a.label;
      b.setAttribute('aria-pressed', String(on));
      b.title = a.chance > 0 ? `${Math.round(a.chance * 100)}% chance in this theme` : 'Not rolled in this theme, but selectable';
      b.onclick = () => toggleAccessory(a, !on);
      chips.append(b);
    }
    g.append(h, chips);
    box.append(g);
  }
  $('lock-acc').checked = state.locks.accessories;
}

function toggleAccessory(a, on) {
  let list = state.traits.accessories.filter((id) => id !== a.id);
  if (on) {
    // Exclusive groups, including extra ones (a spectacle helm also counts as eyewear).
    const groupsOf = (id) => { const p = getPart('accessories', id); return [p.group, ...(p.alsoGroups ?? [])].filter(Boolean); };
    const mine = groupsOf(a.id);
    if (mine.length) list = list.filter((id) => !groupsOf(id).some((x) => mine.includes(x)));
    list.push(a.id);
  }
  state.traits = { ...state.traits, accessories: list };
  state.locks.accessories = true;
  refresh();
}

// ------------------------------------------------------------------ theme / archetype
function fillArchetypes() {
  const sel = $('archetype');
  const cat = catalog($('theme').value);
  sel.textContent = '';
  sel.append(new Option('Any', ''));
  for (const a of cat.archetypes) sel.append(new Option(a.label, a.id));
  sel.disabled = !cat.archetypes.length;
}

// ------------------------------------------------------------------ export
function exportSize() {
  const n = Math.round(Number($('size').value));
  if (!Number.isFinite(n) || n < 16 || n > 8192) {
    status('Size must be between 16 and 8192 px.');
    return null;
  }
  return n;
}
const fileBase = () => `portrait-${state.traits.theme}-${state.traits.seed}`.replace(/[^\w.-]+/g, '_');
function status(msg) {
  $('status').textContent = msg;
}

async function exportPNG() {
  const size = exportSize();
  if (!size) return;
  status(`Rendering ${size}×${size}…`);
  try {
    const blob = await toPNGBlob(render(state.traits, { size, transparent: $('transparent').checked }), { size });
    download(blob, `${fileBase()}-${size}.png`);
    status(`Saved ${fileBase()}-${size}.png (${Math.round(blob.size / 1024)} KB)`);
  } catch (e) {
    status(`PNG export failed: ${e.message}`);
  }
}

function encodeTraits(t) {
  return btoa(unescape(encodeURIComponent(JSON.stringify(t))));
}
function decodeTraits(s) {
  return JSON.parse(decodeURIComponent(escape(atob(s))));
}

// ------------------------------------------------------------------ keyboard
function onKey(e) {
  if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName ?? '')) return;
  const mod = e.ctrlKey || e.metaKey;
  const k = e.key.toLowerCase();
  if (mod && k === 'z') { e.preventDefault(); return e.shiftKey ? redo() : undo(); }
  if (mod && k === 'y') { e.preventDefault(); return redo(); }
  if (mod || e.altKey) return;
  if (k === '?' || (e.shiftKey && k === '/')) return $('help').showModal?.();
  if (k === 'r') return regenerate(randomSeed());
  if (k === 'v') return renderVariations();
  if (k === 'u') return undo();
  if (k === 'd') return rerollOne('accessories');
  if (/^[1-8]$/.test(k)) return $('variations').children[Number(k) - 1]?.click();
  if (FEATURE_KEYS[k]) {
    const c = FEATURE_KEYS[k];
    if (e.shiftKey) {
      state.locks.parts.has(c) ? state.locks.parts.delete(c) : state.locks.parts.add(c);
      status(`${LABELS[c]} ${state.locks.parts.has(c) ? 'locked' : 'unlocked'}.`);
      return buildParts();
    }
    return rerollOne(c);
  }
  if (TRAIT_KEYS[k]) return rerollOne(TRAIT_KEYS[k]);
}

// ------------------------------------------------------------------ wiring
function init() {
  for (const t of themes()) $('theme').append(new Option(t.label, t.id));
  for (const s of STYLES) $('style').append(new Option(RENDER_STYLES[s]?.label ?? s, s));
  $('style').onchange = () => regenerate($('seed').value);
  for (const p of [128, 256, 512, 1024, 2048, 4096]) {
    const b = document.createElement('button');
    b.textContent = p;
    b.onclick = () => ($('size').value = p);
    $('presets').append(b);
  }
  // The style is independent of the theme, so a chosen style survives a theme change.
  $('theme').onchange = () => {
    fillArchetypes();
    regenerate($('seed').value);
  };
  $('archetype').onchange = () => regenerate($('seed').value);
  $('seed').onchange = () => regenerate($('seed').value.trim() || randomSeed());
  $('describe').onchange = () => {
    const text = $('describe').value.trim();
    // A new description starts fresh: the theme follows the description, picks are released.
    state.locks.parts.clear();
    state.pins = {};
    const d = describe(text).options;
    if (d.theme && d.theme !== $('theme').value) { $('theme').value = d.theme; fillArchetypes(); }
    if (d.archetype) $('archetype').value = d.archetype;
    if (d.style) $('style').value = d.style;
    regenerate(randomSeed());
    status(text ? `Understood: ${describe(text).matched.join(', ') || 'nothing (random)'}` : 'Description cleared.');
  };
  $('randomize').onclick = () => regenerate(randomSeed());
  $('undo').onclick = undo;
  $('redo').onclick = redo;
  $('help-btn').onclick = () => $('help').showModal?.();
  $('help-close').onclick = () => $('help').close?.();
  $('more').onclick = renderVariations;
  $('unlock-all').onclick = () => {
    state.locks.parts.clear();
    state.locks.colors.clear();
    state.locks.accessories = false;
    state.pins = {};
    refresh();
  };
  $('reset-tweaks').onclick = () => {
    const { tweaks, ...rest } = state.traits;
    state.traits = rest;
    refresh();
  };
  $('lock-acc').onchange = (e) => (state.locks.accessories = e.target.checked);
  $('dl-png').onclick = exportPNG;
  $('dl-svg').onclick = () => download(render(state.traits, { size: exportSize() ?? 512, ...viewOptions() }), `${fileBase()}.svg`, 'image/svg+xml');
  // Preview the transparent export on the checkerboard.
  $('transparent').onchange = showPreview;
  // A new line restarts the lip-sync (only Talk uses it).
  $('say').onchange = () => { if (EMOTES[state.emote.play]?.visemes) showPreview(); };
  buildEmotes();
  $('dl-json').onclick = () => download(JSON.stringify(state.traits, null, 2), `${fileBase()}.json`, 'application/json');
  $('load-json').onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      setTraits(JSON.parse(await f.text()));
      status(`Loaded ${f.name}`);
    } catch (err) {
      status(`Could not load ${f.name}: ${err.message}`);
    }
    e.target.value = '';
  };
  $('copy-link').onclick = async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      status('Link copied. It encodes this exact portrait.');
    } catch {
      status('Clipboard unavailable; copy the address bar instead.');
    }
  };
  document.addEventListener('keydown', onKey);

  let initial = null;
  if (location.hash.length > 1) {
    try {
      initial = decodeTraits(location.hash.slice(1));
    } catch { /* ignore malformed links */ }
  }
  $('theme').value = initial?.theme ?? 'fantasy';
  $('style').value = themes().find((t) => t.id === $('theme').value)?.style ?? 'illustrated';
  fillArchetypes();
  if (initial) setTraits(initial);
  else regenerate(randomSeed());
}

init();
