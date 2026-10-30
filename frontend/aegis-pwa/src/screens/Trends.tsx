import { useEffect, useMemo, useState } from 'react';
import { api } from '../core/api';
import { CATEGORIES, type Budget, type BudgetStatus, type SpendingSummary } from '../core/types';
import { categoryKey, direction, monthLabel } from '../core/format';
import { formatMoney, fromCents, isValidAmount, normalizeAmount, percent, toCents } from '../core/money';
import { useApp, useLoad } from '../app/state';
import { Amount, Icon, Sheet, Skeleton } from '../ui/kit';
import { loadAccounts, loadRecent } from './Home';

interface Month {
  year: number;
  month: number;
}

const key = (m: Month) => `${m.year}-${String(m.month).padStart(2, '0')}`;

function lastMonths(count: number): Month[] {
  const d = new Date();
  return Array.from({ length: count }, (_, i) => {
    const x = new Date(d.getFullYear(), d.getMonth() - i, 1);
    return { year: x.getFullYear(), month: x.getMonth() + 1 };
  });
}

export function Trends() {
  const { t, locale } = useApp();
  const months = useMemo(() => lastMonths(12), []);
  const [sel, setSel] = useState<Month | null>(null);
  const [budgetOpen, setBudgetOpen] = useState(false);

  // Start on the month of the latest spending so seeded history is visible.
  const latest = useLoad(async () => {
    const tx = await loadRecent(await loadAccounts(), 30);
    const out = tx.find(x => direction(x) === 'out' && x.posted_at);
    return out?.posted_at?.slice(0, 7) ?? null;
  });
  useEffect(() => {
    if (sel || latest.loading) return;
    const found = months.find(m => key(m) === latest.data);
    setSel(found ?? months[0]);
  }, [latest.data, latest.loading, sel, months]);

  useEffect(() => {
    document.querySelector('.seg button.on')?.scrollIntoView({ inline: 'center', block: 'nearest' });
  }, [sel]);

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
      <div className="seg" role="tablist">
        {months.map(m => (
          <button key={key(m)} role="tab" aria-selected={!!sel && key(sel) === key(m)} className={sel && key(sel) === key(m) ? 'on' : ''} onClick={() => setSel(m)}>
            {new Date(m.year, m.month - 1, 1).toLocaleDateString(locale, { month: 'short', year: m.year === new Date().getFullYear() ? undefined : '2-digit' })}
          </button>
        ))}
      </div>

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
