import { CATEGORIES, getPart, RENDER_STYLES, baseStyle } from './registry.js';
import { faceGeometry, realisticGeometry, blurFilter, pt, SIZE, CX } from './geometry.js';
import { neckStyles } from './parts/face.js';
import { createRng, hashSeed } from './rng.js';
import { softenOutlines, volumeFilter, depthOfField, clothFolds, maskCopy } from './realism.js';
import { lightingGrade } from './lighting.js';
import { ageValue, agedHair, ageModelling } from './age.js';
import { expressionModelling } from './expression.js';
import { emoteTracks, createAnimator, sidePose } from './emote.js';
import { blushMarkup, tearsMarkup, zzzMarkup, heartsMarkup } from './emoteParts.js';
import { saturate } from './color.js';
import { bodyPath } from './parts/clothing.js';
import { BUILDS, buildShape, buildModelling } from './build.js';

/** Draw order, back to front. Parts contribute markup to any of these. */
export const LAYERS = [
  'background', 'accBack', 'hairBack', 'neck', 'body', 'shade', 'accNeck', 'hairLocks', 'ears', 'face', 'marks',
  'eyes', 'brows', 'nose', 'facialHair', 'mouth', 'mustache', 'hairFront', 'accFace', 'accHead', 'frame',
];

// Realistic style: how markup from parts without a realistic renderer is lit, per layer.
const GENERIC_VOLUME = {
  // Tall: clothing runs below the canvas so the bust framing has a torso to show.
  body: { depth: 10, relief: 7, shine: 0.2, weave: 0.35, tall: true },
  accBack: { depth: 5, relief: 5 },
  accNeck: { depth: 2, relief: 3, shine: 0.6, gloss: 20 },
  accHead: { depth: 3, relief: 4, shine: 0.5, gloss: 18 },
  accFace: { depth: 1.5, relief: 2, shine: 0.4, gloss: 20 },
};

/**
 * Render a traits object (from generate()) to an SVG string.
 * options: { size = 512, idPrefix, background = true, transparent = false, style, emotes, blink, say, once }
 * `transparent` (or the 'transparent' backdrop) leaves everything around the figure transparent.
 * `style` overrides traits.style ('illustrated' when absent).
 * `emotes` (a list of emote ids, e.g. ['blink', 'talk']) animates the face (see emote.js).
 * `blink` (true, or { every: seconds, delay: seconds, double }) is short for the 'blink' emote.
 * `once` plays the emotes one time, ending on the still portrait; idle emotes (blink, breathe) go on.
 */
export function render(traits, options = {}) {
  const size = options.size ?? SIZE;
  const prefix = options.idPrefix ?? `pg${hashSeed(JSON.stringify(traits)).toString(36)}`;
  let counter = 0;
  const faceDef = getPart('face', traits.face) ?? getPart('face', 'oval');
  const style = RENDER_STYLES[options.style ?? traits.style] ? options.style ?? traits.style : 'illustrated';
  const def = RENDER_STYLES[style];
  const base = baseStyle(style);
  const realistic = base === 'realistic';
  const ctx = {
    traits,
    style,
    g: def.geometry ? def.geometry(geometryFor(faceDef.shape, traits, realistic), traits) : geometryFor(faceDef.shape, traits, realistic),
    colors: portraitColors(traits),
    rng: createRng(`${traits.seed}:render`),
    uid: (name) => `${prefix}-${name}-${counter++}`,
  };
  const layers = Object.fromEntries(LAYERS.map((l) => [l, '']));
  let defs = '';
  const volumes = {};
  const volume = (layer) => {
    if (!volumes[layer]) {
      volumes[layer] = ctx.uid(`vol-${layer}`);
      defs += volumeFilter(volumes[layer], GENERIC_VOLUME[layer]);
    }
    return volumes[layer];
  };
  let marksFilter;
  const softMarks = () => {
    if (!marksFilter) {
      marksFilter = ctx.uid('marks');
      defs += blurFilter(marksFilter, 0.7);
    }
    return marksFilter;
  };
  // `generic`: markup drawn by a part that has no renderer for the active style.
  const add = (out, generic = false, target = layers) => {
    if (!out) return;
    for (const [layer, raw] of Object.entries(out)) {
      if (!raw) continue;
      let markup = generic && realistic ? softenOutlines(raw) : raw;
      if (def.prepare && layer !== 'defs') markup = def.prepare(markup, layer);
      if (generic && def.prepareGeneric && layer !== 'defs') markup = def.prepareGeneric(markup, layer);
      if (layer === 'defs') defs += markup;
      else if (!(layer in target)) throw new Error(`Part rendered into unknown layer "${layer}"`);
      else if (generic && realistic && GENERIC_VOLUME[layer]) target[layer] += `<g filter="url(#${volume(layer)})">${markup}</g>`;
      // Painted-on skin marks (scars, tattoos, freckles) lose their crisp vector edge.
      else if (generic && realistic && layer === 'marks') target[layer] += `<g filter="url(#${softMarks()})" opacity="0.85">${markup}</g>`;
      else target[layer] += markup;
    }
  };
  const draw = (part, target) => {
    const styled = part.styles?.[style] ?? part.styles?.[base];
    add((styled ?? part.render)(ctx), !styled, target);
  };

  // Emotes: animated features are drawn once per pose and switched by CSS (see emote.js).
  const emotes = [...(options.blink ? ['blink'] : []), ...(options.emotes ?? []).filter((id) => id !== 'blink' || !options.blink)];
  const motion = emotes.length ? emoteTracks(traits, emotes, { blink: options.blink, say: options.say, once: options.once }) : {};
  const animator = emotes.length ? createAnimator(ctx.uid, { once: options.once }) : null;
  // Masks for one half of the face (as the viewer sees it), for poses that differ per side.
  // Masks rather than clip paths: resvg can panic on clipped groups containing blur filters.
  const halfMasks = {};
  const half = (side, markup) => {
    if (!halfMasks[side]) {
      const { cx } = ctx.g;
      halfMasks[side] = ctx.uid('half');
      defs += `<mask id="${halfMasks[side]}" maskUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}"><rect x="${side === 'left' ? 0 : cx}" y="0" width="${side === 'left' ? cx : SIZE - cx}" height="${SIZE}" fill="#fff"/></mask>`;
    }
    return `<g mask="url(#${halfMasks[side]})">${markup}</g>`;
  };
  const sided = (p) => p && (p.left || p.right);
  const posedEyes = (part, p) => (sided(p)
    ? ['left', 'right'].map((s) => half(s, redraw(part, { eyes: sidePose(p, s) }).eyes)).join('')
    : redraw(part, { eyes: p }).eyes);
  // A part drawn again, in a pose, into layers of its own. It replays the random draws the
  // portrait's drawing of it makes (same lashes, same lip texture); the portrait's stream is untouched.
  const redraw = (part, pose) => {
    const rng = ctx.rng;
    const target = Object.fromEntries(LAYERS.map((l) => [l, '']));
    Object.assign(ctx, { rng: rng.snapshot(), pose });
    draw(part, target);
    Object.assign(ctx, { rng, pose: undefined });
    return target;
  };
  const posedMouth = (part, pose) => {
    // Racial mouths (tusks, fangs) keep their shape and only open and close.
    const shape = pose.part && !KEEP_MOUTH.has(traits.mouth) ? getPart('mouth', pose.part) ?? part : part;
    const m = redraw(shape, { mouth: pose }).mouth;
    const sx = pose.sx ?? 1, sy = pose.sy ?? 1, rot = pose.rot ?? 0;
    if (sx === 1 && sy === 1 && !rot) return m;
    const { cx, mouthY } = ctx.g;
    return `<g transform="translate(${pt(cx, mouthY)}) rotate(${+rot.toFixed(2)}) scale(${+sx.toFixed(3)},${+sy.toFixed(3)}) translate(${pt(-cx, -mouthY)})">${m}</g>`;
  };
  for (const cat of CATEGORIES) {
    if (cat === 'background' && (options.background === false || options.transparent)) continue;
    const part = getPart(cat, traits[cat]);
    if (!part) continue;
    const track = (cat === 'eyes' || cat === 'mouth') && motion[cat];
    if (!track) {
      draw(part);
      continue;
    }
    const frames = track.poses.slice(1).map((p) => (cat === 'eyes' ? posedEyes(part, p) : posedMouth(part, p)));
    const before = layers[cat];
    draw(part);
    layers[cat] = before + animator.swap(track, [layers[cat].slice(before.length), ...frames]);
  }
  for (const id of traits.accessories ?? []) {
    const part = getPart('accessories', id);
    if (part) draw(part);
  }
  const neck = (neckStyles[style] ?? neckStyles[base] ?? neckStyles.illustrated)(ctx);
  if (typeof neck === 'string') layers.neck = neck + layers.neck;
  else {
    layers.neck = (neck.neck ?? '') + layers.neck;
    layers.shade = (neck.shade ?? '') + layers.shade;
    defs += neck.defs ?? '';
  }
  // Headwear that covers the top of the head hides the hair above its rim.
  const covers = (traits.accessories ?? []).map((id) => getPart('accessories', id)?.hidesHairAbove?.(ctx.g)).filter((y) => y !== undefined);
  if (covers.length) {
    const mask = ctx.uid('underHat');
    const y = Math.min(...covers);
    // Below the rim, hair stays close to the head (big styles would bulge out under the brim);
    // long hair still falls freely below the jaw.
    // The allowed region follows a rounded outline around the head, so what's left reads as
    // hair spilling out under the brim rather than a boxy cut.
    const { cx, w, jawY, eyeY, bottom } = ctx.g;
    const hairRoom = `M${pt(cx - w - 22, y)}L${pt(cx + w + 22, y)}C${pt(cx + w + 30, eyeY)} ${pt(cx + w + 26, jawY)} ${pt(cx + w + 6, bottom)}` +
      `L${pt(cx - w - 6, bottom)}C${pt(cx - w - 26, jawY)} ${pt(cx - w - 30, eyeY)} ${pt(cx - w - 22, y)}Z`;
    defs += `<mask id="${mask}" maskUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}">` +
      `<path d="${hairRoom}" fill="#fff"/><rect x="0" y="${bottom}" width="${SIZE}" height="${SIZE - bottom}" fill="#fff"/></mask>`;
    for (const l of ['hairBack', 'hairFront']) if (layers[l]) layers[l] = `<g mask="url(#${mask})">${layers[l]}</g>`;
  }
  // Hair length (fine-tune): shorter cuts hair off at a hem; longer is handled by the realistic shapes.
  const hairLength = traits.tweaks?.hairLength ?? 1;
  if (hairLength < 1) {
    const { jawY } = ctx.g;
    const hem = jawY + (480 - jawY) * Math.max(0, hairLength);
    const cut = ctx.uid('hairHem');
    defs += `<mask id="${cut}" maskUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}"><rect width="${SIZE}" height="${hem}" fill="#fff"/></mask>`;
    for (const l of ['hairBack', 'hairLocks', 'hairFront']) if (layers[l]) layers[l] = `<g mask="url(#${cut})">${layers[l]}</g>`;
  }
  // Age and expression: lines, folds and modelling on the face and neck.
  const am = ageModelling(ctx, ctx.g.age, realistic);
  const em = expressionModelling(ctx, traits.expression, realistic);
  if (motion.marks) {
    // Emotes show the face lines of another expression (smile crinkles, a furrowed brow).
    const posed = motion.marks.poses.slice(1).map((p) => expressionModelling(ctx, p, realistic));
    defs += posed.map((m) => m.defs).join('');
    em.marks = animator.swap(motion.marks, [em.marks, ...posed.map((m) => m.marks)]);
  }
  // Emote extras, faded in and out by their tracks: a blush, tears, snoring z's.
  if (motion.blush) {
    const b = blushMarkup(ctx);
    defs += b.defs;
    em.marks += animator.fade(motion.blush, b.markup);
  }
  if (motion.tears) em.marks += animator.fade(motion.tears, tearsMarkup(ctx, animator));
  if (motion.zzz) layers.accHead += animator.fade(motion.zzz, zzzMarkup(ctx, animator));
  if (motion.hearts) layers.accHead += animator.fade(motion.hearts, heartsMarkup(ctx, animator));
  defs += am.defs + em.defs;
  layers.marks += am.marks + em.marks;
  layers.shade += am.shade;
  const bm = buildModelling(ctx, traits.build, realistic);
  defs += bm.defs;
  layers.shade += bm.markup;
  if (realistic && layers.body) {
    const folds = clothFolds(ctx, bodyPath(ctx.g));
    defs += folds.defs;
    layers.body += folds.markup;
  }
  // Shoulder width: the clothing scales horizontally around the centre line.
  const sx = BUILDS[traits.build]?.shoulders ?? 1;
  if (sx !== 1) layers.body = `<g transform="translate(${CX},0) scale(${sx},1) translate(${-CX},0)">${layers.body}</g>`;
  if (realistic) {
    if (layers.background) {
      const dof = depthOfField(layers.background, ctx);
      defs += dof.defs;
      layers.background = dof.markup;
    }
  }
  let finish = '';
  if (realistic && def.finish !== false) {
    const lit = lightingGrade(ctx);
    defs += lit.defs;
    finish = lit.markup;
  }
  if (motion.brows && layers.brows) {
    // Emotes raise and tilt each brow about its middle, whatever its shape. Each side is
    // masked to its half of the face (a mask: resvg can panic on clipped blur filters).
    const { cx, eyeDX, browY } = ctx.g;
    const posed = (p) => ['left', 'right'].map((s) => {
      const side = s === 'left' ? -1 : 1;
      const q = sidePose(p, s);
      // Positive tilt drops the inner ends (towards the nose): anger.
      const rot = -side * (q.tilt ?? 0);
      return half(s, `<g transform="translate(0,${+(q.dy ?? 0).toFixed(2)}) rotate(${+rot.toFixed(2)},${pt(cx + side * (eyeDX - 2), browY)})">${layers.brows}</g>`);
    }).join('');
    layers.brows = animator.swap(motion.brows, [layers.brows, ...motion.brows.poses.slice(1).map(posed)]);
  }

  const frame = getPart('frame', traits.frame);
  const group = (names) => names.map((l) => layers[l] && `<g data-layer="${l}">${layers[l]}</g>`).join('');
  const background = group(['background']);
  // Head turn: each layer shifts sideways by its depth (parallax). The nose, nearest the
  // viewer, moves most; ears and the back of the hair, behind the turning axis, move
  // the other way; the shoulders don't turn. Facial layers foreshorten slightly.
  const turn = Math.max(-1, Math.min(1, traits.tweaks?.turn ?? traits.turn ?? 0)) * 0.8;
  const parallax = (l) => {
    const depth = TURN_DEPTH[l] ?? 0;
    if (!turn || !depth) return layers[l];
    const k = FORESHORTEN.has(l) ? 1 - Math.abs(turn) * 0.07 : 1;
    return `<g transform="translate(${+(turn * depth + CX).toFixed(2)},0) scale(${+k.toFixed(3)},1) translate(${-CX},0)">${layers[l]}</g>`;
  };
  for (const l of LAYERS) if (layers[l] && l !== 'background' && l !== 'frame') layers[l] = parallax(l);
  // Ears turn with the head individually: the near ear stays attached to the cheek, the far
  // ear tucks in behind it (one shared shift left one ear floating beside the face).
  if (turn && layers.ears) {
    const half = (side, dx) => {
      const id = ctx.uid('earHalf');
      const x = side < 0 ? -64 : CX;
      defs += `<clipPath id="${id}"><rect x="${x}" y="-64" width="${side < 0 ? CX + 64 : CX + 64}" height="${SIZE + 128}"/></clipPath>`;
      return `<g clip-path="url(#${id})"><g transform="translate(${+dx.toFixed(2)},0)">${layers.ears}</g></g>`;
    };
    const near = turn * 5, far = -turn * 16;
    // turn > 0: the face looks to the viewer's right, so the left ear is the near one.
    layers.ears = turn > 0 ? half(-1, near) + half(1, far) : half(1, near) + half(-1, far);
  }
  // Emotes move the head (and what's on it), not the shoulders: every head layer follows
  // the same animation, pivoting in the neck.
  if (motion.head) {
    const move = animator.mover(motion.head, [CX, ctx.g.bottom + 30]);
    for (const l of HEAD_LAYERS) if (layers[l]) layers[l] = move(layers[l]);
  }
  if (animator) defs += animator.defs();
  let figure = group(LAYERS.filter((l) => l !== 'frame' && l !== 'background'));
  // Framing: zoom the figure (not the backdrop) to a head close-up or out to the bust.
  const zoom = FRAMING[traits.framing];
  if (zoom) figure = `<g transform="translate(${CX},${zoom.y}) scale(${zoom.s}) translate(${-CX},${-zoom.y})">${figure}</g>`;
  let clip = (m) => m;
  if (frame?.clip) {
    // A mask rather than clip-path: resvg can panic on clipped groups containing blur filters.
    const mask = ctx.uid('frameMask');
    defs += `<mask id="${mask}" maskUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}"><circle cx="${CX}" cy="${CX}" r="${CX - 6}" fill="#fff"/></mask>`;
    clip = (m) => `<g mask="url(#${mask})">${m}</g>`;
  }
  // Transparent background: no backdrop, and everything painted over the full canvas (lighting,
  // engraving paper, canvas texture) is masked to the figure's silhouette.
  const transparent = !layers.background;
  let markup = clip(background + figure + finish) + (transparent ? '' : layers.frame);
  if (def.post) {
    // Post-processing styles get the pieces too, e.g. to treat the backdrop differently.
    const out = def.post({ content: markup, ctx, background, figure, frame: layers.frame, clip });
    defs += out.defs ?? '';
    markup = out.markup;
  }
  if (transparent) {
    const m = ctx.uid('alpha');
    const f = ctx.uid('alphaOnly');
    defs += `<filter id="${f}" filterUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}"><feColorMatrix type="matrix" values="0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 1 0"/></filter>` +
      `<mask id="${m}" maskUnits="userSpaceOnUse" x="0" y="0" width="${SIZE}" height="${SIZE}">${clip(`<g filter="url(#${f})">${maskCopy(figure)}</g>`)}</mask>`;
    markup = `<g mask="url(#${m})">${markup}</g>` + layers.frame;
  }
  return flattenOpacity(`<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${SIZE} ${SIZE}">` +
    `<defs>${defs}</defs>${markup}</svg>`);
}

// Sideways shift per layer at full head turn (px), and which layers foreshorten.
const TURN_DEPTH = {
  accBack: -14, hairBack: -16, neck: -3, hairLocks: -8, face: 5, marks: 9, eyes: 11, brows: 11,
  nose: 24, facialHair: 10, mouth: 14, mustache: 15, hairFront: 3, accFace: 12, accHead: 4,
};
// Layers that move with the head when an emote nods or shakes it.
const HEAD_LAYERS = ['hairBack', 'hairLocks', 'ears', 'face', 'marks', 'eyes', 'brows', 'nose', 'facialHair', 'mouth', 'mustache', 'hairFront', 'accFace', 'accHead'];
// Mouths that are part of a race (tusks, fangs) keep their shape when an emote moves the mouth.
const KEEP_MOUTH = new Set(['tusks', 'fangs']);
const FORESHORTEN = new Set(['face', 'marks', 'eyes', 'brows', 'nose', 'facialHair', 'mouth', 'mustache', 'accFace']);
// Framing zoom: scale about a point near the face (head) or the top of the canvas (bust).
const FRAMING = { head: { s: 1.32, y: 250 }, bust: { s: 0.8, y: 110 } };

/** Colours as rendered: hair greys with age; a saturation fine-tune applies to all. */
function portraitColors(traits) {
  const c = { ...traits.colors, hair: agedHair(traits.colors.hair, ageValue(traits)) };
  const sat = traits.tweaks?.saturation;
  if (sat !== undefined && sat !== 1) for (const k of Object.keys(c)) c[k] = saturate(c[k], sat);
  return c;
}

/** Face geometry for a portrait: face shape, build, and the realistic refinements. */
function geometryFor(shape, traits, realistic) {
  // The neck emerges from behind the jaw, so it stays narrower than the jaw:
  // wider, its top shows beside the face like a ghostly second jaw.
  const neck = (geo) => Math.min(geo.neckW * (BUILDS[traits.build]?.neck ?? 1), geo.jawW * (traits.build === 'muscular' || traits.build === 'heavy' ? 0.86 : 0.78));
  // Fine-tune: jaw width scales jaw and chin.
  const jaw = traits.tweaks?.jaw ?? 1;
  const tuned = jaw === 1 ? shape : { ...shape, jawW: shape.jawW * jaw, chinW: shape.chinW * jaw };
  const g = faceGeometry(buildShape(tuned, traits.build));
  g.neckW = neck(g);
  g.build = traits.build;
  g.age = ageValue(traits);
  // Eye size: the fine-tune, and slightly larger on younger faces.
  g.eyeScale = (traits.tweaks?.eyeSize ?? 1) * (1 + (0.35 - g.age) * 0.08);
  g.hairLength = traits.tweaks?.hairLength ?? 1;
  if (!realistic) return g;
  const r = realisticGeometry(g, traits.presentation, createRng(`${traits.seed}:asymmetry`));
  r.neckW = neck(r);
  return r;
}

/**
 * Rewrite element-level `opacity` on leaf shapes into fill/stroke opacity.
 * Visually equivalent for single shapes, but avoids per-element compositing
 * layers (tiny shapes like freckles or stars can make some rasterisers crash).
 */
export function flattenOpacity(svg) {
  return svg.replace(/<(circle|ellipse|path|rect|line|polygon|polyline)\b([^>]*?)\/>/g, (tag, name, attrs) => {
    const m = attrs.match(/\sopacity="([\d.]+)"/);
    if (!m) return tag;
    const o = Number(m[1]);
    let a = attrs.replace(m[0], '');
    for (const k of ['fill-opacity', 'stroke-opacity']) {
      const ex = a.match(new RegExp(`\\s${k}="([\\d.]+)"`));
      a = ex ? a.replace(ex[0], ` ${k}="${+(Number(ex[1]) * o).toFixed(3)}"`) : `${a} ${k}="${o}"`;
    }
    return `<${name}${a}/>`;
  });
}
