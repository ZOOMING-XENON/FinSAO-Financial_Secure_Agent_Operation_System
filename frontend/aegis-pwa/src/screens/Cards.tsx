import { useState } from 'react';
import { api } from '../core/api';
import type { Card } from '../core/types';
import { currentMonth, summarize } from '../core/insights';
import { formatMoney, fromCents, toCents } from '../core/money';
import { getProfile } from '../core/profile';
import { go, useApp, useLoad } from '../app/state';
import { useShield } from '../ui/Shield';
import { BankCard, type CardFinish } from '../ui/BankCard';
import { Badge, Icon, Sheet, Skeleton } from '../ui/kit';
import { TxRow } from '../ui/TxRow';
import { loadAccounts, loadRecent, type AccountWithBalance } from './Home';

interface Slide {
  key: string;
  finish: CardFinish;
  kind: string;
  last4: string;
  account?: AccountWithBalance;
  card?: Card;
}

async function loadCards() {
  const [accounts, cards] = await Promise.all([loadAccounts(), api.get<Card[]>('/cards')]);
  const tx = await loadRecent(accounts, 200);
  return { accounts, cards, tx };
}

export function Cards() {
  const { t, toast, errorText, refresh } = useApp();
  const authorize = useShield();
  const data = useLoad(loadCards);
  const [idx, setIdx] = useState(0);
  const [sheet, setSheet] = useState<'limit' | 'details' | null>(null);
  const [limit, setLimit] = useState(5000);

  if (!data.data) {
    return (
      <>
        <div className="ph">
          <h1>{t('cards.title')}</h1>
        </div>
        <Skeleton rows={5} />
      </>
    );
  }
  const { accounts, cards, tx } = data.data;
  const finishes: CardFinish[] = ['purple', 'white'];
  const slides: Slide[] = [
    ...cards.map(c => ({ key: c.id, finish: 'black' as const, kind: t('cards.debit'), last4: c.last_four, card: c, account: accounts.find(a => a.id === c.account_id) })),
    // An account that already has a debit card (Checking) would just repeat that card.
    ...accounts.filter(a => !cards.some(c => c.account_id === a.id)).map((a, i) => ({ key: a.id, finish: finishes[i % finishes.length], kind: a.name, last4: a.account_number.slice(-4), account: a })),
  ];
  const cur = slides[Math.min(idx, slides.length - 1)];
  const card = cur?.card;
  const acctTx = tx.slice(0, 6);
  const month = summarize(tx, currentMonth());
  const spent = month.spent;
  const cap = card ? toCents(card.spending_limit) : 0n;
  const pct = cap > 0n ? Math.min(100, Number((spent * 100n) / cap)) : 0;
  const frozen = card?.status === 'FROZEN';

  const act = async (action: 'freeze' | 'unfreeze' | 'report-lost') => {
    if (!card) return;
    const type = action === 'report-lost' ? 'card.report_lost' : `card.${action}`;
    const ref = await authorize({ operationType: type, operationId: card.id, rows: [[t('shield.card'), `${card.label} · •••• ${card.last_four}`]] });
    if (!ref) return;
    try {
      await api.post(`/cards/${card.id}/${action}`, { authorization_ref: ref });
      toast(t(action === 'freeze' ? 'cards.frozenDone' : action === 'unfreeze' ? 'cards.unfrozenDone' : 'me.lostDone'));
      setSheet(null);
      data.reload();
      refresh();
    } catch (e) {
      toast(errorText(e));
    }
  };

  const saveLimit = async () => {
    if (!card) return;
    const value = `${limit}.00`;
    const ref = await authorize({
      operationType: 'card.limit',
      operationId: card.id,
      amount: value,
      rows: [
        [t('shield.card'), `${card.label} · •••• ${card.last_four}`],
        [t('cards.newLimit'), formatMoney(value)],
      ],
    });
    if (!ref) return;
    try {
      await api.patch(`/cards/${card.id}/limit`, { spending_limit: value, authorization_ref: ref });
      toast(t('cards.limitDone', { amount: formatMoney(value) }));
      setSheet(null);
      data.reload();
    } catch (e) {
      toast(errorText(e));
    }
  };

  return (
    <>
      <div className="ph">
        <h1>{t('cards.title')}</h1>
        <button className="icon-btn" aria-label={t('cards.add')} onClick={() => toast(t('cards.addSoon'))}>
          <Icon name="i-plus" />
        </button>
      </div>

      <div
        className="carousel"
        onScroll={e => {
          const el = e.currentTarget;
          const w = (el.firstElementChild as HTMLElement | null)?.offsetWidth || 1;
          setIdx(Math.round(el.scrollLeft / (w + 12)));
        }}
      >
        {slides.map(s => (
          <BankCard
            key={s.key}
            finish={s.finish}
            kind={s.kind}
            last4={s.last4}
            holder={getProfile().name}
            holderLabel={t('cards.holder')}
            balance={s.account?.balance}
            balanceLabel={t('cards.available')}
            frozenLabel={s.card?.status === 'FROZEN' ? t('me.frozen') : s.card && s.card.status !== 'ACTIVE' ? s.card.status : undefined}
          />
        ))}
      </div>
      {slides.length > 1 && (
        <div className="dots" aria-hidden="true">
          {slides.map((s, i) => (
            <i key={s.key} className={i === idx ? 'on' : ''} />
          ))}
        </div>
      )}

      <div className="card-actions">
        {card ? (
          <>
            <button className={frozen ? 'on' : ''} onClick={() => act(frozen ? 'unfreeze' : 'freeze')} aria-pressed={frozen}>
              <Icon name="i-snow" />
              {frozen ? t('cards.unfreeze') : t('cards.freeze')}
            </button>
            <button
              onClick={() => {
                setLimit(Number(toCents(card.spending_limit) / 100n));
                setSheet('limit');
              }}
            >
              <Icon name="i-gauge" />
              {t('cards.limits')}
            </button>
          </>
        ) : (
          <>
            <button onClick={() => go('pay')}>
              <Icon name="i-send" />
              {t('home.send')}
            </button>
            <button onClick={() => go('activity')}>
              <Icon name="i-book" />
              {t('cards.statement')}
            </button>
          </>
        )}
        <button onClick={() => setSheet('details')}>
          <Icon name="i-info" />
          {t('cards.details')}
        </button>
        <button onClick={() => toast(t('home.addMoneyPreview'))}>
          <Icon name="i-plus" />
          {t('cards.topUp')}
        </button>
      </div>

      <section className="card limit-card">
        <div className="goal-top">
          <span className="small">{t('cards.spentMonth')}</span>
          <span>
            <b>{formatMoney(fromCents(spent))}</b>
            {card && <span className="mut small"> / {formatMoney(card.spending_limit)}</span>}
          </span>
        </div>
        {card ? (
          <>
            <div className="limit-bar" aria-hidden="true">
              <i style={{ width: pct + '%' }} />
            </div>
            <div className="limit-foot">
              <span>{t('cards.ofLimit', { pct })}</span>
              <span>100%</span>
            </div>
          </>
        ) : (
          <p className="mut small" style={{ margin: '8px 0 0' }}>
            {t('cards.accountHint')}
          </p>
        )}
      </section>

      <section className="card flush">
        <div className="card-h">
          <h3>{t('cards.transactions')}</h3>
          <a className="link" href="#/activity">
            {t('home.seeAll')}
          </a>
        </div>
        {acctTx.length === 0 && <div className="empty">{t('home.noActivity')}</div>}
        {acctTx.map(x => (
          <TxRow tx={x} key={x.id} />
        ))}
      </section>

      <Sheet open={sheet === 'limit'} onClose={() => setSheet(null)} label={t('cards.limits')}>
        <h3>{t('cards.limitTitle')}</h3>
        <p className="sub">{t('cards.limitHint')}</p>
        <div className="amt big center" style={{ display: 'block' }}>
          {formatMoney(`${limit}.00`)}
        </div>
        <input className="range" type="range" min={500} max={50000} step={500} value={limit} onChange={e => setLimit(Number(e.target.value))} aria-label={t('cards.newLimit')} />
        <div className="limit-foot">
          <span>¥500</span>
          <span>¥50,000</span>
        </div>
        <button className="btn primary" style={{ marginTop: 16 }} onClick={saveLimit}>
          {t('cards.saveLimit')}
        </button>
      </Sheet>

      <Sheet open={sheet === 'details'} onClose={() => setSheet(null)} label={t('cards.details')}>
        <h3>{cur?.kind}</h3>
        <div className="card" style={{ background: 'var(--surface-2)', boxShadow: 'none', marginTop: 10 }}>
          <div className="kv">
            <span>{t('cards.holder')}</span>
            <span>{getProfile().name}</span>
          </div>
          <div className="kv">
            <span>{card ? t('cards.number') : t('pay.accountNumber')}</span>
            <span className="mono">{card ? `•••• •••• •••• ${card.last_four}` : cur?.account?.account_number}</span>
          </div>
          {card && (
            <div className="kv">
              <span>{t('pay.status')}</span>
              <span>
                <Badge tone={card.status}>{card.status === 'FROZEN' ? t('me.frozen') : card.status}</Badge>
              </span>
            </div>
          )}
          {card && (
            <div className="kv">
              <span>{t('me.limit')}</span>
              <span>{formatMoney(card.spending_limit)}</span>
            </div>
          )}
          {cur?.account && (
            <div className="kv">
              <span>{t('cards.linked')}</span>
              <span>
                {cur.account.name} · {cur.account.currency}
              </span>
            </div>
          )}
        </div>
        {card && card.status !== 'LOST' && (
          <button className="btn danger" onClick={() => act('report-lost')}>
            <Icon name="i-lock" />
            {t('me.reportLost')}
          </button>
        )}
      </Sheet>
    </>
  );
}
