import { useEffect, useRef, useState } from 'react';
import { api, ApiError, uid } from '../core/api';
import type { Beneficiary, Subscription, TransferDraft, TransferReceipt } from '../core/types';
import { daysUntil, formatDate } from '../core/format';
import { formatMoney, isValidAmount, normalizeAmount, toCents } from '../core/money';
import { go, useApp, useLoad } from '../app/state';
import { useShield } from '../ui/Shield';
import { Amount, Badge, Icon, Sheet, Skeleton } from '../ui/kit';
import { PersonAvatar } from '../ui/art';
import { CONTACTS, contactForAccount, contactName, type Contact } from '../core/people';
import { loadAccounts } from './Home';

/** Avatar key and display name for a saved recipient, using the contact list when it matches. */
export function recipientLook(b: Beneficiary, lang: 'zh' | 'en') {
  const c = contactForAccount(b.destination_account_number);
  return { key: c?.key ?? b.id, name: c ? contactName(c, lang) : b.nickname || b.name };
}

/**
 * Contacts and saved recipients as one grid. Picking a contact who isn't saved yet saves them
 * through Banking Core first (exact account-number match), then opens the send screen.
 */
export function PeopleGrid({ limit, onAdd, strip }: { limit?: number; onAdd?: () => void; strip?: boolean }) {
  const { t, lang, toast, errorText } = useApp();
  const saved = useLoad(() => api.get<Beneficiary[]>('/beneficiaries'));
  const [busy, setBusy] = useState('');
  const savedFor = (c: Contact) => saved.data?.find(b => b.destination_account_number === c.accountNumber);
  const extras = (saved.data ?? []).filter(b => !contactForAccount(b.destination_account_number));
  const people = [
    ...CONTACTS.map(c => ({ key: c.key, name: contactName(c, lang), contact: c as Contact | null, saved: savedFor(c) })),
    ...extras.map(b => ({ key: b.id, name: b.nickname || b.name, contact: null, saved: b as Beneficiary | undefined })),
  ];
  const shown = limit ? people.slice(0, limit) : people;

  const pick = async (p: (typeof people)[number]) => {
    if (busy) return;
    if (p.saved) return go('pay/' + p.saved.id);
    if (!p.contact) return;
    setBusy(p.key);
    try {
      const b = await api.post<Beneficiary>('/beneficiaries', { name: p.contact.zh, account_number: p.contact.accountNumber });
      go('pay/' + b.id);
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy('');
    }
  };

  return (
    <div className={'people' + (strip ? ' strip' : '')}>
      {onAdd && (
        <button onClick={onAdd}>
          <span className="more">
            <Icon name="i-plus" />
          </span>
          <span>{t('pay.newRecipient')}</span>
        </button>
      )}
      {shown.map(p => (
        <button key={p.key} onClick={() => pick(p)} aria-busy={busy === p.key} style={busy === p.key ? { opacity: 0.5 } : undefined}>
          <PersonAvatar id={p.key} label={p.name} />
          <span>{p.name}</span>
        </button>
      ))}
      {limit && people.length > limit && (
        <a href="#/pay">
          <span className="more">
            <Icon name="i-chev" />
          </span>
          <span>{t('home.more')}</span>
        </a>
      )}
    </div>
  );
}

/** One scrollable row of people for Home. */
export function PeopleStrip() {
  return <PeopleGrid strip />;
}

export function Pay({ preselect }: { preselect?: string }) {
  const { t, locale, toast, errorText, refresh } = useApp();
  const authorize = useShield();
  const accounts = useLoad(loadAccounts);
  const payees = useLoad(() => api.get<Beneficiary[]>('/beneficiaries'));
  const subs = useLoad(() => api.get<Subscription[]>('/subscriptions'));
  const [to, setTo] = useState<Beneficiary | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [receipt, setReceipt] = useState<{ r: TransferReceipt; name: string } | null>(null);

  useEffect(() => {
    if (preselect && payees.data && !to) setTo(payees.data.find(p => p.id === preselect) ?? null);
  }, [preselect, payees.data, to]);

  const cancelSub = async (s: Subscription) => {
    const ref = await authorize({
      operationType: 'subscription.cancel',
      operationId: s.id,
      rows: [
        [t('shield.merchant'), s.merchant_name],
        [t('shield.amount'), formatMoney(s.amount, s.currency)],
      ],
    });
    if (!ref) return;
    try {
      await api.post(`/subscriptions/${s.id}/cancel`, { authorization_ref: ref });
      toast(t('pay.subCancelled'));
      refresh();
    } catch (e) {
      toast(errorText(e));
    }
  };

  if (receipt) return <Receipt receipt={receipt.r} name={receipt.name} onDone={() => { setReceipt(null); setTo(null); go('home'); }} />;

  if (to && accounts.data) {
    return (
      <AmountStep
        to={to}
        accounts={accounts.data}
        onBack={() => setTo(null)}
        onSent={r => {
          refresh();
          setReceipt({ r, name: to.name });
        }}
      />
    );
  }

  return (
    <>
      <div className="ph">
        <h1>{t('pay.title')}</h1>
      </div>
      <div className="section-t">{t('pay.to')}</div>
      <PeopleGrid onAdd={() => setAddOpen(true)} />

      <div className="tier-hint">
        <Icon name="i-shield" />
        <span>{t('pay.tierHint')}</span>
      </div>

      <section className="card flush">
        <div className="card-h">
          <h3>{t('pay.upcoming')}</h3>
        </div>
        {subs.loading && !subs.data && <Skeleton rows={1} />}
        {subs.data?.length === 0 && <div className="empty">{t('pay.noSubs')}</div>}
        {subs.data?.map(s => {
          const d = daysUntil(s.next_billing_date);
          return (
            <div className="row" key={s.id}>
              <span className="ico ENTERTAINMENT">
                <Icon name="c-ENTERTAINMENT" />
              </span>
              <span className="main">
                <span className="t" style={{ display: 'block' }}>
                  {s.merchant_name}
                </span>
                <span className="s" style={{ display: 'block' }}>
                  {s.active ? (d > 0 ? t('home.inDays', { n: d }) : t('pay.nextBilling', { date: formatDate(s.next_billing_date, locale) })) : <Badge tone="CANCELLED">{s.status}</Badge>}
                </span>
              </span>
              <span className="v">
                <Amount value={s.amount} currency={s.currency} />
                {s.active && (
                  <button className="link" style={{ display: 'block', marginLeft: 'auto', marginTop: 2 }} onClick={() => cancelSub(s)}>
                    {t('pay.cancelSub')}
                  </button>
                )}
              </span>
            </div>
          );
        })}
      </section>

      <AddRecipient
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSaved={b => {
          payees.reload();
          setAddOpen(false);
          setTo(b);
        }}
      />
    </>
  );
}

function AmountStep({ to, accounts, onBack, onSent }: { to: Beneficiary; accounts: { id: string; name: string; account_number: string; balance: string; currency: string }[]; onBack: () => void; onSent: (r: TransferReceipt) => void }) {
  const { t, lang, errorText } = useApp();
  const authorize = useShield();
  const [amount, setAmount] = useState('');
  const [src, setSrc] = useState(accounts[0]?.id ?? '');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [pendingDraft, setPendingDraft] = useState<string | null>(null);
  // One Idempotency-Key per intent: retries of the same transfer reuse it; any change makes a new one.
  const intent = useRef<{ sig: string; key: string } | null>(null);
  const source = accounts.find(a => a.id === src);

  const submit = async () => {
    setMsg('');
    setPendingDraft(null);
    if (!isValidAmount(amount)) return setMsg(t('pay.invalidAmount'));
    const value = normalizeAmount(amount);
    if (source && toCents(value) > toCents(source.balance)) return setMsg(t('pay.insufficient'));
    const sig = [src, to.destination_account_id, value].join('|');
    if (intent.current?.sig !== sig) intent.current = { sig, key: 'transfer-' + uid() };
    setBusy(true);
    let draft: TransferDraft;
    try {
      draft = await api.post<TransferDraft>(
        '/transfers/drafts',
        { source_account_id: src, destination_account_id: to.destination_account_id, amount: value, currency: 'CNY' },
        { 'Idempotency-Key': intent.current.key },
      );
    } catch (e) {
      setBusy(false);
      return setMsg(errorText(e));
    }
    const ref = await authorize({
      operationType: 'transfer.commit',
      operationId: draft.id,
      rows: [
        [t('shield.to'), `${to.name} · •••• ${to.destination_account_number.slice(-4)}`],
        [t('shield.amount'), formatMoney(draft.amount, draft.currency)],
        [t('shield.from'), source ? `${source.name} · •••• ${source.account_number.slice(-4)}` : src],
      ],
    });
    if (!ref) {
      setBusy(false);
      return setMsg(t('pay.cancelled'));
    }
    try {
      const receipt = await api.post<TransferReceipt>(`/transfers/${draft.id}/commit`, { authorization_ref: ref });
      if (receipt.status !== 'COMPLETED') throw new ApiError(409, 'CONFLICT');
      intent.current = null;
      onSent(receipt);
    } catch (e) {
      setMsg(errorText(e));
      if (e instanceof ApiError && e.code === 'NETWORK') setPendingDraft(draft.id);
    } finally {
      setBusy(false);
    }
  };

  const checkStatus = async () => {
    if (!pendingDraft) return;
    try {
      const d = await api.get<TransferDraft>(`/transfers/${pendingDraft}`);
      setMsg(`${t('pay.status')}: ${d.status}`);
    } catch (e) {
      setMsg(errorText(e));
    }
  };

  return (
    <>
      <div className="ph">
        <button className="icon-btn" onClick={onBack} aria-label={t('common.back')}>
          <Icon name="i-back" />
        </button>
        <h2>{t('pay.confirmTitle')}</h2>
        <span style={{ width: 40 }} />
      </div>
      <section className="amount-card">
        <div className="who">
          <PersonAvatar id={recipientLook(to, lang).key} label={recipientLook(to, lang).name} size={44} />
          <div>
            <div style={{ fontWeight: 700 }}>{recipientLook(to, lang).name}</div>
            <div className="s">•••• {to.destination_account_number.slice(-4)}</div>
          </div>
        </div>
        <label className="amount-in">
          <span className="cur">¥</span>
          <input
            aria-label={t('pot.amount')}
            inputMode="decimal"
            placeholder="0"
            value={amount}
            onChange={e => setAmount(e.target.value.replace(/[^\d.]/g, '').replace(/(\..*)\./g, '$1').replace(/^(\d*\.\d{0,2}).*$/, '$1'))}
            style={{ width: Math.max(2, amount.length + 0.5) + 'ch' }}
            autoFocus
          />
        </label>
        <div className="note">{t('pay.noFees')}</div>
        <div className="src-pill">
          <select aria-label={t('pay.from')} value={src} onChange={e => setSrc(e.target.value)}>
            {accounts.map(a => (
              <option value={a.id} key={a.id}>
                {a.name} · {formatMoney(a.balance, a.currency)}
              </option>
            ))}
          </select>
          <Icon name="i-chev" />
        </div>
        <div className="arrive">{t('pay.arriving')}</div>
      </section>
      <p className="err" role="alert">
        {msg}{' '}
        {pendingDraft && (
          <button className="link" onClick={checkStatus}>
            {t('pay.checkStatus')}
          </button>
        )}
      </p>
      <button className="btn primary" onClick={submit} disabled={busy || !amount}>
        {t('pay.continue')}
      </button>
      <div className="tier-hint">
        <Icon name="i-shield" />
        <span>{t('pay.tierHint')}</span>
      </div>
    </>
  );
}

function Receipt({ receipt, name, onDone }: { receipt: TransferReceipt; name: string; onDone: () => void }) {
  const { t } = useApp();
  return (
    <div className="receipt">
      <div className="ok">
        <Icon name="i-check" />
      </div>
      <h1 style={{ fontSize: 22 }}>{t('pay.sentTitle')}</h1>
      <Amount value={receipt.amount} currency={receipt.currency} />
      <p className="mut">{t('pay.sentTo', { name })}</p>
      <section className="card" style={{ marginTop: 18 }}>
        <div className="kv">
          <span>{t('pay.status')}</span>
          <span>
            <Badge tone={receipt.status}>{receipt.status}</Badge>
          </span>
        </div>
        <div className="kv">
          <span>{t('pay.reference')}</span>
          <span className="mono">{receipt.reference}</span>
        </div>
        <div className="kv">
          <span>{t('pay.txId')}</span>
          <span className="mono">{receipt.transaction_id}</span>
        </div>
      </section>
      <button className="btn primary" onClick={onDone}>
        {t('pay.done')}
      </button>
    </div>
  );
}

function AddRecipient({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: (b: Beneficiary) => void }) {
  const { t, errorText } = useApp();
  const [name, setName] = useState('');
  const [number, setNumber] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!name.trim() || !number.trim()) return setMsg(t('err.VALIDATION_ERROR'));
    setBusy(true);
    try {
      const b = await api.post<Beneficiary>('/beneficiaries', { name: name.trim(), account_number: number.trim() });
      setName('');
      setNumber('');
      setMsg('');
      onSaved(b);
    } catch (e) {
      setMsg(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet open={open} onClose={onClose} label={t('pay.addRecipient')}>
      <h3>{t('pay.addRecipient')}</h3>
      <p className="sub">{t('pay.addHint')}</p>
      <label className="f" htmlFor="r-name">
        {t('pay.name')}
      </label>
      <input id="r-name" className="input" value={name} onChange={e => setName(e.target.value)} autoComplete="off" placeholder="爸爸" />
      <label className="f" htmlFor="r-num">
        {t('pay.accountNumber')}
      </label>
      <input id="r-num" className="input mono" value={number} onChange={e => setNumber(e.target.value)} inputMode="numeric" autoComplete="off" placeholder="299000000001" />
      <p className="err">{msg}</p>
      <button className="btn primary" onClick={save} disabled={busy}>
        {t('pay.save')}
      </button>
    </Sheet>
  );
}
