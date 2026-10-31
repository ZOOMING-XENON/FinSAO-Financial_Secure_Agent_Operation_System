// Money-management maths on top of Banking Core data. Pure functions, integer cents only.
import type { Budget, BudgetStatus, SavingsPot, Subscription, Transaction } from './types';
import { categoryKey, daysUntil, direction } from './format';
import { fromCents, toCents } from './money';

export interface Month {
  year: number;
  month: number; // 1-12
}

export const monthKey = (m: Month) => `${m.year}-${String(m.month).padStart(2, '0')}`;
export const shiftMonth = (m: Month, by: number): Month => {
  const d = new Date(m.year, m.month - 1 + by, 1);
  return { year: d.getFullYear(), month: d.getMonth() + 1 };
};
export const currentMonth = (now = new Date()): Month => ({ year: now.getFullYear(), month: now.getMonth() + 1 });
export const daysInMonth = (m: Month) => new Date(m.year, m.month, 0).getDate();
const localDay = (iso: string) => new Date(iso);

export const isIncome = (tx: Transaction) => direction(tx) === 'in' && tx.category !== 'OPENING_BALANCE';
export const isSpend = (tx: Transaction) => direction(tx) === 'out';

/** Spending buckets in the fixed chart-colour order (see styles: --cat-*). */
export const SPEND_ORDER = ['TRANSPORT', 'DINING', 'GROCERIES', 'ENTERTAINMENT', 'HOUSEHOLD', 'UNKNOWN'] as const;

export interface MonthSummary {
  spent: bigint;
  income: bigint;
  moved: bigint;
  byCategory: Record<string, bigint>;
  cumulative: bigint[]; // index 0 = day 1
  merchants: { name: string; cents: bigint; count: number }[];
  count: number;
}

export function summarize(tx: Transaction[], m: Month): MonthSummary {
  const days = daysInMonth(m);
  const daily = Array.from({ length: days }, () => 0n);
  const byCategory: Record<string, bigint> = {};
  const merch = new Map<string, { cents: bigint; count: number }>();
  let spent = 0n;
  let income = 0n;
  let moved = 0n;
  let count = 0;
  for (const t of tx) {
    if (!t.posted_at) continue;
    const d = localDay(t.posted_at);
    if (d.getFullYear() !== m.year || d.getMonth() + 1 !== m.month) continue;
    const c = toCents(t.amount);
    count++;
    if (isIncome(t)) income += c;
    else if (isSpend(t)) {
      spent += c;
      daily[d.getDate() - 1] += c;
      const k = categoryKey(t.category);
      byCategory[k] = (byCategory[k] ?? 0n) + c;
      const e = merch.get(t.description) ?? { cents: 0n, count: 0 };
      e.cents += c;
      e.count++;
      merch.set(t.description, e);
    } else if (direction(t) === 'move') moved += c;
  }
  let run = 0n;
  const cumulative = daily.map(v => (run += v));
  const merchants = [...merch.entries()]
    .map(([name, e]) => ({ name, ...e }))
    .sort((a, b) => (b.cents > a.cents ? 1 : b.cents < a.cents ? -1 : 0))
    .slice(0, 5);
  return { spent, income, moved, byCategory, cumulative, merchants, count };
}

export function cashflow(tx: Transaction[], end: Month, months = 6) {
  return Array.from({ length: months }, (_, i) => {
    const m = shiftMonth(end, i - months + 1);
    const s = summarize(tx, m);
    return { month: m, income: s.income, spent: s.spent };
  });
}

/** Percent change as an integer, or null when there's no base to compare with. */
export function change(now: bigint, before: bigint): number | null {
  if (before <= 0n) return null;
  return Number(((now - before) * 100n) / before);
}

export interface BudgetView {
  budget: Budget;
  status: BudgetStatus;
  used: bigint;
  limit: bigint;
  left: bigint;
  perDay: bigint; // what can still be spent per remaining day
  pct: number;
  state: 'ok' | 'warn' | 'over';
}

export function budgetView(budget: Budget, status: BudgetStatus, today = new Date()): BudgetView {
  const used = toCents(status.used);
  const limit = toCents(status.limit);
  const left = limit - used;
  const [y, mo] = budget.month.split('-').map(Number);
  const isCurrent = today.getFullYear() === y && today.getMonth() + 1 === mo;
  const remainingDays = isCurrent ? daysInMonth({ year: y, month: mo }) - today.getDate() + 1 : 1;
  const perDay = left > 0n ? left / BigInt(Math.max(1, remainingDays)) : 0n;
  const pct = limit > 0n ? Number((used * 100n) / limit) : 0;
  return { budget, status, used, limit, left, perDay, pct, state: left < 0n ? 'over' : pct >= 80 || status.threshold_exceeded ? 'warn' : 'ok' };
}

/** Consecutive days up to today where spending stayed within the daily allowance. */
export function underBudgetStreak(tx: Transaction[], dailyAllowance: bigint, today = new Date()): number {
  if (dailyAllowance <= 0n) return 0;
  const byDay = new Map<string, bigint>();
  for (const t of tx) {
    if (!t.posted_at || !isSpend(t) || t.category === 'HOUSEHOLD') continue; // rent and bills would break every streak
    const k = localDay(t.posted_at).toDateString();
    byDay.set(k, (byDay.get(k) ?? 0n) + toCents(t.amount));
  }
  let streak = 0;
  for (let i = 1; i <= 60; i++) {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
    if ((byDay.get(d.toDateString()) ?? 0n) > dailyAllowance) break;
    streak++;
  }
  return streak;
}

export interface PotPlan {
  pct: number;
  remaining: bigint;
  expectedNow: bigint;
  gap: bigint; // >0 ahead, <0 behind
  perMonth: bigint;
  perWeek: bigint;
  daysLeft: number;
  reached: boolean;
}

export function potPlan(p: SavingsPot, today = new Date()): PotPlan {
  const target = toCents(p.target_amount);
  const saved = toCents(p.saved_amount);
  const remaining = target - saved > 0n ? target - saved : 0n;
  const start = Date.parse(p.created_at);
  const end = Date.parse(p.target_date + 'T23:59:59');
  const span = Math.max(1, end - start);
  const elapsed = Math.min(span, Math.max(0, today.getTime() - start));
  const expectedNow = (target * BigInt(Math.round((elapsed / span) * 10000))) / 10000n;
  const daysLeft = Math.max(0, daysUntil(p.target_date, today));
  const months = BigInt(Math.max(1, Math.ceil(daysLeft / 30.4)));
  const weeks = BigInt(Math.max(1, Math.ceil(daysLeft / 7)));
  const ceil = (a: bigint, b: bigint) => (a + b - 1n) / b;
  return {
    pct: target > 0n ? Math.min(100, Number((saved * 100n) / target)) : 0,
    remaining,
    expectedNow,
    gap: saved - expectedNow,
    perMonth: ceil(remaining, months),
    perWeek: ceil(remaining, weeks),
    daysLeft,
    reached: saved >= target,
  };
}

export type NudgeTone = 'good' | 'warn' | 'alert' | 'info';
export interface Nudge {
  id: string;
  tone: NudgeTone;
  icon: string;
  key: string; // i18n key
  vars: Record<string, string | number>;
  href: string;
}

export interface NudgeInput {
  budgets: BudgetView[];
  subs: Subscription[];
  pots: SavingsPot[];
  tx: Transaction[];
  today?: Date;
  money: (cents: bigint) => string;
  cat: (category: string) => string;
}

/** The reminders a good money manager would give, most urgent first. */
export function buildNudges({ budgets, subs, pots, tx, today = new Date(), money, cat }: NudgeInput): Nudge[] {
  const out: Nudge[] = [];
  const cur = currentMonth(today);
  const mine = budgets.filter(b => b.budget.month.startsWith(monthKey(cur)));
  for (const b of mine) {
    const c = cat(b.budget.category);
    if (b.state === 'over') out.push({ id: 'b-over-' + b.budget.id, tone: 'alert', icon: 'i-alert', key: 'nudge.over', vars: { cat: c, amount: money(-b.left) }, href: '#/insights' });
    else if (b.state === 'warn') out.push({ id: 'b-warn-' + b.budget.id, tone: 'warn', icon: 'i-target', key: 'nudge.left', vars: { cat: c, amount: money(b.left), perDay: money(b.perDay) }, href: '#/insights' });
  }
  for (const s of subs.filter(x => x.active)) {
    const d = daysUntil(s.next_billing_date, today);
    if (d >= 0 && d <= 7) out.push({ id: 'sub-' + s.id, tone: 'info', icon: 'i-repeat', key: d === 0 ? 'nudge.subToday' : 'nudge.sub', vars: { name: s.merchant_name, n: d, amount: money(toCents(s.amount)) }, href: '#/insights' });
  }
  for (const p of pots) {
    const plan = potPlan(p, today);
    if (!plan.reached && plan.pct >= 90) out.push({ id: 'pot-near-' + p.id, tone: 'good', icon: 'i-target', key: 'nudge.potNear', vars: { name: p.name, amount: money(plan.remaining) }, href: '#/pot/' + p.id });
    else if (!plan.reached && plan.gap < -10000n) out.push({ id: 'pot-behind-' + p.id, tone: 'warn', icon: 'i-clock', key: 'nudge.potBehind', vars: { name: p.name, amount: money(-plan.gap), perWeek: money(plan.perWeek) }, href: '#/pot/' + p.id });
  }
  // Pace vs the same point last month.
  const thisM = summarize(tx, cur);
  const lastM = summarize(tx, shiftMonth(cur, -1));
  const dayIdx = Math.min(today.getDate(), lastM.cumulative.length) - 1;
  const lastSoFar = dayIdx >= 0 ? lastM.cumulative[dayIdx] : 0n;
  const pace = change(thisM.spent, lastSoFar);
  if (pace !== null && pace <= -10) out.push({ id: 'pace-good', tone: 'good', icon: 'i-trend-down', key: 'nudge.paceGood', vars: { pct: -pace }, href: '#/insights' });
  if (pace !== null && pace >= 20) out.push({ id: 'pace-bad', tone: 'warn', icon: 'i-trend-up', key: 'nudge.paceBad', vars: { pct: pace }, href: '#/insights' });
  // Unusually large payment in the last 3 days.
  const recentSpend = tx.filter(t => isSpend(t) && t.posted_at && today.getTime() - Date.parse(t.posted_at) < 3 * 86_400_000);
  const amounts = tx.filter(isSpend).map(t => toCents(t.amount)).sort((a, b) => (a < b ? -1 : 1));
  const median = amounts.length ? amounts[Math.floor(amounts.length / 2)] : 0n;
  const big = recentSpend.find(t => median > 0n && toCents(t.amount) > median * 20n && t.category !== 'HOUSEHOLD');
  if (big) out.push({ id: 'big-' + big.id, tone: 'alert', icon: 'i-shield', key: 'nudge.big', vars: { amount: money(toCents(big.amount)), name: big.description }, href: '#/activity' });
  if (!mine.length) out.push({ id: 'no-budget', tone: 'info', icon: 'i-target', key: 'nudge.noBudget', vars: {}, href: '#/insights' });
  const rank: Record<NudgeTone, number> = { alert: 0, warn: 1, info: 2, good: 3 };
  return out.sort((a, b) => rank[a.tone] - rank[b.tone]);
}

export const centsToMoney = fromCents;
