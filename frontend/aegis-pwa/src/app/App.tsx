import { useEffect, useState } from 'react';
import { api } from '../core/api';
import { AppProvider, useApp, useClient, useHashRoute } from './state';
import { ShieldProvider } from '../ui/Shield';
import { Icon } from '../ui/kit';
import { Home } from '../screens/Home';
import { Trends } from '../screens/Trends';
import { Aegis } from '../screens/Aegis';
import { Pay } from '../screens/Pay';
import { Me } from '../screens/Me';
import { NewPot, PotDetail } from '../screens/Pot';
import { Activity } from '../screens/Activity';

const TABS = [
  { id: 'home', icon: 'i-home', key: 'nav.home' },
  { id: 'trends', icon: 'i-chart', key: 'nav.trends' },
  { id: 'aegis', icon: 'i-shield', key: 'nav.aegis' },
  { id: 'pay', icon: 'i-swap', key: 'nav.pay' },
  { id: 'me', icon: 'i-user', key: 'nav.me' },
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
      view = <Trends />;
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
    case 'activity':
      view = <Activity />;
      break;
    case 'pot':
      if (arg === 'new') view = <NewPot />;
      else {
        view = <PotDetail id={arg} key={arg} />;
        mainClass = 'full';
      }
      break;
    default:
      view = <Home />;
  }
  const activeTab = route === 'pot' || route === 'activity' ? 'home' : route;

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
