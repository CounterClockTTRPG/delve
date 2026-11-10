// Emotes: short looping animations of the face (blinking, talking, a smile, a laugh,
// surprise, fear, a wink, tears...). The renderer draws each animated feature once per
// distinct pose, and CSS keyframes inside the SVG switch between them (the head, a blush and
// tears ease with CSS). Browsers animate it; rasterisers (PNG export) show the still portrait.
// Reduced-motion viewers see no animation.
//
// Emotes are data: the built-in ones are read from emotes.json at startup, and
// registerEmote(id, definition) adds or replaces one. A definition:
//   label   name shown in UIs
//   rest    ms of the face at rest before the emote (default 900)
//   pose    features held for the whole emote, eased in and out:
//             eyes  { lid 0..1, top, bot (opening, x1), pupil (size, x1),
//                     gx, gy (gaze -1..1: where the irises look; +x is the viewer's right) }
//             brows { dy (px, negative raises), tilt (degrees, positive drops the inner ends) }
//               eyes and brows also take `left` / `right` (as the viewer sees them):
//               fields for that side only, e.g. a wink { "right": { "lid": 1 } }
//             mouth { part (a mouth id), sx, sy (scale), rot (degrees, negative lifts the viewer's right corner) }
//             marks an expression id whose face lines to show (smile, stern, sad, surprised, tired)
//             head  { dx, dy, rot (degrees) }        eased between poses
//             blush 0..1, a flush on the cheeks      eased
//             tears 0..1, tears running down         eased
//             zzz   0..1, snoring z's drifting up    eased
//             hearts 0..1, hearts floating up        eased
//   hold    ms the pose is held (default 2000), when there are no steps
//   steps   instead of hold: a sequence of { ms, <feature>: pose }, played `repeat` times
//           (default 1). A step's feature overrides `pose`; null puts it at rest.
//   after   ms at rest after the emote (default 0)
//   idle    makes it an idle emote that loops on its own clock and carries on over other
//           emotes' poses (blinking, breathing): { every: s, delay: s, double: chance, gap: ms }
//   visemes lip-sync: mouth poses for a, e, o (vowels), m (closed: m b p), f (f v) and c (other
//           letters). With render(..., { say: 'text' }) the text becomes the steps.
//   speech  lip-sync timing: { vowel: ms, consonant: ms, space: ms, pause: ms (after . , ! ?),
//           nod: a head pose at the start of each word }
// Any number can be a [min, max] range and any value { "pick": [...] }; both are rolled
// from the portrait's seed, so a portrait always emotes the same way.
import { createRng } from './rng.js';
import BUILT_IN from './emotes.json' with { type: 'json' };

const FEATURES = {
  eyes: { lid: 0, top: 1, bot: 1, pupil: 1, gx: 0, gy: 0 },
  brows: { dy: 0, tilt: 0 },
  mouth: { part: null, sx: 1, sy: 1, rot: 0 },
  marks: null,
  head: { dx: 0, dy: 0, rot: 0 },
  blush: null,
  tears: null,
  zzz: null,
  hearts: null,
};
// Features with a pose per side.
const SIDED = ['eyes', 'brows'];
// Features drawn from numbers get an in-between pose when they change at the start and end.
const EASED = ['eyes', 'brows'];
// Features that ease continuously (CSS transitions between points) instead of switching frames.
export const SMOOTH = ['head', 'blush', 'tears', 'zzz', 'hearts'];
const T = 70;
const VISEMES = ['a', 'e', 'o', 'm', 'f', 'c'];

export const EMOTES = {};

/** Add or replace an emote (see the format above). Throws on a malformed definition. */
export function registerEmote(id, def) {
  const where = `emote "${id}"`;
  if (!def || typeof def !== 'object') throw new Error(`${where}: definition must be an object`);
  const checkFields = (f, o, at) => {
    for (const k of Object.keys(o)) {
      if (SIDED.includes(f) && (k === 'left' || k === 'right')) checkFields(f, o[k] ?? {}, `${at} (${k})`);
      else if (!(k in FEATURES[f])) throw new Error(`${where}: unknown ${f} field "${k}" in ${at} (known: ${Object.keys(FEATURES[f]).join(', ')}${SIDED.includes(f) ? ', left, right' : ''})`);
    }
  };
  const checkPose = (pose, at) => {
    for (const [f, p] of Object.entries(pose ?? {})) {
      if (f === 'ms') continue;
      if (!(f in FEATURES)) throw new Error(`${where}: unknown feature "${f}" in ${at} (known: ${Object.keys(FEATURES).join(', ')})`);
      if (!FEATURES[f]) continue;
      for (const o of p?.pick ?? [p]) if (o && typeof o === 'object' && !Array.isArray(o)) checkFields(f, o, at);
    }
  };
  checkPose(def.pose, 'pose');
  if (def.steps !== undefined && !Array.isArray(def.steps)) throw new Error(`${where}: steps must be a list`);
  (def.steps ?? []).forEach((s, i) => {
    if (s.ms === undefined) throw new Error(`${where}: step ${i + 1} needs ms`);
    checkPose(s, `step ${i + 1}`);
  });
  for (const [k, p] of Object.entries(def.visemes ?? {})) {
    if (!VISEMES.includes(k)) throw new Error(`${where}: unknown viseme "${k}" (known: ${VISEMES.join(', ')})`);
    checkPose({ mouth: p }, `viseme ${k}`);
  }
  if (def.idle && !def.steps?.length) throw new Error(`${where}: an idle emote needs steps`);
  EMOTES[id] = { label: def.label ?? id, ...def };
}

for (const [id, def] of Object.entries(BUILT_IN)) if (!id.startsWith('$')) registerEmote(id, def);

/** Resolve ranges and picks in a value. */
function roll(v, rng) {
  if (Array.isArray(v) && v.length === 2 && v.every((n) => typeof n === 'number')) return rng.range(v[0], v[1]);
  if (v && typeof v === 'object' && Array.isArray(v.pick)) return roll(rng.pick(v.pick), rng);
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, roll(x, rng)]));
  return v;
}
const count = (v, rng) => (Array.isArray(v) ? rng.int(v[0], v[1]) : v ?? 1);

/** A sided feature's pose for one side: the shared fields with that side's on top. */
export function sidePose(p, side) {
  if (!p) return p;
  const { left, right, ...shared } = p;
  return { ...shared, ...(side === 'left' ? left : right) };
}

/** A numeric pose between a and b (null is the feature at rest). */
function tween(f, a, b, k = 0.5) {
  const base = FEATURES[f];
  const mid = (A, B) => Object.fromEntries(Object.keys(base).map((key) => {
    const x = A?.[key] ?? base[key], y = B?.[key] ?? base[key];
    return [key, +(x + (y - x) * k).toFixed(3)];
  }));
  const out = mid(a, b);
  for (const s of ['left', 'right']) if (a?.[s] || b?.[s]) out[s] = mid(sidePose(a, s), sidePose(b, s));
  return out;
}

/** Steps that say `text`: each letter's mouth shape (its viseme), merged where they repeat. */
function speechSteps(def, text, rng) {
  const v = def.visemes, d = def.speech ?? {};
  const kind = (ch) => (/[aàáâäå]/.test(ch) ? 'a' : /[eéèêëiíìîïy]/.test(ch) ? 'e' : /[oóòôöuúùûüw]/.test(ch) ? 'o'
    : /[mbp]/.test(ch) ? 'm' : /[fv]/.test(ch) ? 'f' : /\p{L}|\d/u.test(ch) ? 'c' : /[.,!?;:…]/.test(ch) ? 'pause' : 'space');
  const steps = [];
  let wordStart = true;
  for (const ch of text.toLowerCase()) {
    const k = kind(ch);
    if (k === 'space' || k === 'pause') {
      steps.push({ ms: roll(k === 'pause' ? d.pause ?? 350 : d.space ?? 110, rng), mouth: null });
      wordStart = true;
      continue;
    }
    const step = { ms: roll('aeo'.includes(k) ? d.vowel ?? [100, 140] : d.consonant ?? [55, 85], rng), mouth: roll(v[k] ?? null, rng) };
    if (wordStart && d.nod) step.head = roll(d.nod, rng);
    wordStart = false;
    const prev = steps.at(-1);
    if (prev && !step.head && JSON.stringify(prev.mouth) === JSON.stringify(step.mouth)) prev.ms += step.ms;
    else steps.push(step);
  }
  return steps.length ? steps : [{ ms: 500, mouth: null }];
}

/** The steps of one play-through: [{ ms, ...features }], rolled. */
function playSteps(def, rng, say) {
  if (say && def.visemes) return speechSteps(def, say, rng);
  if (!def.steps?.length) return [{ ms: def.hold ?? 2000 }];
  const out = [];
  for (let i = 0, n = count(def.repeat, rng); i < n; i++) for (const s of def.steps) out.push(roll(s, rng));
  return out;
}

/** Tracks of a regular emote: { feature: { total, keys: [[ms, pose]] } }, smooth ones as points. */
function build(def, rng, say) {
  const pose = roll(def.pose ?? {}, rng);
  const steps = playSteps(def, rng, say);
  const rest = def.rest ?? 900, after = def.after ?? 0;
  const hold = steps.reduce((s, x) => s + x.ms, 0);
  const total = rest + hold + 2 * T + after;
  const used = new Set([...Object.keys(pose), ...steps.flatMap((s) => Object.keys(s))].filter((f) => f in FEATURES));
  const out = {};
  for (const f of used) {
    const stepped = steps.some((s) => f in s);
    const value = (s) => (f in s ? s[f] : pose[f] ?? null);
    if (SMOOTH.includes(f)) {
      let t = 0;
      const pts = stepped ? steps.map((s) => [(t += s.ms) - s.ms, value(s)]) : [[0, pose[f]], [Math.max(0, hold - 2 * T), pose[f]]];
      out[f] = { total, points: [[0, null], [rest, null], ...pts.map(([at, p]) => [rest + T + at, p]), [rest + hold + T, pts.at(-1)[1]], [rest + hold + 2 * T, null], [total, null]] };
      continue;
    }
    const keys = stepped
      ? [[rest + T, null], ...steps.map((s) => [s.ms, value(s)]), [T + after, null]]
      : EASED.includes(f)
        ? [[rest, null], [T, tween(f, null, pose[f])], [hold, pose[f]], [T, tween(f, pose[f], null)], [after, null]]
        : [[rest + T, null], [hold, pose[f]], [T + after, null]];
    out[f] = { total, keys };
  }
  return out;
}

/** An idle emote's timing; overriding one setting doesn't reshuffle the others. */
export function idleTiming(def, rng, option) {
  const o = typeof option === 'object' ? option : {};
  const idle = def.idle ?? {};
  const rolled = { every: roll(idle.every ?? 5, rng), delay: roll(idle.delay ?? 0, rng), double: rng.chance(idle.double ?? 0) };
  return { every: Math.max(1, o.every ?? rolled.every), delay: Math.max(0, o.delay ?? rolled.delay), double: o.double ?? rolled.double };
}

/** [[start, end, pose]] from [[duration, pose]]. */
function segments(keys, offset = 0) {
  let t = offset;
  return keys.filter(([d]) => d > 0).map(([d, p]) => [t, (t += d), p]);
}

/** Pose at each moment of a, with b's fields laid over it (b's gaps leave a as it is). */
function overlay(a, b) {
  const cuts = [...new Set([...a, ...b].flatMap(([s, e]) => [s, e]))].sort((x, y) => x - y);
  const at = (segs, t) => segs.find(([s, e]) => t >= s && t < e)?.[2] ?? null;
  const out = [];
  for (let i = 0; i < cuts.length - 1; i++) {
    const pa = at(a, cuts[i]), pb = at(b, cuts[i]);
    // Lids only ever close further: a blink doesn't half-open sleeping eyes.
    const lid = Math.max(pa?.lid ?? 0, pb?.lid ?? 0);
    out.push([cuts[i], cuts[i + 1], pb ? { ...pa, ...pb, ...(lid && { lid }) } : pa]);
  }
  return out;
}

/**
 * The tracks to animate for a list of emote ids, per feature: { total, delay, segments,
 * poses } (ms; segments are [start, end, poseIndex], pose 0 is the feature at rest), or
 * for smooth features (head, blush, tears) { total, delay, points }. A later emote takes
 * over a feature from an earlier one; idle emotes carry on over the others.
 * options: { say: text for emotes with visemes, once, [idleId]: { every, delay, double } }.
 * With `once`, a track an idle emote shares with another also gets `then`: the idle emote's
 * own loop, { total, segments }, to run once the other has played.
 */
export function emoteTracks(traits, ids, options = {}) {
  const tracks = {};
  const idle = [];
  for (const id of ids) {
    const def = EMOTES[id];
    if (!def) continue;
    const rng = createRng(`${traits.seed}:${id}`);
    if (def.idle) { idle.push([def, rng, options[id]]); continue; }
    for (const [f, t] of Object.entries(build(def, rng, options.say))) {
      tracks[f] = t.points ? { ...t, delay: 0 } : { total: t.total, delay: 0, segments: segments(t.keys) };
    }
  }
  for (const [def, rng, option] of idle) {
    const { every, delay, double } = idleTiming(def, rng, option);
    const once = def.steps.map((s) => roll(s, rng));
    const play = [...once, ...(double ? [{ ms: def.idle.gap ?? 250 }, ...once] : [])];
    const used = play.reduce((s, x) => s + x.ms, 0);
    const total = Math.max(every * 1000, used + 100);
    for (const f of Object.keys(FEATURES).filter((f) => once.some((s) => f in s))) {
      if (SMOOTH.includes(f)) {
        // A smooth idle (breathing) only runs while no other emote drives the feature.
        if (tracks[f]) continue;
        let t = 0;
        const pts = play.map((s) => [(t += s.ms) - s.ms, s[f] ?? null]);
        tracks[f] = { total, delay: delay * 1000, points: [...pts, [total, pts[0][1]]], idle: true };
        continue;
      }
      const keys = play.map((s) => [s.ms, s[f] ?? null]);
      if (!tracks[f]) {
        tracks[f] = { total, delay: delay * 1000, segments: segments([...keys, [total - used, null]]), idle: true };
      } else {
        // On another emote's clock: early in its cycle, then about every `every` seconds.
        const own = tracks[f].total;
        const plays = [];
        for (let s = Math.min(own * 0.3, 1200); s + used < own; s += every * 1000) plays.push(...segments(keys, s));
        tracks[f].segments = overlay(tracks[f].segments, plays);
        if (options.once) tracks[f].then = { total, segments: segments([...keys, [total - used, null]]) };
      }
    }
  }
  for (const t of Object.values(tracks)) {
    if (t.points) continue;
    const seen = ['null'];
    t.poses = [null];
    const index = (segs) => segs.map(([s, e, p]) => {
      const k = JSON.stringify(p);
      if (!seen.includes(k)) { seen.push(k); t.poses.push(p); }
      return [s, e, seen.indexOf(k)];
    });
    t.segments = index(t.segments);
    if (t.then) t.then.segments = index(t.then.segments);
  }
  return tracks;
}

/**
 * How long a portrait's emotes take to play once, in ms (the longest track, its delay
 * included); 0 without any. Idle emotes (blink, breathe) never end and count for nothing.
 * options: { emotes, say } as render() takes them.
 */
export function emoteDuration(traits, options = {}) {
  const tracks = emoteTracks(traits, options.emotes ?? [], { say: options.say });
  return Object.values(tracks).reduce((most, t) => (t.idle ? most : Math.max(most, t.delay + t.total)), 0);
}

/**
 * Writes the CSS for a portrait's animated groups. With `once`, every track but an idle
 * emote's plays one time and stays on its last frame, the feature at rest.
 */
export function createAnimator(uid, { once = false } = {}) {
  const all = uid('emote');
  let css = '';
  const pct = (ms, total) => +((ms / total) * 100).toFixed(3);
  const count = (idle) => (once && !idle ? '1 forwards' : 'infinite');
  const timing = (t, ease) => `${+(t.total / 1000).toFixed(3)}s ${ease} ${+(t.delay / 1000).toFixed(3)}s ${count(t.idle)}`;
  const n = (x) => +(x ?? 0).toFixed(2);
  return {
    /** Frame groups for a track: markups[i] is the feature drawn in pose i. */
    swap(track, markups) {
      const name = uid('frames');
      return markups.map((markup, i) => {
        const cls = `${name}-${i}`;
        const frames = (t) => t.segments.map(([s, , p]) => `${pct(s, t.total)}%{opacity:${p === i ? 1 : 0}}`).join('');
        const rest = `100%{opacity:${i === 0 ? 1 : 0}}`;
        // The idle loop that takes over once the emote has played: later in the list, so it wins.
        const then = once && track.then ? `,${cls}-then ${timing({ ...track.then, delay: track.delay + track.total, idle: true }, 'step-end')}` : '';
        css += `.${cls}{animation:${cls} ${timing(track, 'step-end')}${then}}@keyframes ${cls}{${frames(track)}${rest}}`;
        if (then) css += `@keyframes ${cls}-then{${frames(track.then)}${rest}}`;
        return `<g class="${all} ${cls}"${i ? ' opacity="0"' : ''}>${markup}</g>`;
      }).join('');
    },
    /** A wrapper that moves markup along a head track, about a pivot; every use moves in step. */
    mover(track, [px, py]) {
      const cls = uid('head');
      const keys = track.points.map(([t, p]) => `${pct(t, track.total)}%{transform:translate(${n(p?.dx)}px,${n(p?.dy)}px) rotate(${n(p?.rot)}deg)}`).join('');
      css += `.${cls}{transform-box:view-box;transform-origin:${n(px)}px ${n(py)}px;animation:${cls} ${timing(track, 'ease-in-out')}}@keyframes ${cls}{${keys}}`;
      return (markup) => `<g class="${all} ${cls}">${markup}</g>`;
    },
    /** Markup faded in and out along a 0..1 track (hidden when still). */
    fade(track, markup) {
      const cls = uid('fade');
      const keys = track.points.map(([t, p]) => `${pct(t, track.total)}%{opacity:${n(p)}}`).join('');
      css += `.${cls}{animation:${cls} ${timing(track, 'ease-in-out')}}@keyframes ${cls}{${keys}}`;
      return `<g class="${all} ${cls}" opacity="0">${markup}</g>`;
    },
    /** Markup that keeps moving by (dx, dy) px and fading out, every `period` s (a running tear, a rising z). */
    fall(markup, dy, period, delay = 0, dx = 0) {
      const cls = uid('fall');
      css += `.${cls}{animation:${cls} ${period}s ease-in ${delay}s ${count(false)}}@keyframes ${cls}{0%{transform:translate(0,0);opacity:0}15%{opacity:1}80%{opacity:1}100%{transform:translate(${n(dx)}px,${n(dy)}px);opacity:0}}`;
      return `<g class="${all} ${cls}">${markup}</g>`;
    },
    defs: () => css && `<style>${css}@media (prefers-reduced-motion: reduce){.${all}{animation:none}}</style>`,
  };
}
