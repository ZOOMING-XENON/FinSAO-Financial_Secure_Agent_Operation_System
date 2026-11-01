import { useEffect, useRef, useState, type ReactNode } from 'react';
import { api, uid } from '../core/api';
import { CATEGORIES, type Category, type Transaction } from '../core/types';
import { categoryKey, direction, formatDate } from '../core/format';
import { formatMoney, isValidAmount, normalizeAmount, toCents } from '../core/money';
import { recognizeReceipt, takePendingReceipt } from '../core/recognition';
import { addLedgerEntry, ledgerCatFor } from '../core/ledger';
import { go, useApp, useLoad } from '../app/state';
import { Amount, Icon, Sheet, Skeleton } from '../ui/kit';
import { loadAccounts, loadRecent } from './Home';

export function Track() {
  const { t, locale, toast, errorText, refresh } = useApp();
  const recent = useLoad(async () => (await loadRecent(await loadAccounts(), 100)).filter(x => direction(x) === 'out'));
  const [photo, setPhoto] = useState<string | null>(null);
  const [state, setState] = useState<'idle' | 'reading' | 'done' | 'failed'>('idle');
  const [progress, setProgress] = useState(0);
  const [merchant, setMerchant] = useState('');
  const [amount, setAmount] = useState('');
  const [date, setDate] = useState<string | null>(null);
  const [cat, setCat] = useState<Category>('UNKNOWN');
  const [editing, setEditing] = useState<Transaction | null>(null);
  const photoRef = useRef<string | null>(null);

  const onFile = async (file: File | undefined | null) => {
    if (!file) return;
    if (photoRef.current) URL.revokeObjectURL(photoRef.current);
    photoRef.current = URL.createObjectURL(file);
    setPhoto(photoRef.current);
    setState('reading');
    setProgress(0);
    try {
      const g = await recognizeReceipt(file, p => setProgress(Math.round(p * 100)));
      setMerchant(g.merchant);
      setAmount(g.amount ?? '');
      setDate(g.date);
      setCat(g.category);
      setState(g.amount ? 'done' : 'failed');
    } catch {
      setState('failed');
    }
  };

  useEffect(() => {
    onFile(takePendingReceipt());
    return () => {
      if (photoRef.current) URL.revokeObjectURL(photoRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const saveCash = () => {
    if (!isValidAmount(amount)) return toast(t('pay.invalidAmount'));
    addLedgerEntry({ id: uid(), kind: 'out', cat: ledgerCatFor(cat), cents: normalizeAmount(amount), note: merchant.trim(), at: date ? `${date}T12:00:00` : new Date().toISOString() });
    toast(t('track.savedCash'));
    go('ledger');
  };

  const valid = isValidAmount(amount);
  const matches = valid ? (recent.data ?? []).filter(x => toCents(x.amount) === toCents(amount)) : [];
  const needs = (recent.data ?? []).filter(x => !x.category || categoryKey(x.category) === 'UNKNOWN');
  const rest = (recent.data ?? []).filter(x => !needs.includes(x)).slice(0, 15);

  const row = (x: Transaction, action?: ReactNode) => {
    const c = categoryKey(x.category);
    const missing = !x.category || c === 'UNKNOWN';
    return (
      <div className="row" key={x.id}>
        <span className="ico">
          <Icon name={'c-' + c} />
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
            {missing ? t('track.needs') : t(`cat.${c}`)}
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
        <span style={{ width: 42 }} />
      </div>

      <label className="drop" htmlFor="receipt">
        <span className="sq">
          <Icon name="i-scan" />
        </span>
        <b>{photo ? t('track.another') : t('track.scan')}</b>
        <span className="mut small">{t('track.scanHint')}</span>
        <input id="receipt" type="file" accept="image/*" capture="environment" onChange={e => onFile(e.target.files?.[0])} />
      </label>

      {photo && (
        <section className="card" style={{ marginTop: 14 }}>
          <img className="receipt-img" src={photo} alt={t('track.photo')} />
          {state === 'reading' && (
            <>
              <p className="mut small">{t('track.reading', { pct: progress })}</p>
              <div className="bar">
                <i style={{ width: progress + '%' }} />
              </div>
            </>
          )}
          {state === 'failed' && <p className="small" style={{ color: 'var(--yellow)' }}>{t('track.failed')}</p>}
          {(state === 'done' || state === 'failed') && (
            <>
              <label className="f" htmlFor="rc-m">
                {t('track.merchant')}
              </label>
              <input id="rc-m" className="input" value={merchant} onChange={e => setMerchant(e.target.value)} />
              <div className="btn-row">
                <div style={{ flex: 1 }}>
                  <label className="f" htmlFor="rc-a">
                    {t('track.amount')}
                  </label>
                  <input id="rc-a" className="input" inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" />
                </div>
                <div style={{ flex: 1 }}>
                  <label className="f">{t('track.date')}</label>
                  <div className="input" style={{ display: 'flex', alignItems: 'center' }}>
                    {date ? formatDate(date, locale, { year: 'numeric', month: 'short', day: 'numeric' }) : t('track.today')}
                  </div>
                </div>
              </div>
              <label className="f">{t('track.category')}</label>
              <div className="cat-pick">
                {CATEGORIES.map(c => (
                  <button key={c} className={cat === c ? 'on' : ''} onClick={() => setCat(c)} aria-pressed={cat === c}>
                    <span className="ico">
                      <Icon name={'c-' + c} />
                    </span>
                    {t(`cat.${c}`)}
                  </button>
                ))}
              </div>
              <label className="f">{t('track.match')}</label>
              {valid && matches.length === 0 && <p className="mut small">{t('track.noMatch')}</p>}
              {matches.map(x =>
                row(
                  x,
                  <button className="btn primary sm" onClick={() => setCategory(x, cat)}>
                    {t('track.use')}
                  </button>,
                ),
              )}
              <button className="btn dark" style={{ marginTop: 12 }} onClick={saveCash} disabled={!valid}>
                <Icon name="i-book" />
                {t('track.saveCash')}
              </button>
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
                  <span className="ico">
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
