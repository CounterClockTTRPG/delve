import { registerPart } from '../registry.js';
import { pt, mirrorPath, mirrored, sampleCubic, decorateEdge } from '../geometry.js';
import { darken, lighten, mix } from '../color.js';

// ---------------------------------------------------------------- top silhouettes (left side -> right side)
export function arc(g, kind, rng) {
  const { cx, w, top, eyeY } = g;
  if (kind === 'afro') {
    const ecx = cx, ecy = eyeY - 30, rx = w + 64, ry = eyeY - top + 62;
    const pts = [];
    for (let i = 0; i <= 22; i++) {
      const a = Math.PI * (1.2 - (1.4 * i) / 22);
      pts.push([ecx + Math.cos(a) * rx, ecy - Math.sin(a) * ry]);
    }
    return { L: pts[0], R: pts[pts.length - 1], d: decorateEdge(pts, [ecx, ecy], 'curly', 7, rng) };
  }
  const pad = kind === 'close' ? 3 : 11;
  const h = { close: 9, tall: 62, smooth: 28, spiky: 26, curly: 30 }[kind] ?? 28;
  const sideY = eyeY - 6;
  const L = [cx - w - pad, sideY];
  const R = [cx + w + pad, sideY];
  const lean = kind === 'tall' ? 18 : 0;
  const T = [cx + lean, top - h];
  const l1 = [cx - w - pad - 2, top - h * 0.3];
  const l2 = [cx - w * 0.6 + lean, top - h];
  const r1 = [cx + w * 0.6 + lean, top - h];
  const r2 = [cx + w + pad + 2, top - h * 0.3];
  if (kind === 'spiky' || kind === 'curly') {
    const pts = [...sampleCubic(L, l1, l2, T, 6), ...sampleCubic(T, r1, r2, R, 6).slice(1)];
    const style = kind === 'spiky' ? 'spiky' : 'curly';
    return { L, R, d: decorateEdge(pts, [cx, eyeY + 10], style, kind === 'spiky' ? 20 : 6, rng) };
  }
  return { L, R, d: `C${pt(...l1)} ${pt(...l2)} ${pt(...T)}C${pt(...r1)} ${pt(...r2)} ${pt(...R)}` };
}

// ---------------------------------------------------------------- hairlines / fringes (right side -> left side)
export function fringe(g, kind, R, L, rng) {
  const { cx, w, top, eyeY, hairY: hy } = g;
  const X = (x) => cx + x;
  const end = `L${pt(...L)}`;
  switch (kind) {
    case 'short':
      return `L${pt(X(w - 3), eyeY - 28)}Q${pt(X(w - 6), hy)} ${pt(X(w * 0.45), hy - 3)}Q${pt(X(0), hy - 12)} ${pt(X(-w * 0.45), hy - 3)}` +
        `Q${pt(X(-w + 6), hy)} ${pt(X(-w + 3), eyeY - 28)}${end}`;
    case 'sidepart':
      return `L${pt(X(w - 3), eyeY - 30)}C${pt(X(w - 4), hy + 26)} ${pt(X(w * 0.35), hy + 30)} ${pt(X(-w * 0.05), hy + 14)}` +
        `C${pt(X(-w * 0.3), hy + 2)} ${pt(X(-w * 0.42), top + 4)} ${pt(X(-w * 0.5), top + 10)}` +
        `C${pt(X(-w * 0.75), hy - 4)} ${pt(X(-w + 4), hy + 8)} ${pt(X(-w + 3), eyeY - 30)}${end}`;
    case 'middle':
      return `L${pt(X(w - 2), eyeY - 18)}C${pt(X(w - 6), hy + 6)} ${pt(X(w * 0.25), hy - 10)} ${pt(X(0), top + 10)}` +
        `C${pt(X(-w * 0.25), hy - 10)} ${pt(X(-w + 6), hy + 6)} ${pt(X(-w + 2), eyeY - 18)}${end}`;
    case 'bangs': {
      const y = hy + 40;
      let d = `L${pt(X(w - 1), eyeY - 10)}L${pt(X(w - 6), y)}`;
      const n = 6;
      for (let i = 0; i < n; i++) {
        const x0 = w - 6 - ((2 * w - 12) * i) / n;
        const x1 = w - 6 - ((2 * w - 12) * (i + 1)) / n;
        d += `Q${pt(X((x0 + x1) / 2), y + 8 + (rng ? rng.range(-2, 3) : 0))} ${pt(X(x1), y + (i === n - 1 ? 0 : rng ? rng.range(-3, 2) : 0))}`;
      }
      return d + `L${pt(X(-w + 1), eyeY - 10)}${end}`;
    }
    case 'buzz':
      return `L${pt(X(w - 3), eyeY - 32)}Q${pt(X(w - 6), hy - 2)} ${pt(X(w * 0.45), hy - 6)}Q${pt(X(0), hy - 12)} ${pt(X(-w * 0.45), hy - 6)}` +
        `Q${pt(X(-w + 6), hy - 2)} ${pt(X(-w + 3), eyeY - 32)}${end}`;
    case 'receding':
      return `L${pt(X(w - 3), eyeY - 34)}Q${pt(X(w - 8), top + 12)} ${pt(X(w * 0.35), top + 6)}Q${pt(X(0), top + 22)} ${pt(X(-w * 0.35), top + 6)}` +
        `Q${pt(X(-w + 8), top + 12)} ${pt(X(-w + 3), eyeY - 34)}${end}`;
    case 'curly':
    case 'afro': {
      const start = kind === 'afro' ? [X(w + 4), eyeY + 34] : [X(w - 3), eyeY - 24];
      const pts = [];
      for (let i = 0; i <= 8; i++) {
        const t = i / 8;
        const x = w - 3 - (2 * w - 6) * t;
        pts.push([X(x), hy + 4 + Math.sin(t * Math.PI) * -10]);
      }
      let d = `L${pt(...start)}`;
      if (kind === 'afro') d += `L${pt(X(w - 3), eyeY - 20)}`;
      d += `L${pt(...pts[0])}` + decorateEdge(pts, [cx, top - 60], 'curly', -6, rng);
      if (kind === 'afro') d += `L${pt(X(-w + 3), eyeY - 20)}L${pt(X(-w - 4), eyeY + 34)}`;
      else d += `L${pt(X(-w + 3), eyeY - 24)}`;
      return d + end;
    }
    default:
      return end;
  }
}

// ---------------------------------------------------------------- back masses (behind head and body)
export function back(g, kind, rng) {
  const { cx, w, top, eyeY, jawY } = g;
  switch (kind) {
    case 'bob':
      return mirrorPath(cx, [0, top - 28], [
        [[w * 0.8, top - 28], [w + 24, top + 16], [w + 24, eyeY]],
        [[w + 26, eyeY + 50], [w + 26, jawY + 4], [w + 20, jawY + 22]],
        [[w * 0.6, jawY + 30], [w * 0.3, jawY + 20], [0, jawY + 10]],
      ]);
    case 'long':
      return mirrorPath(cx, [0, top - 28], [
        [[w * 0.8, top - 28], [w + 24, top + 20], [w + 26, eyeY]],
        [[w + 30, eyeY + 90], [w + 44, 400], [w + 38, 466]],
        [[w * 0.6, 480], [w * 0.3, 450], [0, 450]],
      ]);
    case 'curlyLong': {
      const pts = [];
      for (let i = 0; i <= 16; i++) {
        const a = Math.PI * (1.25 - (1.5 * i) / 16);
        pts.push([cx + Math.cos(a) * (w + 44), eyeY + 40 - Math.sin(a) * (eyeY - top + 110)]);
      }
      return `M${pt(...pts[0])}${decorateEdge(pts, [cx, eyeY + 40], 'curly', 8, rng)}L${pt(cx + w, 470)}L${pt(cx - w, 470)}Z`;
    }
    case 'ponytail':
      return `M${pt(cx + w - 30, top + 20)}C${pt(cx + w + 56, top + 10)} ${pt(cx + w + 64, 330)} ${pt(cx + w + 36, 440)}` +
        `C${pt(cx + w + 30, 380)} ${pt(cx + w + 18, 320)} ${pt(cx + w - 6, eyeY + 10)}Z`;
    case 'bun':
      return `M${pt(cx + 36, top - 26)}a36,34 0 1,0 -72,0a36,34 0 1,0 72,0Z`;
    case 'topknot':
      return `M${pt(cx + 23, top - 20)}a23,23 0 1,0 -46,0a23,23 0 1,0 46,0Z`;
    case 'spaceBuns':
      return [-1, 1].map((k) => `M${pt(cx + k * w * 0.6 + 26, top - 26)}a26,25 0 1,0 -52,0a26,25 0 1,0 52,0Z`).join('');
    case 'wavyLong': {
      // Long hair whose sides fall in loose waves.
      const pts = [];
      for (let i = 0; i <= 12; i++) {
        const t = i / 12, y = eyeY - 10 + t * (470 - eyeY + 10);
        pts.push([cx + w + 30 + Math.sin(t * Math.PI * 3) * 8 + t * 10, y]);
      }
      const right = pts.map((p) => pt(...p)).join('L');
      const left = pts.slice().reverse().map(([x, y]) => pt(2 * cx - x, y)).join('L');
      return `M${pt(cx - w - 24, eyeY - 10)}C${pt(cx - w - 24, top - 10)} ${pt(cx - w * 0.6, top - 30)} ${pt(cx, top - 30)}` +
        `C${pt(cx + w * 0.6, top - 30)} ${pt(cx + w + 24, top - 10)} ${pt(cx + w + 30, eyeY - 10)}L${right}L${pt(cx, 470)}L${left}Z`;
    }
    default:
      return null;
  }
}

// ---------------------------------------------------------------- locks (in front of shoulders, behind face)
/** Right-hand lock of long hair falling in front of the shoulder. */
export const longLockPath = ({ cx, w, eyeY }) =>
  `M${pt(cx + w - 4, eyeY - 10)}C${pt(cx + w + 26, eyeY + 70)} ${pt(cx + w + 36, 410)} ${pt(cx + w + 26, 488)}` +
  `C${pt(cx + w + 10, 470)} ${pt(cx + w - 2, 420)} ${pt(cx + w - 12, 360)}Z`;

function locks(g, kind, hair, line) {
  const { cx, w, eyeY } = g;
  if (kind === 'long') {
    const d = longLockPath(g);
    const strand = `<path d="${d}" fill="${hair}" stroke="${line}" stroke-width="3" stroke-linejoin="round"/>` +
      `<path d="M${pt(cx + w + 6, eyeY + 40)}C${pt(cx + w + 20, 380)} ${pt(cx + w + 22, 430)} ${pt(cx + w + 18, 470)}" fill="none" stroke="${line}" stroke-width="1.6" opacity="0.5"/>`;
    return strand + mirrored(cx, strand);
  }
  if (kind === 'dreads') {
    // Rope-like locks hanging from around the head over the shoulders.
    let d = '';
    for (let i = 0; i < 5; i++) {
      const x0 = cx + w - 6 + i * 6, x1 = cx + w + 4 + i * 9;
      const y1 = eyeY + 150 + (i % 2) * 40 + i * 8;
      const one = `<path d="M${pt(x0, eyeY - 12 + i * 6)}Q${pt(x0 + 10, eyeY + 60)} ${pt(x1, y1)}" fill="none" stroke="${line}" stroke-width="13" stroke-linecap="round"/>` +
        `<path d="M${pt(x0, eyeY - 12 + i * 6)}Q${pt(x0 + 10, eyeY + 60)} ${pt(x1, y1)}" fill="none" stroke="${i % 2 ? darken(hair, 0.08) : hair}" stroke-width="9" stroke-linecap="round"/>`;
      d += one;
    }
    return d + mirrored(cx, d);
  }
  if (kind === 'braids') {
    let b = '';
    for (let i = 0; i < 9; i++) {
      const y = eyeY + 40 + i * 21;
      const x = cx + w + 8 + Math.min(i, 5) * 2.4;
      b += `<ellipse cx="${x}" cy="${y}" rx="13" ry="12" fill="${hair}" stroke="${line}" stroke-width="2.6"/>` +
        `<path d="M${pt(x - 9, y - 4)}Q${pt(x, y + 4)} ${pt(x + 9, y - 4)}" fill="none" stroke="${line}" stroke-width="1.6" opacity="0.6"/>`;
    }
    b += `<rect x="${cx + w + 12}" y="${eyeY + 228}" width="18" height="8" rx="3" fill="${darken(hair, 0.4)}"/>`;
    return b + mirrored(cx, b);
  }
  return '';
}

/** Cornrows: braided rows running from the hairline back over the crown. */
export function cornrowLines(g, hair, line) {
  let s = '';
  for (let i = -3; i <= 3; i++) {
    const x0 = g.cx + i * g.w * 0.24, x1 = g.cx + i * g.w * 0.34;
    // Rows end on the crown, inside the close-cut scalp line.
    const d = `M${pt(x0, g.hairY + 4 - Math.abs(i) * 2)}Q${pt(x0 + i * 3, g.top + 14)} ${pt(x1 * 0.6 + g.cx * 0.4, g.top - 2 + Math.abs(i) * 3)}`;
    s += `<path d="${d}" fill="none" stroke="${line}" stroke-width="7" stroke-linecap="round" opacity="0.8"/>` +
      `<path d="${d}" fill="none" stroke="${hair}" stroke-width="5" stroke-linecap="round" stroke-dasharray="3 2"/>`;
  }
  return s;
}

// ---------------------------------------------------------------- extra top pieces
export function extra(g, kind) {
  const { cx, w, top, hairY: hy } = g;
  if (kind === 'mohawk') {
    return `M${pt(cx - 22, hy + 6)}L${pt(cx - 26, top - 20)}L${pt(cx - 40, top - 44)}L${pt(cx - 16, top - 42)}L${pt(cx - 12, top - 84)}` +
      `L${pt(cx + 4, top - 50)}L${pt(cx + 20, top - 80)}L${pt(cx + 20, top - 40)}L${pt(cx + 42, top - 46)}L${pt(cx + 26, top - 16)}` +
      `L${pt(cx + 22, hy + 6)}Q${pt(cx, hy + 14)} ${pt(cx - 22, hy + 6)}Z`;
  }
  if (kind === 'undercut') {
    return `M${pt(cx - w * 0.8, hy + 8)}C${pt(cx - w * 0.98, top - 24)} ${pt(cx - w * 0.1, top - 52)} ${pt(cx + w * 0.45, top - 44)}` +
      `C${pt(cx + w + 6, top - 38)} ${pt(cx + w + 20, top + 6)} ${pt(cx + w + 4, top + 34)}` +
      `C${pt(cx + w * 0.9, top + 18)} ${pt(cx + w * 0.75, hy)} ${pt(cx + w * 0.7, hy + 10)}` +
      `Q${pt(cx, hy - 10)} ${pt(cx - w * 0.8, hy + 8)}Z`;
  }
  return null;
}

// ---------------------------------------------------------------- style table
export const styles = {
  bald: { label: 'Bald' },
  buzz: { label: 'Buzz cut', arc: 'close', fringe: 'buzz', blend: 0.55 },
  short: { label: 'Short', arc: 'smooth', fringe: 'short' },
  sidepart: { label: 'Side part', arc: 'smooth', fringe: 'sidepart' },
  spiky: { label: 'Spiky', arc: 'spiky', fringe: 'short' },
  curly: { label: 'Curly', arc: 'curly', fringe: 'curly' },
  afro: { label: 'Afro', arc: 'afro', fringe: 'afro' },
  pompadour: { label: 'Pompadour', arc: 'tall', fringe: 'short' },
  receding: { label: 'Receding', arc: 'close', fringe: 'receding' },
  bob: { label: 'Bob with bangs', arc: 'smooth', fringe: 'bangs', back: 'bob' },
  long: { label: 'Long', arc: 'smooth', fringe: 'middle', back: 'long', locks: 'long' },
  longSwept: { label: 'Long side-swept', arc: 'smooth', fringe: 'sidepart', back: 'long', locks: 'long' },
  curlyLong: { label: 'Long curls', arc: 'curly', fringe: 'curly', back: 'curlyLong' },
  ponytail: { label: 'Ponytail', arc: 'smooth', fringe: 'middle', back: 'ponytail' },
  bun: { label: 'Bun', arc: 'smooth', fringe: 'middle', back: 'bun' },
  topknot: { label: 'Top knot', arc: 'close', fringe: 'buzz', blend: 0.5, back: 'topknot' },
  braids: { label: 'Braids', arc: 'smooth', fringe: 'middle', back: 'bob', locks: 'braids' },
  mohawk: { label: 'Mohawk', arc: 'close', fringe: 'buzz', blend: 0.45, extra: 'mohawk' },
  undercut: { label: 'Undercut', arc: 'close', fringe: 'buzz', blend: 0.45, extra: 'undercut' },
  wavy: { label: 'Long waves', arc: 'smooth', fringe: 'middle', back: 'wavyLong' },
  pixie: { label: 'Pixie cut', arc: 'close', fringe: 'sidepart' },
  dreadlocks: { label: 'Dreadlocks', arc: 'smooth', fringe: 'middle', back: 'bob', locks: 'dreads' },
  cornrows: { label: 'Cornrows', arc: 'close', fringe: 'buzz', blend: 0.7, rows: true },
  slickedBack: { label: 'Slicked back', arc: 'smooth', fringe: 'receding', sleek: true },
  manBun: { label: 'Man bun', arc: 'smooth', fringe: 'buzz', back: 'bun' },
  spaceBuns: { label: 'Space buns', arc: 'smooth', fringe: 'middle', back: 'spaceBuns' },
};

for (const [id, s] of Object.entries(styles)) {
  registerPart('hair', {
    id,
    label: s.label,
    style: s,
    render({ g, colors, rng, uid }) {
      const hair = colors.hair;
      const line = darken(hair, 0.55);
      const stroke = `stroke="${line}" stroke-width="3" stroke-linejoin="round"`;
      const out = {};
      const b = back(g, s.back, rng);
      if (b) out.hairBack = `<path d="${b}" fill="${darken(hair, 0.12)}" ${stroke}/>`;
      if (s.back === 'ponytail') out.hairBack += `<rect x="${g.cx + g.w - 4}" y="${g.top + 18}" width="14" height="20" rx="4" transform="rotate(30 ${g.cx + g.w} ${g.top + 28})" fill="${darken(hair, 0.45)}"/>`;
      if (s.locks) out.hairLocks = locks(g, s.locks, hair, line);
      if (s.arc) {
        const a = arc(g, s.arc, rng);
        const d = `M${pt(...a.L)}${a.d}${fringe(g, s.fringe, a.R, a.L, rng)}Z`;
        const fill = s.blend ? mix(colors.skin, hair, s.blend) : hair;
        const clip = uid('hairClip');
        let front = `<path d="${d}" fill="${fill}" stroke="${s.blend ? darken(fill, 0.3) : line}" stroke-width="${s.blend ? 1.5 : 3}" stroke-linejoin="round"/>`;
        if (!s.blend) {
          front += `<clipPath id="${clip}"><path d="${d}"/></clipPath><g clip-path="url(#${clip})">` +
            `<path d="M${pt(g.cx - g.w * 0.55, g.top + 4)}Q${pt(g.cx, g.top - 26)} ${pt(g.cx + g.w * 0.55, g.top + 4)}" fill="none" stroke="${lighten(hair, 0.35)}" stroke-width="8" stroke-linecap="round" opacity="0.35"/></g>`;
        }
        const ex = extra(g, s.extra);
        if (ex) front += `<path d="${ex}" fill="${hair}" ${stroke}/>`;
        if (s.rows) front += cornrowLines(g, hair, line);
        if (s.sleek) front += `<g clip-path="url(#${clip})">${[-0.5, -0.2, 0.15, 0.45].map((t) => `<path d="M${pt(g.cx + g.w * t, g.hairY)}Q${pt(g.cx + g.w * t * 1.2, g.top - 10)} ${pt(g.cx + g.w * t * 1.6, g.top - 30)}" fill="none" stroke="${lighten(hair, 0.3)}" stroke-width="2.5" opacity="0.5"/>`).join('')}</g>`;
        out.hairFront = front;
      }
      return out;
    },
  });
}
