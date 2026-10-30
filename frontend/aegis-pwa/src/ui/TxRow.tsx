import type { Transaction } from '../core/types';
import { categoryKey, direction, formatDate } from '../core/format';
import { useApp } from '../app/state';
import { Amount, Icon } from './kit';

export function TxRow({ tx }: { tx: Transaction }) {
  const { t, locale } = useApp();
  const dir = direction(tx);
  const cat = categoryKey(tx.category);
  const icon = dir === 'in' ? 'IN' : dir === 'move' ? 'MOVE' : cat;
  const label = dir === 'in' ? t('tx.in') : dir === 'move' ? t('tx.move') : t(`cat.${cat}`);
  return (
    <div className="row">
      <span className={'ico ' + icon}>
        <Icon name={'c-' + icon} />
      </span>
      <span className="main">
        <span className="t" style={{ display: 'block' }}>
          {tx.description}
        </span>
        <span className="s" style={{ display: 'block' }}>
          {label} · {formatDate(tx.posted_at, locale)}
          {tx.status !== 'COMPLETED' ? ` · ${tx.status}` : ''}
        </span>
      </span>
      <span className={'v' + (dir === 'in' ? ' pos' : '')}>
        <Amount value={tx.amount} currency={tx.currency} sign={dir === 'in' ? '+' : undefined} />
      </span>
    </div>
  );
}
