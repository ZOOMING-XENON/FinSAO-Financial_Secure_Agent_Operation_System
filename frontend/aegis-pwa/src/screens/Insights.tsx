import { useState } from 'react';
import { api } from '../core/api';
import type { Subscription } from '../core/types';
import { change, cashflow, currentMonth, monthKey, periodRange, rangeSummary, shiftMonth, SPEND_ORDER, summarize, underBudgetStreak, type Month, type Period } from '../core/insights';
import { daysUntil, formatDate, monthLabel } from '../core/format';
import { formatMoney, fromCents, toCents } from '../core/money';
import { useApp, useLoad } from '../app/state';
import { useShield } from '../ui/Shield';
import { Amount, Icon, Skeleton } from '../ui/kit';
import { CashflowBars, Donut, PaceChart } from '../ui/charts';
import { loadMoneyPicture, NudgeCard, useNudges } from './Home';
import { BudgetSheet } from './Calendar';

const m$ = (c: bigint) => formatMoney(fromCents(c));

export function Insights() {
  const { t, locale, toast, errorText, refresh } = useApp();
  const authorize = useShield();
  const pic = useLoad(loadMoneyPicture);
  const nudges = useNudges(pic.data);
  const [month, setMonth] = useState<Month>(currentMonth());
  const [budgetOpen, setBudgetOpen] = useState(false);
  const [period, setPeriod] = useState<Period>('month');
  const [offset, setOffset] = useState(0);
  const now = currentMonth();
  const isCurrent = monthKey(month) === monthKey(now);
  const atLatest = monthKey(month) >= monthKey(now);

  if (!pic.data) {
    return (
      <>
        <div className="ph">
          <h1>{t('ins.title')}</h1>
        </div>
        <Skeleton rows={6} />
      </>
    );
  }
  const { tx, budgets, subs } = pic.data;
  const rr = period === 'month' ? null : periodRange(period, offset);
  const range = rr ? rangeSummary(tx, rr.from, rr.to, period === 'week' ? 'day' : 'month') : null;
  const rangeDays = rr ? Math.round((Math.min(Date.now(), rr.to.getTime()) - rr.from.getTime()) / 86_400_000) || 1 : 1;
  const rangeTitle = rr
    ? period === 'year'
      ? String(rr.from.getFullYear())
      : `${rr.from.toLocaleDateString(locale, { month: 'short', day: 'numeric' })} – ${new Date(rr.to.getTime() - 86_400_000).toLocaleDateString(locale, { month: 'short', day: 'numeric' })}`
    : '';
  const rangeParts = range ? SPEND_ORDER.filter(k => (range.byCategory[k] ?? 0n) > 0n).map(k => ({ key: k, cents: range.byCategory[k], label: t(`cat.${k}`) })) : [];
  const s = summarize(tx, month);
  const prev = summarize(tx, shiftMonth(month, -1));
  const todayIdx = isCurrent ? new Date().getDate() - 1 : s.cumulative.length - 1;
  const prevSoFar = prev.cumulative[Math.min(todayIdx, prev.cumulative.length - 1)] ?? 0n;
  const pace = change(s.spent, isCurrent ? prevSoFar : prev.spent);
  const monthBudgets = budgets.filter(b => b.budget.month.startsWith(monthKey(month)));
  const budgetTotal = monthBudgets.reduce((sum, b) => sum + b.limit, 0n);
  const flexible = monthBudgets.filter(b => b.budget.category !== 'HOUSEHOLD').reduce((sum, b) => sum + b.limit, 0n);
  const streak = isCurrent && flexible > 0n ? underBudgetStreak(tx, flexible / 30n) : 0;
  const parts = SPEND_ORDER.filter(k => (s.byCategory[k] ?? 0n) > 0n).map(k => ({ key: k, cents: s.byCategory[k], label: t(`cat.${k}`) }));
  const flow = cashflow(tx, month, 6).map(f => ({ label: new Date(f.month.year, f.month.month - 1, 1).toLocaleDateString(locale, { month: 'short' }), income: f.income, spent: f.spent }));
  const activeSubs = subs.filter(x => x.active);
  const subsTotal = activeSubs.reduce((sum, x) => sum + toCents(x.amount), 0n);

  const cancelSub = async (sub: Subscription) => {
    const ref = await authorize({ operationType: 'subscription.cancel', operationId: sub.id, rows: [[t('shield.merchant'), sub.merchant_name], [t('shield.amount'), formatMoney(sub.amount, sub.currency)]] });
    if (!ref) return;
    try {
      await api.post(`/subscriptions/${sub.id}/cancel`, { authorization_ref: ref });
      toast(t('pay.subCancelled'));
      refresh();
    } catch (e) {
      toast(errorText(e));
    }
  };

  return (
    <>
      <div className="ph">
        <h1>{t('ins.title')}</h1>
        <a className="icon-btn" href="#/track" aria-label={t('home.tileScan')}>
          <Icon name="i-receipt" />
        </a>
        <a className="icon-btn" href="#/calendar" aria-label={t('ins.calendar')}>
          <Icon name="i-cal" />
        </a>
      </div>

      <div className="seg" role="tablist" style={{ marginBottom: 12 }}>
        {(['week', 'month', 'year'] as const).map(p => (
          <button
            key={p}
            role="tab"
            aria-selected={period === p}
            className={period === p ? 'on' : ''}
            onClick={() => {
              setPeriod(p);
              setOffset(0);
              setMonth(currentMonth());
            }}
          >
            {t(`ins.p.${p}` as 'ins.p.week')}
          </button>
        ))}
      </div>
      <div className="cal-head">
        <button className="icon-btn" aria-label={t('trends.prev')} onClick={() => (period === 'month' ? setMonth(shiftMonth(month, -1)) : setOffset(o => o - 1))}>
          <Icon name="i-left" />
        </button>
        <h2 className="center">{period === 'month' ? monthLabel(month.year, month.month, locale) : rangeTitle}</h2>
        <button
          className="icon-btn"
          aria-label={t('trends.next')}
          disabled={period === 'month' ? atLatest : offset >= 0}
          style={(period === 'month' ? atLatest : offset >= 0) ? { opacity: 0.35 } : undefined}
          onClick={() => (period === 'month' ? setMonth(shiftMonth(month, 1)) : setOffset(o => o + 1))}
        >
          <Icon name="i-chev" />
        </button>
      </div>

      {period !== 'month' && range && (
        <>
          <section className="card summary">
            <span className="hero-t">{t('ins.spentPeriod')}</span>
            <div className="sum-row">
              <Amount value={fromCents(range.spent)} className="big" />
            </div>
            <div className="stats">
              <div className="stat">
                <small>{t('ins.income')}</small>
                <b>{m$(range.income)}</b>
              </div>
              <div className="stat">
                <small>{t('ins.net')}</small>
                <b>{(range.income >= range.spent ? '+' : '-') + m$(range.income >= range.spent ? range.income - range.spent : range.spent - range.income)}</b>
              </div>
              <div className="stat">
                <small>{t('ins.dailyAvg')}</small>
                <b>{m$(range.spent / BigInt(Math.max(1, rangeDays)))}</b>
              </div>
              <div className="stat">
                <small>{t('ins.biggestCat')}</small>
                <b>{rangeParts[0] ? rangeParts.slice().sort((a, b) => (b.cents > a.cents ? 1 : -1))[0].label : '—'}</b>
              </div>
            </div>
          </section>
          <section className="card">
            <div className="card-h">
              <h3>{t(period === 'week' ? 'ins.byDay' : 'ins.byMonth')}</h3>
            </div>
            <CashflowBars data={range.buckets.map(x => ({ label: period === 'week' ? x.start.toLocaleDateString(locale, { weekday: 'narrow' }) + x.start.getDate() : x.start.toLocaleDateString(locale, { month: 'narrow' }), income: x.income, spent: x.spent }))} labels={{ income: t('ins.income'), spent: t('ins.spentShort') }} />
          </section>
          <section className="card">
            <div className="card-h">
              <h3>{t('trends.byCategory')}</h3>
            </div>
            {rangeParts.length === 0 ? (
              <div className="empty">{t('trends.noSpend')}</div>
            ) : (
              <div className="cat-split">
                <Donut parts={rangeParts} total={range.spent} centerLabel={t('ins.spentShort')} />
                <ul className="cat-legend">
                  {rangeParts.map(p => (
                    <li key={p.key}>
                      <i className="sw" style={{ background: `var(--cat-${p.key})` }} />
                      <span className="main">
                        <b>{p.label}</b>
                        <span className="mut small">{range.spent > 0n ? Number((p.cents * 100n) / range.spent) : 0}%</span>
                      </span>
                      <span className="v">{m$(p.cents)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        </>
      )}
      {period === 'month' && (
        <>
      <section className="card summary">
        <span className="hero-t">{t('ins.spent')}</span>
        <div className="sum-row">
          <Amount value={fromCents(s.spent)} className="big" />
          {pace !== null && (
            <span className={'delta ' + (pace <= 0 ? 'up' : 'down')}>
              <Icon name={pace <= 0 ? 'i-trend-down' : 'i-trend-up'} />
              {t(pace <= 0 ? 'ins.less' : 'ins.more', { pct: Math.abs(pace) })}
            </span>
          )}
        </div>
        <div className="stats">
          <div className="stat s-in">
            <small>{t('ins.income')}</small>
            <b>{m$(s.income)}</b>
          </div>
          <div className="stat s-net">
            <small>{t('ins.net')}</small>
            <b>{(s.income - s.spent < 0n ? '-' : '+') + m$(s.income - s.spent < 0n ? s.spent - s.income : s.income - s.spent)}</b>
          </div>
          <div className="stat s-save">
            <small>{t('ins.moved')}</small>
            <b>{m$(s.moved)}</b>
          </div>
        </div>
      </section>

      {isCurrent && nudges.length > 0 && (
        <div className="nudges">
          {nudges.map(x => (
            <NudgeCard n={x} key={x.id} />
          ))}
        </div>
      )}

      <section className="card flush">
        <div className="card-h">
          <h3>{t('ins.subs')}</h3>
          {activeSubs.length > 0 && <span className="mut small">{t('ins.subsTotal', { amount: m$(subsTotal) })}</span>}
        </div>
        {subs.length === 0 && <div className="empty">{t('pay.noSubs')}</div>}
        {subs.map(sub => {
          const d = daysUntil(sub.next_billing_date);
          return (
            <div className="row" key={sub.id}>
              <span className="ico ENTERTAINMENT">
                <Icon name="i-repeat" />
              </span>
              <span className="main">
                <span className="t" style={{ display: 'block' }}>
                  {sub.merchant_name}
                </span>
                <span className="s" style={{ display: 'block' }}>
                  {!sub.active ? t('ins.cancelled') : d >= 0 ? t('ins.renews', { n: d }) : formatDate(sub.next_billing_date, locale)}
                </span>
              </span>
              <span className="v">
                {m$(toCents(sub.amount))}
                {sub.active && (
                  <button className="link block" onClick={() => cancelSub(sub)}>
                    {t('pay.cancelSub')}
                  </button>
                )}
              </span>
            </div>
          );
        })}
      </section>

      <a className="card cal-cta" href="#/calendar">
        <span className="cal-cta-ico">
          <Icon name="i-cal" />
        </span>
        <span className="main">
          <b>{t('ins.calendar')}</b>
          <span className="mut small">{t('ins.calendarHint')}</span>
        </span>
        <Icon name="i-chev" />
      </a>

      <section className="card">
        <div className="card-h">
          <h3>{t('ins.pace')}</h3>
          {streak >= 2 && <span className="badge streak">{t('ins.streak', { n: streak })}</span>}
        </div>
        {s.spent === 0n ? (
          <div className="empty">{t('trends.noSpend')}</div>
        ) : (
          <>
            <p className="mut small" style={{ margin: '0 0 8px' }}>
              {pace === null ? t('ins.paceNone') : t(pace <= 0 ? 'ins.paceBelow' : 'ins.paceAbove', { amount: m$((isCurrent ? prevSoFar : prev.spent) > s.spent ? (isCurrent ? prevSoFar : prev.spent) - s.spent : s.spent - (isCurrent ? prevSoFar : prev.spent)) })}
            </p>
            <PaceChart current={s.cumulative} previous={prev.cumulative} budget={budgetTotal || undefined} todayIdx={todayIdx} labels={{ now: t('ins.thisMonth'), before: t('ins.lastMonth'), budget: t('ins.budgetLine') }} />
          </>
        )}
      </section>

      <section className="card">
        <div className="card-h">
          <h3>{t('trends.budgets')}</h3>
          <button className="link" onClick={() => setBudgetOpen(true)}>
            + {t('trends.newBudget')}
          </button>
        </div>
        {monthBudgets.length === 0 && <div className="empty">{t('ins.noBudgets')}</div>}
        {monthBudgets.map(b => (
          <div className="budget" key={b.budget.id}>
            <span className={'ico ' + b.budget.category}>
              <Icon name={'c-' + b.budget.category} />
            </span>
            <div className="main">
              <div className="goal-top">
                <b>{t(`cat.${b.budget.category}` as 'cat.UNKNOWN')}</b>
                <span className="small">
                  {m$(b.used)} / {m$(b.limit)}
                </span>
              </div>
              <div className={'bar' + (b.state === 'over' ? ' over' : b.state === 'warn' ? ' warn' : ' ok')}>
                <i style={{ width: Math.min(100, b.pct) + '%' }} />
              </div>
              <div className={'small budget-note ' + b.state}>
                {b.state === 'over'
                  ? t('trends.over', { amount: m$(-b.left) })
                  : isCurrent
                    ? t('ins.leftPerDay', { amount: m$(b.left), perDay: m$(b.perDay) })
                    : t('trends.left', { amount: m$(b.left) })}
              </div>
            </div>
          </div>
        ))}
      </section>

      <section className="card">
        <div className="card-h">
          <h3>{t('trends.byCategory')}</h3>
        </div>
        {parts.length === 0 ? (
          <div className="empty">{t('trends.noSpend')}</div>
        ) : (
          <div className="cat-split">
            <Donut parts={parts} total={s.spent} centerLabel={t('ins.spentShort')} />
            <ul className="cat-legend">
              {parts.map(p => {
                const pct = s.spent > 0n ? Number((p.cents * 100n) / s.spent) : 0;
                const ch = change(p.cents, prev.byCategory[p.key] ?? 0n);
                return (
                  <li key={p.key}>
                    <i className="sw" style={{ background: `var(--cat-${p.key})` }} />
                    <span className="main">
                      <b>{p.label}</b>
                      <span className="mut small">
                        {pct}% {ch !== null && <span className={ch <= 0 ? 'good' : 'bad'}>{ch <= 0 ? '↓' : '↑'}{Math.abs(ch)}%</span>}
                      </span>
                    </span>
                    <span className="v">{m$(p.cents)}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-h">
          <h3>{t('ins.cashflow')}</h3>
        </div>
        <CashflowBars data={flow} labels={{ income: t('ins.income'), spent: t('ins.spentShort') }} />
      </section>

      {s.merchants.length > 0 && (
        <section className="card flush">
          <div className="card-h">
            <h3>{t('ins.top')}</h3>
          </div>
          {s.merchants.map((x, i) => (
            <div className="row" key={x.name}>
              <span className="rank">{i + 1}</span>
              <span className="main">
                <span className="t" style={{ display: 'block' }}>
                  {x.name}
                </span>
                <span className="s" style={{ display: 'block' }}>
                  {t('ins.visits', { n: x.count })}
                </span>
              </span>
              <span className="v">{m$(x.cents)}</span>
            </div>
          ))}
        </section>
      )}

        </>
      )}

      <BudgetSheet open={budgetOpen} onClose={() => setBudgetOpen(false)} month={monthKey(month)} onSaved={() => pic.reload()} />
    </>
  );
}
