// The notification inbox behind the Home bell: bills due, progress towards goals, investment
// payouts and spending that is out of the ordinary. Built on the device from the same data as
// Home; which items were already seen is remembered locally.
import { useSyncExternalStore } from 'react';
import type { SavingsPot, Subscription, Transaction } from './types';
import { toCents } from './money';
import { daysUntil } from './format';
import { buildNudges, isSpend, potPlan, type BudgetView, type Nudge } from './insights';

export interface InboxItem extends Nudge {
  at: string | null; // when it happened, for display and ordering; null = right now
}

const DAY = 86_400_000;
const PAYOUT = /dividend|interest|分红|利息|收益/i;

/** Spending in a time window; for one category, or (no category) everything except rent and bills. */
function spentBetween(tx: Transaction[], from: number, to: number, cat?: string): bigint {
  let s = 0n;
  for (const t of tx) {
    if (!isSpend(t) || !t.posted_at || (!cat && t.category === 'HOUSEHOLD')) continue;
    const at = Date.parse(t.posted_at);
    if (at >= from && at < to && (!cat || t.category === cat)) s += toCents(t.amount);
  }
  return s;
}

const pct = (now: bigint, usual: bigint) => Number(((now - usual) * 100n) / usual);

export function buildInbox(input: {
  tx: Transaction[];
  subs: Subscription[];
  pots: SavingsPot[];
  budgets: BudgetView[];
  money: (cents: bigint) => string;
  cat: (c: string) => string;
  today?: Date;
}): InboxItem[] {
  const { tx, subs, pots, money, cat, today = new Date() } = input;
  const now = today.getTime();
  const items: InboxItem[] = [];

  // Budgets, pace, unusually large payments: the same reminders Home shows.
  for (const n of buildNudges(input)) {
    if (n.id.startsWith('pot-') || n.id.startsWith('sub-') || n.id === 'no-budget' || n.id.startsWith('pace-')) continue;
    items.push({ ...n, at: null });
  }

  // Bills and subscriptions due within a week.
  for (const s of subs.filter(x => x.active)) {
    const d = daysUntil(s.next_billing_date, today);
    if (d >= 0 && d <= 7) {
      items.push({ id: `sub-${s.id}-${s.next_billing_date}`, tone: d <= 2 ? 'warn' : 'info', icon: 'i-repeat', key: d === 0 ? 'nudge.subToday' : 'nudge.sub', vars: { name: s.merchant_name, n: d, amount: money(toCents(s.amount)) }, href: '#/insights', at: null });
    }
  }

  // How far each savings goal still has to go.
  for (const p of pots) {
    const plan = potPlan(p, today);
    if (plan.reached) items.push({ id: 'goal-done-' + p.id, tone: 'good', icon: 'i-check', key: 'inbox.goalDone', vars: { name: p.name }, href: '#/pot/' + p.id, at: null });
    else items.push({ id: `goal-${p.id}-${plan.pct}`, tone: plan.gap < -10000n ? 'warn' : 'good', icon: 'i-target', key: 'inbox.goal', vars: { name: p.name, amount: money(plan.remaining), pct: plan.pct }, href: '#/pot/' + p.id, at: null });
  }

  // Interest paid into savings pots.
  for (const p of pots) {
    const earned = toCents(p.interest_earned ?? '0');
    if (earned > 0n && p.interest_rate) {
      items.push({ id: `pot-interest-${p.id}-${today.toISOString().slice(0, 7)}`, tone: 'good', icon: 'i-trend-up', key: 'inbox.potInterest', vars: { name: p.name, amount: money(earned), rate: (Number(p.interest_rate) * 100).toFixed(2) }, href: '#/pot/' + p.id, at: null });
    }
  }

  // Investment payouts (dividends, interest) in the last 45 days.
  for (const t of tx) {
    if (!t.posted_at || now - Date.parse(t.posted_at) > 45 * DAY || isSpend(t)) continue;
    if (t.category === 'INTEREST' || PAYOUT.test(t.description)) {
      items.push({ id: 'payout-' + t.id, tone: 'good', icon: 'i-trend-up', key: 'inbox.dividend', vars: { name: t.description, amount: money(toCents(t.amount)) }, href: '#/wealth', at: t.posted_at });
    }
  }

  // This week against the four weeks before it (rent and bills left out: they land on one day).
  const week = spentBetween(tx, now - 7 * DAY, now);
  const usual = spentBetween(tx, now - 35 * DAY, now - 7 * DAY) / 4n;
  if (usual > 10000n) {
    const p = pct(week, usual);
    if (p >= 25) items.push({ id: `more-${today.toISOString().slice(0, 10)}`, tone: 'alert', icon: 'i-trend-up', key: 'inbox.more', vars: { pct: p, amount: money(week), usual: money(usual) }, href: '#/insights', at: null });
    else if (p <= -20) items.push({ id: `less-${today.toISOString().slice(0, 10)}`, tone: 'good', icon: 'i-trend-down', key: 'inbox.less', vars: { pct: -p }, href: '#/insights', at: null });
  }

  // The category that has grown most this month against the two months before (same days).
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1).getTime();
  const sameDays = now - monthStart;
  let top: { c: string; p: number } | null = null;
  for (const c of new Set(tx.filter(isSpend).map(t => t.category ?? 'UNKNOWN'))) {
    if (c === 'HOUSEHOLD') continue; // rent lands on one day and would always look like a jump
    const cur = spentBetween(tx, monthStart, now, c);
    const prev = [1, 2].map(k => {
      const s = new Date(today.getFullYear(), today.getMonth() - k, 1).getTime();
      return spentBetween(tx, s, s + sameDays, c);
    });
    const avg = (prev[0] + prev[1]) / 2n;
    if (avg < 5000n || cur - avg < 10000n) continue;
    const p = pct(cur, avg);
    if (p >= 30 && (!top || p > top.p)) top = { c, p };
  }
  if (top) items.push({ id: `cat-${top.c}-${today.toISOString().slice(0, 7)}`, tone: 'warn', icon: 'i-chart', key: 'inbox.catUp', vars: { cat: cat(top.c), pct: top.p }, href: '#/insights', at: null });

  const rank = { alert: 0, warn: 1, info: 2, good: 3 } as const;
  return items.sort((a, b) => (a.at && b.at ? b.at.localeCompare(a.at) : a.at ? 1 : b.at ? -1 : rank[a.tone] - rank[b.tone]));
}

// Seen items, so the bell can show how many are new.
const KEY = 'aegis.inboxSeen';
const listeners = new Set<() => void>();
let seen: Set<string> = (() => {
  try {
    return new Set(JSON.parse(localStorage.getItem(KEY) || '[]') as string[]);
  } catch {
    return new Set<string>();
  }
})();

export function markSeen(ids: string[]) {
  if (ids.every(id => seen.has(id))) return;
  seen = new Set([...seen, ...ids]);
  try {
    localStorage.setItem(KEY, JSON.stringify([...seen].slice(-400)));
  } catch {
    /* storage unavailable */
  }
  listeners.forEach(l => l());
}

export function useSeen(): Set<string> {
  return useSyncExternalStore(
    l => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => seen,
  );
}
