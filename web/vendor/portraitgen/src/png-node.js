// Node-side PNG export using @resvg/resvg-js (optional dependency).
import { render } from './index.js';

let Resvg;
async function loadResvg() {
  if (!Resvg) {
    try {
      ({ Resvg } = await import('@resvg/resvg-js'));
    } catch {
      throw new Error('PNG export in Node needs @resvg/resvg-js: npm install @resvg/resvg-js');
    }
  }
  return Resvg;
}

/**
 * Render traits (or an SVG string) to a PNG Buffer of `size` x `size` pixels.
 */
export async function toPNG(traitsOrSvg, { size = 512, background } = {}) {
  const R = await loadResvg();
  const svg = typeof traitsOrSvg === 'string' ? traitsOrSvg : render(traitsOrSvg, { size });
  const r = new R(svg, { fitTo: { mode: 'width', value: size }, background });
  return r.render().asPng();
}
