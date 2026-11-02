import { useEffect, useRef, useState, type ReactNode } from 'react';
import { api, uid } from '../core/api';
import type { AgentTask, AgentTurnResponse, ClarificationField, ConversationMessage, SpendingSummary } from '../core/types';
import { categoryKey, monthLabel } from '../core/format';
import { formatMoney } from '../core/money';
import { go, useApp, useClient } from '../app/state';
import { useShield } from '../ui/Shield';
import { Amount, Icon } from '../ui/kit';
import { startMicLevel, VoiceOrb, type OrbLevel } from '../ui/Orb';
import { haptic } from '../ui/celebrate';
import { loadAccounts } from './Home';

interface Msg {
  id: string;
  role: 'me' | 'bot';
  body: ReactNode;
}

// Chat lives in memory only for this app session; nothing is persisted.
const session = { id: uid(), messages: [] as Msg[], history: [] as ConversationMessage[], pending: '', voiceLang: '' as '' | 'zh-CN' | 'en-US' };

export function askAegis(text: string) {
  session.pending = text;
  go('aegis');
}

const SENSITIVE = /(?:密码|口令|password|passcode)\s*(?:是|为|[:：=])?\s*\S{4,}|(?:验证码|动态码|otp|mfa|code)\s*(?:是|为|[:：=])?\s*\d{4,8}|(?:cvv|cvc|安全码)\s*(?:是|为|[:：=])?\s*\d{3,4}|\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,7}\b/i;
const INJECTION = /ignore (?:all |previous |the )*(?:instructions|rules)|忽略(?:之前|以上|所有)?(?:的)?(?:指令|规则)|system prompt|系统提示|developer mode|越权|bypass|绕过(?:审批|验证|护盾)/i;

const DRAFT_TOOLS: Record<string, string> = {
  create_transfer_draft: 'transfer.commit',
  create_wealth_subscription_draft: 'wealth.subscribe',
  create_wealth_redemption_draft: 'wealth.redeem',
};
const DIRECT_TOOLS: Record<string, string> = {
  cancel_subscription: 'subscription.cancel',
  update_card_limit: 'card.limit',
  freeze_card: 'card.freeze',
  unfreeze_card: 'card.unfreeze',
  report_card_lost: 'card.report_lost',
  contribute_savings_pot: 'savings.contribute',
};

/** Finds the operation the agent is waiting on, so the shield can approve it. */
export function pendingOperation(task: AgentTask): { type: string; id: string; amount?: string; args: Record<string, unknown> } | null {
  const steps = task.plan?.steps ?? [];
  const call = [...steps].reverse().find(s => s.tool_call)?.tool_call;
  if (!call) return null;
  const args = call.arguments ?? {};
  const draftType = DRAFT_TOOLS[call.tool_name];
  const type = draftType ?? DIRECT_TOOLS[call.tool_name];
  if (!type) return null;
  const result = task.result ?? {};
  const id = draftType ? (result.id as string | undefined) : ((args.resource_id ?? args.card_id ?? args.subscription_id ?? args.pot_id) as string | undefined);
  if (!id) return null;
  const amount = (result.amount ?? args.amount ?? args.spending_limit) as string | undefined;
  return { type, id, amount, args };
}

export function Aegis() {
  const { t, lang, locale, errorText } = useApp();
  const { agent, core } = useClient();
  const authorize = useShield();
  const [messages, setMessages] = useState<Msg[]>(session.messages);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [replyTarget, setReplyTarget] = useState<{ bundleId: string; itemId: string } | null>(null);
  const [listening, setListening] = useState(false);
  // Speech recognition hears one language at a time; it starts as the UI language and the user can switch it.
  const [voiceLang, setVoiceLang] = useState<'zh-CN' | 'en-US'>(session.voiceLang || (lang === 'zh' ? 'zh-CN' : 'en-US'));
  const switchVoiceLang = () => {
    const next = voiceLang === 'zh-CN' ? 'en-US' : 'zh-CN';
    session.voiceLang = next;
    setVoiceLang(next);
    if (voiceOpen) void startVoiceCapture(next);
  };
  const endRef = useRef<HTMLDivElement>(null);
  const recRef = useRef<{ stop: () => void } | null>(null);
  const level = useRef<OrbLevel>({ current: 0 }).current;
  const stopMic = useRef<() => void>(() => undefined);
  const heard = useRef('');
  const backendStop = useRef<(() => Promise<Blob>) | null>(null);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [voiceText, setVoiceText] = useState('');
  const [voiceError, setVoiceError] = useState('');
  const captureId = useRef(0);
  const recognitionFailed = useRef(false);
  useEffect(() => () => {
    recRef.current?.stop();
    stopMic.current();
  }, []);

  const push = (m: Omit<Msg, 'id'>) => {
    session.messages = [...session.messages, { ...m, id: uid() }];
    setMessages(session.messages);
  };
  const remember = (role: ConversationMessage['role'], content: string) => {
    session.history = [...session.history, { role, content }].slice(-10);
  };

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, busy]);

  useEffect(() => {
    if (session.pending && agent !== 'checking') {
      const p = session.pending;
      session.pending = '';
      send(p);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent]);

  const renderResult = (task: AgentTask): ReactNode => {
    const r = task.result ?? {};
    const msg = task.public_message || t('aegis.done');
    if (typeof r.reply === 'string') return r.reply;
    if (typeof r.balance === 'string') {
      return (
        <>
          {t('aegis.balance')}
          <Amount value={r.balance} currency={(r.currency as string) || 'CNY'} />
        </>
      );
    }
    if (Array.isArray(r.accounts)) {
      return (r.accounts as { name: string; account_number: string; status: string }[]).map(a => (
        <div key={a.account_number}>
          {a.name} · •••• {a.account_number.slice(-4)}
        </div>
      ));
    }
    if (typeof r.total === 'string' && r.by_category) {
      return (
        <>
          <Amount value={r.total} />
          {Object.entries(r.by_category as Record<string, string>).map(([c, v]) => (
            <div key={c} className="small">
              {t(`cat.${categoryKey(c)}`)} · {formatMoney(v)}
            </div>
          ))}
        </>
      );
    }
    if (Array.isArray(r.items)) {
      const items = r.items as Record<string, unknown>[];
      if (!items.length) return msg;
      return items.slice(0, 8).map((v, i) => (
        <div key={i} className="small">
          {String(v.name ?? v.label ?? v.merchant_name ?? v.description ?? '')}
          {v.last_four ? ` · •••• ${v.last_four}` : ''}
          {typeof v.amount === 'string' ? ` · ${formatMoney(v.amount)}` : ''}
          {v.status ? ` · ${v.status}` : ''}
        </div>
      ));
    }
    return msg;
  };

  const planSteps = (task: AgentTask) =>
    task.plan?.steps?.length ? (
      <ul className="steps">
        {task.plan.steps.map(s => (
          <li key={s.step_id}>
            <Icon name="i-check" />
            {s.purpose}
          </li>
        ))}
      </ul>
    ) : null;

  async function handleTurn(turn: AgentTurnResponse) {
    const bundle = turn.bundle;
    setReplyTarget(null);
    remember('assistant', turn.public_message || 'done');
    const active = bundle.items.find(item => item.item_id === bundle.active_item_id) ?? null;
    const rows = (
      <div className="steps">
        {bundle.items.map(item => (
          <div key={item.item_id} className="small">
            <Icon name={item.status === 'COMPLETED' ? 'i-check' : 'i-clock'} />
            {item.evidence} · {item.status}
          </div>
        ))}
      </div>
    );
    const results = bundle.items
      .filter(item => item.status === 'COMPLETED' && item.intent !== 'GENERAL_CHAT')
      .map(item => (
        <div key={`result-${item.item_id}`}>
          {renderResult({
            id: item.task_id || item.item_id,
            status: item.status,
            public_message: null,
            plan: item.plan,
            result: item.result,
            error_code: item.error_code,
          })}
        </div>
      ));
    if (active?.clarification) {
      push({
        role: 'bot',
        body: (
          <>
            {turn.public_message}
            {rows}
            {results}
            {active.clarification.fields.length ? (
              <ClarifyForm
                fields={active.clarification.fields}
                onSubmit={(fields, display) => send(display, {
                  item_id: active.item_id,
                  intent: active.intent,
                  fields,
                }, bundle.bundle_id)}
              />
            ) : (
              <button className="btn" onClick={() => setReplyTarget({ bundleId: bundle.bundle_id, itemId: active.item_id })}>
                {t('aegis.replyToTask')}
              </button>
            )}
          </>
        ),
      });
      return;
    }
    if (active?.status === 'WAITING_APPROVAL' && active.task_id) {
      const task: AgentTask = {
        id: active.task_id,
        status: active.status,
        public_message: turn.public_message,
        plan: active.plan,
        result: active.result,
        error_code: active.error_code,
      };
      push({ role: 'bot', body: <>{turn.public_message}{rows}{results}{planSteps(task)}</> });
      const op = pendingOperation(task);
      if (!op) return;
      const approvalRows: [string, string][] = [[t('shield.action'), task.plan?.goal || op.type]];
      if (op.amount) approvalRows.push([t('shield.amount'), formatMoney(op.amount)]);
      const ref = await authorize({
        operationType: op.type,
        operationId: op.id,
        targetAccountId: op.args.source_account_id as string | undefined,
        amount: op.amount,
        rows: approvalRows,
      });
      if (!ref) {
        push({ role: 'bot', body: t('aegis.declined') });
        return;
      }
      return handleTurn(await api.agentBundleResume(bundle.bundle_id, active.item_id, ref));
    }
    push({ role: 'bot', body: <>{turn.public_message}{rows}{results}</> });
  }

  async function demoReply(q: string) {
    if (/余额|balance/i.test(q)) {
      const accounts = await loadAccounts();
      push({
        role: 'bot',
        body: (
          <>
            {t('aegis.demoBalance')}
            {accounts.map(a => (
              <div key={a.id}>
                {a.name}: <b>{formatMoney(a.balance, a.currency)}</b>
              </div>
            ))}
          </>
        ),
      });
      return;
    }
    const month = q.match(/(\d{1,2})\s*月|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i);
    if (/花|支出|消费|spend|spent/i.test(q)) {
      const names = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
      const m = month ? (month[1] ? Number(month[1]) : names.indexOf(month[2].toLowerCase()) + 1) : new Date().getMonth() + 1;
      const year = 2026;
      const s = await api.get<SpendingSummary>('/analytics/monthly-summary', { year, month: m });
      push({ role: 'bot', body: t('aegis.demoSpend', { amount: formatMoney(s.total), month: monthLabel(year, m, locale) }) });
      return;
    }
    if (/转|send|pay|transfer/i.test(q)) {
      push({ role: 'bot', body: t('aegis.offline') });
      go('pay');
      return;
    }
    push({ role: 'bot', body: t('aegis.offline') });
  }

  async function send(raw: string, confirmation?: unknown, confirmationBundleId?: string): Promise<boolean> {
    const q = raw.trim();
    if (!q || busy) return false;
    setText('');
    if (SENSITIVE.test(q)) {
      push({ role: 'bot', body: t('aegis.sensitive') });
      return false;
    }
    push({ role: 'me', body: q });
    if (INJECTION.test(q)) {
      push({ role: 'bot', body: t('aegis.injection') });
      return false;
    }
    const conversation = session.history.slice(-10);
    remember('user', q);
    setBusy(true);
    try {
      if (agent === 'live') {
        const target = confirmation ? null : replyTarget;
        await handleTurn(await api.agentTurn(
          q,
          session.id,
          conversation,
          confirmationBundleId || target?.bundleId,
          confirmation,
          target?.itemId,
        ));
      }
      else await demoReply(q);
      return true;
    } catch (e) {
      push({ role: 'bot', body: <span style={{ color: 'var(--red)' }}>{t('aegis.failed', { msg: errorText(e) })}</span> });
      return false;
    } finally {
      setBusy(false);
    }
  }

  const recognitionError = (code: string) => {
    if (code === 'not-allowed' || code === 'service-not-allowed') return t('aegis.micDenied');
    if (code === 'audio-capture') return t('aegis.micUnavailable');
    if (code === 'network') return t('aegis.voiceNetwork');
    return t('aegis.noSpeech');
  };

  const startBackendVoice = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      throw new Error('recording unavailable');
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    const chunks: BlobPart[] = [];
    const recorded = new Promise<Blob>(resolve => {
      recorder.ondataavailable = event => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach(track => track.stop());
        resolve(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }));
      };
    });
    recorder.start();
    backendStop.current = () => {
      if (recorder.state !== 'inactive') recorder.stop();
      return recorded;
    };
    setListening(true);
  };

  const startVoiceCapture = async (captureLang = voiceLang) => {
    const id = ++captureId.current;
    const previous = recRef.current;
    recRef.current = null;
    previous?.stop();
    stopMic.current();
    stopMic.current = () => undefined;
    heard.current = '';
    recognitionFailed.current = false;
    setVoiceText('');
    setVoiceError('');
    setListening(true);

    const mic = await startMicLevel(level);
    if (id !== captureId.current) {
      mic.stop();
      return;
    }
    if (mic.error) {
      setListening(false);
      setVoiceError(t(mic.error === 'denied' ? 'aegis.micDenied' : 'aegis.micUnavailable'));
      return;
    }
    stopMic.current = mic.stop;

    const w = window as unknown as Record<string, unknown>;
    const Rec = (w.SpeechRecognition || w.webkitSpeechRecognition) as (new () => SpeechRec) | undefined;
    if (!Rec) {
      if (import.meta.env.VITE_MULTIMEDIA_BACKEND === 'true' && api.agent === 'live') {
        try {
          await startBackendVoice();
          return;
        } catch {
          stopMic.current();
          stopMic.current = () => undefined;
          setListening(false);
          setVoiceError(t('aegis.micUnavailable'));
          return;
        }
      }
      stopMic.current();
      stopMic.current = () => undefined;
      setListening(false);
      setVoiceError(t('aegis.noVoice'));
      return;
    }
    const rec = new Rec();
    rec.lang = captureLang;
    rec.interimResults = true;
    rec.onresult = e => {
      if (id !== captureId.current) return;
      heard.current = Array.from(e.results).map(r => r[0].transcript).join('');
      setVoiceText(heard.current);
      if (level.current < 0.25) level.current = 0.35;
    };
    rec.onerror = e => {
      if (id !== captureId.current || e.error === 'aborted') return;
      recognitionFailed.current = true;
      stopMic.current();
      stopMic.current = () => undefined;
      setListening(false);
      setVoiceError(recognitionError(e.error));
    };
    rec.onend = () => {
      if (id !== captureId.current) return;
      setListening(false);
      if (heard.current.trim()) void closeVoice(true);
      else if (!recognitionFailed.current) {
        stopMic.current();
        stopMic.current = () => undefined;
        setVoiceError(t('aegis.noSpeech'));
      }
    };
    recRef.current = rec;
    try {
      rec.start();
    } catch {
      recognitionFailed.current = true;
      stopMic.current();
      stopMic.current = () => undefined;
      setListening(false);
      setVoiceError(t('aegis.micUnavailable'));
    }
  };

  // Voice mode: full-screen orb that reacts to the mic; what you say is sent when you stop.
  const closeVoice = async (sendIt: boolean) => {
    captureId.current += 1;
    const rec = recRef.current;
    recRef.current = null;
    rec?.stop();
    stopMic.current();
    stopMic.current = () => undefined;
    const stopBackend = backendStop.current;
    backendStop.current = null;
    setListening(false);
    setVoiceOpen(false);
    setVoiceError('');
    let said = heard.current.trim();
    if (stopBackend) {
      if (sendIt) {
        try {
          const blob = await stopBackend();
          if (!blob.size) throw new Error('empty recording');
          const result = await api.transcribeAudio(blob);
          said = result.text.trim();
          heard.current = said;
          setVoiceText(said);
        } catch {
          setVoiceError(t('aegis.voiceNetwork'));
          push({ role: 'bot', body: t('aegis.voiceNetwork') });
          return;
        }
      } else {
        void stopBackend();
      }
    }
    heard.current = '';
    setVoiceText('');
    if (sendIt && said) void send(said);
    else if (sendIt) push({ role: 'bot', body: t('aegis.noSpeech') });
  };
  const toggleVoice = async () => {
    if (voiceOpen) return void closeVoice(true);
    const w = window as unknown as Record<string, unknown>;
    const Rec = (w.SpeechRecognition || w.webkitSpeechRecognition) as (new () => SpeechRec) | undefined;
    if (!Rec && import.meta.env.VITE_MULTIMEDIA_BACKEND !== 'true') {
      push({ role: 'bot', body: t('aegis.noVoice') });
      return;
    }
    if (!Rec && api.agent !== 'live') {
      push({ role: 'bot', body: t('aegis.noVoice') });
      return;
    }
    haptic(10);
    heard.current = '';
    setVoiceText('');
    setVoiceError('');
    setVoiceOpen(true);
    await startVoiceCapture();
  };

  const suggestions = [t('aegis.s1'), t('aegis.s2'), t('aegis.s3'), t('aegis.s4'), t('aegis.s5')];

  return (
    <>
      <div className="chat-head">
        <button className="orb-btn" onClick={toggleVoice} aria-label={t('aegis.tapToTalk')}>
          <VoiceOrb size={150} active={false} />
        </button>
        <h1>{t('aegis.title')}</h1>
        <p>{t('aegis.sub')}</p>
        {(agent !== 'live' || core !== 'live') && agent !== 'checking' && <p className="small" style={{ color: 'var(--yellow)' }}>{t('conn.agentOffline')}</p>}
      </div>

      {messages.length === 0 && (
        <div className="suggest">
          {suggestions.map(s => (
            <button key={s} onClick={() => send(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="msgs" aria-live="polite">
        {messages.map(m => (
          <div key={m.id} className={'msg ' + m.role}>
            {m.body}
          </div>
        ))}
        {busy && (
          <div className="msg bot typing" aria-label={t('common.loading')}>
            <i />
            <i />
            <i />
          </div>
        )}
        <div ref={endRef} />
      </div>

      {replyTarget && (
        <div className="small" style={{ padding: '0 1rem' }}>
          {t('aegis.replyToTask')}
          <button type="button" className="btn" onClick={() => setReplyTarget(null)}>{t('aegis.cancelReply')}</button>
        </div>
      )}
      <form
        className="composer"
        onSubmit={e => {
          e.preventDefault();
          send(text);
        }}
      >
        <button type="button" className={'icon-btn' + (voiceOpen ? ' on' : '')} onClick={toggleVoice} aria-label={t('aegis.tapToTalk')}>
          <Icon name="i-mic" />
        </button>
        <button type="button" className="voice-lang" onClick={switchVoiceLang} aria-label={t('aegis.voiceLang')} title={t('aegis.voiceLang')}>
          {voiceLang === 'zh-CN' ? '中' : 'EN'}
        </button>
        <input value={text} onChange={e => setText(e.target.value)} placeholder={t('aegis.placeholder')} aria-label={t('aegis.placeholder')} maxLength={2000} enterKeyHint="send" lang={lang === 'zh' ? 'zh-CN' : 'en'} />
        <button type="submit" className="icon-btn brand" disabled={busy || !text.trim()} aria-label={t('aegis.placeholder')}>
          <Icon name="i-send" />
        </button>
      </form>
      {voiceOpen && (
        <div className="voice-mode" role="dialog" aria-modal="true" aria-label={t('aegis.listen')}>
          <button className="icon-btn glass vm-close" onClick={() => void closeVoice(false)} aria-label={t('common.close')}>
            <Icon name="i-x" />
          </button>
          <button className="vm-lang" onClick={switchVoiceLang}>{voiceLang === 'zh-CN' ? '中文' : 'English'}</button>
          <button
            className="vm-orb"
            onClick={() => (listening || voiceText.trim() ? void closeVoice(true) : void startVoiceCapture())}
            aria-label={t(listening || voiceText.trim() ? 'aegis.tapToSend' : 'aegis.retryVoice')}
          >
            <VoiceOrb size={280} level={level} active />
          </button>
          <p className={'vm-status' + (voiceError ? ' error' : '')} role={voiceError ? 'alert' : undefined}>
            {voiceError || (listening ? t('aegis.listen') : t('aegis.paused'))}
          </p>
          <p className="vm-text">{voiceText || (voiceError ? t('aegis.voiceRecover') : t('aegis.voiceHint'))}</p>
          <button className="btn vm-send" onClick={() => (voiceText.trim() ? void closeVoice(true) : void startVoiceCapture())} disabled={listening && !voiceText.trim()}>
            <Icon name={voiceText.trim() ? 'i-send' : 'i-mic'} />
            {t(voiceText.trim() ? 'aegis.tapToSend' : 'aegis.retryVoice')}
          </button>
        </div>
      )}
    </>
  );
}

interface SpeechRec {
  lang: string;
  interimResults: boolean;
  onresult: (e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void;
  onend: () => void;
  onerror: (e: { error: string }) => void;
  start: () => void;
  stop: () => void;
}

function ClarifyForm({ fields, onSubmit }: { fields: ClarificationField[]; onSubmit: (values: Record<string, string>, display: string) => Promise<boolean> }) {
  const { t } = useApp();
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map(f => [f.name, f.value == null ? '' : f.input_type === 'month' ? String(f.value).slice(0, 7) : String(f.value)])),
  );
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [optionsByField, setOptions] = useState<Record<string, { value: string; label: string }[]>>({});

  // The agent sometimes asks for an account without listing options; offer the user's accounts.
  useEffect(() => {
    fields
      .filter(f => /account_id$/.test(f.name) && f.name !== 'destination_account_id' && !f.options.length)
      .forEach(f =>
        loadAccounts().then(accounts =>
          setOptions(o => ({ ...o, [f.name]: accounts.map(a => ({ value: a.id, label: `${a.name} · •••• ${a.account_number.slice(-4)}` })) })),
        ),
      );
  }, [fields]);

  const submit = async () => {
    if (done || submitting) return;
    if (fields.some(f => f.required && !values[f.name]?.trim())) return;
    const out = { ...values };
    for (const f of fields) if (f.input_type === 'month' && /^\d{4}-\d{2}$/.test(out[f.name] ?? '')) out[f.name] += '-01';
    // The chat bubble shows what the user picked, not raw IDs; the agent gets the structured fields.
    const display = fields
      .filter(f => values[f.name])
      .map(f => {
        const options = f.options.length ? f.options : optionsByField[f.name] ?? [];
        return `${f.label}: ${options.find(o => o.value === values[f.name])?.label ?? values[f.name]}`;
      })
      .join(' · ');
    setSubmitting(true);
    try {
      if (await onSubmit(out, display || t('aegis.confirm'))) setDone(true);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="form">
      {fields.map(f => {
        const options = f.options.length ? f.options : optionsByField[f.name] ?? [];
        const id = 'cf-' + f.name;
        const set = (v: string) => setValues(x => ({ ...x, [f.name]: v }));
        return (
          <div key={f.name}>
            <label className="f" htmlFor={id}>
              {f.label}
              {f.inferred ? ' · AI' : ''}
            </label>
            {options.length ? (
              <select id={id} className="input" value={values[f.name]} onChange={e => set(e.target.value)} disabled={done}>
                <option value="">{t('aegis.chooseAccount')}</option>
                {options.map(o => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={id}
                className="input"
                disabled={done}
                value={values[f.name]}
                onChange={e => set(e.target.value)}
                type={f.input_type === 'date' ? 'date' : f.input_type === 'month' ? 'month' : 'text'}
                inputMode={f.input_type === 'amount' ? 'decimal' : undefined}
              />
            )}
          </div>
        );
      })}
      {!done && (
        <button className="btn primary" onClick={submit} disabled={submitting}>
          {t('aegis.confirm')}
        </button>
      )}
    </div>
  );
}
