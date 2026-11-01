import { useState } from 'react';
import { useApp, useClient } from '../app/state';
import { Icon } from '../ui/kit';
import { ProfileAvatar } from '../ui/art';
import { displayName, resizePhoto, saveProfile, useProfile, type AvatarIcon, type AvatarTone, type Gender } from '../core/profile';

const TONES: AvatarTone[] = ['brand', 'ink', 'lilac', 'grey'];
const ICONS: AvatarIcon[] = ['initials', 'i-shield', 'i-spark', 'i-target', 'i-wallet', 'i-globe', 'i-bolt', 'i-moon'];
const GENDERS: Gender[] = ['female', 'male', 'other', 'unsaid'];

/** Profile: picture or icon, personal details, then the app settings. Reached from Services and the Home avatar. */
export function Me() {
  const { t, lang, setLang, theme, setTheme, toast } = useApp();
  const { core, agent, log } = useClient();
  const [showLog, setShowLog] = useState(false);
  const p = useProfile();
  const name = displayName(p, lang);

  const pickPhoto = async (file: File | undefined) => {
    if (!file) return;
    try {
      saveProfile({ photo: await resizePhoto(file) });
    } catch {
      toast(t('prof.photoFailed'));
    }
  };

  const modeLabel = (m: string) => (m === 'live' ? t('me.live') : m === 'demo' ? t('me.demo') : '…');

  return (
    <>
      <div className="ph">
        <a className="icon-btn" href="#/services" aria-label={t('common.back')}>
          <Icon name="i-back" />
        </a>
        <h2>{t('prof.title')}</h2>
        <span style={{ width: 42 }} />
      </div>

      <div className="prof-head">
        <label className="prof-pic" aria-label={t('prof.photo')}>
          <ProfileAvatar profile={p} label={name} size={104} />
          <span className="prof-cam">
            <Icon name="i-camera" />
          </span>
          <input type="file" accept="image/*" onChange={e => pickPhoto(e.target.files?.[0])} />
        </label>
        <h1>{name}</h1>
        <span className="chip ok" style={{ height: 28 }}>
          <Icon name="i-shield" />
          {t('home.protected')}
        </span>
        {p.photo && (
          <button className="link small" onClick={() => saveProfile({ photo: null })}>
            {t('prof.removePhoto')}
          </button>
        )}
      </div>

      <div className="section-t">{t('prof.icon')}</div>
      <section className="card">
        <div className="tone-row" role="radiogroup" aria-label={t('prof.colour')}>
          {TONES.map(tone => (
            <button key={tone} className={'tone-dot ' + tone + (p.tone === tone ? ' on' : '')} role="radio" aria-checked={p.tone === tone} aria-label={tone} onClick={() => saveProfile({ tone, photo: null })} />
          ))}
        </div>
        <div className="icon-grid" role="radiogroup" aria-label={t('prof.icon')}>
          {ICONS.map(icon => (
            <button key={icon} className={'person avt ' + p.tone + (!p.photo && p.icon === icon ? ' on' : '')} role="radio" aria-checked={!p.photo && p.icon === icon} onClick={() => saveProfile({ icon, photo: null })}>
              {icon === 'initials' ? <span>Aa</span> : <Icon name={icon} />}
            </button>
          ))}
        </div>
      </section>

      <div className="section-t">{t('prof.details')}</div>
      <section className="card">
        <label className="f" htmlFor="pf-name">
          {t('prof.name')}
        </label>
        <input id="pf-name" className="input" value={p.name} onChange={e => saveProfile({ name: e.target.value })} autoComplete="name" />
        <label className="f" htmlFor="pf-zh">
          {t('prof.nameZh')}
        </label>
        <input id="pf-zh" className="input" value={p.nameZh} onChange={e => saveProfile({ nameZh: e.target.value })} />
        <label className="f">{t('prof.gender')}</label>
        <div className="seg gender-seg" role="radiogroup" aria-label={t('prof.gender')}>
          {GENDERS.map(g => (
            <button key={g} className={p.gender === g ? 'on' : ''} role="radio" aria-checked={p.gender === g} onClick={() => saveProfile({ gender: g })}>
              {t(`prof.g.${g}` as 'prof.g.female')}
            </button>
          ))}
        </div>
        <div className="btn-row">
          <div style={{ flex: 1, minWidth: 0 }}>
            <label className="f" htmlFor="pf-bd">
              {t('prof.birthday')}
            </label>
            <input id="pf-bd" className="input" type="date" value={p.birthday} onChange={e => saveProfile({ birthday: e.target.value })} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <label className="f" htmlFor="pf-ph">
              {t('prof.phone')}
            </label>
            <input id="pf-ph" className="input" type="tel" inputMode="tel" value={p.phone} onChange={e => saveProfile({ phone: e.target.value })} autoComplete="tel" placeholder="138 0000 0000" />
          </div>
        </div>
        <p className="mut small" style={{ margin: '12px 0 0' }}>
          {t('prof.local')}
        </p>
      </section>

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
