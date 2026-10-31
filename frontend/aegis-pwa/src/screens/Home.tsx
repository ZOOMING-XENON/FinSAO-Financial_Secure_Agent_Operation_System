import { useState } from 'react';
import { api } from '../core/api';
import type { Account, Balance, Budget, BudgetStatus, SavingsPot, Subscription, Transaction, TransactionPage } from '../core/types';
import { formatMoney, fromCents, toCents } from '../core/money';
import { budgetView, buildNudges, currentMonth, summarize, type BudgetView, type Nudge } from '../core/insights';
import { categoryKey } from '../core/format';
import { PROFILE } from '../core/people';
import { go, useApp, useLoad } from '../app/state';
import { Amount, Icon, Skeleton } from '../ui/kit';
import { TxRow } from '../ui/TxRow';
import { PersonAvatar } from '../ui/art';
import { PeopleStrip } from './Pay';

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

export async function loadBudgetViews(): Promise<BudgetView[]> {
  const budgets = await api.get<Budget[]>('/budgets');
  const statuses = await Promise.all(budgets.map(b => api.get<BudgetStatus>(`/budgets/${b.id}/status`)));
  return budgets.map((b, i) => budgetView(b, statuses[i]));
}

/** Everything Home and Insights need for reminders, loaded once. */
export async function loadMoneyPicture() {
  const accounts = await loadAccounts();
  const [tx, budgets, subs, pots] = await Promise.all([
    loadRecent(accounts, 200),
    loadBudgetViews(),
    api.get<Subscription[]>('/subscriptions'),
    api.get<SavingsPot[]>('/savings-pots'),
  ]);
  return { accounts, tx, budgets, subs, pots };
}
export type MoneyPicture = Awaited<ReturnType<typeof loadMoneyPicture>>;

export function useNudges(data: MoneyPicture | undefined): Nudge[] {
  const { t } = useApp();
  if (!data) return [];
  return buildNudges({
    budgets: data.budgets,
    subs: data.subs,
    pots: data.pots,
    tx: data.tx,
    money: c => formatMoney(fromCents(c)),
    cat: c => t(`cat.${categoryKey(c)}`),
  });
}

export function NudgeCard({ n }: { n: Nudge }) {
  const { t } = useApp();
  return (
    <a className={'nudge ' + n.tone} href={n.href}>
      <span className="nudge-ico">
        <Icon name={n.icon} />
      </span>
      <span className="nudge-txt">{t(n.key as 'nudge.left', n.vars)}</span>
    </a>
  );
}

export function Home() {
  const { t, lang, toast } = useApp();
  const pic = useLoad(loadMoneyPicture);
  const nudges = useNudges(pic.data);
  const [slide, setSlide] = useState(0);
  const accounts = pic.data?.accounts;
  const total = fromCents((accounts ?? []).reduce((s, a) => s + toCents(a.balance), 0n));
  const month = pic.data ? summarize(pic.data.tx, currentMonth()) : null;
  const net = month ? month.income - month.spent : 0n;
  const hour = new Date().getHours();
  const first = lang === 'zh' ? PROFILE.nameZh : PROFILE.name.split(' ')[0];
  const greet = t(hour < 12 ? 'home.morning' : hour < 18 ? 'home.afternoon' : 'home.evening', { name: first });

  return (
    <>
      <header className="home-top">
        <div className="home-bar">
          <a href="#/me" aria-label={t('nav.me')}>
            <PersonAvatar id={PROFILE.key} label={PROFILE.name} size={40} />
          </a>
          <span className="home-hi">{greet}</span>
          <span className="spacer" />
          <a className="chip ok" href="#/me">
            <Icon name="i-shield" />
            {t('home.protected')}
          </a>
        </div>
        <div className="home-total">
          <span className="hero-t">{t('home.total')}</span>
          {accounts ? <Amount value={total} className="big" /> : <span className="amt big">…</span>}
          {month && (month.income > 0n || month.spent > 0n) && (
            <span className={'delta ' + (net >= 0n ? 'up' : 'down')}>
              <Icon name={net >= 0n ? 'i-trend-up' : 'i-trend-down'} />
              {t(net >= 0n ? 'home.netUp' : 'home.netDown', { amount: formatMoney(fromCents(net < 0n ? -net : net)) })}
            </span>
          )}
        </div>
      </header>

      <div className="pad">
        <div
          className="carousel"
          onScroll={e => {
            const el = e.currentTarget;
            const width = (el.firstElementChild as HTMLElement | null)?.offsetWidth || 1;
            setSlide(Math.round(el.scrollLeft / (width + 12)));
          }}
        >
          {!accounts && <div className="acct g0" />}
          {(accounts ?? []).map((a, i) => (
            <section className={'acct g' + (i % 3)} key={a.id} aria-label={a.name}>
              <div className="acct-head">
                <div>
                  <div className="acct-name">{a.name}</div>
                  <div className="acct-no">
                    <Icon name="i-lock" />
                    •••• {a.account_number.slice(-4)} · {a.currency}
                  </div>
                </div>
                <Icon name="i-shield" className="acct-badge" />
              </div>
              <div className="acct-bal">
                <Amount value={a.balance} currency={a.currency} />
              </div>
            </section>
          ))}
        </div>
        {(accounts?.length ?? 0) > 1 && (
          <div className="dots" aria-hidden="true">
            {accounts!.map((a, i) => (
              <i key={a.id} className={i === slide ? 'on' : ''} />
            ))}
          </div>
        )}

        <nav className="actions" aria-label={t('home.quick')}>
          <a href="#/pay" className="act a1">
            <span>
              <Icon name="i-send" />
            </span>
            {t('home.tileSend')}
          </a>
          <a href="#/track" className="act a2">
            <span>
              <Icon name="i-receipt" />
            </span>
            {t('home.tileScan')}
          </a>
          <a href="#/wealth" className="act a3">
            <span>
              <Icon name="i-target" />
            </span>
            {t('home.tileSave')}
          </a>
          <button className="act a4" onClick={() => toast(t('home.addMoneyPreview'))}>
            <span>
              <Icon name="i-plus" />
            </span>
            {t('home.addMoney')}
          </button>
        </nav>

        {nudges.length > 0 && (
          <>
            <div className="sec-h">
              <h2>{t('home.forYou')}</h2>
              <a className="link" href="#/insights">
                {t('home.seeInsights')}
              </a>
            </div>
            <div className="nudges">
              {nudges.slice(0, 6).map(x => (
                <NudgeCard n={x} key={x.id} />
              ))}
            </div>
          </>
        )}

        <button className="ask" onClick={() => go('aegis')}>
          <span className="orb-sm" />
          <span>{t('home.ask')}</span>
          <Icon name="i-mic" />
        </button>

        <div className="sec-h">
          <h2>{t('home.people')}</h2>
          <a className="link" href="#/pay">
            {t('home.seeAll')}
          </a>
        </div>
        <PeopleStrip />

        <section className="card flush" aria-label={t('home.activity')}>
          <div className="card-h">
            <h3>{t('home.activity')}</h3>
            <a className="link" href="#/activity">
              {t('home.seeAll')}
            </a>
          </div>
          {pic.loading && !pic.data && <Skeleton rows={3} />}
          {pic.data?.tx.length === 0 && <div className="empty">{t('home.noActivity')}</div>}
          {pic.data?.tx.slice(0, 5).map(tx => <TxRow tx={tx} key={tx.id} />)}
        </section>
      </div>
    </>
  );
}
