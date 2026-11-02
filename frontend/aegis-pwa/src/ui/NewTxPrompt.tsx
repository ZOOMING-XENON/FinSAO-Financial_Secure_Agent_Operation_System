// Asks "what was this for?" when new spending appears (card payments, transfers to shops),
// then saves the category to Banking Core. Each transaction is asked about once per device.
import { useEffect, useState } from 'react';
import { api } from '../core/api';
import { PICKABLE, type Category, type Transaction } from '../core/types';
import { categoryKey, direction, formatDate } from '../core/format';
import { formatMoney } from '../core/money';
import { useApp, useClient } from '../app/state';
import { loadAccounts, loadRecent } from '../screens/Home';
import { Icon, Sheet } from './kit';

const KEY = 'aegis.seenTx';
const FRESH_MS = 36 * 3600 * 1000;

function readSeen(): Set<string> | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? new Set(JSON.parse(raw) as string[]) : null;
  } catch {
    return new Set();
  }
}
function writeSeen(seen: Set<string>) {
  try {
    localStorage.setItem(KEY, JSON.stringify([...seen].slice(-600)));
  } catch {
    /* storage unavailable */
  }
}

export function NewTxPrompt() {
  const { t, locale, toast, errorText, refresh, version } = useApp();
  const { core } = useClient();
  const [queue, setQueue] = useState<Transaction[]>([]);
  const [pick, setPick] = useState<Category>('UNKNOWN');

  useEffect(() => {
    if (core === 'checking') return;
    let alive = true;
    (async () => {
      const tx = (await loadRecent(await loadAccounts(), 60)).filter(x => direction(x) === 'out' && x.category !== 'INTERNAL_TRANSFER');
      let seen = readSeen();
      if (!seen) {
        // First run: only payments from the last day and a half count as new.
        seen = new Set(tx.filter(x => !x.posted_at || Date.now() - Date.parse(x.posted_at) > FRESH_MS).map(x => x.id));
        writeSeen(seen);
      }
      const fresh = tx.filter(x => !seen!.has(x.id)).slice(0, 3);
      if (alive) setQueue(fresh);
    })().catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [core, version]);

  const cur = queue[0];
  useEffect(() => {
    if (cur) setPick(categoryKey(cur.category));
  }, [cur]);

  const done = (tx: Transaction) => {
    const seen = readSeen() ?? new Set<string>();
    seen.add(tx.id);
    writeSeen(seen);
    setQueue(q => q.filter(x => x.id !== tx.id));
  };

  const save = async () => {
    if (!cur) return;
    try {
      if (pick !== categoryKey(cur.category)) await api.patch(`/transactions/${cur.id}/category`, { category: pick });
      toast(t('track.saved', { cat: t(`cat.${pick}`) }));
      done(cur);
      if (queue.length <= 1) refresh();
    } catch (e) {
      toast(errorText(e));
    }
  };

  return (
    <Sheet open={!!cur} onClose={() => cur && done(cur)} label={t('newtx.title')}>
      {cur && (
        <>
          <span className="badge INFO">{t('newtx.badge')}</span>
          <h3 style={{ marginTop: 10 }}>{t('newtx.title')}</h3>
          <p className="sub">
            {cur.description} · {formatMoney(cur.amount, cur.currency)} · {formatDate(cur.posted_at, locale, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
          </p>
          <div className="cat-pick">
            {PICKABLE.map(c => (
              <button key={c} className={pick === c ? 'on' : ''} onClick={() => setPick(c)} aria-pressed={pick === c}>
                <span className="ico">
                  <Icon name={'c-' + c} />
                </span>
                {t(`cat.${c}`)}
              </button>
            ))}
          </div>
          <div className="btn-row">
            <button className="btn" onClick={() => done(cur)}>
              {t('newtx.skip')}
            </button>
            <button className="btn primary" onClick={save}>
              {t('newtx.save')}
              {queue.length > 1 ? ` (${queue.length})` : ''}
            </button>
          </div>
        </>
      )}
    </Sheet>
  );
}
