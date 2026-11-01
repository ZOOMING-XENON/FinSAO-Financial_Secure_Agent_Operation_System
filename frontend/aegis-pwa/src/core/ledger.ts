// Cash ledger storage. Banking Core has no endpoint for manual entries, so they live on this device.
import type { Transaction } from './types';
export type LedgerKind = 'out' | 'in';
export interface LedgerEntry {
  id: string;
  kind: LedgerKind;
  cat: string;
  cents: string; // decimal string, like the API
  note: string;
  at: string;
}

const KEY = 'aegis.ledger';

export function readLedger(): LedgerEntry[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]');
  } catch {
    return [];
  }
}

export function writeLedger(list: LedgerEntry[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* storage unavailable */
  }
}

/** Month of the last entry added from elsewhere (e.g. a scanned receipt), so the ledger opens there. */
export let lastAddedMonth: string | null = null;

export function addLedgerEntry(entry: LedgerEntry) {
  writeLedger([entry, ...readLedger()]);
  lastAddedMonth = entry.at.slice(0, 7);
}

/** Maps a bank spending category to the closest ledger category. */
export function ledgerCatFor(category: string): string {
  return { DINING: 'food', GROCERIES: 'shopping', TRANSPORT: 'transport', HOUSEHOLD: 'housing', ENTERTAINMENT: 'fun' }[category] ?? 'other';
}

const TO_BANK: Record<string, string> = { food: 'DINING', shopping: 'GROCERIES', transport: 'TRANSPORT', housing: 'HOUSEHOLD', fun: 'ENTERTAINMENT' };

/** Ledger entries shaped like bank transactions, so Activity, Calendar and Analytics can show them. */
export function ledgerTransactions(): Transaction[] {
  return readLedger().map(e => ({
    id: 'cash-' + e.id,
    reference: 'CASH',
    status: 'COMPLETED',
    amount: e.cents,
    currency: 'CNY',
    description: e.note.trim(),
    category: e.kind === 'in' ? 'INCOME' : TO_BANK[e.cat] ?? 'UNKNOWN',
    posted_at: new Date(e.at).toISOString(),
    cash: e.cat,
  }));
}

/** Bank transactions plus cash-ledger entries, newest first. */
export function withCash(tx: Transaction[]): Transaction[] {
  return [...tx, ...ledgerTransactions()].sort((a, b) => (b.posted_at ?? '').localeCompare(a.posted_at ?? ''));
}
