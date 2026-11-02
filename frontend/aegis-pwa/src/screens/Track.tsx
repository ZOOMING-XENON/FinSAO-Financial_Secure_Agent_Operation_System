import { useEffect, useRef, useState, type ReactNode } from 'react';
import { api, uid } from '../core/api';
import { CATEGORIES, type Category, type Transaction } from '../core/types';
import { categoryKey, direction, formatDate } from '../core/format';
import { formatMoney, isValidAmount, normalizeAmount, toCents } from '../core/money';
import { recognizeReceipt, takePendingReceipts } from '../core/recognition';
import { addLedgerEntry, ledgerCatFor } from '../core/ledger';
import { go, useApp, useLoad } from '../app/state';
import { Amount, Icon, Sheet, Skeleton } from '../ui/kit';
import { loadAccounts, loadRecent } from './Home';

interface Found {
  id: string;
  photo: number;
  merchant: string;
  amount: string;
  currency: string;
  date: string | null;
  cat: Category;
  kind: 'out' | 'in';
  include: boolean;
}

export function Track() {
  const { t, locale, toast, errorText, refresh } = useApp();
  const recent = useLoad(async () => (await loadRecent(await loadAccounts(), 100)).filter(x => direction(x) === 'out'));
  const [photos, setPhotos] = useState<string[]>([]);
  const [state, setState] = useState<'idle' | 'reading' | 'done' | 'failed'>('idle');
  const [progress, setProgress] = useState(0);
  const [reading, setReading] = useState({ n: 0, of: 0 });
  const [items, setItems] = useState<Found[]>([]);
  const [editing, setEditing] = useState<Transaction | null>(null);
  const urls = useRef<string[]>([]);

  const onFiles = async (files: File[]) => {
    if (!files.length) return;
    urls.current.forEach(u => URL.revokeObjectURL(u));
    urls.current = files.map(f => URL.createObjectURL(f));
    setPhotos(urls.current);
    setItems([]);
    setState('reading');
    const found: Found[] = [];
    for (let i = 0; i < files.length; i++) {
      setReading({ n: i + 1, of: files.length });
      setProgress(0);
      try {
        const guesses = await recognizeReceipt(files[i], p => setProgress(Math.round(p * 100)));
        for (const g of guesses) {
          found.push({ id: uid(), photo: i, merchant: g.merchant, amount: g.amount ?? '', currency: g.currency, date: g.date, cat: g.category, kind: g.kind, include: g.kind === 'out' });
        }
      } catch {
        /* unreadable picture: the others still count */
      }
      setItems([...found]);
    }
    if (!found.length) found.push({ id: uid(), photo: 0, merchant: '', amount: '', currency: 'CNY', date: null, cat: 'UNKNOWN', kind: 'out', include: true });
    setItems(found);
    setState(found.some(x => x.amount) ? 'done' : 'failed');
  };

  useEffect(() => {
    onFiles(takePendingReceipts());
    return () => urls.current.forEach(u => URL.revokeObjectURL(u));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patch = (id: string, change: Partial<Found>) => setItems(list => list.map(x => (x.id === id ? { ...x, ...change } : x)));

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

  const chosen = items.filter(x => x.include && isValidAmount(x.amount));
  const saveCash = async () => {
    if (!chosen.length) return toast(t('pay.invalidAmount'));
    if (chosen.some(x => !x.merchant.trim())) return toast(t('track.merchantRequired'));
    const saveLocal = (rows: Found[]) => {
      for (const x of rows) {
        const cat = x.kind === 'in' ? (/salary|payroll/i.test(x.merchant) ? 'salary' : 'other') : ledgerCatFor(x.cat);
        addLedgerEntry({ id: uid(), kind: x.kind, cat, cents: normalizeAmount(x.amount), note: x.merchant.trim(), at: x.date ? `${x.date}T12:00:00` : new Date().toISOString() });
      }
    };
    const outgoing = chosen.filter(item => item.kind === 'out');
    if (api.core === 'live' && outgoing.length > 0) {
      try {
        for (const x of outgoing) {
          await api.post('/expenses', {
            amount: normalizeAmount(x.amount),
            currency: x.currency,
            merchant: x.merchant.trim(),
            category: x.cat,
            occurred_at: x.date ? new Date(`${x.date}T12:00:00`).toISOString() : undefined,
            origin: 'MANUAL',
          }, { 'Idempotency-Key': `receipt-${x.id}` });
        }
        saveLocal(chosen.filter(item => item.kind === 'in'));
        toast(chosen.length > 1 ? t('track.savedMany', { n: chosen.length }) : t('track.savedCash'));
        recent.reload();
        refresh();
        go('activity');
        return;
      } catch (e) {
        toast(errorText(e));
        return;
      }
    }
    saveLocal(chosen);
    toast(chosen.length > 1 ? t('track.savedMany', { n: chosen.length }) : t('track.savedCash'));
    go('ledger');
  };

  const matchesFor = (x: Found) => (x.kind === 'out' && isValidAmount(x.amount) ? (recent.data ?? []).filter(tx => toCents(tx.amount) === toCents(x.amount)) : []);
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
        <b>{photos.length ? t('track.another') : t('track.scan')}</b>
        <span className="mut small">{t('track.pickHint')}</span>
        <input id="receipt" type="file" accept="image/*" multiple onChange={e => onFiles([...(e.target.files ?? [])])} />
      </label>

      {photos.length > 0 && (
        <div className="receipt-thumbs">
          {photos.map((src, i) => (
            <img key={src} src={src} alt={t('track.fromPhoto', { n: i + 1 })} />
          ))}
        </div>
      )}

      {state === 'reading' && (
        <section className="card" style={{ marginTop: 14 }}>
          <p className="mut small" style={{ marginTop: 0 }}>
            {reading.of > 1 ? `${t('track.fromPhoto', { n: reading.n })} / ${reading.of} · ` : ''}
            {t('track.reading', { pct: progress })}
          </p>
          <div className="bar">
            <i style={{ width: progress + '%' }} />
          </div>
        </section>
      )}

      {(state === 'done' || state === 'failed') && (
        <>
          {state === 'failed' && <p className="small" style={{ color: 'var(--yellow)', margin: '12px 4px 0' }}>{t('track.failed')}</p>}
          {items.length > 1 && (
            <div className="sec-h" style={{ marginTop: 16 }}>
              <h2>{t('track.found', { n: items.length })}</h2>
            </div>
          )}
          {items.map(x => {
            const matches = matchesFor(x);
            return (
              <section className={'card found' + (x.include ? '' : ' off')} key={x.id} style={{ marginTop: 12 }}>
                {items.length > 1 && (
                  <label className="found-top">
                    <input type="checkbox" checked={x.include} onChange={e => patch(x.id, { include: e.target.checked })} />
                    <span>{t('track.include')}</span>
                    <span className="spacer" />
                    {photos.length > 1 && <span className="mut small">{t('track.fromPhoto', { n: x.photo + 1 })}</span>}
                    <span className={'badge ' + (x.kind === 'in' ? 'GREEN' : 'INFO')}>{t(x.kind === 'in' ? 'led.income' : 'led.expense')}</span>
                  </label>
                )}
                <label className="f" htmlFor={'m' + x.id}>
                  {t('track.merchant')}
                </label>
                <input id={'m' + x.id} className="input" value={x.merchant} onChange={e => patch(x.id, { merchant: e.target.value })} />
                <div className="btn-row">
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <label className="f" htmlFor={'a' + x.id}>
                      {t('track.amount')}
                    </label>
                    <input id={'a' + x.id} className="input" inputMode="decimal" value={x.amount} onChange={e => patch(x.id, { amount: e.target.value })} placeholder="0.00" />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <label className="f" htmlFor={'d' + x.id}>
                      {t('track.date')}
                    </label>
                    <input id={'d' + x.id} className="input" type="date" value={x.date ?? ''} onChange={e => patch(x.id, { date: e.target.value || null })} />
                  </div>
                </div>
                {x.kind === 'out' && (
                  <>
                    <label className="f">{t('track.category')}</label>
                    <div className="cat-pick">
                      {CATEGORIES.map(c => (
                        <button key={c} className={x.cat === c ? 'on' : ''} onClick={() => patch(x.id, { cat: c })} aria-pressed={x.cat === c}>
                          <span className="ico">
                            <Icon name={'c-' + c} />
                          </span>
                          {t(`cat.${c}`)}
                        </button>
                      ))}
                    </div>
                    {matches.length > 0 && <label className="f">{t('track.match')}</label>}
                    {matches.map(tx =>
                      row(
                        tx,
                        <button className="btn primary sm" onClick={() => setCategory(tx, x.cat)}>
                          {t('track.use')}
                        </button>,
                      ),
                    )}
                  </>
                )}
              </section>
            );
          })}
          <button className="btn dark" style={{ marginTop: 14 }} onClick={() => void saveCash()} disabled={!chosen.length}>
            <Icon name="i-book" />
            {chosen.length > 1 ? t('track.saveAll', { n: chosen.length }) : t('track.saveCash')}
          </button>
        </>
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
