// Banking Core + Agent client. Framework-free so a React Native port can reuse it.
// Rules: X-Trace-Id on every call, money as decimal strings, authorization refs never logged or stored.
import { localizeDemo, mockCore, MOCK_MFA_CODE } from './mock';
import type { AgentTask, ConversationMessage } from './types';

export class ApiError extends Error {
  constructor(public status: number, public code: string, message?: string) {
    super(message || code);
  }
}

export type Mode = 'checking' | 'live' | 'demo';
export interface LogEntry {
  at: string;
  method: string;
  path: string;
  status: number;
  traceId: string;
  request: unknown;
  response: unknown;
}

interface RequestOptions {
  query?: Record<string, string | number | undefined | null>;
  body?: unknown;
  headers?: Record<string, string>;
}

// Native builds have no same-origin proxy; VITE_API_BASE points at a credential-adding gateway.
const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
const SECRET_KEYS = new Set(['authorization_ref', 'authorization_reference', 'code']);

export const uid = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx'.replace(/x/g, () => ((Math.random() * 16) | 0).toString(16));

export function scrub(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(scrub);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, SECRET_KEYS.has(k) ? '••••••' : scrub(v)]),
    );
  }
  return value;
}

type Listener = () => void;

class Client {
  core: Mode = 'checking';
  agent: Mode = 'checking';
  lang: 'zh-CN' | 'en-US' = 'zh-CN';
  log: LogEntry[] = [];
  private listeners = new Set<Listener>();

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
  private emit() {
    this.listeners.forEach(fn => fn());
  }

  async detect(): Promise<void> {
    const probe = async (path: string) => {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 2500);
      try {
        return (await fetch(BASE + path, { signal: ctrl.signal })).ok;
      } catch {
        return false;
      } finally {
        clearTimeout(timer);
      }
    };
    const [coreOk, agentOk] = await Promise.all([probe('/api/core/health'), probe('/api/agent/openapi.json')]);
    this.core = coreOk ? 'live' : 'demo';
    this.agent = agentOk ? 'live' : 'demo';
    this.emit();
  }

  get mfaHint(): string | null {
    return this.core === 'demo' ? MOCK_MFA_CODE : null;
  }

  private record(entry: LogEntry) {
    this.log = [entry, ...this.log].slice(0, 60);
    this.emit();
  }

  async request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
    const traceId = uid();
    const query = opts.query
      ? Object.entries(opts.query).filter(([, v]) => v !== undefined && v !== null && v !== '')
      : [];
    const qs = query.length ? '?' + new URLSearchParams(query.map(([k, v]) => [k, String(v)])).toString() : '';
    const headers: Record<string, string> = {
      Accept: 'application/json',
      'Accept-Language': this.lang,
      'X-Trace-Id': traceId,
      ...(opts.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(opts.headers ?? {}),
    };
    let status: number;
    let data: unknown;
    if (this.core !== 'live') {
      await new Promise(r => setTimeout(r, 120));
      [status, data] = mockCore(method, path, Object.fromEntries(query.map(([k, v]) => [k, String(v)])), opts.body, headers);
      // Copy like a real network response would, so screens never share objects with the demo store.
      data = data === null || data === undefined ? data : localizeDemo(JSON.parse(JSON.stringify(data)), this.lang);
    } else {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 15000);
      try {
        const res = await fetch(`${BASE}/api/core${path}${qs}`, {
          method,
          headers,
          body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
          signal: ctrl.signal,
        });
        status = res.status;
        data = status === 204 ? null : await res.json().catch(() => null);
      } catch {
        this.record({ at: new Date().toISOString(), method, path: path + qs, status: 0, traceId, request: scrub(opts.body), response: null });
        throw new ApiError(0, 'NETWORK');
      } finally {
        clearTimeout(timer);
      }
    }
    this.record({ at: new Date().toISOString(), method, path: path + qs, status, traceId, request: scrub(opts.body), response: scrub(data) });
    if (status >= 400) {
      const d = data as { code?: string; message?: string; detail?: { code?: string; message?: string } } | null;
      throw new ApiError(status, d?.code || d?.detail?.code || 'ERROR', d?.message || d?.detail?.message);
    }
    return data as T;
  }

  get<T>(path: string, query?: RequestOptions['query']) {
    return this.request<T>('GET', path, { query });
  }
  post<T>(path: string, body?: unknown, headers?: Record<string, string>) {
    return this.request<T>('POST', path, { body: body ?? {}, headers });
  }
  patch<T>(path: string, body: unknown) {
    return this.request<T>('PATCH', path, { body });
  }
  del<T>(path: string) {
    return this.request<T>('DELETE', path);
  }

  async agentTask(message: string, sessionId: string, conversation: ConversationMessage[], confirmation?: unknown): Promise<AgentTask> {
    return this.agentPost<AgentTask>('/agent/tasks', {
      schema_version: 'v1',
      session_id: sessionId,
      message,
      conversation,
      locale: this.lang,
      ...(confirmation ? { confirmation } : {}),
    });
  }

  async agentResume(taskId: string, authorizationRef: string): Promise<AgentTask> {
    return this.agentPost<AgentTask>(`/agent/tasks/${taskId}/resume`, { authorization_reference: authorizationRef });
  }

  private async agentPost<T>(path: string, body: unknown): Promise<T> {
    const traceId = uid();
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 45000);
    let status = 0;
    let data: unknown = null;
    try {
      const res = await fetch(`${BASE}/api${path}`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Accept-Language': this.lang, 'X-Trace-Id': traceId },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
      status = res.status;
      data = await res.json().catch(() => null);
    } catch {
      throw new ApiError(0, 'AGENT_UNAVAILABLE');
    } finally {
      clearTimeout(timer);
      this.record({ at: new Date().toISOString(), method: 'POST', path: '/api' + path, status, traceId, request: scrub(body), response: scrub(data) });
    }
    if (status >= 400) {
      const d = data as { code?: string; message?: string; detail?: { code?: string; message?: string } } | null;
      throw new ApiError(status, d?.detail?.code || d?.code || 'AGENT_ERROR', d?.detail?.message || d?.message);
    }
    return data as T;
  }
}

export const api = new Client();
