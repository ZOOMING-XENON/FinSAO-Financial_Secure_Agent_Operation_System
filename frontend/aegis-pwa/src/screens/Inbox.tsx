// Notifications: everything Aegis wants you to know, newest and most urgent first.
import { useEffect } from 'react';
import { formatMoney, fromCents } from '../core/money';
import { categoryKey, formatDate } from '../core/format';
import { buildInbox, markSeen, useSeen, type InboxItem } from '../core/inbox';
import { useApp, useLoad } from '../app/state';
import { Icon, Skeleton } from '../ui/kit';
import { loadMoneyPicture, type MoneyPicture } from './Home';

export function useInbox(data: MoneyPicture | undefined): InboxItem[] {
  const { t } = useApp();
  if (!data) return [];
  return buildInbox({ ...data, money: c => formatMoney(fromCents(c)), cat: c => t(`cat.${categoryKey(c)}`) });
}

export function Inbox() {
  const { t, locale } = useApp();
  const pic = useLoad(loadMoneyPicture);
  const items = useInbox(pic.data);
  const seen = useSeen();
  // Remember what was new when the screen opened, then mark everything as read.
  const fresh = items.filter(x => !seen.has(x.id)).map(x => x.id).join('|');
  useEffect(() => {
    if (!items.length) return;
    const id = window.setTimeout(() => markSeen(items.map(x => x.id)), 1500);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fresh]);

  const row = (n: InboxItem) => (
    <a className={'inbox-row ' + n.tone + (seen.has(n.id) ? '' : ' unread')} href={n.href} key={n.id}>
      <span className="nudge-ico">
        <Icon name={n.icon} />
      </span>
      <span className="main">
        <span className="txt">{t(n.key as 'nudge.left', n.vars)}</span>
        {n.at && <small>{formatDate(n.at, locale, { month: 'short', day: 'numeric' })}</small>}
      </span>
      <Icon name="i-chev" />
    </a>
  );
  const unread = items.filter(x => !seen.has(x.id));
  const read = items.filter(x => seen.has(x.id));

  return (
    <>
      <div className="ph">
        <a className="icon-btn" href="#/home" aria-label={t('common.back')}>
          <Icon name="i-back" />
        </a>
        <h2>{t('inbox.title')}</h2>
        <span style={{ width: 42 }} />
      </div>
      {pic.loading && !pic.data && <Skeleton rows={4} />}
      {pic.data && items.length === 0 && <div className="empty">{t('inbox.empty')}</div>}
      {unread.length > 0 && (
        <>
          <div className="section-t">{t('inbox.new')}</div>
          <section className="card flush">{unread.map(row)}</section>
        </>
      )}
      {read.length > 0 && (
        <>
          <div className="section-t">{t('inbox.earlier')}</div>
          <section className="card flush">{read.map(row)}</section>
        </>
      )}
    </>
  );
}
