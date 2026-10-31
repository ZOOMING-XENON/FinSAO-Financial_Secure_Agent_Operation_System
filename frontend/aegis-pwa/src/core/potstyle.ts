// Per-device pot look (emoji + colour theme). Banking Core stores the money, not the look,
// so this lives in localStorage as a convenience and falls back to a guess from the name.
import { hashIndex } from './format';

export const POT_THEMES = [
  { id: 'violet', bg: 'linear-gradient(140deg, #5b3df5 0%, #a14dff 60%, #ff5fa2 100%)', ring: '#ffffff' },
  { id: 'ocean', bg: 'linear-gradient(140deg, #0b8f84 0%, #13a89a 45%, #3d8bff 100%)', ring: '#ffffff' },
  { id: 'sunset', bg: 'linear-gradient(140deg, #ff7a1a 0%, #ff9f1c 40%, #ff5fa2 100%)', ring: '#ffffff' },
  { id: 'berry', bg: 'linear-gradient(140deg, #c2185b 0%, #ff5fa2 55%, #ffb347 100%)', ring: '#ffffff' },
  { id: 'sky', bg: 'linear-gradient(140deg, #1f63d6 0%, #3d8bff 50%, #2ec4b6 100%)', ring: '#ffffff' },
  { id: 'forest', bg: 'linear-gradient(140deg, #0f6b4f 0%, #1baf7a 55%, #c3e66e 100%)', ring: '#ffffff' },
] as const;

export const POT_EMOJI = ['✈️', '📱', '🛟', '🏠', '🎓', '🎁', '🚗', '💍', '🐶', '🎮', '🌴', '💰'];

export const POT_TEMPLATES = [
  { key: 'travel', emoji: '✈️', theme: 'ocean', target: '8000' },
  { key: 'emergency', emoji: '🛟', theme: 'forest', target: '20000' },
  { key: 'phone', emoji: '📱', theme: 'violet', target: '6000' },
  { key: 'home', emoji: '🏠', theme: 'sky', target: '50000' },
  { key: 'study', emoji: '🎓', theme: 'sunset', target: '15000' },
  { key: 'gift', emoji: '🎁', theme: 'berry', target: '1000' },
] as const;

const GUESS: [RegExp, string][] = [
  [/trip|travel|旅|japan|日本|holiday|vacation/i, '✈️'],
  [/phone|手机|iphone|laptop|电脑/i, '📱'],
  [/emergency|应急|rainy|safety/i, '🛟'],
  [/home|house|房|rent|apartment/i, '🏠'],
  [/study|school|学|course|tuition/i, '🎓'],
  [/gift|礼|birthday|生日/i, '🎁'],
  [/car|车/i, '🚗'],
  [/wedding|婚/i, '💍'],
];

export interface PotLook {
  emoji: string;
  theme: (typeof POT_THEMES)[number]['id'];
}

export function potLook(id: string, name: string): PotLook {
  try {
    const raw = localStorage.getItem('aegis.pot.' + id);
    if (raw) return JSON.parse(raw) as PotLook;
  } catch {
    /* storage unavailable */
  }
  const emoji = GUESS.find(([re]) => re.test(name))?.[1] ?? '💰';
  return { emoji, theme: POT_THEMES[hashIndex(id, POT_THEMES.length)].id };
}

export function savePotLook(id: string, look: PotLook) {
  try {
    localStorage.setItem('aegis.pot.' + id, JSON.stringify(look));
  } catch {
    /* storage unavailable */
  }
}

export const themeBg = (theme: string) => (POT_THEMES.find(x => x.id === theme) ?? POT_THEMES[0]).bg;

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
