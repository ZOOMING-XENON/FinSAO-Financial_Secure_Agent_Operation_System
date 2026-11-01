import { useState } from 'react';
import type { Key } from '../core/i18n';
import { go, useApp } from '../app/state';
import { Icon } from '../ui/kit';

type Group = 'account' | 'savings' | 'transfer' | 'card' | 'payment' | 'wealth' | 'ledger';
interface Service {
  id: string;
  icon: string;
  label: Key;
  group: Group;
  href?: string; // undefined = not available yet
  hot?: boolean;
}

const SERVICES: Service[] = [
  { id: 'send', icon: 'i-send', label: 'svc.send', group: 'transfer', href: 'pay', hot: true },
  { id: 'recipients', icon: 'i-users', label: 'svc.recipients', group: 'transfer', href: 'pay' },
  { id: 'ledger', icon: 'i-book', label: 'svc.ledger', group: 'ledger', href: 'ledger', hot: true },
  { id: 'receipt', icon: 'i-receipt', label: 'svc.receipt', group: 'ledger', href: 'track' },
  { id: 'pots', icon: 'i-target', label: 'svc.pots', group: 'savings', href: 'wealth', hot: true },
  { id: 'newpot', icon: 'i-plus', label: 'svc.newPot', group: 'savings', href: 'pot/new' },
  { id: 'week52', icon: 'i-cal', label: 'plan.week52', group: 'savings', href: 'pot/new-week52' },
  { id: 'day365', icon: 'i-cal', label: 'plan.day365', group: 'savings', href: 'pot/new-day365' },
  { id: 'bills', icon: 'i-repeat', label: 'svc.bills', group: 'payment', href: 'insights', hot: true },
  { id: 'topup', icon: 'i-phone', label: 'svc.topup', group: 'payment' },
  { id: 'utility', icon: 'i-bolt', label: 'svc.utility', group: 'payment' },
  { id: 'cards', icon: 'i-card', label: 'svc.cards', group: 'card', href: 'cards' },
  { id: 'freeze', icon: 'i-snow', label: 'cards.freeze', group: 'card', href: 'cards' },
  { id: 'limit', icon: 'i-gauge', label: 'cards.limits', group: 'card', href: 'cards' },
  { id: 'accounts', icon: 'i-bank', label: 'svc.accounts', group: 'account', href: 'cards' },
  { id: 'activity', icon: 'i-book', label: 'svc.activity', group: 'account', href: 'activity' },
  { id: 'analytics', icon: 'i-chart', label: 'nav.insights', group: 'account', href: 'insights' },
  { id: 'calendar', icon: 'i-cal', label: 'ins.calendar', group: 'account', href: 'calendar' },
  { id: 'settings', icon: 'i-gear', label: 'svc.settings', group: 'account', href: 'me' },
  { id: 'invest', icon: 'i-trend-up', label: 'inv.title', group: 'wealth', href: 'wealth' },
  { id: 'worth', icon: 'i-wallet', label: 'wealth.netWorth', group: 'wealth', href: 'wealth' },
  { id: 'aegis', icon: 'i-spark', label: 'svc.ask', group: 'wealth', href: 'aegis' },
];
const GROUPS: Group[] = ['account', 'savings', 'transfer', 'card', 'payment', 'wealth', 'ledger'];

export function Services() {
  const { t, toast } = useApp();
  const [q, setQ] = useState('');
  const [group, setGroup] = useState<Group | 'all'>('all');
  const query = q.trim().toLowerCase();
  const open = (s: Service) => (s.href ? go(s.href) : toast(t('svc.soon')));
  const tile = (s: Service) => (
    <button key={s.id} className={'svc' + (s.hot ? ' hot' : '')} onClick={() => open(s)}>
      <span className="i">
        <Icon name={s.icon} />
      </span>
      <span className="l">{t(s.label)}</span>
      {!s.href && <span className="soon-tag">{t('svc.soonTag')}</span>}
    </button>
  );
  const found = query ? SERVICES.filter(s => t(s.label).toLowerCase().includes(query)) : [];

  return (
    <>
      <div className="ph">
        <h1>{t('svc.title')}</h1>
      </div>
      <label className="search">
        <Icon name="i-search" />
        <input value={q} onChange={e => setQ(e.target.value)} placeholder={t('svc.search')} aria-label={t('svc.search')} />
      </label>

      {query ? (
        <section className="card">
          {found.length === 0 ? <div className="empty">{t('svc.none')}</div> : <div className="svc-grid">{found.map(tile)}</div>}
        </section>
      ) : (
        <>
          <section className="card">
            <div className="card-h">
              <h3>{t('svc.frequent')}</h3>
            </div>
            <div className="svc-grid">{SERVICES.filter(s => s.hot).map(tile)}</div>
          </section>

          <div className="svc-tabs" role="tablist">
            {(['all', ...GROUPS] as const).map(g => (
              <button key={g} role="tab" aria-selected={group === g} className={group === g ? 'on' : ''} onClick={() => setGroup(g)}>
                {t(`svc.g.${g}` as 'svc.g.all')}
              </button>
            ))}
          </div>
          {(group === 'all' ? GROUPS : [group]).map(g => (
            <section className="card" key={g}>
              <div className="card-h">
                <h3>{t(`svc.g.${g}` as 'svc.g.all')}</h3>
              </div>
              <div className="svc-grid">{SERVICES.filter(s => s.group === g).map(tile)}</div>
            </section>
          ))}
        </>
      )}
    </>
  );
}
