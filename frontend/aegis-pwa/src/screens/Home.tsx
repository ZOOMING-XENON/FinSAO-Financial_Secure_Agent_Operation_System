import { useState } from 'react';
import { api } from '../core/api';
import type { Account, Balance, Budget, BudgetStatus, SavingsPot, Subscription, Transaction, TransactionPage } from '../core/types';
import { formatMoney, fromCents, toCents } from '../core/money';
import { budgetView, buildNudges, currentMonth, summarize, type BudgetView, type Nudge } from '../core/insights';
import { categoryKey, daysUntil } from '../core/format';
import { PROFILE } from '../core/people';
import { go, useApp, useLoad } from '../app/state';
import { Amount, Icon, Skeleton } from '../ui/kit';
import { TxRow } from '../ui/TxRow';
import { PersonAvatar } from '../ui/art';
import { PeopleStrip } from './Pay';

export interface AccountWithBalance extends Account {
  balance: string;
}

// Banking Core names the seeded accounts in English; show them in the app's language.
const ACCOUNT_ZH: Record<string, string> = { Checking: '活期账户', Savings: '储蓄账户' };

export async function loadAccounts(): Promise<AccountWithBalance[]> {
  const accounts = await api.get<Account[]>('/accounts');
  const balances = await Promise.all(accounts.map(a => api.get<Balance>(`/accounts/${a.id}/balance`)));
  const zh = api.lang === 'zh-CN';
  return accounts.map((a, i) => ({ ...a, name: zh ? ACCOUNT_ZH[a.name] ?? a.name : a.name, balance: balances[i].balance }));
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

const HIDE_KEY = 'aegis.hideBalance';
function readHidden() {
  try {
    return localStorage.getItem(HIDE_KEY) === '1';
  } catch {
    return false;
  }
}

/** Upcoming subscriptions and bills, soonest first. */
export function BillsCard({ subs }: { subs: Subscription[] }) {
  const { t } = useApp();
  const active = subs.filter(x => x.active).sort((a, b) => a.next_billing_date.localeCompare(b.next_billing_date));
  if (!active.length) return null;
  const total = active.reduce((sum, x) => sum + toCents(x.amount), 0n);
  return (
    <section className="card flush bills-card">
      <div className="card-h">
        <h3>{t('home.bills')}</h3>
        <a className="link" href="#/insights">
          {t('ins.subsTotal', { amount: formatMoney(fromCents(total)) })}
        </a>
      </div>
      <div className="bills">
        {active.slice(0, 4).map(x => {
          const d = daysUntil(x.next_billing_date);
          return (
            <a className={'bill' + (d >= 0 && d <= 3 ? ' soon' : '')} href="#/insights" key={x.id}>
              <span className="bill-ico">
                <Icon name="i-repeat" />
              </span>
              <b>{x.merchant_name}</b>
              <span className="amt">{formatMoney(x.amount, x.currency)}</span>
              <small>{d === 0 ? t('home.today') : d > 0 ? t('home.inDays', { n: d }) : x.next_billing_date}</small>
            </a>
          );
        })}
      </div>
    </section>
  );
}

export function Home() {
  const { t, lang } = useApp();
  const pic = useLoad(loadMoneyPicture);
  const nudges = useNudges(pic.data);
  const [hidden, setHidden] = useState(readHidden);
  const [acct, setAcct] = useState<string>('all');
  const toggleHidden = () => {
    setHidden(h => {
      try {
        localStorage.setItem(HIDE_KEY, h ? '0' : '1');
      } catch {
        /* storage unavailable */
      }
      return !h;
    });
  };
  const accounts = pic.data?.accounts;
  const chosen = accounts?.find(a => a.id === acct);
  const total = chosen ? chosen.balance : fromCents((accounts ?? []).reduce((s, a) => s + toCents(a.balance), 0n));
  const month = pic.data ? summarize(pic.data.tx, currentMonth()) : null;
  const net = month ? month.income - month.spent : 0n;
  const hour = new Date().getHours();
  const name = lang === 'zh' ? PROFILE.nameZh : PROFILE.name;
  const cardsCount = (accounts?.length ?? 0) + 1;

  return (
    <>
      <header className="home-top">
        <div className="home-bar">
          <a href="#/me" aria-label={t('nav.me')}>
            <PersonAvatar id={PROFILE.key} label={PROFILE.name} size={42} />
          </a>
          <span className="home-hi">
            <small>{t(hour < 12 ? 'home.morningShort' : hour < 18 ? 'home.afternoonShort' : 'home.eveningShort')}</small>
            <b>{name}</b>
          </span>
          <span className="spacer" />
          <a className="icon-btn" href="#/insights" aria-label={t('home.forYou')}>
            <Icon name="i-bell" />
          </a>
        </div>

        <div className="home-total">
          <span className="acct-label">{chosen ? `${chosen.name} · ${chosen.account_number}` : t('home.allAccounts', { n: accounts?.length ?? 0 })}</span>
          <span className="total-row">
            {hidden ? <span className="amt big masked">¥ ••••••</span> : accounts ? <Amount value={total} className="big" /> : <span className="amt big">…</span>}
            <button className="eye" onClick={toggleHidden} aria-pressed={hidden} aria-label={t(hidden ? 'home.showBalance' : 'home.hideBalance')}>
              <Icon name={hidden ? 'i-eye-off' : 'i-eye'} />
            </button>
          </span>
          <span className="updated">
            <Icon name="i-clock" />
            {t('home.updated')}
            {!hidden && !chosen && month && (month.income > 0n || month.spent > 0n) && (
              <span className={net >= 0n ? 'good' : 'bad'}>
                {' · '}
                {(net >= 0n ? '+' : '-') + formatMoney(fromCents(net < 0n ? -net : net))} {t('home.thisMonth')}
              </span>
            )}
          </span>
        </div>
        {(accounts?.length ?? 0) > 1 && (
          <div className="acct-chips" role="tablist">
            <button className={acct === 'all' ? 'on' : ''} onClick={() => setAcct('all')} role="tab" aria-selected={acct === 'all'}>
              {t('home.all')}
            </button>
            {accounts!.map(a => (
              <button key={a.id} className={acct === a.id ? 'on' : ''} onClick={() => setAcct(a.id)} role="tab" aria-selected={acct === a.id}>
                {a.name} ··{a.account_number.slice(-4)}
              </button>
            ))}
          </div>
        )}
      </header>

      <div className="pad">
        <div className="sec-h">
          <h2>{t('home.quick')}</h2>
          <a className="link" href="#/services">
            {t('home.more')}
          </a>
        </div>
        <nav className="quick" aria-label={t('home.quick')}>
          <a className="qa" href="#/pay">
            <Icon name="i-send" />
            <b>{t('home.tileSend')}</b>
            <small>{t('home.qaSend')}</small>
          </a>
          <a className="qa" href="#/ledger">
            <Icon name="i-book" />
            <b>{t('home.qaRecord')}</b>
            <small>{t('home.qaRecordD')}</small>
          </a>
          <a className="qa" href="#/insights">
            <Icon name="i-bolt" />
            <b>{t('home.qaBills')}</b>
            <small>{t('home.qaBillsD')}</small>
          </a>
          <a className="qa" href="#/cards">
            <Icon name="i-card" />
            <b>{t('nav.cards')}</b>
            <small>{t('home.qaCardsD', { n: cardsCount })}</small>
          </a>
        </nav>

        <button className="ask" onClick={() => go('aegis')}>
          <span className="orb-sm">
            <Icon name="i-spark" />
          </span>
          <span>{t('home.ask')}</span>
          <Icon name="i-mic" />
        </button>

        {nudges.length > 0 && (
          <>
            <div className="sec-h">
              <h2>{t('home.forYou')}</h2>
              <a className="link" href="#/insights">
                {t('home.seeAll')}
              </a>
            </div>
            <div className="nudges">
              {nudges.slice(0, 3).map(x => (
                <NudgeCard n={x} key={x.id} />
              ))}
            </div>
          </>
        )}

        {pic.data && (
          <>
            <div style={{ height: 14 }} />
            <BillsCard subs={pic.data.subs} />
          </>
        )}

        <div className="sec-h">
          <h2>{t('home.people')}</h2>
          <a className="link" href="#/pay">
            {t('home.seeAll')}
          </a>
        </div>
        <PeopleStrip />

        <div className="sec-h">
          <h2>{t('home.history')}</h2>
          <a className="link" href="#/activity">
            {t('home.seeAll')}
          </a>
        </div>
        <section className="card flush" aria-label={t('home.history')}>
          {pic.loading && !pic.data && <Skeleton rows={3} />}
          {pic.data?.tx.length === 0 && <div className="empty">{t('home.noActivity')}</div>}
          {pic.data?.tx.slice(0, 5).map(tx => <TxRow tx={tx} key={tx.id} />)}
        </section>
      </div>
    </>
  );
}
