// Copies the on-device receipt reader (Tesseract) and its English + Chinese language data
// from node_modules into public/ocr, so scanning works offline and needs no third-party CDN.
import { copyFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const nm = join(root, 'node_modules');
const out = join(root, 'public', 'ocr');
const files = [
  ['tesseract.js/dist/worker.min.js', 'worker.min.js'],
  ['tesseract.js-core/tesseract-core-lstm.wasm.js', 'core/tesseract-core-lstm.wasm.js'],
  ['tesseract.js-core/tesseract-core-simd-lstm.wasm.js', 'core/tesseract-core-simd-lstm.wasm.js'],
  ['tesseract.js-core/tesseract-core-relaxedsimd-lstm.wasm.js', 'core/tesseract-core-relaxedsimd-lstm.wasm.js'],
  ['@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz', 'lang/eng.traineddata.gz'],
  ['@tesseract.js-data/chi_sim/4.0.0_best_int/chi_sim.traineddata.gz', 'lang/chi_sim.traineddata.gz'],
];
for (const [from, to] of files) {
  const src = join(nm, from);
  if (!existsSync(src)) {
    console.warn(`[copy-ocr] missing ${from}; run npm install`);
    continue;
  }
  const dest = join(out, to);
  mkdirSync(dirname(dest), { recursive: true });
  copyFileSync(src, dest);
}
console.log('[copy-ocr] receipt reader ready in public/ocr');
