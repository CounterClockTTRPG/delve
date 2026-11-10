// Browser-side PNG export via <canvas>.
import { render } from './index.js';

/** Render traits (or an SVG string) to a PNG Blob of `size` x `size` pixels. */
export async function toPNGBlob(traitsOrSvg, { size = 512 } = {}) {
  const svg = typeof traitsOrSvg === 'string' ? traitsOrSvg : render(traitsOrSvg, { size });
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
  try {
    const img = new Image();
    img.decoding = 'async';
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = () => reject(new Error('Could not rasterise SVG'));
      img.src = url;
    });
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    canvas.getContext('2d').drawImage(img, 0, 0, size, size);
    return await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Trigger a download of a Blob/string under `filename`. */
export function download(data, filename, type = 'image/png') {
  const blob = data instanceof Blob ? data : new Blob([data], { type });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
