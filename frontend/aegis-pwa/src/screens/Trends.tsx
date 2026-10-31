import { useEffect, useMemo, useState } from 'react';
import { api } from '../core/api';
import { CATEGORIES, type Budget, type BudgetStatus, type SpendingSummary, type Transaction } from '../core/types';
import { categoryKey, direction, monthLabel } from '../core/format';
import { formatMoney, fromCents, isValidAmount, normalizeAmount, percent, toCents } from '../core/money';
import { useApp, useLoad } from '../app/state';
import { Amount, Icon, Sheet, Skeleton } from '../ui/kit';
import { TxRow } from '../ui/TxRow';
import { loadAccounts, loadRecent } from './Home';

interface Month {
  year: number;
  month: number;
}

const key = (m: Month) => `${m.year}-${String(m.month).padStart(2, '0')}`;

const shift = (m: Month, by: number): Month => {
  const d = new Date(m.year, m.month - 1 + by, 1);
  return { year: d.getFullYear(), month: d.getMonth() + 1 };
};
const thisMonth = (): Month => ({ year: new Date().getFullYear(), month: new Date().getMonth() + 1 });
const dayKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/** Short calendar label in integer math: ¥142, ¥1.2k. */
function compact(cents: bigint): string {
  const whole = cents / 100n;
  if (whole < 1000n) return '¥' + whole.toString();
  const tenths = whole / 100n;
  return `¥${tenths / 10n}.${tenths % 10n}k`;
}

interface DayTotals {
  out: bigint;
  in: bigint;
  items: Transaction[];
}

function SpendCalendar({ month, tx, selected, onSelect }: { month: Month; tx: Transaction[]; selected: string | null; onSelect: (day: string | null) => void }) {
  const { t, locale } = useApp();
  const days = useMemo(() => {
    const map = new Map<string, DayTotals>();
    for (const x of tx) {
      if (!x.posted_at) continue;
      const k = dayKey(new Date(x.posted_at));
      const d = map.get(k) ?? { out: 0n, in: 0n, items: [] };
      if (direction(x) === 'in') d.in += toCents(x.amount);
      else d.out += toCents(x.amount);
      d.items.push(x);
      map.set(k, d);
    }
    return map;
  }, [tx]);
  const max = [...days.values()].reduce((m, d) => (d.out > m ? d.out : m), 0n);
  const first = new Date(month.year, month.month - 1, 1);
  const start = new Date(first);
  start.setDate(1 - first.getDay());
  const weeks = Math.ceil((first.getDay() + new Date(month.year, month.month, 0).getDate()) / 7);
  const cells = Array.from({ length: weeks * 7 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  const today = dayKey(new Date());
  const weekday = (i: number) => new Date(2026, 1, 1 + i).toLocaleDateString(locale, { weekday: 'narrow' }); // Feb 1 2026 is a Sunday

  return (
    <>
      <div className="cal" role="grid" aria-label={monthLabel(month.year, month.month, locale)}>
        {Array.from({ length: 7 }, (_, i) => (
          <div className="wd" key={'w' + i} role="columnheader">
            {weekday(i)}
          </div>
        ))}
        {cells.map(d => {
          const k = dayKey(d);
          const info = days.get(k);
          const inMonth = d.getMonth() === month.month - 1;
          const cls = ['day', inMonth ? '' : 'other', k === today ? 'today' : '', k === selected ? 'sel' : ''].join(' ');
          return (
            <button key={k} className={cls} role="gridcell" aria-selected={k === selected} onClick={() => onSelect(k === selected ? null : k)} disabled={!inMonth}>
              <span className="n">{d.getDate()}</span>
              {inMonth && info && info.out > 0n && (
                <span className={'chipd out' + (max > 0n && info.out * 2n >= max ? ' hot' : '')}>{compact(info.out)}</span>
              )}
              {inMonth && info && info.in > 0n && <span className="chipd in">+{compact(info.in)}</span>}
            </button>
          );
        })}
      </div>
      <div className="cal-legend">
        <span>
          <i style={{ background: 'var(--brand-soft)' }} />
          {t('trends.legendOut')}
        </span>
        <span>
          <i style={{ background: 'var(--brand-2)' }} />
          {t('trends.legendBig')}
        </span>
        <span>
          <i style={{ background: 'var(--green-bg)' }} />
          {t('trends.legendIn')}
        </span>
      </div>
      {selected && (
        <section className="card flush">
          <div className="card-h">
            <h3>{new Date(selected + 'T00:00:00').toLocaleDateString(locale, { weekday: 'long', month: 'long', day: 'numeric' })}</h3>
          </div>
          {(days.get(selected)?.items ?? []).length === 0 && <div className="empty">{t('trends.dayEmpty')}</div>}
          {days.get(selected)?.items.map(x => <TxRow tx={x} key={x.id} />)}
        </section>
      )}
    </>
  );
}

export function Trends() {
  const { t, locale } = useApp();
  const [sel, setSel] = useState<Month | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const allTx = useLoad(async () => loadRecent(await loadAccounts(), 200));
  const [budgetOpen, setBudgetOpen] = useState(false);

  // Start on the month of the latest spending so seeded history is visible.
  const latest = useLoad(async () => {
    const tx = await loadRecent(await loadAccounts(), 30);
    const out = tx.find(x => direction(x) === 'out' && x.posted_at);
    return out?.posted_at?.slice(0, 7) ?? null;
  });
  useEffect(() => {
    if (sel || latest.loading) return;
    if (latest.data) {
      const [y, m] = latest.data.split('-').map(Number);
      setSel({ year: y, month: m });
    } else setSel(thisMonth());
  }, [latest.data, latest.loading, sel]);
  const monthTx = (allTx.data ?? []).filter(x => sel && x.posted_at?.startsWith(key(sel)));
  const atLatest = !!sel && key(sel) >= key(thisMonth());

  const spend = useLoad(async () => (sel ? api.get<SpendingSummary>('/analytics/monthly-summary', { year: sel.year, month: sel.month }) : undefined), [sel && key(sel)]);
  const budgets = useLoad(async () => {
    if (!sel) return [];
    const all = await api.get<Budget[]>('/budgets');
    const mine = all.filter(b => b.month.startsWith(key(sel)));
    const statuses = await Promise.all(mine.map(b => api.get<BudgetStatus>(`/budgets/${b.id}/status`)));
    return mine.map((b, i) => ({ budget: b, status: statuses[i] }));
  }, [sel && key(sel)]);

  const cats = Object.entries(spend.data?.by_category ?? {})
    .map(([c, v]) => ({ cat: categoryKey(c), value: v }))
    .sort((a, b) => (toCents(b.value) > toCents(a.value) ? 1 : -1));
  const total = spend.data?.total ?? '0.00';

  return (
    <>
      <div className="ph">
        <h1>{t('trends.title')}</h1>
      </div>
      <div className="cal-head">
        <h2>{sel ? monthLabel(sel.year, sel.month, locale) : ''}</h2>
        <button className="icon-btn" aria-label={t('trends.prev')} onClick={() => sel && (setSel(shift(sel, -1)), setDay(null))}>
          <Icon name="i-left" />
        </button>
        <button className="icon-btn" aria-label={t('trends.next')} disabled={atLatest} style={atLatest ? { opacity: 0.4 } : undefined} onClick={() => sel && (setSel(shift(sel, 1)), setDay(null))}>
          <Icon name="i-chev" />
        </button>
      </div>
      {sel && allTx.data && <SpendCalendar month={sel} tx={monthTx} selected={day} onSelect={setDay} />}
      {allTx.loading && !allTx.data && <Skeleton rows={3} />}
      {sel && allTx.data && !day && <p className="mut small" style={{ margin: '0 2px 14px' }}>{t('trends.tapDay')}</p>}

      <section className="card">
        <div className="hero-t">{sel ? t('trends.spent', { month: monthLabel(sel.year, sel.month, locale) }) : ''}</div>
        <div className="hero-n">
          <Amount value={total} />
        </div>
        {cats.length > 0 && (
          <div className="stack-bar" aria-hidden="true">
            {cats.map(c => (
              <i key={c.cat} className={'c-' + c.cat} style={{ width: Math.max(percent(c.value, total), 3) + '%' }} />
            ))}
          </div>
        )}
      </section>

      <section className="card flush">
        <div className="card-h">
          <h3>{t('trends.byCategory')}</h3>
        </div>
        {spend.loading && !spend.data && <Skeleton rows={2} />}
        {spend.data && cats.length === 0 && <div className="empty">{t('trends.noSpend')}</div>}
        {cats.map(c => (
          <div className="row" key={c.cat}>
            <span className={'ico ' + c.cat}>
              <Icon name={'c-' + c.cat} />
            </span>
            <span className="main">
              <span className="t" style={{ display: 'block' }}>
                {t(`cat.${c.cat}`)}
              </span>
              <span className="s" style={{ display: 'block' }}>
                {percent(c.value, total)}%
              </span>
            </span>
            <span className="v">
              <Amount value={c.value} />
            </span>
          </div>
        ))}
      </section>

      <section className="card">
        <div className="card-h">
          <h3>{t('trends.budgets')}</h3>
          <button className="link" onClick={() => setBudgetOpen(true)}>
            + {t('trends.newBudget')}
          </button>
        </div>
        {budgets.data?.length === 0 && <div className="empty">{t('trends.noBudgets')}</div>}
        {budgets.data?.map(({ budget, status }) => {
          const pct = percent(status.used, status.limit);
          const over = toCents(status.remaining) < 0n;
          const cat = categoryKey(budget.category);
          return (
            <div key={budget.id} style={{ padding: '10px 0' }}>
              <div className="goal-top">
                <b>{t(`cat.${cat}`)}</b>
                <span className="small">
                  <Amount value={status.used} /> / <Amount value={status.limit} />
                </span>
              </div>
              <div className={'bar' + (over ? ' over' : status.threshold_exceeded ? ' warn' : '')}>
                <i style={{ width: pct + '%' }} />
              </div>
              <div className="small mut" style={{ marginTop: 6 }}>
                {over ? t('trends.over', { amount: formatMoney(fromCents(-toCents(status.remaining))) }) : t('trends.left', { amount: formatMoney(status.remaining) })} ·{' '}
                {t('trends.forecast', { amount: formatMoney(status.estimate) })}
              </div>
            </div>
          );
        })}
      </section>

      {sel && <BudgetSheet open={budgetOpen} onClose={() => setBudgetOpen(false)} month={key(sel)} onSaved={budgets.reload} />}
    </>
  );
}

function BudgetSheet({ open, onClose, month, onSaved }: { open: boolean; onClose: () => void; month: string; onSaved: () => void }) {
  const { t, errorText } = useApp();
  const [category, setCategory] = useState<string>('DINING');
  const [limit, setLimit] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!isValidAmount(limit)) return setMsg(t('pay.invalidAmount'));
    setBusy(true);
    try {
      await api.post('/budgets', { category, month: month + '-01', limit_amount: normalizeAmount(limit), currency: 'CNY' });
      setLimit('');
      setMsg('');
      onSaved();
      onClose();
    } catch (e) {
      setMsg(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet open={open} onClose={onClose} label={t('trends.newBudget')}>
      <h3>{t('trends.newBudget')}</h3>
      <label className="f" htmlFor="b-cat">
        {t('trends.category')}
      </label>
      <select id="b-cat" className="input" value={category} onChange={e => setCategory(e.target.value)}>
        {CATEGORIES.map(c => (
          <option key={c} value={c}>
            {t(`cat.${c}`)}
          </option>
        ))}
      </select>
      <label className="f" htmlFor="b-limit">
        {t('trends.limit')} · {month}
      </label>
      <input id="b-limit" className="input" inputMode="decimal" placeholder="1500" value={limit} onChange={e => setLimit(e.target.value)} />
      <p className="err">{msg}</p>
      <button className="btn primary" onClick={save} disabled={busy}>
        {t('trends.create')}
      </button>
    </Sheet>
  );
}
