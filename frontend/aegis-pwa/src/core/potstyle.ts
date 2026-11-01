// Per-device pot look (icon + flat colour) and saving-plan type. Banking Core stores the money,
// not the look, so this lives in localStorage as a convenience with a guess from the name.
import { hashIndex } from './format';
import { fromCents, toCents } from './money';

export const POT_THEMES = [
  { id: 'purple', bg: '#5b4cf5', fg: '#ffffff' },
  { id: 'black', bg: '#121215', fg: '#ffffff' },
  { id: 'white', bg: '#ffffff', fg: '#111114' },
  { id: 'lilac', bg: '#e9e6fe', fg: '#2d2780' },
  { id: 'deep', bg: '#2d2780', fg: '#ffffff' },
  { id: 'grey', bg: '#e7e7ec', fg: '#111114' },
] as const;
export type PotTheme = (typeof POT_THEMES)[number]['id'];

export const POT_ICONS = ['p-plane', 'i-phone', 'p-lifebuoy', 'i-home', 'p-cap', 'p-gift', 'p-car', 'p-ring', 'p-heart', 'p-game', 'p-sun', 'p-coins'];

export const POT_TEMPLATES = [
  { key: 'travel', icon: 'p-plane', theme: 'purple', target: '8000' },
  { key: 'emergency', icon: 'p-lifebuoy', theme: 'black', target: '20000' },
  { key: 'phone', icon: 'i-phone', theme: 'lilac', target: '6000' },
  { key: 'home', icon: 'i-home', theme: 'deep', target: '50000' },
  { key: 'study', icon: 'p-cap', theme: 'white', target: '15000' },
  { key: 'gift', icon: 'p-gift', theme: 'grey', target: '1000' },
] as const;

/** Saving plans from classic bookkeeping apps. Week/day challenges raise the deposit each time. */
export type PlanType = 'fixed' | 'flexible' | 'week52' | 'day365';
export const PLAN_TYPES: PlanType[] = ['fixed', 'flexible', 'week52', 'day365'];

/** Target for a challenge: the n-th deposit is start + (n-1) × step, over 52 weeks or 365 days. */
export function challengeTarget(type: PlanType, start: string, step: string): string | null {
  const n = type === 'week52' ? 52n : type === 'day365' ? 365n : 0n;
  if (!n) return null;
  const s = toCents(start);
  const d = toCents(step);
  return fromCents(n * s + ((n * (n - 1n)) / 2n) * d);
}

/** Deposit due for the current period of a challenge, counted from the pot's start. */
export function challengeDue(type: PlanType, start: string, step: string, createdAt: string, now = new Date()): { n: number; amount: string } | null {
  if (type !== 'week52' && type !== 'day365') return null;
  const days = Math.max(0, Math.floor((now.getTime() - Date.parse(createdAt)) / 86_400_000));
  const n = Math.min(type === 'week52' ? 52 : 365, (type === 'week52' ? Math.floor(days / 7) : days) + 1);
  return { n, amount: fromCents(toCents(start) + BigInt(n - 1) * toCents(step)) };
}

const GUESS: [RegExp, string][] = [
  [/trip|travel|旅|japan|日本|holiday|vacation/i, 'p-plane'],
  [/phone|手机|iphone|laptop|电脑/i, 'i-phone'],
  [/emergency|应急|rainy|safety/i, 'p-lifebuoy'],
  [/home|house|房|rent|apartment/i, 'i-home'],
  [/study|school|学|course|tuition/i, 'p-cap'],
  [/gift|礼|birthday|生日/i, 'p-gift'],
  [/car|车/i, 'p-car'],
  [/wedding|婚/i, 'p-ring'],
];

export interface PotLook {
  icon: string;
  theme: PotTheme;
  plan?: { type: PlanType; start: string; step: string };
}

export function potLook(id: string, name: string): PotLook {
  try {
    const raw = localStorage.getItem('aegis.pot.' + id);
    if (raw) {
      const saved = JSON.parse(raw) as PotLook & { emoji?: string };
      if (saved.icon && POT_THEMES.some(x => x.id === saved.theme)) return saved;
    }
  } catch {
    /* storage unavailable */
  }
  const icon = GUESS.find(([re]) => re.test(name))?.[1] ?? 'p-coins';
  return { icon, theme: POT_THEMES[hashIndex(id, POT_THEMES.length)].id };
}

export function savePotLook(id: string, look: PotLook) {
  try {
    localStorage.setItem('aegis.pot.' + id, JSON.stringify(look));
  } catch {
    /* storage unavailable */
  }
}

const theme = (id: string) => POT_THEMES.find(x => x.id === id) ?? POT_THEMES[0];
export const themeBg = (id: string) => theme(id).bg;
export const themeFg = (id: string) => theme(id).fg;

/** Milestones already celebrated for a pot, so each one fires once per device. */
export function celebrated(id: string): number[] {
  try {
    return JSON.parse(localStorage.getItem('aegis.potmilestones.' + id) || '[]');
  } catch {
    return [];
  }
}
export function markCelebrated(id: string, milestone: number) {
  try {
    localStorage.setItem('aegis.potmilestones.' + id, JSON.stringify([...new Set([...celebrated(id), milestone])]));
  } catch {
    /* storage unavailable */
  }
}
