import { useMemo, useRef, useState } from 'react';
import { api, uid } from '../core/api';
import type { SavingsContribution, SavingsPot } from '../core/types';
import { formatDate } from '../core/format';
import { formatMoney, fromCents, isValidAmount, normalizeAmount, toCents } from '../core/money';
import { potPlan } from '../core/insights';
import { celebrated, markCelebrated, POT_EMOJI, POT_TEMPLATES, POT_THEMES, potLook, savePotLook, themeBg, type PotLook } from '../core/potstyle';
import { go, useApp, useLoad } from '../app/state';
import { Icon, Sheet, Skeleton } from '../ui/kit';
import { useShield } from '../ui/Shield';
import { celebrate } from '../ui/celebrate';
import { askAegis } from './Aegis';
import { loadAccounts } from './Home';
import { Ring } from './Wealth';

const m$ = (c: bigint) => formatMoney(fromCents(c));
const MILESTONES = [25, 50, 75, 100];

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
  const [add, setAdd] = useState<string | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);
  const [lookOpen, setLookOpen] = useState(false);
  const [goal, setGoal] = useState(false);
  const [lookVer, setLookVer] = useState(0);

  if (pot.error) {
    return (
      <div className="empty">
        {errorText(pot.error)}
        <br />
        <a className="link" href="#/wealth">
          {t('common.back')}
        </a>
      </div>
    );
  }
  const p = pot.data;
  const look = p ? potLook(p.id, p.name) : { emoji: '💰', theme: 'violet' as const };
  const plan = p ? potPlan(p) : null;

  const afterSave = (before: number, after: number) => {
    pot.reload();
    history.reload();
    if (!p) return;
    const done = celebrated(p.id);
    const crossed = MILESTONES.filter(ms => before < ms && after >= ms && !done.includes(ms));
    crossed.forEach(ms => markCelebrated(p.id, ms));
    if (crossed.includes(100)) {
      celebrate(true);
      setGoal(true);
    } else if (crossed.length) {
      celebrate(false);
      toast(t('pot.milestone', { pct: crossed[crossed.length - 1] }));
    }
  };

  const remove = async () => {
    try {
      await api.del(`/savings-pots/${id}`);
      toast(t('pot.deleted'));
      refresh();
      go('wealth');
    } catch (e) {
      toast(errorText(e));
    }
  };

  return (
    <>
      <section className="pot-hero2" style={{ background: themeBg(look.theme) }} key={lookVer}>
        <a className="icon-btn back glass" href="#/wealth" aria-label={t('common.back')}>
          <Icon name="i-back" />
        </a>
        <button className="icon-btn edit glass" onClick={() => setLookOpen(true)} aria-label={t('pot.customize')}>
          <Icon name="i-spark" />
        </button>
        <Ring pct={plan?.pct ?? 0} size={150} stroke={10}>
          <span className="hero-emoji">{look.emoji}</span>
        </Ring>
        <div className="n">{p?.name ?? '…'}</div>
        <div className="amt big">{p ? m$(toCents(p.saved_amount)) : '…'}</div>
        {p && <div className="of">{t('pot.ofTarget', { pct: plan!.pct, amount: m$(toCents(p.target_amount)) })}</div>}
      </section>

      <div className="pad pot-body">
        <div className="milestones" aria-label={t('pot.milestones')}>
          {MILESTONES.map(ms => (
            <div key={ms} className={'ms' + ((plan?.pct ?? 0) >= ms ? ' hit' : '')}>
              <span>{(plan?.pct ?? 0) >= ms ? <Icon name="i-check" /> : ms === 100 ? '🏁' : ''}</span>
              <small>{ms}%</small>
            </div>
          ))}
        </div>

        {p && plan && (
          <>
            <div className="quick-add">
              {['50', '100', '500'].map(v => (
                <button key={v} onClick={() => setAdd(v)}>
                  +¥{v}
                </button>
              ))}
              <button className="primary" onClick={() => setAdd('')}>
                <Icon name="i-plus" />
                {t('pot.add')}
              </button>
            </div>

            <section className={'card plan ' + (plan.reached ? 'done' : plan.gap >= 0n ? 'ahead' : 'behind')}>
              <div className="plan-head">
                <span className="plan-ico">
                  <Icon name={plan.reached ? 'i-check' : plan.gap >= 0n ? 'i-trend-up' : 'i-clock'} />
                </span>
                <div>
                  <b>{plan.reached ? t('pot.reached') : plan.gap >= 0n ? t('pot.ahead', { amount: m$(plan.gap) }) : t('pot.behind', { amount: m$(-plan.gap) })}</b>
                  <span className="mut small">
                    {plan.reached ? t('pot.reachedHint') : t('pot.by', { date: formatDate(p.target_date, locale, { year: 'numeric', month: 'short', day: 'numeric' }), n: plan.daysLeft })}
                  </span>
                </div>
              </div>
              {!plan.reached && (
                <div className="kpis">
                  <div className="kpi">
                    <small>{t('pot.toGo')}</small>
                    <b>{m$(plan.remaining)}</b>
                  </div>
                  <div className="kpi">
                    <small>{t('pot.perMonth')}</small>
                    <b>{m$(plan.perMonth)}</b>
                  </div>
                  <div className="kpi">
                    <small>{t('pot.perWeek')}</small>
                    <b>{m$(plan.perWeek)}</b>
                  </div>
                </div>
              )}
            </section>
          </>
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
                  {c.note || t('pot.deposit')}
                </span>
                <span className="s" style={{ display: 'block' }}>
                  {formatDate(c.created_at, locale, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </span>
              </span>
              <span className="v pos">+{m$(toCents(c.amount))}</span>
            </div>
          ))}
        </section>

        {p && plan && !plan.reached && <Calculator pot={p} months={Math.max(1, Math.ceil(plan.daysLeft / 30.4))} />}

        <div className="pot-actions">
          <button className="btn" onClick={() => p && askAegis(t('pot.askPrompt', { name: p.name }))}>
            <Icon name="i-spark" />
            {t('pot.askAegis')}
          </button>
          <button className="btn ghost" onClick={() => setMoreOpen(true)}>
            {t('pot.more')}
          </button>
        </div>
        <p className="mut small">{t('pot.virtual')}</p>
      </div>

      {p && add !== null && <AddToPot pot={p} initial={add} onClose={() => setAdd(null)} onSaved={afterSave} />}
      {p && lookOpen && (
        <LookSheet
          initial={look}
          onClose={() => setLookOpen(false)}
          onSave={l => {
            savePotLook(p.id, l);
            setLookVer(v => v + 1);
            setLookOpen(false);
          }}
        />
      )}
      <Sheet open={moreOpen} onClose={() => setMoreOpen(false)} label={t('pot.more')}>
        <h3>{p?.name}</h3>
        <p className="sub">{t('pot.deleteHint')}</p>
        <button className="btn danger" onClick={remove}>
          {t('pot.delete')}
        </button>
        <button className="btn" onClick={() => setMoreOpen(false)}>
          {t('common.cancel')}
        </button>
      </Sheet>
      <Sheet open={goal} onClose={() => setGoal(false)} label={t('pot.goalTitle')}>
        <div className="center goal-done">
          <span className="goal-emoji">{look.emoji}</span>
          <h3>{t('pot.goalTitle')}</h3>
          <p className="sub">{t('pot.goalBody', { name: p?.name ?? '', amount: p ? m$(toCents(p.target_amount)) : '' })}</p>
          <button className="btn primary" onClick={() => (setGoal(false), celebrate(true))}>
            🎉 {t('pot.goalAgain')}
          </button>
          <button className="btn" onClick={() => setGoal(false)}>
            {t('pay.done')}
          </button>
        </div>
      </Sheet>
    </>
  );
}

function Calculator({ pot, months }: { pot: SavingsPot; months: number }) {
  const { t } = useApp();
  const remaining = toCents(pot.target_amount) - toCents(pot.saved_amount);
  const [monthly, setMonthly] = useState(() => fromCents(remaining > 0n ? (remaining + BigInt(months) - 1n) / BigInt(months) : 0n).replace(/\.00$/, ''));
  const [rate, setRate] = useState('2');
  const result = useMemo(() => {
    if (!isValidAmount(monthly) && monthly !== '0') return null;
    const bp = /^\d{1,2}(\.\d{1,2})?$/.test(rate) ? toCents(rate) : 0n;
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
      {result && <p style={{ margin: '14px 2px 4px', fontWeight: 700 }}>{t('pot.calcResult', { n: months, amount: formatMoney(result) })}</p>}
      <p className="mut small" style={{ margin: '4px 2px 0' }}>
        {t('pot.calcNote')}
      </p>
    </section>
  );
}

function AddToPot({ pot, initial, onClose, onSaved }: { pot: SavingsPot; initial: string; onClose: () => void; onSaved: (beforePct: number, afterPct: number) => void }) {
  const { t, errorText, refresh } = useApp();
  const authorize = useShield();
  const accounts = useLoad(loadAccounts);
  const [amount, setAmount] = useState(initial);
  const [note, setNote] = useState('');
  const [sourceId, setSourceId] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const intent = useRef<{ sig: string; key: string } | null>(null);
  const save = async () => {
    if (!isValidAmount(amount)) return setMsg(t('pay.invalidAmount'));
    const value = normalizeAmount(amount);
    const source = accounts.data?.find(account => account.id === sourceId) ?? accounts.data?.[0];
    if (!source) return setMsg(t('err.VALIDATION_ERROR'));
    if (toCents(value) > toCents(source.balance)) return setMsg(t('pay.insufficient'));
    const sig = source.id + '|' + value + '|' + note;
    if (intent.current?.sig !== sig) intent.current = { sig, key: 'pot-contribution-' + uid() };
    setBusy(true);
    // Funded pots: Banking Core moves the money, so the shield approves it first.
    const ref = await authorize({
      operationType: 'savings.contribute',
      operationId: pot.id,
      targetAccountId: source.id,
      amount: value,
      rows: [
        [t('shield.action'), t('pot.addTitle', { name: pot.name })],
        [t('shield.amount'), formatMoney(value, pot.currency)],
        [t('shield.from'), `${source.name} · •••• ${source.account_number.slice(-4)}`],
      ],
    });
    if (!ref) {
      setBusy(false);
      return setMsg(t('pay.cancelled'));
    }
    try {
      await api.post(`/savings-pots/${pot.id}/contributions`, {
        source_account_id: source.id,
        amount: value,
        note: note.trim() || null,
        idempotency_key: intent.current.key,
        authorization_ref: ref,
      });
      intent.current = null;
      const target = toCents(pot.target_amount);
      const before = toCents(pot.saved_amount);
      const pct = (c: bigint) => (target > 0n ? Number((c * 100n) / target) : 0);
      refresh();
      onSaved(pct(before), pct(before + toCents(value)));
      onClose();
    } catch (e) {
      setMsg(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const remaining = toCents(pot.target_amount) - toCents(pot.saved_amount);
  return (
    <Sheet open onClose={onClose} label={t('pot.addTitle', { name: pot.name })}>
      <h3>{t('pot.addTitle', { name: pot.name })}</h3>
      <p className="sub">{t('pot.virtual')}</p>
      <label className="f" htmlFor="ps">
        {t('shield.from')}
      </label>
      <select id="ps" className="input" value={sourceId || accounts.data?.[0]?.id || ''} onChange={e => setSourceId(e.target.value)}>
        {(accounts.data ?? []).map(account => (
          <option key={account.id} value={account.id}>
            {account.name} · {formatMoney(account.balance, account.currency)}
          </option>
        ))}
      </select>
      <label className="f" htmlFor="pa">
        {t('pot.amount')}
      </label>
      <input id="pa" className="input" inputMode="decimal" placeholder="100" value={amount} onChange={e => setAmount(e.target.value)} autoFocus />
      {remaining > 0n && (
        <button className="chip-cat" style={{ marginTop: 8 }} onClick={() => setAmount(fromCents(remaining))}>
          {t('pot.fillUp', { amount: m$(remaining) })}
        </button>
      )}
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

function LookSheet({ initial, onClose, onSave }: { initial: PotLook; onClose: () => void; onSave: (l: PotLook) => void }) {
  const { t } = useApp();
  const [look, setLook] = useState(initial);
  return (
    <Sheet open onClose={onClose} label={t('pot.customize')}>
      <h3>{t('pot.customize')}</h3>
      <div className="look-preview" style={{ background: themeBg(look.theme) }}>
        {look.emoji}
      </div>
      <label className="f">{t('pot.icon')}</label>
      <div className="emoji-pick">
        {POT_EMOJI.map(e => (
          <button key={e} className={look.emoji === e ? 'on' : ''} onClick={() => setLook({ ...look, emoji: e })}>
            {e}
          </button>
        ))}
      </div>
      <label className="f">{t('pot.color')}</label>
      <div className="theme-pick">
        {POT_THEMES.map(th => (
          <button key={th.id} className={look.theme === th.id ? 'on' : ''} style={{ background: th.bg }} onClick={() => setLook({ ...look, theme: th.id })} aria-label={th.id} />
        ))}
      </div>
      <button className="btn primary" style={{ marginTop: 16 }} onClick={() => onSave(look)}>
        {t('pot.saveLook')}
      </button>
    </Sheet>
  );
}

export function NewPot() {
  const { t, errorText, refresh } = useApp();
  const [tpl, setTpl] = useState<(typeof POT_TEMPLATES)[number] | null>(null);
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');
  const [look, setLook] = useState<PotLook>({ emoji: '💰', theme: 'violet' });
  const [date, setDate] = useState(() => {
    const d = new Date();
    d.setMonth(d.getMonth() + 6);
    return d.toISOString().slice(0, 10);
  });
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const key = useRef('pot-' + uid());
  const months = Math.max(1, Math.round((Date.parse(date) - Date.now()) / (30.4 * 86_400_000)));
  const perMonth = isValidAmount(target) ? m$((toCents(target) + BigInt(months) - 1n) / BigInt(months)) : null;

  const pick = (x: (typeof POT_TEMPLATES)[number]) => {
    setTpl(x);
    setName(t(`pot.tpl.${x.key}` as 'pot.tpl.travel'));
    setTarget(x.target);
    setLook({ emoji: x.emoji, theme: x.theme });
  };

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
      savePotLook(pot.id, look);
      refresh();
      celebrate(false);
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
        <a className="icon-btn" href="#/wealth" aria-label={t('common.back')}>
          <Icon name="i-back" />
        </a>
        <h2>{t('pot.newTitle')}</h2>
        <span style={{ width: 40 }} />
      </div>
      <div className="look-preview big" style={{ background: themeBg(look.theme) }}>
        <span>{look.emoji}</span>
        <b>{name || t('pot.name')}</b>
        <small>{target ? m$(toCents(isValidAmount(target) ? target : '0')) : '¥0'}</small>
      </div>
      <label className="f">{t('pot.pickTemplate')}</label>
      <div className="tpl-grid">
        {POT_TEMPLATES.map(x => (
          <button key={x.key} className={tpl?.key === x.key ? 'on' : ''} onClick={() => pick(x)}>
            <span>{x.emoji}</span>
            {t(`pot.tpl.${x.key}` as 'pot.tpl.travel')}
          </button>
        ))}
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
      {perMonth && <p className="plan-preview">{t('pot.planPreview', { amount: perMonth, n: months })}</p>}
      <label className="f">{t('pot.color')}</label>
      <div className="theme-pick">
        {POT_THEMES.map(th => (
          <button key={th.id} className={look.theme === th.id ? 'on' : ''} style={{ background: th.bg }} onClick={() => setLook({ ...look, theme: th.id })} aria-label={th.id} />
        ))}
      </div>
      <p className="err">{msg}</p>
      <button className="btn primary" onClick={create} disabled={busy}>
        {t('pot.create')}
      </button>
    </>
  );
}
