// Display helpers shared by screens. No React here.
import type { Transaction } from './types';
import { CATEGORIES } from './types';

export type Direction = 'in' | 'out' | 'move';

const INBOUND = new Set(['OPENING_BALANCE', 'INCOME', 'SALARY', 'REFUND', 'INTEREST']);
const MOVES = new Set(['INTERNAL_TRANSFER', 'WEALTH', 'SAVINGS']);

/** Banking Core does not expose debit/credit per row yet, so direction is inferred from category. */
export function direction(tx: Transaction): Direction {
  const c = tx.category ?? '';
  if (INBOUND.has(c)) return 'in';
  if (MOVES.has(c)) return 'move';
  return 'out';
}

export function categoryKey(category: string | null): (typeof CATEGORIES)[number] {
  return (CATEGORIES as readonly string[]).includes(category ?? '') ? (category as (typeof CATEGORIES)[number]) : 'UNKNOWN';
}

export function daysUntil(isoDate: string, from = new Date()): number {
  const target = new Date(isoDate + (isoDate.length === 10 ? 'T00:00:00' : ''));
  const start = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  return Math.round((target.getTime() - start.getTime()) / 86_400_000);
}

export function monthsUntil(isoDate: string, from = new Date()): number {
  const d = new Date(isoDate + 'T00:00:00');
  const months = (d.getFullYear() - from.getFullYear()) * 12 + (d.getMonth() - from.getMonth());
  return Math.max(1, months + (d.getDate() >= from.getDate() ? 0 : -1) || 1);
}

export function formatDate(iso: string | null, locale: string, opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }): string {
  if (!iso) return '';
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso);
  return d.toLocaleDateString(locale, opts);
}

export function monthLabel(year: number, month: number, locale: string): string {
  return new Date(year, month - 1, 1).toLocaleDateString(locale, { year: 'numeric', month: 'long' });
}

export function initials(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return '?';
  if (/[一-鿿]/.test(trimmed)) return trimmed.replace(/^(好友)/, '').slice(0, 1);
  return trimmed.split(/\s+/).map(w => w[0]).join('').slice(0, 2).toUpperCase();
}

/** Stable 0..n-1 from a string, for picking artwork and avatar colours. */
export function hashIndex(text: string, n: number): number {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  return h % n;
}
