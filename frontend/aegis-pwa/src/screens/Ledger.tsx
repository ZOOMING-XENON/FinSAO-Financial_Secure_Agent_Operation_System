// Cash ledger: record spending and income the bank can't see (cash, a friend paid).
// Banking Core has no endpoint for manual entries, so these stay on this device only.
import { useEffect, useState } from 'react';
import { uid } from '../core/api';
import { currentMonth, monthKey, shiftMonth, type Month } from '../core/insights';
import { formatDate, monthLabel } from '../core/format';
import { formatMoney, fromCents, toCents } from '../core/money';
import type { Key } from '../core/i18n';
import { useApp } from '../app/state';
import { Icon, Sheet } from '../ui/kit';
import { haptic } from '../ui/celebrate';
import { lastAddedMonth, readLedger, writeLedger, type LedgerEntry, type LedgerKind } from '../core/ledger';

type Kind = LedgerKind;
type Entry = LedgerEntry;

const CATS: Record<Kind, { id: string; icon: string }[]> = {
  out: [
    { id: 'food', icon: 'c-DINING' },
    { id: 'shopping', icon: 'c-GROCERIES' },
    { id: 'transport', icon: 'c-TRANSPORT' },
    { id: 'housing', icon: 'c-HOUSEHOLD' },
    { id: 'fun', icon: 'c-ENTERTAINMENT' },
    { id: 'health', icon: 'p-heart' },
    { id: 'clothes', icon: 'p-shirt' },
    { id: 'study', icon: 'p-cap' },
    { id: 'gifts', icon: 'p-gift' },
    { id: 'other', icon: 'p-dots' },
  ],
  in: [
    { id: 'salary', icon: 'p-briefcase' },
    { id: 'bonus', icon: 'p-star' },
    { id: 'redenv', icon: 'p-envelope' },
    { id: 'parttime', icon: 'i-clock' },
    { id: 'invest', icon: 'i-trend-up' },
    { id: 'other', icon: 'p-dots' },
  ],
};
const iconFor = (kind: Kind, cat: string) => CATS[kind].find(c => c.id === cat)?.icon ?? 'p-dots';

const readEntries = readLedger;
const writeEntries = writeLedger;

/** Evaluates "12.5+30-4" in integer cents. Returns null for an invalid expression. */
export function evalAmount(expr: string): bigint | null {
  if (!expr) return 0n;
  const parts = expr.match(/[+-]?[^+-]+/g);
  if (!parts) return null;
  let total = 0n;
  for (const part of parts) {
    const sign = part.startsWith('-') ? -1n : 1n;
    const num = part.replace(/^[+-]/, '');
    if (!/^\d{1,9}(\.\d{0,2})?$/.test(num)) return null;
    total += sign * toCents(num.endsWith('.') ? num + '0' : num);
  }
  return total;
}

export function Ledger({ startRecording = false }: { startRecording?: boolean }) {
  const { t, locale, toast } = useApp();
  const [entries, setEntries] = useState<Entry[]>(readEntries);
  const [month, setMonth] = useState<Month>(() => {
    if (!lastAddedMonth) return currentMonth();
    const [y, m] = lastAddedMonth.split('-').map(Number);
    return { year: y, month: m };
  });
  const [recording, setRecording] = useState(startRecording);
  const [editing, setEditing] = useState<Entry | null>(null);
  const mine = entries.filter(e => e.at.startsWith(monthKey(month))).sort((a, b) => b.at.localeCompare(a.at));
  const out = mine.filter(e => e.kind === 'out').reduce((s, e) => s + toCents(e.cents), 0n);
  const inc = mine.filter(e => e.kind === 'in').reduce((s, e) => s + toCents(e.cents), 0n);
  const atLatest = monthKey(month) >= monthKey(currentMonth());

  const save = (e: Entry) => {
    const next = [e, ...entries];
    setEntries(next);
    writeEntries(next);
    toast(t('led.saved'));
  };
  const remove = (id: string) => {
    const next = entries.filter(e => e.id !== id);
    setEntries(next);
    writeEntries(next);
    setEditing(null);
  };

  const days = new Map<string, Entry[]>();
  for (const e of mine) {
    const d = e.at.slice(0, 10);
    days.set(d, [...(days.get(d) ?? []), e]);
  }

  return (
    <>
      <div className="ph">
        <a className="icon-btn" href="#/services" aria-label={t('common.back')}>
          <Icon name="i-back" />
        </a>
        <h2>{t('svc.ledger')}</h2>
        <button className="icon-btn brand" onClick={() => setRecording(true)} aria-label={t('led.record')}>
          <Icon name="i-plus" />
        </button>
      </div>
      <div className="cal-head">
        <button className="icon-btn" aria-label={t('trends.prev')} onClick={() => setMonth(shiftMonth(month, -1))}>
          <Icon name="i-left" />
        </button>
        <h2 className="center">{monthLabel(month.year, month.month, locale)}</h2>
        <button className="icon-btn" aria-label={t('trends.next')} disabled={atLatest} style={atLatest ? { opacity: 0.35 } : undefined} onClick={() => setMonth(shiftMonth(month, 1))}>
          <Icon name="i-chev" />
        </button>
      </div>
      <div className="stats" style={{ marginBottom: 12 }}>
        <div className="stat">
          <small>{t('led.expense')}</small>
          <b>{formatMoney(fromCents(out))}</b>
        </div>
        <div className="stat">
          <small>{t('led.income')}</small>
          <b>{formatMoney(fromCents(inc))}</b>
        </div>
      </div>
      <p className="device-note">
        <Icon name="i-phone" />
        {t('led.device')}
      </p>

      {mine.length === 0 && (
        <section className="card center">
          <div className="empty">{t('led.empty')}</div>
          <button className="btn primary" onClick={() => setRecording(true)}>
            <Icon name="i-plus" />
            {t('led.record')}
          </button>
        </section>
      )}
      {[...days.entries()].map(([d, list]) => (
        <section className="card flush" key={d}>
          <div className="card-h">
            <h3>{formatDate(d, locale, { weekday: 'short', month: 'short', day: 'numeric' })}</h3>
          </div>
          {list.map(e => (
            <button className="row" key={e.id} onClick={() => setEditing(e)}>
              <span className="ico">
                <Icon name={iconFor(e.kind, e.cat)} />
              </span>
              <span className="main">
                <span className="t" style={{ display: 'block' }}>
                  {e.note || t(`led.c.${e.cat}` as Key)}
                </span>
                <span className="s" style={{ display: 'block' }}>
                  {t(`led.c.${e.cat}` as Key)} · {new Date(e.at).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}
                </span>
              </span>
              <span className={'v' + (e.kind === 'in' ? ' pos' : '')}>
                {e.kind === 'in' ? '+' : '-'}
                {formatMoney(e.cents)}
              </span>
            </button>
          ))}
        </section>
      ))}

      {recording && <Recorder onClose={() => setRecording(false)} onSave={save} />}
      <Sheet open={!!editing} onClose={() => setEditing(null)} label={t('led.entry')}>
        {editing && (
          <>
            <h3>{editing.note || t(`led.c.${editing.cat}` as Key)}</h3>
            <p className="sub">
              {t(`led.c.${editing.cat}` as Key)} · {formatDate(editing.at, locale, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
            </p>
            <div className="amt big center" style={{ display: 'block', margin: '6px 0 16px' }}>
              {editing.kind === 'in' ? '+' : '-'}
              {formatMoney(editing.cents)}
            </div>
            <button className="btn danger" onClick={() => remove(editing.id)}>
              {t('led.delete')}
            </button>
            <button className="btn" onClick={() => setEditing(null)}>
              {t('common.close')}
            </button>
          </>
        )}
      </Sheet>
    </>
  );
}

function Recorder({ onClose, onSave }: { onClose: () => void; onSave: (e: Entry) => void }) {
  const { t } = useApp();
  const [kind, setKind] = useState<Kind>('out');
  const [cat, setCat] = useState('food');
  const [expr, setExpr] = useState('');
  const [note, setNote] = useState('');
  const [msg, setMsg] = useState('');
  const value = evalAmount(expr);

  // Typing works too: digits, . + - Backspace and Enter, unless the note field has focus.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT' || e.metaKey || e.ctrlKey) return;
      const k = e.key;
      if (/^[0-9]$/.test(k) || k === '.' || k === '+' || k === '-') press(k);
      else if (k === 'Backspace') press('del');
      else if (k === 'Enter') done();
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const press = (k: string) => {
    haptic(6);
    setMsg('');
    if (k === 'del') return setExpr(e => e.slice(0, -1));
    if (k === '+' || k === '-') return setExpr(e => (e === '' || /[+-]$/.test(e) ? e : e + k));
    if (k === '.') return setExpr(e => (/(^|[+-])\d*\.\d*$/.test(e) ? e : e + (/(^|[+-])$/.test(e) ? '0.' : '.')));
    setExpr(e => (/\.\d{2}$/.test(e) ? e : e + k));
  };
  const done = () => {
    if (value === null || value <= 0n) return setMsg(t('pay.invalidAmount'));
    if (/[+-]/.test(expr.slice(1)) && fromCents(value) !== expr) {
      setExpr(fromCents(value).replace(/\.00$/, ''));
      return;
    }
    onSave({ id: uid(), kind, cat, cents: fromCents(value), note: note.trim(), at: new Date().toISOString() });
    onClose();
  };

  return (
    <Sheet open onClose={onClose} label={t('led.record')}>
      <div className="led-tabs">
        <div className="seg" style={{ width: 220 }}>
          {(['out', 'in'] as const).map(k => (
            <button
              key={k}
              className={kind === k ? 'on' : ''}
              onClick={() => {
                setKind(k);
                setCat(CATS[k][0].id);
              }}
            >
              {t(k === 'out' ? 'led.expense' : 'led.income')}
            </button>
          ))}
        </div>
      </div>
      <div className="cat-grid">
        {CATS[kind].map(c => (
          <button key={c.id} className={cat === c.id ? 'on' : ''} onClick={() => setCat(c.id)} aria-pressed={cat === c.id}>
            <span className="i">
              <Icon name={c.icon} />
            </span>
            {t(`led.c.${c.id}` as Key)}
          </button>
        ))}
      </div>
      <div className="led-display">
        <span className={'amt ' + kind}>¥{expr || '0'}</span>
        {value !== null && /[+-]/.test(expr.slice(1)) && <span className="mut small">= {formatMoney(fromCents(value))}</span>}
        <input value={note} onChange={e => setNote(e.target.value)} placeholder={t('led.note')} maxLength={80} aria-label={t('led.note')} />
      </div>
      <p className="err">{msg}</p>
      <div className="keypad">
        {['1', '2', '3', '+', '4', '5', '6', '-', '7', '8', '9', 'del', '.', '0'].map(k => (
          <button key={k} className={k === '+' || k === '-' || k === 'del' ? 'op' : ''} onClick={() => press(k)} aria-label={k === 'del' ? t('led.del') : k}>
            {k === 'del' ? <Icon name="i-backspace" /> : k === '-' ? '−' : k}
          </button>
        ))}
        <button className="done" style={{ gridColumn: 'span 2' }} onClick={done}>
          {/[+-]/.test(expr.slice(1)) ? '=' : t('led.done')}
        </button>
      </div>
    </Sheet>
  );
}
