// Realistic noses: modelled with light and shadow only, no contour lines.
import { registerStyle } from '../../registry.js';
import { pt } from '../../geometry.js';
import { blur, blob } from '../../realism.js';
import { shadowTone, lightTone, flush } from './face.js';

// tip: half width of the tip; ala: half width of the nostril wings; bridge: length
// up from the tip; nostril: nostril size; up: how upturned (nostrils visible);
// hook: bump on the bridge.
const noses = {
  button: { tip: 7, ala: 11, bridge: 18, nostril: 2.2, up: 0.4 },
  straight: { tip: 7, ala: 13, bridge: 40, nostril: 2.4, up: 0 },
  wide: { tip: 9.5, ala: 17, bridge: 32, nostril: 3, up: 0.2 },
  pointed: { tip: 5.5, ala: 11, bridge: 42, nostril: 2, up: 0 },
  hooked: { tip: 7, ala: 12.5, bridge: 42, nostril: 2.3, up: -0.3, hook: 1 },
  small: { tip: 5.5, ala: 9, bridge: 18, nostril: 1.8, up: 0.2 },
  snub: { tip: 7.5, ala: 12, bridge: 24, nostril: 2.8, up: 1 },
  flat: { tip: 10, ala: 18, bridge: 12, nostril: 3.8, up: 1 },
};

const BOX = [-50, -100, 100, 130];

for (const [id, n] of Object.entries(noses)) {
  registerStyle('nose', id, 'realistic', ({ g, colors, uid }) => {
    const skin = colors.skin;
    const sh = shadowTone(skin, 0.42);
    const deep = shadowTone(skin, 0.62);
    const hi = lightTone(skin, 0.4);
    const b5 = uid('b5');
    const b2 = uid('b2');
    const b1 = uid('b1');
    // Scaled up from the cartoon proportions: a nose is about as wide as the gap between the eyes.
    const m = 1 + (g.masc ?? 0) * 0.15;
    const tip = n.tip * 1.25 * m, ala = n.ala * 1.35 * m, nostril = n.nostril * 1.2, up = n.up;
    // The bridge always rises to between the eyes; short noses just show it more faintly.
    const bridge = (g.noseY - g.eyeY + 4) * Math.min(1, 0.6 + n.bridge / 100);
    const faint = Math.min(1, 0.45 + n.bridge / 60);
    const bump = n.hook ? 5 : 0;
    const ny = 4 - up * 1.6;
    // Broad, very soft forms.
    const broad =
      `<path d="M${pt(5, -bridge)}Q${pt(8 + bump, -bridge * 0.45)} ${pt(tip + 2, -3)}" fill="none" stroke="${sh}" stroke-width="8" opacity="${(0.55 * faint).toFixed(2)}"/>` + // shadow side of the bridge
      `<path d="M${pt(-5, -bridge)}Q${pt(-7, -bridge * 0.45)} ${pt(-tip - 1, -3)}" fill="none" stroke="${sh}" stroke-width="5" opacity="0.14"/>` +
      blob(3, 11 + up, ala * 1.05, 5, deep, 0.7) + // cast shadow under the nose
      blob(0, 1, tip + 2, tip * 0.8, flush(skin), 0.2); // warm tip
    // Defined forms.
    const forms =
      `<path d="M${pt(ala * 0.5, -7)}Q${pt(ala + 2.5, -2)} ${pt(ala * 0.75, 5)}" fill="none" stroke="${sh}" stroke-width="3" opacity="0.75"/>` + // right wing crease
      `<path d="M${pt(-ala * 0.5, -7)}Q${pt(-ala - 2.5, -2)} ${pt(-ala * 0.75, 5)}" fill="none" stroke="${sh}" stroke-width="2.6" opacity="0.5"/>` +
      blob(ala * 0.82, 1, 3.5, 4.5, lightTone(skin, 0.15), 0.25) + blob(-ala * 0.82, 1, 3.5, 4.5, hi, 0.3) + // wing tops
      blob(0, 6.5 - up, tip * 0.7, 2.2, sh, 0.35) + // columella underside
      `<path d="M${pt(-tip * 0.9, 2)}Q${pt(0, tip * 0.75)} ${pt(tip * 0.9, 2)}" fill="none" stroke="${sh}" stroke-width="2.4" opacity="0.4"/>`; // underside of the tip
    const crisp =
      blob(-ala * 0.45, ny, nostril * 1.3, nostril * (0.6 + up * 0.25), deep, 0.95, 18) +
      blob(ala * 0.45, ny, nostril * 1.3, nostril * (0.6 + up * 0.25), deep, 1, -18) +
      blob(-1.5, -2.5, tip * 0.5, tip * 0.36, hi, 0.75) + // tip highlight
      `<path d="M${pt(-1.5, -bridge + 4)}Q${pt(-1 + bump * 0.8, -bridge * 0.5)} ${pt(-1.5, -8)}" fill="none" stroke="${hi}" stroke-width="2.4" stroke-linecap="round" opacity="${((n.hook ? 0.45 : 0.32) * faint).toFixed(2)}"/>`;
    return {
      defs: blur(b5, 5, BOX) + blur(b2, 2, BOX) + blur(b1, 1, BOX),
      nose: `<g transform="translate(${pt(g.cx + (g.asym?.noseDX ?? 0), g.noseY)})"><g filter="url(#${b5})">${broad}</g><g filter="url(#${b2})">${forms}</g><g filter="url(#${b1})">${crisp}</g></g>`,
    };
  });
}
