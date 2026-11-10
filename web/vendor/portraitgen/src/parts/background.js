import { registerPart } from '../registry.js';
import { SIZE, CX, blurFilter } from '../geometry.js';
import { darken, lighten, mix } from '../color.js';
import { grainFilter } from '../realism.js';

const full = (fill) => `<rect width="${SIZE}" height="${SIZE}" fill="${fill}"/>`;

const lin = (id, stops, x2 = 0, y2 = 1) => `<linearGradient id="${id}" x1="0" y1="0" x2="${x2}" y2="${y2}">${stops.map(([o, c]) => `<stop offset="${o}" stop-color="${c}"/>`).join('')}</linearGradient>`;

/** Stone blocks filling a path region (for walls, arches, ruins). */
function masonry(rng, stone, x0, y0, x1, y1, bw = 46, bh = 30) {
  let s = '';
  for (let r = 0, y = y0; y < y1; r++, y += bh) {
    for (let x = x0 - (r % 2 ? bw / 2 : 0); x < x1; x += bw) {
      s += `<rect x="${x + 1.5}" y="${y + 1.5}" width="${bw - 3}" height="${bh - 3}" rx="3" fill="${mix(stone, '#000', rng.range(0, 0.16))}"/>`;
    }
  }
  return s;
}

const backgrounds = {
  // ---------------- illustrated fantasy settings
  archway: {
    label: 'Stone archway',
    render({ colors, uid, rng }) {
      const stone = mix(colors.background, '#9a8a72', 0.6);
      const sky = uid('sky');
      const clip = uid('wall');
      // A wall with a round-headed arch opening onto bright light behind the figure.
      const opening = `M${CX - 150},${SIZE}V200A150,150 0 0,1 ${CX + 150},200V${SIZE}Z`;
      return lin(sky, [[0, lighten(colors.background, 0.7)], [1, lighten(colors.background, 0.35)]]) +
        `<clipPath id="${clip}"><path d="M0,0H${SIZE}V${SIZE}H0Z${opening}" clip-rule="evenodd"/></clipPath>` +
        full(`url(#${sky})`) +
        `<rect x="${CX - 150}" y="380" width="300" height="140" fill="${lighten(stone, 0.2)}"/>` +
        `<g clip-path="url(#${clip})">${full(darken(stone, 0.45))}${masonry(rng, stone, 0, 0, SIZE, SIZE)}</g>` +
        // Voussoirs around the arch and its shadowed reveal.
        `<path d="M${CX - 150},200A150,150 0 0,1 ${CX + 150},200" fill="none" stroke="${darken(stone, 0.1)}" stroke-width="26"/>` +
        `<path d="M${CX - 150},200A150,150 0 0,1 ${CX + 150},200" fill="none" stroke="${darken(stone, 0.45)}" stroke-width="26" stroke-dasharray="3 31"/>` +
        `<path d="M${CX + 137},200V${SIZE}" stroke="${darken(stone, 0.4)}" stroke-width="12" opacity="0.6"/>`;
    },
  },
  ruins: {
    label: 'Castle ruins',
    render({ colors, uid, rng }) {
      const sky = uid('sky');
      const far = mix(colors.background, '#8a8a90', 0.5);
      let towers = '';
      for (let i = 0; i < 6; i++) {
        const x = rng.int(-20, SIZE - 40), w = rng.int(40, 80), h = rng.int(160, 330);
        const top = SIZE - h;
        // Broken tops and gothic window slits.
        let d = `M${x},${SIZE}V${top + 20}`;
        for (let k = 0; k <= 4; k++) d += `L${x + (w * k) / 4},${top + rng.int(0, 30)}`;
        d += `V${SIZE}Z`;
        towers += `<path d="${d}" fill="${darken(far, rng.range(0.05, 0.35))}"/>`;
        for (let k = 0; k < 3; k++) towers += `<path d="M${x + w * 0.35},${top + 60 + k * 60}v-18a${w * 0.15},${w * 0.15} 0 0,1 ${w * 0.3},0v18Z" fill="${lighten(colors.background, 0.4)}" opacity="0.7"/>`;
      }
      return lin(sky, [[0, darken(colors.background, 0.2)], [0.7, lighten(colors.background, 0.35)], [1, lighten(colors.background, 0.5)]]) +
        full(`url(#${sky})`) + towers +
        `<rect y="440" width="${SIZE}" height="72" fill="${darken(far, 0.45)}"/>`;
    },
  },
  candlehall: {
    label: 'Candlelit hall',
    render({ colors, uid, rng }) {
      const glow = uid('glow');
      const blur = uid('blur');
      const c = mix(colors.background, '#2a1c12', 0.65);
      let flames = '';
      for (let i = 0; i < 26; i++) {
        const x = rng.int(0, SIZE), y = rng.int(230, 470), s = rng.range(0.6, 1.4);
        flames += `<rect x="${x - 2 * s}" y="${y}" width="${4 * s}" height="${18 * s}" fill="#e8dcc0" opacity="0.8"/>` +
          `<circle cx="${x}" cy="${y - 4 * s}" r="${10 * s}" fill="#ffb24a" opacity="0.35"/><ellipse cx="${x}" cy="${y - 4 * s}" rx="${2.2 * s}" ry="${4 * s}" fill="#fff2c0"/>`;
      }
      let pillars = '';
      for (const x of [40, 150, 362, 472]) pillars += `<rect x="${x - 22}" y="0" width="44" height="${SIZE}" fill="${darken(c, 0.4)}"/>`;
      return `<radialGradient id="${glow}" cx="0.5" cy="0.75" r="0.8"><stop offset="0" stop-color="${mix(c, '#c07030', 0.5)}"/><stop offset="1" stop-color="${darken(c, 0.6)}"/></radialGradient>` +
        `${blurFilter(blur, 2)}${full(`url(#${glow})`)}<g filter="url(#${blur})">${pillars}${flames}</g>`;
    },
  },
  market: {
    label: 'Market street',
    render({ colors, uid, rng }) {
      const sky = uid('sky');
      const wall = mix(colors.background, '#c8b490', 0.55);
      let houses = '';
      // Timber-framed houses receding to a vanishing point, awnings over stalls.
      for (const side of [-1, 1]) {
        for (let i = 0; i < 3; i++) {
          const x0 = side < 0 ? i * 70 : SIZE - (i + 1) * 70, w = 70, top = 60 + i * 50;
          houses += `<rect x="${x0}" y="${top}" width="${w}" height="${SIZE - top}" fill="${mix(wall, '#000', 0.08 * i)}"/>` +
            `<path d="M${x0},${top + 50}H${x0 + w}M${x0 + w / 2},${top}V${SIZE}M${x0},${top}L${x0 + w},${top + 50}" stroke="${darken(wall, 0.55)}" stroke-width="5"/>` +
            `<path d="M${x0 - 6},${300 + i * 20}L${x0 + w + 6},${300 + i * 20}L${x0 + w - 4},${330 + i * 20}L${x0 + 4},${330 + i * 20}Z" fill="${rng.pick(['#9a3a2a', '#c0902a', '#3a6a5a'])}"/>`;
        }
      }
      return lin(sky, [[0, lighten(colors.background, 0.55)], [1, lighten(colors.background, 0.25)]]) +
        full(`url(#${sky})`) + houses + `<rect y="430" width="${SIZE}" height="82" fill="${darken(wall, 0.25)}"/>`;
    },
  },
  birches: {
    label: 'Birch forest',
    render({ colors, uid, rng }) {
      const sky = uid('sky');
      let trees = '';
      for (let i = 0; i < 14; i++) {
        const x = rng.int(-10, SIZE + 10), w = rng.int(8, 26), shade = rng.range(0, 0.25);
        trees += `<rect x="${x}" y="0" width="${w}" height="${SIZE}" fill="${mix('#f2efe6', '#000', shade)}"/>`;
        for (let k = 0; k < 9; k++) trees += `<rect x="${x + rng.range(0, w * 0.5)}" y="${rng.int(0, SIZE)}" width="${rng.range(w * 0.3, w * 0.8)}" height="${rng.range(2, 5)}" fill="#2a2620" opacity="0.8"/>`;
      }
      return lin(sky, [[0, lighten(colors.background, 0.6)], [1, mix(colors.background, '#6a8a4a', 0.4)]]) + full(`url(#${sky})`) + trees;
    },
  },
  mountains: {
    label: 'Mountains',
    render({ colors, uid, rng }) {
      const sky = uid('sky');
      let ranges = '';
      for (let r = 0; r < 3; r++) {
        let d = `M0,${SIZE}`;
        for (let x = 0; x <= SIZE + 40; x += 40) d += `L${x},${180 + r * 70 + rng.int(-50, 40)}`;
        d += `L${SIZE},${SIZE}Z`;
        const c = mix(colors.background, '#4a5a6a', 0.3 + r * 0.25);
        ranges += `<path d="${d}" fill="${lighten(c, 0.35 - r * 0.15)}"/>`;
        // Snow on the farthest peaks.
        if (r === 0) ranges += `<path d="${d}" fill="none" stroke="#f6f6f8" stroke-width="10" stroke-dasharray="60 20" opacity="0.7"/>`;
      }
      return lin(sky, [[0, lighten(colors.background, 0.45)], [1, lighten(colors.background, 0.75)]]) + full(`url(#${sky})`) + ranges;
    },
  },
  // Nothing behind the figure: the portrait is exported with a transparent background.
  transparent: { label: 'Transparent', render: () => '' },
  solid: { label: 'Solid', render: ({ colors }) => full(colors.background) },
  studio: {
    label: 'Studio light',
    render({ colors, uid }) {
      const id = uid('bg');
      return `<radialGradient id="${id}" cx="0.5" cy="0.38" r="0.75"><stop offset="0" stop-color="${lighten(colors.background, 0.35)}"/><stop offset="1" stop-color="${darken(colors.background, 0.3)}"/></radialGradient>${full(`url(#${id})`)}`;
    },
  },
  pastel: {
    label: 'Pastel disc',
    render: ({ colors }) => full(lighten(colors.background, 0.45)) + `<circle cx="${CX}" cy="250" r="190" fill="${lighten(colors.background, 0.15)}"/>`,
  },
  urban: {
    label: 'Bokeh',
    render({ colors, uid, rng }) {
      const id = uid('bg');
      const blur = uid('blur');
      let dots = '';
      for (let i = 0; i < 18; i++) {
        const c = rng.pick([colors.accent, lighten(colors.background, 0.5), '#ffd98a']);
        dots += `<circle cx="${rng.int(0, SIZE)}" cy="${rng.int(0, 360)}" r="${rng.int(10, 34)}" fill="${c}" opacity="${rng.range(0.15, 0.45).toFixed(2)}"/>`;
      }
      return `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${darken(colors.background, 0.25)}"/><stop offset="1" stop-color="${darken(colors.background, 0.6)}"/></linearGradient>` +
        `${blurFilter(blur, 4)}${full(`url(#${id})`)}<g filter="url(#${blur})">${dots}</g>`;
    },
  },
  parchment: {
    label: 'Parchment',
    render({ colors, uid }) {
      const id = uid('bg');
      return `<radialGradient id="${id}" cx="0.5" cy="0.45" r="0.72"><stop offset="0" stop-color="${lighten(colors.background, 0.3)}"/><stop offset="0.7" stop-color="${colors.background}"/><stop offset="1" stop-color="${darken(colors.background, 0.45)}"/></radialGradient>${full(`url(#${id})`)}`;
    },
  },
  forest: {
    label: 'Forest',
    render({ colors, uid, rng }) {
      const id = uid('bg');
      const blur = uid('blur');
      let trees = '';
      for (let i = 0; i < 9; i++) {
        const x = rng.int(-20, SIZE + 20);
        const w = rng.int(14, 34);
        trees += `<rect x="${x}" y="0" width="${w}" height="${SIZE}" fill="${darken(colors.background, rng.range(0.3, 0.6))}" opacity="0.7"/>`;
      }
      return `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${lighten(colors.background, 0.25)}"/><stop offset="1" stop-color="${darken(colors.background, 0.45)}"/></linearGradient>` +
        `${blurFilter(blur, 3)}${full(`url(#${id})`)}<g filter="url(#${blur})">${trees}</g>` +
        `<rect width="${SIZE}" height="${SIZE}" fill="${lighten(colors.background, 0.5)}" opacity="0.08"/>`;
    },
  },
  dungeon: {
    label: 'Stone wall',
    render({ colors, rng }) {
      const stone = darken(colors.background, 0.35);
      let bricks = full(darken(stone, 0.45));
      for (let row = 0; row < 11; row++) {
        const off = row % 2 ? -32 : 0;
        for (let col = 0; col < 9; col++) {
          bricks += `<rect x="${off + col * 64 + 2}" y="${row * 48 + 2}" width="60" height="44" rx="5" fill="${mix(stone, '#000', rng.range(0, 0.18))}"/>`;
        }
      }
      return bricks +
        `<rect width="${SIZE}" height="${SIZE}" fill="${colors.accent}" opacity="0.08"/>`;
    },
  },
  sunburst: {
    label: 'Sunburst',
    render({ colors }) {
      let rays = full(colors.background);
      for (let i = 0; i < 24; i += 2) {
        const a0 = (i / 24) * Math.PI * 2, a1 = ((i + 1) / 24) * Math.PI * 2;
        rays += `<path d="M${CX},250L${CX + Math.cos(a0) * 600},${250 + Math.sin(a0) * 600}L${CX + Math.cos(a1) * 600},${250 + Math.sin(a1) * 600}Z" fill="${lighten(colors.background, 0.18)}"/>`;
      }
      return rays;
    },
  },
  grid: {
    label: 'Holo grid',
    render({ colors, uid }) {
      const id = uid('bg');
      const base = darken(colors.background, 0.55);
      // Built as two compound paths: resvg mishandles many zero-width <line> boxes.
      let floor = '';
      for (let i = -8; i <= 8; i++) floor += `M${CX + i * 20},300L${CX + i * 110},${SIZE}`;
      for (let j = 0; j < 7; j++) floor += `M0,${(300 + Math.pow(j / 6, 1.8) * 212).toFixed(1)}H${SIZE}`;
      let wall = '';
      for (let i = 0; i < 12; i++) wall += `M${i * 48 + 8},0V300`;
      const lines = `<path d="${floor}" fill="none"/><path d="${wall}" fill="none" stroke-opacity="0.3"/>`;
      return `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${base}"/><stop offset="0.6" stop-color="${mix(base, colors.accent, 0.18)}"/><stop offset="1" stop-color="${base}"/></linearGradient>` +
        full(`url(#${id})`) + `<g stroke="${colors.accent}" stroke-width="1.2" stroke-opacity="0.45">${lines}</g>`;
    },
  },
  nebula: {
    label: 'Nebula',
    render({ colors, uid, rng }) {
      const blur = uid('blur');
      let stars = '';
      for (let i = 0; i < 60; i++) stars += `<circle cx="${rng.int(0, SIZE)}" cy="${rng.int(0, SIZE)}" r="${rng.range(0.5, 1.8).toFixed(1)}" fill="#fff" opacity="${rng.range(0.3, 1).toFixed(2)}"/>`;
      return full(darken(colors.background, 0.75)) +
        `${blurFilter(blur, 40)}` +
        `<g filter="url(#${blur})"><circle cx="${rng.int(60, 200)}" cy="${rng.int(60, 200)}" r="120" fill="${colors.background}" opacity="0.8"/>` +
        `<circle cx="${rng.int(300, 460)}" cy="${rng.int(200, 420)}" r="140" fill="${colors.accent}" opacity="0.45"/></g>${stars}`;
    },
  },
  hex: {
    label: 'Hex mesh',
    render({ colors }) {
      const r = 26, h = Math.sqrt(3) * r;
      let hexes = '';
      for (let row = -1; row < 13; row++) {
        for (let col = -1; col < 14; col++) {
          const x = col * 1.5 * r, y = row * h + (col % 2 ? h / 2 : 0);
          let d = '';
          for (let k = 0; k < 6; k++) d += `${k ? 'L' : 'M'}${(x + r * Math.cos((k * Math.PI) / 3)).toFixed(1)},${(y + r * Math.sin((k * Math.PI) / 3)).toFixed(1)}`;
          hexes += `<path d="${d}Z"/>`;
        }
      }
      return full(darken(colors.background, 0.6)) + `<g fill="none" stroke="${colors.accent}" stroke-width="1.5" opacity="0.25">${hexes}</g>` +
        `<circle cx="${CX}" cy="240" r="210" fill="${colors.background}" opacity="0.18"/>`;
    },
  },
  // ---------------- photographic backdrops (made for the realistic style, fine in any)
  canvas: {
    label: 'Painted canvas',
    render({ colors, uid, rng }) {
      const id = uid('bg');
      const mottle = uid('mottle');
      const c = colors.background;
      return `<radialGradient id="${id}" cx="0.42" cy="0.36" r="0.8"><stop offset="0" stop-color="${lighten(c, 0.28)}"/><stop offset="0.55" stop-color="${c}"/><stop offset="1" stop-color="${darken(c, 0.55)}"/></radialGradient>` +
        grainFilter(mottle, { fx: 0.01, octaves: 4, strength: 0.7, rng }) +
        full(`url(#${id})`) + `<rect width="${SIZE}" height="${SIZE}" fill="#808080" filter="url(#${mottle})" opacity="0.22"/>`;
    },
  },
  hearth: {
    label: 'Firelit hall',
    render({ colors, uid, rng }) {
      const id = uid('bg');
      const blur = uid('blur');
      const c = mix(colors.background, '#3a2416', 0.6);
      let embers = '';
      for (let i = 0; i < 16; i++) {
        embers += `<circle cx="${rng.int(0, SIZE)}" cy="${rng.int(40, 380)}" r="${rng.int(6, 22)}" fill="${rng.pick(['#ffb050', '#ff8a30', '#ffd890'])}" opacity="${rng.range(0.12, 0.4).toFixed(2)}"/>`;
      }
      let beams = '';
      for (let i = 0; i < 4; i++) beams += `<rect x="${rng.int(-20, SIZE)}" y="0" width="${rng.int(24, 46)}" height="${SIZE}" fill="${darken(c, 0.55)}" opacity="0.6"/>`;
      return `<linearGradient id="${id}" x1="0" y1="0" x2="1" y2="0.3"><stop offset="0" stop-color="${mix(c, '#e07a30', 0.35)}"/><stop offset="0.5" stop-color="${c}"/><stop offset="1" stop-color="${darken(c, 0.6)}"/></linearGradient>` +
        `${blurFilter(blur, 8)}${full(`url(#${id})`)}<g filter="url(#${blur})">${beams}<circle cx="40" cy="300" r="150" fill="#ff9a40" opacity="0.35"/>${embers}</g>`;
    },
  },
  corridor: {
    label: 'Starship corridor',
    render({ colors, uid }) {
      const id = uid('bg');
      const blur = uid('blur');
      const base = darken(colors.background, 0.5);
      let panels = '';
      for (let i = 0; i < 5; i++) {
        // Panels recede towards a vanishing point behind the head.
        const t = i / 5, x0 = t * 200, x1 = (t + 0.16) * 200;
        const y0 = 40 + t * 150, y1 = 470 - t * 120;
        const panel = `<path d="M${x0},${y0 - 10}L${x1},${y0 + 20}L${x1},${y1 - 20}L${x0},${y1 + 10}Z" fill="${lighten(base, 0.12 - t * 0.05)}"/>` +
          `<path d="M${x1 + 4},${y0 + 24}L${x1 + 10},${y0 + 28}L${x1 + 10},${y1 - 26}L${x1 + 4},${y1 - 22}Z" fill="${colors.accent}" opacity="${(0.9 - t * 0.5).toFixed(2)}"/>`;
        panels += panel + `<g transform="translate(${SIZE},0) scale(-1,1)">${panel}</g>`;
      }
      return `<radialGradient id="${id}" cx="0.5" cy="0.45" r="0.6"><stop offset="0" stop-color="${mix(base, colors.accent, 0.25)}"/><stop offset="1" stop-color="${darken(base, 0.5)}"/></radialGradient>` +
        `${blurFilter(blur, 3)}${full(`url(#${id})`)}<g filter="url(#${blur})">${panels}<rect x="0" y="0" width="${SIZE}" height="36" fill="${darken(base, 0.4)}"/><rect x="0" y="470" width="${SIZE}" height="42" fill="${darken(base, 0.3)}"/></g>`;
    },
  },
};

for (const [id, b] of Object.entries(backgrounds)) {
  registerPart('background', { id, label: b.label, render: (ctx) => ({ background: b.render(ctx) }) });
}

// ---------------------------------------------------------------- frames
const frames = {
  none: { label: 'None', render: () => '' },
  simple: {
    label: 'Simple border',
    render: ({ colors }) => `<rect x="10" y="10" width="${SIZE - 20}" height="${SIZE - 20}" rx="14" fill="none" stroke="${darken(colors.background, 0.55)}" stroke-width="6"/>`,
  },
  ornate: {
    label: 'Ornate gold',
    render() {
      const gold = '#c9a443';
      let corners = '';
      for (const [x, y] of [[22, 22], [SIZE - 22, 22], [22, SIZE - 22], [SIZE - 22, SIZE - 22]]) {
        corners += `<path d="M${x},${y - 14}L${x + 14},${y}L${x},${y + 14}L${x - 14},${y}Z" fill="${gold}" stroke="#6e5418" stroke-width="2"/>`;
      }
      return `<rect x="8" y="8" width="${SIZE - 16}" height="${SIZE - 16}" fill="none" stroke="#6e5418" stroke-width="10"/>` +
        `<rect x="8" y="8" width="${SIZE - 16}" height="${SIZE - 16}" fill="none" stroke="${gold}" stroke-width="6"/>` +
        `<rect x="22" y="22" width="${SIZE - 44}" height="${SIZE - 44}" fill="none" stroke="${gold}" stroke-width="2"/>` + corners;
    },
  },
  brackets: {
    label: 'HUD brackets',
    render({ colors }) {
      const c = colors.accent, L = 60, m = 18;
      const corner = (x, y, sx, sy) => `<path d="M${x},${y + sy * L}L${x},${y}L${x + sx * L},${y}" />`;
      return `<g fill="none" stroke="${c}" stroke-width="5" stroke-linecap="square">` +
        corner(m, m, 1, 1) + corner(SIZE - m, m, -1, 1) + corner(m, SIZE - m, 1, -1) + corner(SIZE - m, SIZE - m, -1, -1) +
        `</g><rect x="${m + 8}" y="${SIZE - m - 14}" width="80" height="6" fill="${c}" opacity="0.7"/>`;
    },
  },
  circle: {
    label: 'Circle (avatar)',
    clip: true,
    render: ({ colors }) => `<circle cx="${CX}" cy="${CX}" r="${CX - 6}" fill="none" stroke="${darken(colors.background, 0.5)}" stroke-width="10"/>`,
  },
};

for (const [id, f] of Object.entries(frames)) {
  registerPart('frame', { id, label: f.label, clip: !!f.clip, render: (ctx) => ({ frame: f.render(ctx) }) });
}
