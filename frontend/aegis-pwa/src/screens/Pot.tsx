import { useMemo, useRef, useState } from 'react';
import { api, uid } from '../core/api';
import type { SavingsContribution, SavingsPot } from '../core/types';
import { daysUntil, formatDate, monthsUntil } from '../core/format';
import { formatMoney, fromCents, isValidAmount, normalizeAmount, percent, toCents } from '../core/money';
import { go, useApp, useLoad } from '../app/state';
import { Amount, Icon, potArt, Sheet, Skeleton } from '../ui/kit';
import { askAegis } from './Aegis';

const ceilDiv = (a: bigint, b: bigint) => (b <= 0n ? a : (a + b - 1n) / b);

/** Month-by-month compounding in integer cents; rate is in basis points per year. */
export function projectSavings(startCents: bigint, monthlyCents: bigint, rateBp: bigint, months: number): bigint {
  let balance = startCents;
  for (let i = 0; i < months; i++) {
    balance += monthlyCents;
    balance += (balance * rateBp) / 120000n;
  }
  return balance;
}

export function PotDetail({ id }: { id: string }) {
  const { t, locale, toast, errorText, refresh } = useApp();
  const pot = useLoad(() => api.get<SavingsPot>(`/savings-pots/${id}`), [id]);
  const history = useLoad(() => api.get<SavingsContribution[]>(`/savings-pots/${id}/contributions`), [id]);
  const [addOpen, setAddOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  if (pot.error) {
    return (
      <div className="empty">
        {errorText(pot.error)}
        <br />
        <a className="link" href="#/home">
          {t('common.back')}
        </a>
      </div>
    );
  }
  const p = pot.data;
  const remaining = p ? toCents(p.target_amount) - toCents(p.saved_amount) : 0n;
  const months = p ? monthsUntil(p.target_date) : 1;
  const days = p ? Math.max(0, daysUntil(p.target_date)) : 0;
  const weeks = BigInt(Math.max(1, Math.ceil(days / 7)));

  const remove = async () => {
    try {
      await api.del(`/savings-pots/${id}`);
      toast(t('pot.deleted'));
      refresh();
      go('home');
    } catch (e) {
      toast(errorText(e));
    }
  };

  return (
    <>
      <section className="pot-hero">
        <span className="art" style={{ background: potArt(id) }} />
        <a className="icon-btn back glass" href="#/home" aria-label={t('common.back')}>
          <Icon name="i-back" />
        </a>
        <div className="n">{p?.name ?? '…'}</div>
        {p && <Amount value={p.saved_amount} currency={p.currency} />}
        <span className="chip glass badge">{t('pot.saved')}</span>
      </section>
      <div style={{ padding: '0 16px' }}>
        <div className="round-actions">
          <button onClick={() => setAddOpen(true)}>
            <span className="r brand">
              <Icon name="i-plus" />
            </span>
            {t('pot.add')}
          </button>
          <button onClick={() => p && askAegis(t('pot.askPrompt', { name: p.name }))}>
            <span className="r">
              <Icon name="i-spark" />
            </span>
            {t('pot.ask')}
          </button>
          <button onClick={() => setMoreOpen(true)}>
            <span className="r">
              <Icon name="i-more" />
            </span>
            {t('pot.more')}
          </button>
        </div>

        {p && (
          <section className="card">
            <div className="goal-top">
              <b>{t('pot.goal', { amount: formatMoney(p.target_amount) })}</b>
              <span className="mut small">{remaining > 0n ? t('pot.toSave', { amount: formatMoney(fromCents(remaining)) }) : t('pot.reached')}</span>
            </div>
            <div className="bar">
              <i style={{ width: percent(p.saved_amount, p.target_amount) + '%' }} />
            </div>
            <div className="mut small" style={{ marginTop: 8 }}>
              {t('pot.by', { date: formatDate(p.target_date, locale, { year: 'numeric', month: 'short', day: 'numeric' }), n: days })}
            </div>
            {remaining > 0n && (
              <div className="kpis">
                <div className="kpi">
                  <small>{t('pot.perMonth')}</small>
                  <b>{formatMoney(fromCents(ceilDiv(remaining, BigInt(months))))}</b>
                </div>
                <div className="kpi">
                  <small>{t('pot.perWeek')}</small>
                  <b>{formatMoney(fromCents(ceilDiv(remaining, weeks)))}</b>
                </div>
                <div className="kpi">
                  <small>{t('pot.monthsLeft')}</small>
                  <b>{months}</b>
                </div>
              </div>
            )}
          </section>
        )}

        <section className="card flush">
          <div className="card-h">
            <h3>{t('pot.history')}</h3>
          </div>
          {history.loading && !history.data && <Skeleton rows={2} />}
          {history.data?.length === 0 && <div className="empty">{t('pot.noHistory')}</div>}
          {history.data?.map(c => (
            <div className="row" key={c.id}>
              <span className="ico brand">
                <Icon name="i-down" />
              </span>
              <span className="main">
                <span className="t" style={{ display: 'block' }}>
                  {c.note || p?.name}
                </span>
                <span className="s" style={{ display: 'block' }}>
                  {formatDate(c.created_at, locale, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </span>
              </span>
              <span className="v pos">
                <Amount value={c.amount} sign="+" />
              </span>
            </div>
          ))}
        </section>

        {p && <Calculator pot={p} months={months} />}
        <p className="mut small" style={{ padding: '0 4px' }}>
          {t('pot.virtual')}
        </p>
      </div>

      {p && (
        <AddToPot
          pot={p}
          open={addOpen}
          onClose={() => setAddOpen(false)}
          onSaved={() => {
            setAddOpen(false);
            pot.reload();
            history.reload();
          }}
        />
      )}
      <Sheet open={moreOpen} onClose={() => setMoreOpen(false)} label={t('pot.more')}>
        <h3>{p?.name}</h3>
        <button className="btn danger" onClick={remove} style={{ marginTop: 14 }}>
          {t('pot.delete')}
        </button>
        <button className="btn" onClick={() => setMoreOpen(false)}>
          {t('common.cancel')}
        </button>
      </Sheet>
    </>
  );
}

function Calculator({ pot, months }: { pot: SavingsPot; months: number }) {
  const { t } = useApp();
  const remaining = toCents(pot.target_amount) - toCents(pot.saved_amount);
  const [monthly, setMonthly] = useState(() => fromCents(ceilDiv(remaining > 0n ? remaining : 0n, BigInt(months))).replace(/\.00$/, ''));
  const [rate, setRate] = useState('2');
  const result = useMemo(() => {
    if (!isValidAmount(monthly) && monthly !== '0') return null;
    const bp = /^\d{1,2}(\.\d{1,2})?$/.test(rate) ? toCents(rate) : 0n; // "2.5" → 250 bp
    return fromCents(projectSavings(toCents(pot.saved_amount), toCents(monthly), bp, months));
  }, [monthly, rate, months, pot.saved_amount]);
  return (
    <section className="card">
      <div className="card-h">
        <h3>{t('pot.calcTitle')}</h3>
      </div>
      <div className="btn-row">
        <div style={{ flex: 1 }}>
          <label className="f" htmlFor="c-m">
            {t('pot.calcMonthly')}
          </label>
          <input id="c-m" className="input" inputMode="decimal" value={monthly} onChange={e => setMonthly(e.target.value)} />
        </div>
        <div style={{ width: 120 }}>
          <label className="f" htmlFor="c-r">
            {t('pot.calcRate')}
          </label>
          <input id="c-r" className="input" inputMode="decimal" value={rate} onChange={e => setRate(e.target.value)} />
        </div>
      </div>
      {result && (
        <p style={{ margin: '14px 2px 4px', fontWeight: 600 }}>
          {t('pot.calcResult', { n: months, amount: formatMoney(result) })}
        </p>
      )}
      <p className="mut small" style={{ margin: '4px 2px 0' }}>
        {t('pot.calcNote')}
      </p>
    </section>
  );
}

function AddToPot({ pot, open, onClose, onSaved }: { pot: SavingsPot; open: boolean; onClose: () => void; onSaved: () => void }) {
  const { t, errorText, refresh } = useApp();
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const intent = useRef<{ sig: string; key: string } | null>(null);
  const save = async () => {
    if (!isValidAmount(amount)) return setMsg(t('pay.invalidAmount'));
    const value = normalizeAmount(amount);
    const sig = value + '|' + note;
    if (intent.current?.sig !== sig) intent.current = { sig, key: 'pot-contribution-' + uid() };
    setBusy(true);
    try {
      await api.post(`/savings-pots/${pot.id}/contributions`, { amount: value, note: note.trim() || null, idempotency_key: intent.current.key });
      intent.current = null;
      setAmount('');
      setNote('');
      setMsg('');
      refresh();
      onSaved();
    } catch (e) {
      setMsg(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet open={open} onClose={onClose} label={t('pot.addTitle', { name: pot.name })}>
      <h3>{t('pot.addTitle', { name: pot.name })}</h3>
      <label className="f" htmlFor="pa">
        {t('pot.amount')}
      </label>
      <input id="pa" className="input" inputMode="decimal" placeholder="100" value={amount} onChange={e => setAmount(e.target.value)} />
      <label className="f" htmlFor="pn">
        {t('pot.note')}
      </label>
      <input id="pn" className="input" maxLength={255} value={note} onChange={e => setNote(e.target.value)} />
      <p className="err">{msg}</p>
      <button className="btn primary" onClick={save} disabled={busy}>
        {t('pot.add')}
      </button>
    </Sheet>
  );
}

export function NewPot() {
  const { t, errorText, refresh } = useApp();
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');
  const [date, setDate] = useState(() => {
    const d = new Date();
    d.setMonth(d.getMonth() + 6);
    return d.toISOString().slice(0, 10);
  });
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const key = useRef('pot-' + uid());
  const create = async () => {
    if (!name.trim()) return setMsg(t('err.VALIDATION_ERROR'));
    if (!isValidAmount(target)) return setMsg(t('pay.invalidAmount'));
    setBusy(true);
    try {
      const pot = await api.post<SavingsPot>('/savings-pots', {
        name: name.trim(),
        target_amount: normalizeAmount(target),
        currency: 'CNY',
        target_date: date,
        idempotency_key: key.current,
      });
      refresh();
      go('pot/' + pot.id);
    } catch (e) {
      setMsg(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="ph">
        <a className="icon-btn" href="#/home" aria-label={t('common.back')}>
          <Icon name="i-back" />
        </a>
        <h2>{t('pot.newTitle')}</h2>
        <span style={{ width: 40 }} />
      </div>
      <div className="pot" style={{ width: '100%', height: 160, marginBottom: 8, flex: 'none' }}>
        <span className="art" style={{ background: potArt(name || 'new') }} />
        <span className="n">{name || t('pot.name')}</span>
        <span className="amt">¥{target || '0'}</span>
      </div>
      <label className="f" htmlFor="np-n">
        {t('pot.name')}
      </label>
      <input id="np-n" className="input" maxLength={120} value={name} onChange={e => setName(e.target.value)} />
      <label className="f" htmlFor="np-t">
        {t('pot.target')}
      </label>
      <input id="np-t" className="input" inputMode="decimal" value={target} onChange={e => setTarget(e.target.value)} />
      <label className="f" htmlFor="np-d">
        {t('pot.date')}
      </label>
      <input id="np-d" className="input" type="date" value={date} min={new Date().toISOString().slice(0, 10)} onChange={e => setDate(e.target.value)} />
      <p className="err">{msg}</p>
      <button className="btn primary" onClick={create} disabled={busy}>
        {t('pot.create')}
      </button>
    </>
  );
}
