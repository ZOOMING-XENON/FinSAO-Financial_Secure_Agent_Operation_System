// Integer-cent money math. Never parse money into floats.
import type { Money } from './types';

export const AMOUNT_RE = /^\d{1,13}(\.\d{1,2})?$/;

export function toCents(value: Money | number | null | undefined): bigint {
  const raw = String(value ?? '0').trim();
  const negative = raw.startsWith('-');
  const [whole, frac = ''] = raw.replace(/^[-+]/, '').split('.');
  const cents = BigInt(whole || '0') * 100n + BigInt((frac + '00').slice(0, 2));
  return negative ? -cents : cents;
}

export function fromCents(cents: bigint): Money {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  const whole = abs / 100n;
  const frac = (abs % 100n).toString().padStart(2, '0');
  return `${negative ? '-' : ''}${whole}.${frac}`;
}

export function isValidAmount(value: string): boolean {
  return AMOUNT_RE.test(value.trim()) && toCents(value) > 0n;
}

export function normalizeAmount(value: string): Money {
  return fromCents(toCents(value));
}

const SYMBOL: Record<string, string> = { CNY: '¥', USD: '$', EUR: '€' };

export function currencySymbol(currency = 'CNY'): string {
  return SYMBOL[currency] ?? `${currency} `;
}

/** Splits a money string into display parts with thousands separators. */
export function moneyParts(value: Money, currency = 'CNY') {
  const cents = toCents(value);
  const negative = cents < 0n;
  const [whole, dec] = fromCents(negative ? -cents : cents).split('.');
  return {
    sign: negative ? '-' : '',
    symbol: currencySymbol(currency),
    whole: whole.replace(/\B(?=(\d{3})+(?!\d))/g, ','),
    dec,
  };
}

export function formatMoney(value: Money, currency = 'CNY'): string {
  const p = moneyParts(value, currency);
  return `${p.sign}${p.symbol}${p.whole}.${p.dec}`;
}

/** Ratio as a 0–100 integer percentage, computed in cents. */
export function percent(part: Money, whole: Money): number {
  const w = toCents(whole);
  if (w <= 0n) return 0;
  const p = (toCents(part) * 100n) / w;
  return Number(p > 100n ? 100n : p < 0n ? 0n : p);
}
