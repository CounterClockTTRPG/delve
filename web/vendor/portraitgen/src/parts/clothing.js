import { registerPart } from '../registry.js';
import { pt, mirrorPath, mirrored, blurFilter } from '../geometry.js';
import { darken, lighten, mix } from '../color.js';

/** Torso outline with a configurable neckline depth/shape. */
export function bodyPath(g, neckline = 'crew') {
  const nw = g.neckW;
  const sY = g.shoulderY;
  let start, neck;
  if (neckline === 'v') {
    start = [0, sY + 66];
    neck = [[8, sY + 50], [nw, sY + 14], [nw + 10, sY]];
  } else if (neckline === 'wide') {
    start = [0, sY + 40];
    neck = [[30, sY + 40], [nw + 30, sY + 20], [nw + 40, sY + 6]];
  } else if (neckline === 'high') {
    start = [0, sY - 4];
    neck = [[nw * 0.5, sY - 4], [nw + 6, sY - 6], [nw + 10, sY]];
  } else {
    start = [0, sY + 24];
    neck = [[18, sY + 24], [nw + 4, sY + 12], [nw + 10, sY]];
  }
  return mirrorPath(g.cx, start, [
    neck,
    [[nw + 60, sY + 6], [150, sY + 16], [180, sY + 44]],
    [[198, sY + 64], [206, 480], [212, 700]],
    [[140, 700], [60, 700], [0, 700]],
  ]);
}

const base = (g, fill, neckline, stroke = darken(fill, 0.5)) =>
  `<path d="${bodyPath(g, neckline)}" fill="${fill}" stroke="${stroke}" stroke-width="3" stroke-linejoin="round"/>`;

const shadeFolds = (g, c) =>
  `<path d="M${pt(g.cx - 120, 470)}Q${pt(g.cx - 110, 440)} ${pt(g.cx - 96, 430)}M${pt(g.cx + 120, 470)}Q${pt(g.cx + 110, 440)} ${pt(g.cx + 96, 430)}" stroke="${darken(c, 0.25)}" stroke-width="3" fill="none" stroke-linecap="round" opacity="0.6"/>`;

const clothes = {
  // ---------------- modern
  tshirt: {
    label: 'T-shirt',
    render: (g, c) => base(g, c.clothing) + shadeFolds(g, c.clothing) +
      `<path d="M${pt(g.cx - g.neckW - 10, g.shoulderY)}C${pt(g.cx - g.neckW - 4, g.shoulderY + 12)} ${pt(g.cx - 18, g.shoulderY + 24)} ${pt(g.cx, g.shoulderY + 24)}C${pt(g.cx + 18, g.shoulderY + 24)} ${pt(g.cx + g.neckW + 4, g.shoulderY + 12)} ${pt(g.cx + g.neckW + 10, g.shoulderY)}" stroke="${darken(c.clothing, 0.3)}" stroke-width="7" fill="none"/>`,
  },
  hoodie: {
    label: 'Hoodie',
    render(g, c) {
      const nw = g.neckW, sY = g.shoulderY;
      const hood = mirrorPath(g.cx, [0, sY + 10], [
        [[nw + 10, sY + 14], [nw + 22, sY - 8], [nw + 30, sY - 18]],
        [[nw + 52, sY - 8], [nw + 50, sY + 30], [nw + 20, sY + 40]],
        [[nw, sY + 44], [10, sY + 44], [0, sY + 44]],
      ]);
      return base(g, c.clothing) + shadeFolds(g, c.clothing) +
        `<path d="${hood}" fill="${darken(c.clothing, 0.12)}" stroke="${darken(c.clothing, 0.5)}" stroke-width="3"/>` +
        `<path d="M${pt(g.cx - 14, sY + 40)}l-3,40M${pt(g.cx + 14, sY + 40)}l3,40" stroke="${c.accent}" stroke-width="4" stroke-linecap="round"/>` +
        `<circle cx="${g.cx - 17}" cy="${sY + 82}" r="4" fill="${c.accent}"/><circle cx="${g.cx + 17}" cy="${sY + 82}" r="4" fill="${c.accent}"/>`;
    },
  },
  suit: {
    label: 'Suit & tie',
    render(g, c) {
      const sY = g.shoulderY, cx = g.cx, nw = g.neckW;
      const shirt = mirrorPath(cx, [0, sY + 4], [[[nw * 0.6, sY + 4], [nw + 4, sY - 4], [nw + 8, sY + 2]], [[nw, sY + 50], [20, 500], [0, 700]]]);
      const lapel = `<path d="M${pt(cx + nw + 8, sY + 2)}L${pt(cx + nw + 20, sY + 30)}L${pt(cx + nw + 8, sY + 44)}L${pt(cx + 22, 700)}" fill="none" stroke="${darken(c.clothing, 0.5)}" stroke-width="3" stroke-linejoin="round"/>`;
      return base(g, c.clothing, 'high') + shadeFolds(g, c.clothing) +
        `<path d="${shirt}" fill="#f4f2ee" stroke="#9a978f" stroke-width="2"/>` +
        `<path d="M${pt(cx - 8, sY + 14)}L${pt(cx + 8, sY + 14)}L${pt(cx + 5, sY + 24)}L${pt(cx + 12, 500)}L${pt(cx, 515)}L${pt(cx - 12, 500)}L${pt(cx - 5, sY + 24)}Z" fill="${c.accent}" stroke="${darken(c.accent, 0.5)}" stroke-width="2"/>` +
        `<path d="M${pt(cx - nw - 6, sY - 2)}L${pt(cx - 4, sY + 14)}L${pt(cx - 14, sY + 26)}ZM${pt(cx + nw + 6, sY - 2)}L${pt(cx + 4, sY + 14)}L${pt(cx + 14, sY + 26)}Z" fill="#fff" stroke="#9a978f" stroke-width="1.5"/>` +
        lapel + mirrored(cx, lapel);
    },
  },
  sweater: {
    label: 'Sweater',
    render(g, c) {
      let rib = '';
      for (let i = -3; i <= 3; i++) rib += `<path d="M${pt(g.cx + i * 9, g.shoulderY + 14)}l0,12" stroke="${darken(c.clothing, 0.3)}" stroke-width="2"/>`;
      return base(g, c.clothing) + shadeFolds(g, c.clothing) +
        `<path d="M${pt(g.cx - g.neckW - 10, g.shoulderY)}Q${pt(g.cx, g.shoulderY + 44)} ${pt(g.cx + g.neckW + 10, g.shoulderY)}" stroke="${darken(c.clothing, 0.15)}" stroke-width="14" fill="none"/>` + rib;
    },
  },
  turtleneck: {
    label: 'Turtleneck',
    render(g, c) {
      const nw = g.neckW + 6, y0 = g.jawY + 18, y1 = g.shoulderY + 16;
      let ribs = '';
      for (let i = 1; i < 4; i++) ribs += `<path d="M${pt(g.cx - nw, y0 + i * 14)}Q${pt(g.cx, y0 + i * 14 + 8)} ${pt(g.cx + nw, y0 + i * 14)}" stroke="${darken(c.clothing, 0.3)}" stroke-width="2" fill="none"/>`;
      return base(g, c.clothing, 'high') + shadeFolds(g, c.clothing) +
        `<path d="M${pt(g.cx - nw, y0)}Q${pt(g.cx, y0 + 10)} ${pt(g.cx + nw, y0)}L${pt(g.cx + nw + 4, y1)}Q${pt(g.cx, y1 + 14)} ${pt(g.cx - nw - 4, y1)}Z" fill="${lighten(c.clothing, 0.06)}" stroke="${darken(c.clothing, 0.5)}" stroke-width="3"/>` + ribs;
    },
  },
  jacket: {
    label: 'Jacket',
    render(g, c) {
      const cx = g.cx, sY = g.shoulderY, nw = g.neckW;
      const lapel = `<path d="M${pt(cx + nw + 8, sY - 6)}L${pt(cx + nw + 40, sY + 20)}L${pt(cx + nw + 20, sY + 40)}L${pt(cx + 40, 700)}L${pt(cx + 20, 700)}L${pt(cx + 18, sY + 30)}Z" fill="${darken(c.clothing, 0.1)}" stroke="${darken(c.clothing, 0.55)}" stroke-width="3" stroke-linejoin="round"/>`;
      return base(g, c.clothing) + shadeFolds(g, c.clothing) +
        `<path d="${mirrorPath(cx, [0, sY + 20], [[[16, sY + 20], [nw, sY + 10], [nw + 10, sY]], [[40, 460], [32, 500], [30, 700]], [[20, 700], [10, 700], [0, 700]]])}" fill="${c.accent}" stroke="${darken(c.accent, 0.5)}" stroke-width="2"/>` +
        lapel + mirrored(cx, lapel);
    },
  },
  // ---------------- fantasy
  tunic: {
    label: 'Laced tunic',
    render(g, c) {
      const cx = g.cx, sY = g.shoulderY;
      let lace = '';
      for (let i = 0; i < 3; i++) {
        const y = sY + 20 + i * 14;
        lace += `<path d="M${pt(cx - 10 + i * 2, y)}L${pt(cx + 10 - i * 2, y + 10)}M${pt(cx + 10 - i * 2, y)}L${pt(cx - 10 + i * 2, y + 10)}" stroke="${c.accent}" stroke-width="2.5" stroke-linecap="round"/>`;
      }
      return base(g, c.clothing, 'v') + shadeFolds(g, c.clothing) +
        `<path d="M${pt(cx - g.neckW - 10, sY)}L${pt(cx, sY + 66)}L${pt(cx + g.neckW + 10, sY)}" stroke="${darken(c.clothing, 0.3)}" stroke-width="6" fill="none" stroke-linejoin="round"/>` + lace;
    },
  },
  robe: {
    label: 'Mage robe',
    render(g, c) {
      const cx = g.cx, sY = g.shoulderY;
      const trim = `<path d="M${pt(cx + g.neckW + 10, sY)}L${pt(cx + 4, sY + 66)}L${pt(cx + 30, 700)}" stroke="${c.accent}" stroke-width="12" fill="none" stroke-linejoin="round"/>` +
        `<path d="M${pt(cx + g.neckW + 10, sY)}L${pt(cx + 4, sY + 66)}L${pt(cx + 30, 700)}" stroke="${darken(c.accent, 0.4)}" stroke-width="2" stroke-dasharray="2 6" fill="none"/>`;
      return base(g, c.clothing, 'v') + shadeFolds(g, c.clothing) +
        `<path d="M${pt(cx - 8, sY + 66)}L${pt(cx + 8, sY + 66)}L${pt(cx + 30, 700)}L${pt(cx - 30, 700)}Z" fill="${darken(c.clothing, 0.25)}"/>` +
        trim + mirrored(cx, trim) + `<circle cx="${cx}" cy="${sY + 70}" r="7" fill="${c.accent}" stroke="${darken(c.accent, 0.5)}" stroke-width="2"/>`;
    },
  },
  armor: {
    label: 'Plate armor',
    render(g, c, uid) {
      const metal = mix(c.clothing, '#b8bec6', 0.7);
      const grad = uid('metal');
      const cx = g.cx, sY = g.shoulderY;
      const paul = `<path d="M${pt(cx + 70, sY + 10)}C${pt(cx + 120, sY - 18)} ${pt(cx + 196, sY + 10)} ${pt(cx + 206, sY + 70)}L${pt(cx + 150, sY + 74)}C${pt(cx + 140, sY + 40)} ${pt(cx + 110, sY + 26)} ${pt(cx + 70, sY + 30)}Z" fill="url(#${grad})" stroke="${darken(metal, 0.55)}" stroke-width="3"/>` +
        `<path d="M${pt(cx + 80, sY + 22)}C${pt(cx + 130, sY + 6)} ${pt(cx + 186, sY + 30)} ${pt(cx + 196, sY + 66)}" stroke="${c.accent}" stroke-width="4" fill="none"/>` +
        `<circle cx="${cx + 100}" cy="${sY + 24}" r="3" fill="${darken(metal, 0.4)}"/><circle cx="${cx + 160}" cy="${sY + 30}" r="3" fill="${darken(metal, 0.4)}"/>`;
      const gorget = `<path d="M${pt(cx - g.neckW - 10, sY - 14)}Q${pt(cx, sY + 2)} ${pt(cx + g.neckW + 10, sY - 14)}L${pt(cx + g.neckW + 24, sY + 18)}Q${pt(cx, sY + 40)} ${pt(cx - g.neckW - 24, sY + 18)}Z" fill="url(#${grad})" stroke="${darken(metal, 0.55)}" stroke-width="3"/>`;
      return `<defs><linearGradient id="${grad}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${lighten(metal, 0.35)}"/><stop offset="0.5" stop-color="${metal}"/><stop offset="1" stop-color="${darken(metal, 0.35)}"/></linearGradient></defs>` +
        base(g, `url(#${grad})`, 'high', darken(metal, 0.55)) +
        `<path d="M${pt(cx, sY + 40)}L${pt(cx, 700)}" stroke="${darken(metal, 0.4)}" stroke-width="3"/>` +
        gorget + paul + mirrored(cx, paul);
    },
  },
  leather: {
    label: 'Leather jerkin',
    render(g, c) {
      const cx = g.cx, sY = g.shoulderY;
      return base(g, c.clothing, 'v') + shadeFolds(g, c.clothing) +
        `<path d="M${pt(cx - 150, sY + 30)}L${pt(cx + 120, 700)}" stroke="${darken(c.clothing, 0.45)}" stroke-width="16"/>` +
        `<path d="M${pt(cx - 150, sY + 30)}L${pt(cx + 120, 700)}" stroke="${darken(c.clothing, 0.2)}" stroke-width="2" stroke-dasharray="4 5"/>` +
        `<rect x="${cx - 32}" y="${sY + 62}" width="20" height="16" rx="2" fill="none" stroke="${c.accent}" stroke-width="4" transform="rotate(37 ${cx - 22} ${sY + 70})"/>`;
    },
  },
  cloak: {
    label: 'Cloak & clasp',
    render(g, c) {
      const cx = g.cx, sY = g.shoulderY;
      const cloakC = darken(c.clothing, 0.15);
      const drape = mirrorPath(cx, [0, sY + 30], [
        [[30, sY + 20], [g.neckW + 6, sY - 4], [g.neckW + 26, sY - 8]],
        [[120, sY - 2], [190, sY + 20], [214, sY + 70]],
        [[222, 470], [222, 500], [222, 700]],
        [[180, 700], [150, 700], [130, 700]],
        [[110, 470], [60, sY + 44], [0, sY + 40]],
      ]);
      return base(g, mix(c.clothing, '#3b3027', 0.5), 'v') +
        `<path d="${drape}" fill="${cloakC}" stroke="${darken(cloakC, 0.5)}" stroke-width="3" stroke-linejoin="round"/>` +
        `<path d="M${pt(cx - 30, sY + 44)}L${pt(cx + 30, sY + 44)}" stroke="${darken(c.accent, 0.3)}" stroke-width="3"/>` +
        `<circle cx="${cx - 30}" cy="${sY + 44}" r="9" fill="${c.accent}" stroke="${darken(c.accent, 0.5)}" stroke-width="2.5"/>` +
        `<circle cx="${cx + 30}" cy="${sY + 44}" r="9" fill="${c.accent}" stroke="${darken(c.accent, 0.5)}" stroke-width="2.5"/>`;
    },
  },
  monkRobe: {
    label: 'Monk robe & symbol',
    render(g, c) {
      const cx = g.cx, sY = g.shoulderY;
      // A deep cowl draped around the neck and over the shoulders.
      const cowl = mirrorPath(cx, [0, sY + 30], [
        [[g.neckW + 6, sY + 26], [g.neckW + 20, sY - 14], [g.neckW + 40, sY - 22]],
        [[g.neckW + 96, sY - 8], [g.neckW + 100, sY + 40], [g.neckW + 50, sY + 58]],
        [[g.neckW + 10, sY + 70], [14, sY + 60], [0, sY + 60]],
      ]);
      const symY = sY + 66;
      // Sun disc on a cord (holy symbol).
      const sym = c.accent;
      let rays = '';
      for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2;
        rays += `L${pt(cx + Math.cos(a) * (i % 2 ? 9 : 17), symY + Math.sin(a) * (i % 2 ? 9 : 17))}`;
      }
      return base(g, c.clothing, 'v') + shadeFolds(g, c.clothing) +
        `<path d="M${pt(cx, sY + 70)}L${pt(cx, 700)}" stroke="${darken(c.clothing, 0.35)}" stroke-width="3"/>` +
        `<path d="${cowl}" fill="${darken(c.clothing, 0.12)}" stroke="${darken(c.clothing, 0.5)}" stroke-width="3" stroke-linejoin="round"/>` +
        `<path d="M${pt(cx - 30, sY + 34)}Q${pt(cx, symY - 4)} ${pt(cx + 30, sY + 34)}" fill="none" stroke="#6a4a2a" stroke-width="2.4"/>` +
        `<path d="M${rays.slice(1)}Z" fill="${sym}" stroke="${darken(sym, 0.5)}" stroke-width="1.6"/><circle cx="${cx}" cy="${symY}" r="6" fill="${lighten(sym, 0.3)}"/>`;
    },
  },
  tabard: {
    label: 'Knight tabard',
    render(g, c) {
      const cx = g.cx, sY = g.shoulderY;
      const mail = '#8a9098';
      // Mail shoulders under a tabard bearing a simple charge (a cross).
      let rings = '';
      for (let y = sY + 4; y < sY + 70; y += 6) rings += `<path d="M${pt(cx - 200, y)}H${cx + 200}" stroke="${darken(mail, 0.4)}" stroke-width="1.4" stroke-dasharray="3 2" opacity="0.7"/>`;
      const field = c.clothing, charge = c.accent;
      const tab = `M${pt(cx - 86, sY + 20)}Q${pt(cx, sY + 30)} ${pt(cx + 86, sY + 20)}L${pt(cx + 92, 700)}L${pt(cx - 92, 700)}Z`;
      return base(g, mail, 'crew', darken(mail, 0.55)) + rings +
        `<path d="${tab}" fill="${field}" stroke="${darken(field, 0.5)}" stroke-width="3" stroke-linejoin="round"/>` +
        `<path d="M${pt(cx, sY + 50)}V${sY + 150}M${pt(cx - 36, sY + 88)}H${cx + 36}" stroke="${charge}" stroke-width="16"/>` +
        `<path d="M${pt(cx - g.neckW - 4, sY - 6)}Q${pt(cx, sY + 18)} ${pt(cx + g.neckW + 4, sY - 6)}" fill="none" stroke="${darken(mail, 0.3)}" stroke-width="12"/>`;
    },
  },
  gambeson: {
    label: 'Quilted gambeson',
    render(g, c) {
      const cx = g.cx, sY = g.shoulderY;
      let quilt = '';
      for (let i = -9; i <= 9; i++) quilt += `<path d="M${pt(cx + i * 22, sY + 10)}L${pt(cx + i * 24, 700)}" stroke="${darken(c.clothing, 0.3)}" stroke-width="2"/>`;
      for (let y = sY + 40; y < 600; y += 34) quilt += `<path d="M${pt(cx - 220, y)}H${cx + 220}" stroke="${darken(c.clothing, 0.22)}" stroke-width="1.5" stroke-dasharray="4 3"/>`;
      return base(g, c.clothing, 'high') + quilt +
        `<path d="M${pt(cx - g.neckW - 10, sY - 10)}Q${pt(cx, sY + 6)} ${pt(cx + g.neckW + 10, sY - 10)}L${pt(cx + g.neckW + 16, sY + 10)}Q${pt(cx, sY + 26)} ${pt(cx - g.neckW - 16, sY + 10)}Z" fill="${lighten(c.clothing, 0.08)}" stroke="${darken(c.clothing, 0.5)}" stroke-width="3"/>` +
        [0, 1, 2, 3].map((i) => `<path d="M${pt(cx - 6, sY + 40 + i * 30)}h12" stroke="#5a3a1a" stroke-width="4" stroke-linecap="round"/>`).join('');
    },
  },
  // ---------------- sci-fi
  jumpsuit: {
    label: 'Flight suit',
    render(g, c, uid) {
      const cx = g.cx, sY = g.shoulderY, glow = uid('glow');
      const pipe = `<path d="M${pt(cx + g.neckW + 12, sY - 2)}C${pt(cx + 110, sY + 10)} ${pt(cx + 160, sY + 24)} ${pt(cx + 190, sY + 66)}" stroke="${c.accent}" stroke-width="3" fill="none" filter="url(#${glow})"/>` +
        `<path d="M${pt(cx + g.neckW + 12, sY - 2)}C${pt(cx + 110, sY + 10)} ${pt(cx + 160, sY + 24)} ${pt(cx + 190, sY + 66)}" stroke="${lighten(c.accent, 0.5)}" stroke-width="1.5" fill="none"/>`;
      return `<defs>${blurFilter(glow, 2.5)}</defs>` +
        base(g, c.clothing, 'high') + shadeFolds(g, c.clothing) +
        `<path d="M${pt(cx - g.neckW - 6, g.shoulderY - 30)}L${pt(cx + g.neckW + 6, g.shoulderY - 30)}L${pt(cx + g.neckW + 14, sY + 4)}L${pt(cx - g.neckW - 14, sY + 4)}Z" fill="${darken(c.clothing, 0.15)}" stroke="${darken(c.clothing, 0.5)}" stroke-width="3" stroke-linejoin="round"/>` +
        `<path d="M${pt(cx + 6, sY - 30)}L${pt(cx + 14, 700)}" stroke="${darken(c.clothing, 0.5)}" stroke-width="2.5"/>` +
        `<rect x="${cx + 60}" y="${sY + 50}" width="34" height="14" rx="2" fill="${c.accent}" opacity="0.85"/>` +
        pipe + mirrored(cx, pipe);
    },
  },
  exosuit: {
    label: 'Exo armor',
    render(g, c, uid) {
      const cx = g.cx, sY = g.shoulderY, glow = uid('glow');
      const plate = mix(c.clothing, '#d7dde4', 0.35);
      const pad = `<path d="M${pt(cx + 64, sY + 4)}L${pt(cx + 150, sY + 2)}L${pt(cx + 204, sY + 44)}L${pt(cx + 196, sY + 84)}L${pt(cx + 150, sY + 64)}L${pt(cx + 80, sY + 34)}Z" fill="${plate}" stroke="${darken(plate, 0.6)}" stroke-width="3" stroke-linejoin="round"/>` +
        `<path d="M${pt(cx + 150, sY + 10)}L${pt(cx + 190, sY + 44)}" stroke="${c.accent}" stroke-width="3" filter="url(#${glow})"/>`;
      return `<defs>${blurFilter(glow, 2.5)}</defs>` +
        base(g, darken(c.clothing, 0.25), 'high') +
        `<path d="M${pt(cx - 56, sY + 30)}L${pt(cx + 56, sY + 30)}L${pt(cx + 40, 500)}L${pt(cx - 40, 500)}Z" fill="${plate}" stroke="${darken(plate, 0.6)}" stroke-width="3" stroke-linejoin="round"/>` +
        `<circle cx="${cx}" cy="${sY + 72}" r="15" fill="${c.accent}" filter="url(#${glow})"/><circle cx="${cx}" cy="${sY + 72}" r="10" fill="${lighten(c.accent, 0.6)}"/>` +
        `<path d="M${pt(cx - g.neckW - 8, sY - 34)}L${pt(cx + g.neckW + 8, sY - 34)}L${pt(cx + g.neckW + 20, sY + 10)}L${pt(cx - g.neckW - 20, sY + 10)}Z" fill="${darken(plate, 0.2)}" stroke="${darken(plate, 0.6)}" stroke-width="3" stroke-linejoin="round"/>` +
        pad + mirrored(cx, pad);
    },
  },
  highCollar: {
    label: 'High-collar coat',
    render(g, c, uid) {
      const cx = g.cx, sY = g.shoulderY, glow = uid('glow');
      const collar = `<path d="M${pt(cx + g.neckW + 2, g.jawY + 10)}L${pt(cx + g.neckW + 46, g.jawY - 6)}L${pt(cx + g.neckW + 60, sY + 6)}L${pt(cx + 14, sY + 40)}Z" fill="${darken(c.clothing, 0.12)}" stroke="${darken(c.clothing, 0.55)}" stroke-width="3" stroke-linejoin="round"/>` +
        `<path d="M${pt(cx + g.neckW + 44, g.jawY)}L${pt(cx + g.neckW + 54, sY + 4)}" stroke="${c.accent}" stroke-width="2.5" filter="url(#${glow})"/>`;
      return `<defs>${blurFilter(glow, 2)}</defs>` +
        base(g, c.clothing, 'v') + shadeFolds(g, c.clothing) +
        `<path d="M${pt(cx - 10, sY + 60)}L${pt(cx + 10, sY + 60)}L${pt(cx + 4, 700)}L${pt(cx - 4, 700)}Z" fill="${c.accent}" opacity="0.6"/>` +
        collar + mirrored(cx, collar);
    },
  },
};

for (const [id, cl] of Object.entries(clothes)) {
  registerPart('clothing', {
    id,
    label: cl.label,
    render: ({ g, colors, uid }) => ({ body: cl.render(g, colors, uid) }),
  });
}
