import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react';
import { api, ApiError } from '../core/api';
import { hasKey, localeOf, translate, type Key, type Lang } from '../core/i18n';

type Theme = 'system' | 'light' | 'dark';

interface AppState {
  lang: Lang;
  locale: string;
  setLang: (lang: Lang) => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  t: (key: Key, vars?: Record<string, string | number>) => string;
  errorText: (e: unknown) => string;
  version: number;
  refresh: () => void;
  toast: (text: string) => void;
}

const Ctx = createContext<AppState | null>(null);

// Preferences are per-device conveniences only; banking data and authorization refs are never stored.
function readPref<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}
function writePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() =>
    readPref<Lang>('aegis.lang', navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en'),
  );
  const [theme, setThemeState] = useState<Theme>(() => readPref<Theme>('aegis.theme', 'system'));
  const [version, setVersion] = useState(0);
  const [toastText, setToastText] = useState('');

  useEffect(() => {
    api.lang = localeOf(lang) as 'zh-CN' | 'en-US';
    document.documentElement.lang = localeOf(lang);
  }, [lang]);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    if (!toastText) return;
    const timer = setTimeout(() => setToastText(''), 3200);
    return () => clearTimeout(timer);
  }, [toastText]);

  const t = useCallback((key: Key, vars?: Record<string, string | number>) => translate(lang, key, vars), [lang]);

  const errorText = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError) {
        if (e.code === 'NETWORK' || e.code === 'AGENT_UNAVAILABLE') return t('common.network');
        const key = `err.${e.code}`;
        if (hasKey(key)) return t(key);
        return e.message || t('common.error');
      }
      return t('common.error');
    },
    [t],
  );

  const value = useMemo<AppState>(
    () => ({
      lang,
      locale: localeOf(lang),
      setLang: l => {
        writePref('aegis.lang', l);
        api.lang = localeOf(l) as 'zh-CN' | 'en-US';
        setLangState(l);
        setVersion(v => v + 1); // reload data so names come back in the new language
      },
      theme,
      setTheme: th => {
        writePref('aegis.theme', th);
        setThemeState(th);
      },
      t,
      errorText,
      version,
      refresh: () => setVersion(v => v + 1),
      toast: setToastText,
    }),
    [lang, theme, t, errorText, version],
  );

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className={'toast' + (toastText ? ' show' : '')} role="status" aria-live="polite">
        {toastText}
      </div>
    </Ctx.Provider>
  );
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('AppProvider missing');
  return ctx;
}

/** Re-renders when connection mode or the API log changes. */
export function useClient() {
  const snapshot = useSyncExternalStore(
    fn => api.subscribe(fn),
    () => `${api.core}|${api.agent}|${api.log.length}|${api.log[0]?.traceId ?? ''}`,
  );
  return { core: api.core, agent: api.agent, log: api.log, snapshot };
}

export interface Loaded<T> {
  data?: T;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** Fetches on mount, when deps change, and on every global refresh(). */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []): Loaded<T> {
  const { version } = useApp();
  const { core } = useClient();
  const [state, setState] = useState<{ data?: T; error: unknown; loading: boolean }>({ error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (core === 'checking') return;
    let alive = true;
    setState(s => ({ ...s, loading: true }));
    fn().then(
      data => alive && setState({ data, error: null, loading: false }),
      error => alive && setState(s => ({ data: s.data, error, loading: false })),
    );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, tick, core, ...deps]);
  return { ...state, reload: () => setTick(x => x + 1) };
}

export function useHashRoute(): string[] {
  const read = () => (window.location.hash.replace(/^#\/?/, '') || 'home').split('/');
  const [parts, setParts] = useState(read);
  useEffect(() => {
    const on = () => setParts(read());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return parts;
}

export function go(path: string) {
  window.location.hash = '#/' + path.replace(/^\/+/, '');
}
