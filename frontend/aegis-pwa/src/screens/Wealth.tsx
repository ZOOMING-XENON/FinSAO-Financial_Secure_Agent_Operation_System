import { useRef, useState } from 'react';
import { api, uid } from '../core/api';
import type { RiskTier, SavingsPot } from '../core/types';
import { potPlan } from '../core/insights';
import { potLook, themeBg } from '../core/potstyle';
import { formatMoney, fromCents, isValidAmount, normalizeAmount, toCents } from '../core/money';
import { useApp, useLoad } from '../app/state';
import { useShield } from '../ui/Shield';
import { Badge, Icon, Sheet, Skeleton } from '../ui/kit';
import { celebrate } from '../ui/celebrate';
import { loadAccounts, type AccountWithBalance } from './Home';

const m$ = (c: bigint) => formatMoney(fromCents(c));

interface Product {
  id: string;
  code: string;
  name: string;
  product_type: string;
  risk_tier: RiskTier;
  minimum_amount: string;
  currency: string;
  supports_redemption: boolean;
}
interface Holding {
  id: string;
  product_id: string;
  amount: string;
}
interface Order {
  id: string;
  amount: string;
  status: string;
}

const TIER_RANK: Record<RiskTier, number> = { GREEN: 1, YELLOW: 2, RED: 3 };
const ALLOC = ['var(--brand)', 'var(--brand-2)', 'var(--brand-3)', 'var(--brand-5)', 'var(--brand-4)'];

async function loadWealth() {
  const [accounts, pots, products, holdings, recs] = await Promise.all([
    loadAccounts(),
    api.get<SavingsPot[]>('/savings-pots'),
    api.get<Product[]>('/wealth/products'),
    api.get<Holding[]>('/wealth/holdings'),
    api.get<Product[]>('/wealth/recommendations'),
  ]);
  return { accounts, pots, products, holdings, recs };
}

/** Progress ring used on pot cards and the pot hero. */
export function Ring({ pct, size = 64, stroke = 6, children }: { pct: number; size?: number; stroke?: number; children?: React.ReactNode }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <span className="ring" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} style={{ width: size, height: size }} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} className="ring-track" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} className="ring-fill" strokeWidth={stroke} strokeDasharray={`${(Math.min(100, pct) / 100) * c} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </svg>
      <span className="ring-in">{children}</span>
    </span>
  );
}

export function PotCard({ pot }: { pot: SavingsPot }) {
  const { t } = useApp();
  const look = potLook(pot.id, pot.name);
  const plan = potPlan(pot);
  const status = plan.reached ? 'done' : plan.gap >= 0n ? 'ahead' : 'behind';
  return (
    <a className="potc" href={`#/pot/${pot.id}`} style={{ background: themeBg(look.theme) }}>
      <div className="potc-top">
        <Ring pct={plan.pct} size={58} stroke={5}>
          <span className="potc-emoji">{look.emoji}</span>
        </Ring>
        <span className={'potc-status ' + status}>{t(`pot.st.${status}` as 'pot.st.done')}</span>
      </div>
      <b className="potc-name">{pot.name}</b>
      <span className="potc-amt">{m$(toCents(pot.saved_amount))}</span>
      <span className="potc-sub">
        {plan.pct}% · {t('pot.of', { amount: m$(toCents(pot.target_amount)) })}
      </span>
    </a>
  );
}

export function Wealth() {
  const { t } = useApp();
  const w = useLoad(loadWealth);
  const [quiz, setQuiz] = useState(false);
  const [trade, setTrade] = useState<{ product: Product; mode: 'buy' | 'sell' } | null>(null);

  if (!w.data) {
    return (
      <>
        <div className="ph">
          <h1>{t('wealth.title')}</h1>
        </div>
        <Skeleton rows={6} />
      </>
    );
  }
  const { accounts, pots, products, holdings, recs } = w.data;
  const cash = accounts.reduce((s, a) => s + toCents(a.balance), 0n);
  const potsTotal = pots.reduce((s, p) => s + toCents(p.saved_amount), 0n);
  const invested = holdings.reduce((s, h) => s + toCents(h.amount), 0n);
  const worth = cash + potsTotal + invested;
  const share = (c: bigint) => (worth > 0n ? Number((c * 1000n) / worth) / 10 : 0);
  const profile: RiskTier | null = recs.length ? recs.reduce<RiskTier>((m, p) => (TIER_RANK[p.risk_tier] > TIER_RANK[m] ? p.risk_tier : m), 'GREEN') : null;
  const byId = new Map(products.map(p => [p.id, p]));

  return (
    <>
      <div className="ph">
        <h1>{t('wealth.title')}</h1>
      </div>

      <section className="card worth">
        <span className="hero-t">{t('wealth.netWorth')}</span>
        <span className="amt big">{m$(worth)}</span>
        <div className="worth-bar" aria-hidden="true">
          <i className="w-cash" style={{ width: share(cash) + '%' }} />
          <i className="w-pots" style={{ width: share(potsTotal) + '%' }} />
          <i className="w-inv" style={{ width: share(invested) + '%' }} />
        </div>
        <div className="worth-legend">
          <span><i className="sw w-cash" />{t('wealth.cash')} <b>{m$(cash)}</b></span>
          <span><i className="sw w-pots" />{t('wealth.pots')} <b>{m$(potsTotal)}</b></span>
          <span><i className="sw w-inv" />{t('wealth.invested')} <b>{m$(invested)}</b></span>
        </div>
      </section>

      <div className="sec-h">
        <h2>{t('wealth.pots')}</h2>
        <a className="link" href="#/pot/new">+ {t('home.newPot')}</a>
      </div>
      <div className="pot-grid">
        {pots.map(p => (
          <PotCard pot={p} key={p.id} />
        ))}
        <a className="potc new" href="#/pot/new">
          <span className="potc-plus">
            <Icon name="i-plus" />
          </span>
          <b>{t('pot.newTitle')}</b>
          <span className="mut small">{t('pot.newHint')}</span>
        </a>
      </div>

      <div className="sec-h">
        <h2>{t('inv.title')}</h2>
      </div>
      <section className="inv-hero">
        <div className="inv-hero-top">
          <span className="hero-t">{t('inv.invested')}</span>
          {profile && (
            <button className="inv-profile" onClick={() => setQuiz(true)} aria-label={t('inv.retake')}>
              <span className={'tier-dot ' + profile} />
              {t(`inv.profile.${profile}` as 'inv.profile.GREEN')}
            </button>
          )}
        </div>
        <span className="amt big">{m$(invested)}</span>
        <span className="inv-sub">{holdings.length ? t('inv.holdingsN', { n: holdings.length }) : t('inv.noHoldings')}</span>
        {holdings.length > 0 && (
          <div className="alloc" aria-hidden="true">
            {holdings.map((h, i) => (
              <i key={h.id} style={{ width: (invested > 0n ? Number((toCents(h.amount) * 1000n) / invested) / 10 : 0) + '%', background: ALLOC[i % ALLOC.length] }} />
            ))}
          </div>
        )}
        {!profile && (
          <button className="btn inv-unlock" onClick={() => setQuiz(true)}>
            <Icon name="i-spark" />
            {t('inv.quizTitle')}
          </button>
        )}
      </section>

      {holdings.length > 0 && (
        <section className="card flush">
          <div className="card-h">
            <h3>{t('inv.portfolio')}</h3>
          </div>
          {holdings.map((h, i) => {
            const p = byId.get(h.product_id);
            const pct = invested > 0n ? Number((toCents(h.amount) * 100n) / invested) : 0;
            return (
              <div className="row" key={h.id}>
                <i className="sw big" style={{ background: ALLOC[i % ALLOC.length] }} />
                <span className="main">
                  <span className="t" style={{ display: 'block' }}>
                    {p?.name ?? h.product_id}
                  </span>
                  <span className="s" style={{ display: 'block' }}>
                    {pct}% · {p ? t(`pt.${p.product_type}` as 'pt.BOND_FUND') : ''}
                  </span>
                </span>
                <span className="v">
                  {m$(toCents(h.amount))}
                  {p?.supports_redemption && (
                    <button className="link block" onClick={() => setTrade({ product: p, mode: 'sell' })}>
                      {t('inv.sell')}
                    </button>
                  )}
                </span>
              </div>
            );
          })}
        </section>
      )}

      <div className="sec-h">
        <h2 className="h3">{t('inv.products')}</h2>
      </div>
      <div className="prod-list">
        {products.map(p => {
          const rank = TIER_RANK[p.risk_tier];
          const ok = !!profile && TIER_RANK[profile] >= rank;
          return (
            <article className={'prod ' + p.risk_tier} key={p.id}>
              <div className="prod-top">
                <span className="prod-ico">
                  <Icon name="i-chart" />
                </span>
                <span className="main">
                  <b>{p.name}</b>
                  <small>{t(`pt.${p.product_type}` as 'pt.BOND_FUND')}</small>
                </span>
              </div>
              <div className="risk-meter" aria-label={t(`inv.risk.${p.risk_tier}` as 'inv.risk.GREEN')}>
                {[1, 2, 3].map(i => (
                  <i key={i} className={i <= rank ? 'on' : ''} />
                ))}
                <span>{t(`inv.risk.${p.risk_tier}` as 'inv.risk.GREEN')}</span>
              </div>
              <div className="prod-foot">
                <span className="mut small">{t('inv.min', { amount: formatMoney(p.minimum_amount) })}</span>
                {!profile ? (
                  <button className="btn sm unlock" onClick={() => setQuiz(true)}>
                    <Icon name="i-lock" />
                    {t('inv.unlock')}
                  </button>
                ) : ok ? (
                  <button className="btn primary sm" onClick={() => setTrade({ product: p, mode: 'buy' })}>
                    {t('inv.buy')}
                  </button>
                ) : (
                  <span className="locked">
                    <Icon name="i-lock" />
                    {t('inv.unsuitable')}
                  </span>
                )}
              </div>
            </article>
          );
        })}
      </div>
      <p className="mut small" style={{ margin: '4px 4px 16px' }}>
        {t('inv.disclaimer')}
      </p>

      <RiskQuiz open={quiz} onClose={() => setQuiz(false)} onDone={() => w.reload()} />
      {trade && <TradeSheet trade={trade} accounts={accounts} holding={holdings.find(h => h.product_id === trade.product.id)} onClose={() => setTrade(null)} onDone={() => w.reload()} />}
    </>
  );
}

const QUIZ = ['q1', 'q2', 'q3', 'q4', 'q5'] as const;

function RiskQuiz({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const { t, errorText } = useApp();
  const [answers, setAnswers] = useState<number[]>([0, 0, 0, 0, 0]);
  const [result, setResult] = useState<{ score: number; risk_tier: RiskTier } | null>(null);
  const [msg, setMsg] = useState('');
  const submit = async () => {
    if (answers.some(a => a < 1)) return setMsg(t('inv.answerAll'));
    try {
      const r = await api.post<{ score: number; risk_tier: RiskTier }>('/wealth/risk-assessment', { answers });
      setResult(r);
      celebrate(false);
      onDone();
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  const close = () => {
    setResult(null);
    setAnswers([0, 0, 0, 0, 0]);
    setMsg('');
    onClose();
  };
  return (
    <Sheet open={open} onClose={close} label={t('inv.quizTitle')}>
      {result ? (
        <div className="center">
          <span className={'tier-dot big ' + result.risk_tier} />
          <h3>{t(`inv.profile.${result.risk_tier}` as 'inv.profile.GREEN')}</h3>
          <p className="sub">{t(`inv.profileD.${result.risk_tier}` as 'inv.profileD.GREEN')}</p>
          <button className="btn primary" onClick={close}>
            {t('pay.done')}
          </button>
        </div>
      ) : (
        <>
          <h3>{t('inv.quizTitle')}</h3>
          <p className="sub">{t('inv.quizHint')}</p>
          {QUIZ.map((q, i) => (
            <fieldset className="quiz-q" key={q}>
              <legend>
                {i + 1}. {t(`inv.${q}` as 'inv.q1')}
              </legend>
              <div className="scale">
                {[1, 2, 3, 4, 5].map(v => (
                  <button key={v} type="button" className={answers[i] === v ? 'on' : ''} aria-pressed={answers[i] === v} onClick={() => setAnswers(a => a.map((x, j) => (j === i ? v : x)))}>
                    {v}
                  </button>
                ))}
              </div>
              <div className="scale-ends">
                <span>{t(`inv.${q}lo` as 'inv.q1lo')}</span>
                <span>{t(`inv.${q}hi` as 'inv.q1hi')}</span>
              </div>
            </fieldset>
          ))}
          <p className="err">{msg}</p>
          <button className="btn primary" onClick={submit}>
            {t('inv.seeProfile')}
          </button>
        </>
      )}
    </Sheet>
  );
}

function TradeSheet({ trade, accounts, holding, onClose, onDone }: { trade: { product: Product; mode: 'buy' | 'sell' }; accounts: AccountWithBalance[]; holding?: Holding; onClose: () => void; onDone: () => void }) {
  const { t, toast, errorText, refresh } = useApp();
  const authorize = useShield();
  const { product, mode } = trade;
  const [amount, setAmount] = useState('');
  const [acct, setAcct] = useState(accounts[0]?.id ?? '');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const intent = useRef<{ sig: string; key: string } | null>(null);
  const source = accounts.find(a => a.id === acct);

  const submit = async () => {
    setMsg('');
    if (!isValidAmount(amount)) return setMsg(t('pay.invalidAmount'));
    const value = normalizeAmount(amount);
    if (mode === 'buy' && toCents(value) < toCents(product.minimum_amount)) return setMsg(t('inv.belowMin', { amount: formatMoney(product.minimum_amount) }));
    if (mode === 'buy' && source && toCents(value) > toCents(source.balance)) return setMsg(t('pay.insufficient'));
    if (mode === 'sell' && holding && toCents(value) > toCents(holding.amount)) return setMsg(t('inv.overHolding'));
    const sig = [mode, product.id, acct, value].join('|');
    if (intent.current?.sig !== sig) intent.current = { sig, key: `wealth-${mode}-` + uid() };
    setBusy(true);
    try {
      const order = await api.post<Order>(mode === 'buy' ? '/wealth/orders' : '/wealth/redemptions', { account_id: acct, product_id: product.id, amount: value, idempotency_key: intent.current.key });
      const ref = await authorize({
        operationType: mode === 'buy' ? 'wealth.subscribe' : 'wealth.redeem',
        operationId: order.id,
        amount: value,
        rows: [
          [t('inv.product'), product.name],
          [t('shield.amount'), formatMoney(value)],
          [mode === 'buy' ? t('shield.from') : t('shield.to'), source ? `${source.name} · •••• ${source.account_number.slice(-4)}` : acct],
        ],
      });
      if (!ref) return setMsg(t('pay.cancelled'));
      const done = await api.post<Order>(`/wealth/orders/${order.id}/commit`, { authorization_ref: ref });
      if (done.status !== 'COMPLETED') throw new Error('not completed');
      intent.current = null;
      celebrate(false);
      toast(t(mode === 'buy' ? 'inv.bought' : 'inv.sold', { amount: formatMoney(value) }));
      refresh();
      onDone();
      onClose();
    } catch (e) {
      setMsg(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open onClose={onClose} label={product.name}>
      <h3>{mode === 'buy' ? t('inv.buyTitle') : t('inv.sellTitle')}</h3>
      <p className="sub">
        {product.name} · <Badge tone={product.risk_tier}>{t(`inv.risk.${product.risk_tier}` as 'inv.risk.GREEN')}</Badge>
      </p>
      <label className="f" htmlFor="tr-acct">
        {mode === 'buy' ? t('shield.from') : t('shield.to')}
      </label>
      <select id="tr-acct" className="input" value={acct} onChange={e => setAcct(e.target.value)}>
        {accounts.map(a => (
          <option key={a.id} value={a.id}>
            {a.name} · {formatMoney(a.balance, a.currency)}
          </option>
        ))}
      </select>
      <label className="f" htmlFor="tr-amt">
        {t('pot.amount')} {mode === 'buy' ? `(${t('inv.min', { amount: formatMoney(product.minimum_amount) })})` : holding ? `(${t('inv.holding', { amount: formatMoney(holding.amount) })})` : ''}
      </label>
      <input id="tr-amt" className="input" inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)} placeholder={product.minimum_amount.replace(/\.00$/, '')} />
      <p className="mut small">{t('inv.redNote')}</p>
      <p className="err">{msg}</p>
      <button className="btn primary" onClick={submit} disabled={busy}>
        {mode === 'buy' ? t('inv.buy') : t('inv.sell')}
      </button>
    </Sheet>
  );
}
