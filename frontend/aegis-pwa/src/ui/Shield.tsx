// The Aegis shield: one approval sheet for every sensitive action, from screens and from chat.
// GREEN → approve automatically · YELLOW → user confirms · RED → 6-digit MFA.
// The authorization_ref lives only in memory and is handed straight to the caller.
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';
import { api, ApiError } from '../core/api';
import type { Approval, AuthorizationGrant, MfaChallenge, RiskTier } from '../core/types';
import { hasKey } from '../core/i18n';
import { useApp } from '../app/state';
import { Icon, Sheet } from './kit';

export interface ShieldRequest {
  operationType: string;
  operationId: string;
  targetAccountId?: string;
  amount?: string;
  rows: [string, string][];
}

type Authorize = (req: ShieldRequest) => Promise<string | null>;
const Ctx = createContext<Authorize | null>(null);

export function useShield(): Authorize {
  const fn = useContext(Ctx);
  if (!fn) throw new Error('ShieldProvider missing');
  return fn;
}

interface Pending {
  req: ShieldRequest;
  approval: Approval;
  resolve: (ref: string | null) => void;
}

export function ShieldProvider({ children }: { children: ReactNode }) {
  const { t, toast, errorText } = useApp();
  const [pending, setPending] = useState<Pending | null>(null);
  const [challenge, setChallenge] = useState<MfaChallenge | null>(null);
  const [code, setCode] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const settled = useRef(false);

  const authorize = useCallback<Authorize>(
    async req => {
      let approval: Approval;
      try {
        approval = await api.post<Approval>('/security/approvals', {
          operation_id: req.operationId,
          operation_type: req.operationType,
          ...(req.targetAccountId ? { target_account_id: req.targetAccountId } : {}),
          ...(req.amount ? { amount: req.amount } : {}),
        });
      } catch (e) {
        toast(errorText(e));
        return null;
      }
      if (approval.risk_tier === 'GREEN') {
        try {
          return (await api.post<AuthorizationGrant>(`/security/approvals/${approval.id}/decision`, { accepted: true })).authorization_ref;
        } catch (e) {
          toast(errorText(e));
          return null;
        }
      }
      return new Promise<string | null>(resolve => {
        settled.current = false;
        setChallenge(null);
        setCode('');
        setMsg('');
        setBusy(false);
        setPending({ req, approval, resolve });
      });
    },
    [toast, errorText],
  );

  const finish = (ref: string | null) => {
    if (!pending || settled.current) return;
    settled.current = true;
    pending.resolve(ref);
    setPending(null);
    setChallenge(null);
    setCode('');
  };

  const reject = async () => {
    if (!pending) return;
    const id = pending.approval.id;
    finish(null);
    try {
      await api.post(`/security/approvals/${id}/decision`, { accepted: false });
    } catch {
      /* already expired or decided */
    }
  };

  const approve = async () => {
    if (!pending || busy) return;
    const { approval } = pending;
    setBusy(true);
    setMsg('');
    try {
      if (approval.risk_tier !== 'RED') {
        finish((await api.post<AuthorizationGrant>(`/security/approvals/${approval.id}/decision`, { accepted: true })).authorization_ref);
      } else if (!challenge) {
        setChallenge(await api.post<MfaChallenge>(`/security/approvals/${approval.id}/mfa`));
      } else {
        if (!/^\d{6}$/.test(code)) {
          setMsg(t('shield.badCode'));
        } else {
          finish((await api.post<AuthorizationGrant>(`/security/mfa/${challenge.challenge_id}/verify`, { code })).authorization_ref);
        }
      }
    } catch (e) {
      setCode('');
      // Wrong codes get a localized message; lockout/expiry keep the backend's wording.
      const mfaFailed = e instanceof ApiError && e.code === 'AUTHORIZATION_REQUIRED' && !!challenge;
      setMsg(mfaFailed ? (/locked|expired|used/i.test(e.message) ? e.message : t('err.MFA_INVALID')) : errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const tier: RiskTier | null = pending?.approval.risk_tier ?? null;
  const titleKey = pending ? `shield.title.${pending.approval.operation_type}` : '';
  const title = pending ? (hasKey(titleKey) ? t(titleKey) : pending.approval.operation_type) : '';
  const expires = pending ? new Date(pending.approval.expires_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';

  return (
    <Ctx.Provider value={authorize}>
      {children}
      <Sheet open={!!pending} onClose={reject} label={title}>
        {pending && tier && (
          <>
            <div className="shield-head">
              <span className={'ico ' + tier}>
                <Icon name="i-shield" />
              </span>
              <div>
                <h3>{title}</h3>
                <span className={'badge ' + tier}>{t(`shield.${tier}` as const)}</span>
              </div>
            </div>
            <p className="sub">{tier === 'RED' ? t('shield.redBody') : t('shield.yellowBody')}</p>
            <div className="card" style={{ background: 'var(--surface-2)', boxShadow: 'none' }}>
              {pending.req.rows.map(([k, v]) => (
                <div className="kv" key={k}>
                  <span>{k}</span>
                  <span>{v}</span>
                </div>
              ))}
            </div>
            {tier === 'RED' && challenge && (
              <>
                <label className="f" htmlFor="otp">
                  {t('shield.enterCode')}
                </label>
                <div className="otp">
                  <input
                    id="otp"
                    value={code}
                    onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    onKeyDown={e => e.key === 'Enter' && approve()}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    autoFocus
                  />
                </div>
                {api.mfaHint && <p className="timer">{t('shield.demoCode', { code: api.mfaHint })}</p>}
              </>
            )}
            <p className="err" role="alert">
              {msg}
            </p>
            <p className="timer">{t('shield.expires', { time: expires })}</p>
            <div className="btn-row">
              <button className="btn" onClick={reject}>
                {t('shield.cancel')}
              </button>
              <button className={'btn ' + (tier === 'RED' ? 'danger' : 'primary')} onClick={approve} disabled={busy}>
                {tier === 'RED' ? (challenge ? t('shield.verify') : t('shield.sendCode')) : t('shield.confirm')}
              </button>
            </div>
          </>
        )}
      </Sheet>
    </Ctx.Provider>
  );
}
