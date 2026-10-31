// Receipt recognition client. The service itself is built separately (Yalalt); see README
// "Receipt recognition contract". The app posts the photo to /api/recognition/receipts and
// server.mjs forwards it to RECOGNITION_BACKEND_URL.
import { api, ApiError, uid } from './api';
import type { Category, Money } from './types';
import { CATEGORIES } from './types';
import { AMOUNT_RE, normalizeAmount } from './money';

export interface ReceiptGuess {
  merchant: string;
  amount: Money;
  currency: string;
  category: Category;
  date: string | null;
  confidence: number;
}

const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

/** Demo mode only: a clearly labelled example that matches a seeded transaction. */
const EXAMPLE: ReceiptGuess = { merchant: 'IKEA 宜家', amount: '142.60', currency: 'CNY', category: 'HOUSEHOLD', date: '2026-03-15', confidence: 0.92 };

function parseGuess(raw: unknown): ReceiptGuess {
  const r = (raw ?? {}) as Record<string, unknown>;
  const amount = String(r.amount ?? '');
  if (!AMOUNT_RE.test(amount)) throw new ApiError(502, 'RECOGNITION_BAD_RESPONSE');
  const category = (CATEGORIES as readonly string[]).includes(String(r.category)) ? (r.category as Category) : 'UNKNOWN';
  return {
    merchant: String(r.merchant ?? '').slice(0, 120),
    amount: normalizeAmount(amount),
    currency: String(r.currency ?? 'CNY'),
    category,
    date: typeof r.date === 'string' ? r.date.slice(0, 10) : null,
    confidence: typeof r.confidence === 'number' ? r.confidence : 0,
  };
}

export async function recognizeReceipt(file: File): Promise<{ guess: ReceiptGuess; example: boolean }> {
  if (api.core !== 'live') {
    await new Promise(r => setTimeout(r, 900));
    return { guess: EXAMPLE, example: true };
  }
  const form = new FormData();
  form.append('receipt', file);
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/recognition/receipts`, { method: 'POST', body: form, headers: { 'X-Trace-Id': uid(), Accept: 'application/json' } });
  } catch {
    throw new ApiError(0, 'RECOGNITION_NOT_CONFIGURED');
  }
  if (!res.ok) throw new ApiError(res.status, 'RECOGNITION_NOT_CONFIGURED');
  return { guess: parseGuess(await res.json().catch(() => null)), example: false };
}
