// Receipt scanning on the device: Tesseract OCR (English + Simplified Chinese) runs in a web
// worker, then parseReceipt() picks out the total, date, merchant and a category guess.
// The photo never leaves the phone. Engine and language files are bundled in /ocr.
import type { Worker } from 'tesseract.js';
import type { Category, Money } from './types';
import { CATEGORIES } from './types';
import { parseReceipts } from './receipt';
import { api } from './api';

export interface ReceiptGuess {
  merchant: string;
  amount: Money | null;
  currency: string;
  category: Category;
  date: string | null;
  kind: 'out' | 'in';
}

let workerP: Promise<Worker> | null = null;
let onProgress: ((p: number) => void) | null = null;

function getWorker(): Promise<Worker> {
  if (!workerP) {
    workerP = (async () => {
      const { createWorker } = await import('tesseract.js');
      const base = new URL(import.meta.env.BASE_URL + 'ocr/', window.location.href).href;
      return createWorker(['chi_sim', 'eng'], 1, {
        workerPath: base + 'worker.min.js',
        corePath: base + 'core',
        langPath: base + 'lang',
        gzip: true,
        logger: m => {
          if (m.status === 'recognizing text' && onProgress) onProgress(m.progress);
        },
      });
    })().catch(e => {
      workerP = null;
      throw e;
    });
  }
  return workerP;
}

/**
 * Makes faint text readable before OCR: grey, and darkened with a curve so light-grey dates and
 * category labels in payment-app screenshots come out nearly black while white stays white.
 * Small pictures are enlarged; very large photos are shrunk to keep it quick on a phone.
 */
async function prepare(file: File): Promise<Blob | File> {
  try {
    const bmp = await createImageBitmap(file);
    const long = Math.max(bmp.width, bmp.height);
    const scale = long < 1400 ? 1400 / long : long > 2600 ? 2600 / long : 1;
    const w = Math.round(bmp.width * scale);
    const h = Math.round(bmp.height * scale);
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return file;
    ctx.drawImage(bmp, 0, 0, w, h);
    bmp.close();
    const img = ctx.getImageData(0, 0, w, h);
    const d = img.data;
    // Dark-background screenshots (dark mode) are flipped so text is dark on light.
    let sum = 0;
    for (let i = 0; i < d.length; i += 64) sum += d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114;
    const dark = sum / (d.length / 64) < 110;
    for (let i = 0; i < d.length; i += 4) {
      let l = (d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114) / 255;
      if (dark) l = 1 - l;
      const v = Math.round(255 * l ** 2.2);
      d[i] = d[i + 1] = d[i + 2] = v;
    }
    ctx.putImageData(img, 0, 0);
    return await new Promise<Blob | File>(resolve => canvas.toBlob(b => resolve(b ?? file), 'image/png'));
  } catch {
    return file;
  }
}

/** Reads one picture; a bill-list screenshot can hold several payments. */
export async function recognizeReceipt(file: File, progress?: (p: number) => void): Promise<ReceiptGuess[]> {
  onProgress = progress ?? null;
  try {
    if (import.meta.env.VITE_MULTIMEDIA_BACKEND === 'true' && api.agent === 'live') {
      try {
        const remote = await api.parseReceipt(file);
        if (!remote.items.length) throw new Error('no receipt rows');
        return remote.items.map(item => ({
          merchant: item.merchant,
          amount: item.amount as Money | null,
          currency: item.currency,
          category: (CATEGORIES as readonly string[]).includes(item.category)
            ? (item.category as Category)
            : 'UNKNOWN',
          date: item.date,
          kind: 'out',
        }));
      } catch {
        // Keep the existing on-device OCR path available when the optional backend is unavailable.
      }
    }
    const worker = await getWorker();
    const { data } = await worker.recognize(await prepare(file));
    if (import.meta.env.DEV) console.debug('[receipt OCR]', data.text);
    return parseReceipts(data.text).map(r => ({
      merchant: r.merchant,
      amount: r.amount,
      currency: 'CNY',
      category: (CATEGORIES as readonly string[]).includes(r.category) ? (r.category as Category) : 'UNKNOWN',
      date: r.date,
      kind: r.kind,
    }));
  } finally {
    onProgress = null;
  }
}

/** Photos picked on Home are handed to the scan screen through here. */
let pendingFiles: File[] = [];
export function setPendingReceipts(files: File[]) {
  pendingFiles = files;
}
export function takePendingReceipts(): File[] {
  const f = pendingFiles;
  pendingFiles = [];
  return f;
}
