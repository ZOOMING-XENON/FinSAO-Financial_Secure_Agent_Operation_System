import { useMemo, useState } from 'react';
import { api } from '../core/api';
import { CATEGORIES, type Transaction } from '../core/types';
import { direction, monthLabel } from '../core/format';
import { formatMoney, fromCents, isValidAmount, normalizeAmount, toCents } from '../core/money';
import { useApp, useLoad } from '../app/state';
import { Icon, Sheet, Skeleton } from '../ui/kit';
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

export function SpendCalendar({ month, tx, selected, onSelect }: { month: Month; tx: Transaction[]; selected: string | null; onSelect: (day: string | null) => void }) {
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

export function Calendar() {
  const { t, locale } = useApp();
  const [sel, setSel] = useState<Month>(thisMonth());
  const [day, setDay] = useState<string | null>(null);
  const allTx = useLoad(async () => loadRecent(await loadAccounts(), 200));
  const monthTx = (allTx.data ?? []).filter(x => x.posted_at?.startsWith(key(sel)));
  const atLatest = key(sel) >= key(thisMonth());
  const out = monthTx.filter(x => direction(x) === 'out').reduce((s, x) => s + toCents(x.amount), 0n);
  const inc = monthTx.filter(x => direction(x) === 'in' && x.category !== 'OPENING_BALANCE').reduce((s, x) => s + toCents(x.amount), 0n);

  return (
    <>
      <div className="ph">
        <a className="icon-btn" href="#/insights" aria-label={t('common.back')}>
          <Icon name="i-back" />
        </a>
        <h2>{t('ins.calendar')}</h2>
        <span style={{ width: 40 }} />
      </div>
      <div className="cal-head">
        <button className="icon-btn" aria-label={t('trends.prev')} onClick={() => (setSel(shift(sel, -1)), setDay(null))}>
          <Icon name="i-left" />
        </button>
        <h2 className="center">{monthLabel(sel.year, sel.month, locale)}</h2>
        <button className="icon-btn" aria-label={t('trends.next')} disabled={atLatest} style={atLatest ? { opacity: 0.35 } : undefined} onClick={() => (setSel(shift(sel, 1)), setDay(null))}>
          <Icon name="i-chev" />
        </button>
      </div>
      <div className="stats cal-stats">
        <div className="stat s-out">
          <small>{t('trends.legendOut')}</small>
          <b>{formatMoney(fromCents(out))}</b>
        </div>
        <div className="stat s-in">
          <small>{t('trends.legendIn')}</small>
          <b>{formatMoney(fromCents(inc))}</b>
        </div>
      </div>
      {allTx.loading && !allTx.data && <Skeleton rows={4} />}
      {allTx.data && <SpendCalendar month={sel} tx={monthTx} selected={day} onSelect={setDay} />}
      {allTx.data && !day && <p className="mut small" style={{ margin: '0 2px 14px' }}>{t('trends.tapDay')}</p>}
    </>
  );
}

export function BudgetSheet({ open, onClose, month, onSaved }: { open: boolean; onClose: () => void; month: string; onSaved: () => void }) {
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
