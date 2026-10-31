import { useEffect, useState, type ReactNode } from 'react';
import { api } from '../core/api';
import { CATEGORIES, type Category, type Transaction } from '../core/types';
import { categoryKey, direction, formatDate } from '../core/format';
import { formatMoney, toCents } from '../core/money';
import { recognizeReceipt, type ReceiptGuess } from '../core/recognition';
import { useApp, useLoad } from '../app/state';
import { Amount, Icon, Sheet, Skeleton } from '../ui/kit';
import { loadAccounts, loadRecent } from './Home';

export function Track() {
  const { t, locale, toast, errorText, refresh } = useApp();
  const recent = useLoad(async () => (await loadRecent(await loadAccounts(), 100)).filter(x => direction(x) === 'out'));
  const [photo, setPhoto] = useState<string | null>(null);
  const [state, setState] = useState<'idle' | 'reading' | 'done' | 'unavailable'>('idle');
  const [guess, setGuess] = useState<ReceiptGuess | null>(null);
  const [example, setExample] = useState(false);
  const [editing, setEditing] = useState<Transaction | null>(null);

  useEffect(() => () => {
    if (photo) URL.revokeObjectURL(photo);
  }, [photo]);

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    if (photo) URL.revokeObjectURL(photo);
    setPhoto(URL.createObjectURL(file));
    setGuess(null);
    setState('reading');
    try {
      const r = await recognizeReceipt(file);
      setGuess(r.guess);
      setExample(r.example);
      setState('done');
    } catch {
      setState('unavailable');
    }
  };

  const setCategory = async (tx: Transaction, category: Category) => {
    try {
      await api.patch(`/transactions/${tx.id}/category`, { category });
      toast(t('track.saved', { cat: t(`cat.${category}`) }));
      setEditing(null);
      recent.reload();
      refresh();
    } catch (e) {
      toast(errorText(e));
    }
  };

  const matches = guess ? (recent.data ?? []).filter(x => toCents(x.amount) === toCents(guess.amount)) : [];
  const needs = (recent.data ?? []).filter(x => !x.category || categoryKey(x.category) === 'UNKNOWN');
  const rest = (recent.data ?? []).filter(x => !needs.includes(x));

  const row = (x: Transaction, action?: ReactNode) => {
    const cat = categoryKey(x.category);
    const missing = !x.category || cat === 'UNKNOWN';
    return (
      <div className="row" key={x.id}>
        <span className={'ico ' + cat}>
          <Icon name={'c-' + cat} />
        </span>
        <span className="main">
          <span className="t" style={{ display: 'block' }}>
            {x.description}
          </span>
          <span className="s" style={{ display: 'block' }}>
            {formatDate(x.posted_at, locale)} · {formatMoney(x.amount, x.currency)}
          </span>
        </span>
        {action ?? (
          <button className={'chip-cat' + (missing ? ' need' : '')} onClick={() => setEditing(x)}>
            {missing ? t('track.needs') : t(`cat.${cat}`)}
            <Icon name="i-chev" />
          </button>
        )}
      </div>
    );
  };

  return (
    <>
      <div className="ph">
        <a className="icon-btn" href="#/home" aria-label={t('common.back')}>
          <Icon name="i-back" />
        </a>
        <h2>{t('track.title')}</h2>
        <span style={{ width: 40 }} />
      </div>

      <label className="drop" htmlFor="receipt">
        <span className="sq">
          <Icon name="i-camera" />
        </span>
        <b>{t('track.scan')}</b>
        <span className="mut small">{t('track.scanHint')}</span>
        <input id="receipt" type="file" accept="image/*" capture="environment" onChange={e => onFile(e.target.files?.[0])} />
      </label>

      {photo && (
        <section className="card" style={{ marginTop: 14 }}>
          <img className="receipt-img" src={photo} alt={t('track.photo')} />
          {state === 'reading' && <p className="mut small">{t('track.reading')}</p>}
          {state === 'unavailable' && <p className="small" style={{ color: 'var(--yellow)' }}>{t('track.unavailable')}</p>}
          {state === 'done' && guess && (
            <>
              {example && <p className="small" style={{ color: 'var(--yellow)', fontWeight: 700 }}>{t('track.example')}</p>}
              <div className="kv">
                <span>{t('track.merchant')}</span>
                <span>{guess.merchant || '—'}</span>
              </div>
              <div className="kv">
                <span>{t('track.amount')}</span>
                <span>{formatMoney(guess.amount, guess.currency)}</span>
              </div>
              <div className="kv">
                <span>{t('track.date')}</span>
                <span>{guess.date ? formatDate(guess.date, locale, { year: 'numeric', month: 'short', day: 'numeric' }) : '—'}</span>
              </div>
              <label className="f">{t('track.category')}</label>
              <div className="cat-pick">
                {CATEGORIES.map(c => (
                  <button key={c} className={guess.category === c ? 'on' : ''} onClick={() => setGuess({ ...guess, category: c })} aria-pressed={guess.category === c}>
                    <span className={'ico ' + c}>
                      <Icon name={'c-' + c} />
                    </span>
                    {t(`cat.${c}`)}
                  </button>
                ))}
              </div>
              <label className="f">{t('track.match')}</label>
              {matches.length === 0 && <p className="mut small">{t('track.noMatch')}</p>}
              {matches.map(x =>
                row(
                  x,
                  <button className="btn primary" style={{ width: 'auto', height: 40, fontSize: 14 }} onClick={() => setCategory(x, guess.category)}>
                    {t('track.use')}
                  </button>,
                ),
              )}
            </>
          )}
        </section>
      )}

      {needs.length > 0 && (
        <section className="card flush" style={{ marginTop: 14 }}>
          <div className="card-h">
            <h3>{t('track.needsTitle')}</h3>
            <span className="badge YELLOW">{needs.length}</span>
          </div>
          {needs.map(x => row(x))}
        </section>
      )}

      <section className="card flush" style={{ marginTop: 14 }}>
        <div className="card-h">
          <h3>{t('track.review')}</h3>
        </div>
        <p className="mut small" style={{ margin: '0 16px 6px' }}>
          {t('track.reviewHint')}
        </p>
        {recent.loading && !recent.data && <Skeleton rows={3} />}
        {recent.data?.length === 0 && <div className="empty">{t('trends.noSpend')}</div>}
        {rest.map(x => row(x))}
      </section>

      <Sheet open={!!editing} onClose={() => setEditing(null)} label={t('track.category')}>
        {editing && (
          <>
            <h3>{editing.description}</h3>
            <p className="sub">
              {formatDate(editing.posted_at, locale)} · <Amount value={editing.amount} currency={editing.currency} />
            </p>
            <div className="cat-pick">
              {CATEGORIES.map(c => (
                <button key={c} className={categoryKey(editing.category) === c ? 'on' : ''} onClick={() => setCategory(editing, c)}>
                  <span className={'ico ' + c}>
                    <Icon name={'c-' + c} />
                  </span>
                  {t(`cat.${c}`)}
                </button>
              ))}
            </div>
          </>
        )}
      </Sheet>
    </>
  );
}
