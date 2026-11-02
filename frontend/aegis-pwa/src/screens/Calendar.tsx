import { useMemo, useRef, useState } from 'react';
import { api } from '../core/api';
import { PICKABLE, type Transaction } from '../core/types';
import { categoryKey, direction, txTitle } from '../core/format';
import { withCash } from '../core/ledger';
import { formatMoney, fromCents, isValidAmount, normalizeAmount, toCents } from '../core/money';
import { useApp, useLoad } from '../app/state';
import { Icon, Sheet, Skeleton } from '../ui/kit';
import { loadAccounts, loadRecent } from './Home';

const dayKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const startOfWeek = (d: Date) => addDays(d, -((d.getDay() + 6) % 7)); // weeks start on Monday

/**
 * One day of money, like a schedule: a week strip to pick the day, then an hour-by-hour
 * timeline showing when each payment happened.
 */
export function DayView({ tx, day, onDay }: { tx: Transaction[]; day: Date; onDay: (d: Date) => void }) {
  const { t, locale } = useApp();
  const picker = useRef<HTMLInputElement>(null);
  const week = Array.from({ length: 7 }, (_, i) => addDays(startOfWeek(day), i));
  const today = dayKey(new Date());
  const items = useMemo(
    () => tx.filter(x => x.posted_at && dayKey(new Date(x.posted_at)) === dayKey(day)).sort((a, b) => (a.posted_at ?? '').localeCompare(b.posted_at ?? '')),
    [tx, day],
  );
  const hasTx = useMemo(() => new Set(tx.filter(x => x.posted_at).map(x => dayKey(new Date(x.posted_at!)))), [tx]);
  const out = items.filter(x => direction(x) === 'out').reduce((s, x) => s + toCents(x.amount), 0n);
  const inc = items.filter(x => direction(x) === 'in' && x.category !== 'OPENING_BALANCE').reduce((s, x) => s + toCents(x.amount), 0n);
  const hours = items.map(x => new Date(x.posted_at!).getHours());
  const first = Math.min(8, ...hours);
  const last = Math.max(21, ...hours);
  const slots = Array.from({ length: last - first + 1 }, (_, i) => first + i);
  const hourLabel = (h: number) => new Date(2026, 0, 1, h).toLocaleTimeString(locale, { hour: 'numeric' });

  return (
    <div className="dayview">
      <div className="dv-head">
        <button className="dv-month" onClick={() => picker.current?.showPicker?.() ?? picker.current?.click()}>
          {day.toLocaleDateString(locale, { year: 'numeric', month: 'long' })}
          <Icon name="i-chev" />
        </button>
        <input
          ref={picker}
          className="dv-picker"
          type="date"
          value={dayKey(day)}
          max={today}
          onChange={e => e.target.value && onDay(new Date(e.target.value + 'T00:00:00'))}
          aria-label={t('day.pick')}
        />
        <span className="spacer" />
        <button className="icon-btn" aria-label={t('day.prevWeek')} onClick={() => onDay(addDays(day, -7))}>
          <Icon name="i-left" />
        </button>
        <button className="icon-btn" aria-label={t('day.nextWeek')} disabled={dayKey(addDays(day, 7)) > today && dayKey(day) === today} onClick={() => onDay(dayKey(addDays(day, 7)) > today ? new Date() : addDays(day, 7))}>
          <Icon name="i-chev" />
        </button>
      </div>
      <div className="dv-week" role="tablist">
        {week.map(d => {
          const k = dayKey(d);
          const future = k > today;
          return (
            <button key={k} role="tab" aria-selected={k === dayKey(day)} className={(k === dayKey(day) ? 'on ' : '') + (k === today ? 'today' : '')} disabled={future} onClick={() => onDay(d)}>
              <small>{d.toLocaleDateString(locale, { weekday: 'short' })}</small>
              <b>{d.getDate()}</b>
              <i className={hasTx.has(k) ? 'dot-on' : ''} />
            </button>
          );
        })}
      </div>

      <div className="dv-sum">
        <span>
          <small>{t('trends.legendOut')}</small>
          <b>{formatMoney(fromCents(out))}</b>
        </span>
        <span>
          <small>{t('trends.legendIn')}</small>
          <b className={inc > 0n ? 'good' : ''}>{formatMoney(fromCents(inc))}</b>
        </span>
        <span>
          <small>{t('day.count')}</small>
          <b>{items.length}</b>
        </span>
      </div>

      {items.length === 0 ? (
        <div className="card empty">{t('trends.dayEmpty')}</div>
      ) : (
        <div className="timeline">
          {slots.map(h => {
            const here = items.filter(x => new Date(x.posted_at!).getHours() === h);
            return (
              <div className={'tl-row' + (here.length ? ' has' : '')} key={h}>
                <span className="tl-hour">{hourLabel(h)}</span>
                <div className="tl-col">
                  {here.map(x => {
                    const dir = direction(x);
                    const c = categoryKey(x.category);
                    return (
                      <div className={'tl-card ' + dir} key={x.id}>
                        <div className="tl-top">
                          <b>{txTitle(x, t)}</b>
                          <span className={'amt' + (dir === 'in' ? ' pos' : '')}>
                            {dir === 'in' ? '+' : dir === 'out' ? '-' : ''}
                            {formatMoney(x.amount, x.currency)}
                          </span>
                        </div>
                        <div className="tl-meta">
                          <Icon name={dir === 'in' ? 'c-IN' : dir === 'move' ? 'c-MOVE' : 'c-' + c} />
                          {x.cash ? `${t('tx.cash')} · ` : ''}
                          {dir === 'in' ? t('tx.in') : dir === 'move' ? t('tx.move') : t(`cat.${c}`)}
                          <span className="spacer" />
                          <Icon name="i-clock" />
                          {new Date(x.posted_at!).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function Calendar() {
  const { t } = useApp();
  const [day, setDay] = useState(() => new Date());
  const allTx = useLoad(async () => withCash(await loadRecent(await loadAccounts(), 200)));
  return (
    <>
      <div className="ph">
        <a className="icon-btn" href="#/insights" aria-label={t('common.back')}>
          <Icon name="i-back" />
        </a>
        <h2>{t('ins.calendar')}</h2>
        <button className="icon-btn" onClick={() => setDay(new Date())} aria-label={t('day.today')}>
          <Icon name="i-cal" />
        </button>
      </div>
      {allTx.loading && !allTx.data && <Skeleton rows={4} />}
      {allTx.data && <DayView tx={allTx.data} day={day} onDay={setDay} />}
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
        {PICKABLE.map(c => (
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
