import { Amount, Icon } from './kit';

export type CardFinish = 'black' | 'purple' | 'white';

/** A realistic payment card face: wordmark, chip, contactless mark, number, holder. */
export function BankCard({
  finish,
  kind,
  last4,
  holder,
  balance,
  balanceLabel,
  currency = 'CNY',
  hidden = false,
  frozenLabel,
  holderLabel = 'Card holder',
}: {
  finish: CardFinish;
  kind: string;
  last4: string;
  holder: string;
  balance?: string;
  balanceLabel?: string;
  currency?: string;
  hidden?: boolean;
  frozenLabel?: string;
  holderLabel?: string;
}) {
  return (
    <section className={'bank ' + finish + (frozenLabel ? ' frozen' : '')} aria-label={`${kind} •••• ${last4}`}>
      <div className="bank-top">
        <div>
          <div className="bank-brand">
            <Icon name="i-shield" />
            Aegis
          </div>
          <div className="bank-kind">{kind}</div>
        </div>
        <svg className="bank-nfc" aria-hidden="true">
          <use href="#i-nfc" />
        </svg>
      </div>
      {balance !== undefined && (
        <div className="bank-bal">
          <small>{balanceLabel}</small>
          {hidden ? <span className="amt masked">¥ ••••••</span> : <Amount value={balance} currency={currency} />}
        </div>
      )}
      <div className="bank-num" style={balance === undefined ? { marginTop: 'auto' } : undefined}>
        •••• •••• •••• {last4}
      </div>
      <div className="bank-foot">
        <div>
          <small>{holderLabel}</small>
          <b>{holder.toUpperCase()}</b>
        </div>
        <span className="bank-mark" aria-hidden="true">
          <i />
          <i />
        </span>
      </div>
      {frozenLabel && <div className="frost">{frozenLabel}</div>}
    </section>
  );
}
