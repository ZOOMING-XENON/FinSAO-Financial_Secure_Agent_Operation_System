import { useState } from 'react';
import { api } from '../core/api';
import type { Card } from '../core/types';
import { formatMoney } from '../core/money';
import { useApp, useClient, useLoad } from '../app/state';
import { useShield } from '../ui/Shield';
import { Badge, Icon, Skeleton } from '../ui/kit';
import { PersonAvatar } from '../ui/art';
import { PROFILE } from '../core/people';

export function Me() {
  const { t, lang, setLang, theme, setTheme, toast, errorText, refresh } = useApp();
  const { core, agent, log } = useClient();
  const authorize = useShield();
  const cards = useLoad(() => api.get<Card[]>('/cards'));
  const [showLog, setShowLog] = useState(false);

  const cardAction = async (card: Card, action: 'freeze' | 'unfreeze' | 'report-lost') => {
    const type = action === 'report-lost' ? 'card.report_lost' : `card.${action}`;
    const ref = await authorize({
      operationType: type,
      operationId: card.id,
      rows: [[t('shield.card'), `${card.label} · •••• ${card.last_four}`]],
    });
    if (!ref) return;
    try {
      await api.post(`/cards/${card.id}/${action}`, { authorization_ref: ref });
      if (action === 'report-lost') toast(t('me.lostDone'));
      refresh();
    } catch (e) {
      toast(errorText(e));
    }
  };

  const modeLabel = (m: string) => (m === 'live' ? t('me.live') : m === 'demo' ? t('me.demo') : '…');

  return (
    <>
      <div className="profile">
        <PersonAvatar id={PROFILE.key} label={PROFILE.name} size={64} />
        <div>
          <h1>{lang === 'zh' ? `${PROFILE.nameZh} ${PROFILE.name}` : PROFILE.name}</h1>
          <span className="chip ok" style={{ marginTop: 6, height: 28 }}>
            <Icon name="i-shield" />
            {t('home.protected')}
          </span>
        </div>
      </div>

      <div className="section-t">{t('me.cards')}</div>
      {cards.loading && !cards.data && <Skeleton rows={1} />}
      {cards.data?.map(card => {
        const frozen = card.status === 'FROZEN';
        const usable = card.status === 'ACTIVE' || frozen;
        return (
          <div key={card.id}>
            <div className={'bank-card' + (card.status !== 'ACTIVE' ? ' frozen' : '')}>
              <div className="brand-row">
                <span>{PROFILE.name.toUpperCase()}</span>
                <Icon name="i-shield" />
              </div>
              <span className="chipx" />
              <div>
                <div className="num">•••• •••• •••• {card.last_four}</div>
                <div className="small" style={{ opacity: 0.8, marginTop: 4 }}>
                  {card.label}
                </div>
              </div>
              {card.status !== 'ACTIVE' && (
                <div className="frost">
                  <Badge tone={card.status}>{frozen ? t('me.frozen') : card.status}</Badge>
                </div>
              )}
            </div>
            <section className="card flush">
              <button className="row" onClick={() => usable && cardAction(card, frozen ? 'unfreeze' : 'freeze')} disabled={!usable} aria-pressed={frozen}>
                <span className="ico soft">
                  <Icon name="i-snow" />
                </span>
                <span className="main t">{t('me.freeze')}</span>
                <span className={'toggle' + (frozen ? ' on' : '')} aria-hidden="true" />
              </button>
              <div className="row">
                <span className="ico soft">
                  <Icon name="i-target" />
                </span>
                <span className="main t">{t('me.limit')}</span>
                <span className="v">{formatMoney(card.spending_limit)}</span>
              </div>
              {usable && (
                <button className="row" onClick={() => cardAction(card, 'report-lost')}>
                  <span className="ico" style={{ background: 'var(--red-bg)', color: 'var(--red)' }}>
                    <Icon name="i-lock" />
                  </span>
                  <span className="main t" style={{ color: 'var(--red)' }}>
                    {t('me.reportLost')}
                  </span>
                  <Badge tone="RED">RED</Badge>
                </button>
              )}
            </section>
          </div>
        );
      })}

      <div className="section-t">{t('me.security')}</div>
      <section className="card flush tiers">
        {(['GREEN', 'YELLOW', 'RED'] as const).map(tier => (
          <div className="row" key={tier}>
            <span className={'dot ' + tier} />
            <span className="main">
              <b style={{ display: 'block' }}>{t(tier === 'GREEN' ? 'me.green' : tier === 'YELLOW' ? 'me.yellow' : 'me.red')}</b>
              <span className="mut small">{t(tier === 'GREEN' ? 'me.greenD' : tier === 'YELLOW' ? 'me.yellowD' : 'me.redD')}</span>
            </span>
          </div>
        ))}
      </section>

      <div className="section-t">{t('me.settings')}</div>
      <section className="card flush">
        <div className="row">
          <span className="ico soft">
            <Icon name="i-globe" />
          </span>
          <span className="main t">{t('me.language')}</span>
          <div className="seg" style={{ margin: 0, padding: 0 }}>
            <button className={lang === 'zh' ? 'on' : ''} onClick={() => setLang('zh')}>
              中文
            </button>
            <button className={lang === 'en' ? 'on' : ''} onClick={() => setLang('en')}>
              EN
            </button>
          </div>
        </div>
        <div className="row">
          <span className="ico soft">
            <Icon name="i-moon" />
          </span>
          <span className="main t">{t('me.theme')}</span>
          <select className="input" style={{ width: 'auto', height: 40 }} value={theme} onChange={e => setTheme(e.target.value as typeof theme)} aria-label={t('me.theme')}>
            <option value="system">{t('me.themeSystem')}</option>
            <option value="light">{t('me.themeLight')}</option>
            <option value="dark">{t('me.themeDark')}</option>
          </select>
        </div>
        <div className="row">
          <span className="ico soft">
            <Icon name="i-bell" />
          </span>
          <span className="main">
            <span className="t" style={{ display: 'block' }}>
              {t('me.install')}
            </span>
            <span className="s" style={{ display: 'block', whiteSpace: 'normal' }}>
              {t('me.installHint')}
            </span>
          </span>
        </div>
      </section>

      <div className="section-t">{t('me.connection')}</div>
      <section className="card flush">
        <div className="row">
          <span className="main t">{t('me.core')}</span>
          <span className="v small">
            <span className={'status-dot ' + (core === 'live' ? 'on' : 'demo')} />
            {modeLabel(core)}
          </span>
        </div>
        <div className="row">
          <span className="main t">{t('me.agent')}</span>
          <span className="v small">
            <span className={'status-dot ' + (agent === 'live' ? 'on' : 'demo')} />
            {agent === 'live' ? t('me.live') : agent === 'demo' ? t('me.offline') : '…'}
          </span>
        </div>
        <button className="row" onClick={() => setShowLog(v => !v)} aria-expanded={showLog}>
          <span className="ico soft">
            <Icon name="i-code" />
          </span>
          <span className="main t">{t('me.log')}</span>
          <span className="mut small">{log.length}</span>
        </button>
        {showLog && (
          <div className="log" style={{ padding: '0 16px 10px' }}>
            <p className="mut small">{t('me.logHint')}</p>
            {log.length === 0 && <p className="mut small">{t('me.logEmpty')}</p>}
            {log.map(l => (
              <details key={l.traceId}>
                <summary>
                  {l.method} {l.path} → {l.status}
                </summary>
                <pre>{JSON.stringify({ trace_id: l.traceId, at: l.at, request: l.request, response: l.response }, null, 1)}</pre>
              </details>
            ))}
          </div>
        )}
      </section>
      <p className="mut small" style={{ textAlign: 'center', marginTop: 18 }}>
        Aegis · {t('brand.tagline')}
      </p>
    </>
  );
}
