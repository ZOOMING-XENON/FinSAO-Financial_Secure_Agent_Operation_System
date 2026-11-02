import { Inbox } from '../screens/Inbox';
import { useEffect, useState } from 'react';
import { api } from '../core/api';
import { AppProvider, useApp, useClient, useHashRoute } from './state';
import { ShieldProvider } from '../ui/Shield';
import { Icon } from '../ui/kit';
import { Home } from '../screens/Home';
import { Insights } from '../screens/Insights';
import { Calendar } from '../screens/Calendar';
import { Wealth } from '../screens/Wealth';
import { Aegis } from '../screens/Aegis';
import { Pay } from '../screens/Pay';
import { Me } from '../screens/Me';
import { NewPot, PotDetail } from '../screens/Pot';
import { Activity } from '../screens/Activity';
import { Track } from '../screens/Track';
import { Cards } from '../screens/Cards';
import { Services } from '../screens/Services';
import { Ledger } from '../screens/Ledger';

const TABS = [
  { id: 'home', icon: 'i-home', key: 'nav.home' },
  { id: 'cards', icon: 'i-card', key: 'nav.cards' },
  { id: 'aegis', icon: 'i-shield', key: 'nav.aegis' },
  { id: 'insights', icon: 'i-chart', key: 'nav.insights' },
  { id: 'services', icon: 'i-wallet', key: 'nav.services' },
] as const;

function Shell() {
  const { t } = useApp();
  const { core } = useClient();
  const [route, arg] = useHashRoute();
  // Tapping the active tab again resets that screen (e.g. back from a receipt).
  const [reset, setReset] = useState(0);

  useEffect(() => {
    api.detect();
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
    document.getElementById('view')?.focus({ preventScroll: true });
  }, [route, arg]);

  let view;
  let mainClass = '';
  switch (route) {
    case 'trends':
    case 'insights':
      view = <Insights />;
      break;
    case 'calendar':
      view = <Calendar />;
      break;
    case 'wealth':
      view = <Wealth />;
      break;
    case 'cards':
      view = <Cards />;
      break;
    case 'services':
      view = <Services />;
      break;
    case 'ledger':
      view = <Ledger key={arg ?? 'ledger'} startRecording={arg === 'new'} />;
      break;
    case 'aegis':
      view = <Aegis />;
      mainClass = 'chat';
      break;
    case 'pay':
      view = <Pay key={arg ?? 'pay'} preselect={arg} />;
      break;
    case 'me':
      view = <Me />;
      break;
    case 'inbox':
      view = <Inbox />;
      break;
    case 'activity':
      view = <Activity />;
      break;
    case 'track':
      view = <Track />;
      break;
    case 'pot':
      if (arg?.startsWith('new')) view = <NewPot key={arg} initialPlan={arg === 'new-week52' ? 'week52' : arg === 'new-day365' ? 'day365' : undefined} />;
      else {
        view = <PotDetail id={arg} key={arg} />;
        mainClass = 'full';
      }
      break;
    default:
      view = <Home />;
      mainClass = 'home';
  }
  const parentTab: Record<string, string> = { pot: 'services', wealth: 'services', ledger: 'services', me: 'services', calendar: 'insights', trends: 'insights', track: 'services', activity: 'home', pay: 'home', inbox: 'home' };
  const activeTab = parentTab[route] ?? (TABS.some(x => x.id === route) ? route : 'home');

  return (
    <>
      {core === 'demo' && <div className="conn">{t('conn.demo', { code: api.mfaHint ?? '' })}</div>}
      <main id="view" tabIndex={-1} className={mainClass} key={reset}>
        {view}
      </main>
      <nav className="tabs" aria-label="Main">
        {TABS.map(tab => (
          <a key={tab.id} href={'#/' + tab.id} className={(tab.id === activeTab ? 'on ' : '') + (tab.id === 'aegis' ? 'tab-shield' : '')} aria-current={tab.id === activeTab ? 'page' : undefined}
            onClick={() => tab.id === route && !arg && setReset(r => r + 1)}
          >
            {tab.id === 'aegis' ? (
              <span className="shield-btn">
                <Icon name={tab.icon} />
              </span>
            ) : (
              <Icon name={tab.icon} />
            )}
            <span>{t(tab.key)}</span>
          </a>
        ))}
      </nav>
    </>
  );
}

export function App() {
  return (
    <AppProvider>
      <ShieldProvider>
        <Shell />
      </ShieldProvider>
    </AppProvider>
  );
}
