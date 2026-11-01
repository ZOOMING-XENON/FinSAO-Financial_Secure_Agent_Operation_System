// Receipt scanning on the device: Tesseract OCR (English + Simplified Chinese) runs in a web
// worker, then parseReceipt() picks out the total, date, merchant and a category guess.
// The photo never leaves the phone. Engine and language files are bundled in /ocr.
import type { Worker } from 'tesseract.js';
import type { Category, Money } from './types';
import { CATEGORIES } from './types';
import { parseReceipt } from './receipt';

export interface ReceiptGuess {
  merchant: string;
  amount: Money | null;
  currency: string;
  category: Category;
  date: string | null;
  text: string;
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

export async function recognizeReceipt(file: File, progress?: (p: number) => void): Promise<ReceiptGuess> {
  onProgress = progress ?? null;
  const worker = await getWorker();
  const { data } = await worker.recognize(file);
  onProgress = null;
  const parsed = parseReceipt(data.text);
  return {
    merchant: parsed.merchant,
    amount: parsed.amount,
    currency: 'CNY',
    category: (CATEGORIES as readonly string[]).includes(parsed.category) ? (parsed.category as Category) : 'UNKNOWN',
    date: parsed.date,
    text: data.text,
  };
}

/** A photo picked on Home is handed to the scan screen through here. */
let pendingFile: File | null = null;
export function setPendingReceipt(file: File) {
  pendingFile = file;
}
export function takePendingReceipt(): File | null {
  const f = pendingFile;
  pendingFile = null;
  return f;
}
