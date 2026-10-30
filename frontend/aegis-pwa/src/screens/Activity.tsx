import { useApp, useLoad } from '../app/state';
import { Icon, Skeleton } from '../ui/kit';
import { TxRow } from '../ui/TxRow';
import { loadAccounts, loadRecent } from './Home';

export function Activity() {
  const { t } = useApp();
  const tx = useLoad(async () => loadRecent(await loadAccounts(), 100));
  return (
    <>
      <div className="ph">
        <a className="icon-btn" href="#/home" aria-label={t('common.back')}>
          <Icon name="i-back" />
        </a>
        <h2>{t('home.activity')}</h2>
        <span style={{ width: 40 }} />
      </div>
      <section className="card flush">
        {tx.loading && !tx.data && <Skeleton rows={5} />}
        {tx.data?.length === 0 && <div className="empty">{t('home.noActivity')}</div>}
        {tx.data?.map(x => <TxRow tx={x} key={x.id} />)}
      </section>
    </>
  );
}
