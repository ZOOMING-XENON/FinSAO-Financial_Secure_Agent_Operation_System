import { useState } from 'react';
import { api } from '../core/api';
import type { Account, Balance, Budget, BudgetStatus, SavingsPot, Subscription, Transaction, TransactionPage } from '../core/types';
import { categoryKey, daysUntil, formatDate } from '../core/format';
import { formatMoney, fromCents, percent, toCents } from '../core/money';
import { go, useApp, useLoad } from '../app/state';
import { Amount, Icon, potArt, Skeleton } from '../ui/kit';
import { TxRow } from '../ui/TxRow';
import { loadFreeToSave } from './Pot';

export interface AccountWithBalance extends Account {
  balance: string;
}

export async function loadAccounts(): Promise<AccountWithBalance[]> {
  const accounts = await api.get<Account[]>('/accounts');
  const balances = await Promise.all(accounts.map(a => api.get<Balance>(`/accounts/${a.id}/balance`)));
  return accounts.map((a, i) => ({ ...a, balance: balances[i].balance }));
}

export async function loadRecent(accounts: Account[], limit = 20): Promise<Transaction[]> {
  const pages = await Promise.all(accounts.map(a => api.get<TransactionPage>(`/accounts/${a.id}/transactions`, { limit })));
  const seen = new Map<string, Transaction>();
  pages.flatMap(p => p.items).forEach(tx => seen.set(tx.id, tx));
  return [...seen.values()].sort((a, b) => (b.posted_at ?? '').localeCompare(a.posted_at ?? '')).slice(0, limit);
}

export function Home() {
  const { t, locale, toast } = useApp();
  const accounts = useLoad(loadAccounts);
  const recent = useLoad(async () => (accounts.data ? loadRecent(accounts.data, 6) : []), [accounts.data]);
  const subs = useLoad(() => api.get<Subscription[]>('/subscriptions'));
  const pots = useLoad(() => api.get<SavingsPot[]>('/savings-pots'));
  const insight = useLoad(async () => {
    const budgets = await api.get<Budget[]>('/budgets');
    const latest = [...budgets].sort((a, b) => b.month.localeCompare(a.month))[0];
    if (!latest) return null;
    return { budget: latest, status: await api.get<BudgetStatus>(`/budgets/${latest.id}/status`) };
  });
  const room = useLoad(loadFreeToSave);
  const [slide, setSlide] = useState(0);

  const active = (subs.data ?? []).filter(s => s.active);
  const nextDue = [...active].sort((a, b) => a.next_billing_date.localeCompare(b.next_billing_date))[0];
  const dueTotal = fromCents(active.reduce((sum, s) => sum + toCents(s.amount), 0n));
  const dueIn = nextDue ? daysUntil(nextDue.next_billing_date) : 0;

  return (
    <>
      <header className="top">
        <a className="avatar" href="#/me" aria-label={t('nav.me')}>
          <Icon name="i-user" />
        </a>
        <a className="chip ok" href="#/me">
          <Icon name="i-shield" />
          {t('home.protected')}
        </a>
        <span className="spacer" />
        <button className="icon-btn brand" aria-label={t('home.send')} onClick={() => go('pay')}>
          <Icon name="i-plus" />
        </button>
      </header>

      <div
        className="carousel"
        onScroll={e => {
          const el = e.currentTarget;
          const width = (el.firstElementChild as HTMLElement | null)?.offsetWidth || 1;
          setSlide(Math.round(el.scrollLeft / (width + 12)));
        }}
      >
        {accounts.loading && !accounts.data && <div className="acct g0" />}
        {(accounts.data ?? []).map((a, i) => (
          <section className={'acct g' + (i % 3)} key={a.id} aria-label={a.name}>
            <div className="acct-head">
              <div>
                <div className="acct-name">{a.name}</div>
                <div className="acct-no">
                  <Icon name="i-lock" />
                  •••• {a.account_number.slice(-4)} · {a.currency}
                </div>
              </div>
              <div className="acct-bal">
                <Amount value={a.balance} currency={a.currency} />
                <small>{t('home.balance')}</small>
              </div>
            </div>
            <div className="acct-actions">
              <button className="pill" onClick={() => go('pay')}>
                <Icon name="i-send" />
                {t('home.send')}
              </button>
              <button className="pill" onClick={() => toast(t('home.addMoneyPreview'))}>
                <Icon name="i-plus" />
                {t('home.addMoney')}
              </button>
              <button className="pill round" aria-label={t('home.card')} onClick={() => go('me')}>
                <Icon name="i-card" />
              </button>
            </div>
          </section>
        ))}
      </div>
      {(accounts.data?.length ?? 0) > 1 && (
        <div className="dots" aria-hidden="true">
          {accounts.data!.map((a, i) => (
            <i key={a.id} className={i === slide ? 'on' : ''} />
          ))}
        </div>
      )}

      <button className="ask" onClick={() => go('aegis')}>
        <span className="orb-sm">
          <Icon name="i-spark" />
        </span>
        <span>{t('home.ask')}</span>
        <Icon name="i-mic" />
      </button>

      {insight.data !== undefined && (
        <InsightCard data={insight.data} />
      )}

      <section className="card flush" aria-label={t('home.activity')}>
        <div className="card-h">
          <h3>{t('home.activity')}</h3>
          <a className="link" href="#/activity">
            {t('home.seeAll')}
          </a>
        </div>
        {active.length > 0 && (
          <a className="row tint" href="#/pay">
            <span className="ico stack soft">
              <Icon name="i-repeat" />
              <b>{active.length}</b>
            </span>
            <span className="main">
              <span className="t" style={{ display: 'block' }}>
                {active.length === 1 ? t('home.upcomingOne') : t('home.upcoming', { n: active.length })}
              </span>
              <span className="s" style={{ display: 'block' }}>
                {dueIn > 0 ? t('home.inDays', { n: dueIn }) : dueIn === 0 ? t('home.today') : formatDate(nextDue.next_billing_date, locale)}
              </span>
            </span>
            <span className="v">
              <Amount value={dueTotal} />
            </span>
          </a>
        )}
        {recent.loading && !recent.data && <Skeleton rows={3} />}
        {recent.data?.length === 0 && <div className="empty">{t('home.noActivity')}</div>}
        {recent.data?.map(tx => <TxRow tx={tx} key={tx.id} />)}
      </section>

      <div className="card-h" style={{ padding: '10px 4px 8px' }}>
        <h3>{t('home.pots')}</h3>
        {room.data && toCents(room.data.setAside) > 0n && (
          <span className="mut small">{t('home.setAside', { aside: formatMoney(room.data.setAside), free: formatMoney(room.data.free) })}</span>
        )}
      </div>
      <div className="pots">
        {(pots.data ?? []).map(p => (
          <a className="pot" href={`#/pot/${p.id}`} key={p.id}>
            <span className="art" style={{ background: potArt(p.id) }} />
            <span className="n">{p.name}</span>
            <Amount value={p.saved_amount} currency={p.currency} />
            <span className="bar">
              <i style={{ width: percent(p.saved_amount, p.target_amount) + '%' }} />
            </span>
          </a>
        ))}
        <a className="pot new" href="#/pot/new">
          <span className="ico">
            <Icon name="i-plus" />
          </span>
          <b>{t('home.newPot')}</b>
        </a>
      </div>
    </>
  );
}

function InsightCard({ data }: { data: { budget: Budget; status: BudgetStatus } | null }) {
  const { t } = useApp();
  if (!data) {
    return (
      <a className="card insight" href="#/trends">
        <span className="ico">
          <Icon name="i-target" />
        </span>
        <span>
          <b>{t('home.insightTitle')}</b>
          <span className="mut small">{t('home.insightNone')}</span>
        </span>
      </a>
    );
  }
  const { budget, status } = data;
  const pct = percent(status.used, status.limit);
  const warn = status.threshold_exceeded || pct >= 80;
  const vars = {
    cat: t(`cat.${categoryKey(budget.category)}`),
    used: formatMoney(status.used),
    limit: formatMoney(status.limit),
  };
  return (
    <a className={'card insight' + (warn ? ' warn' : '')} href="#/trends">
      <span className="ico">
        <Icon name="i-shield" />
      </span>
      <span style={{ flex: 1 }}>
        <b>{t('home.insightTitle')}</b>
        <span className="mut small">{t(warn ? 'home.insightWarn' : 'home.insightOk', vars)}</span>
        <span className={'bar' + (pct >= 100 ? ' over' : warn ? ' warn' : '')}>
          <i style={{ width: pct + '%' }} />
        </span>
      </span>
    </a>
  );
}
