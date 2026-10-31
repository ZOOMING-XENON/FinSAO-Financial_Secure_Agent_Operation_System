// The signed-in demo persona and the phone-contacts list shown in the People grid.
// Contacts carry the account numbers seeded in Banking Core, so saving one as a
// recipient still goes through the backend's exact-match lookup.
import type { Lang } from './i18n';

export const PROFILE = { name: 'Jackie Chen', nameZh: '陈嘉琪', key: 'jackie' };

export interface Contact {
  key: string;
  zh: string;
  en: string;
  accountNumber: string;
}

export const CONTACTS: Contact[] = [
  { key: 'dad', zh: '爸爸', en: 'Dad', accountNumber: '299000000001' },
  { key: 'mom', zh: '妈妈', en: 'Mom', accountNumber: '390000000002' },
  { key: 'grandpa-w', zh: '爷爷', en: 'Grandpa Wang', accountNumber: '299000000003' },
  { key: 'grandma-w', zh: '奶奶', en: 'Grandma Wang', accountNumber: '390000000004' },
  { key: 'grandpa-l', zh: '外公', en: 'Grandpa Li', accountNumber: '299000000005' },
  { key: 'grandma-l', zh: '外婆', en: 'Grandma Li', accountNumber: '390000000006' },
  { key: 'brother', zh: '哥哥', en: 'Brother', accountNumber: '299000000007' },
  { key: 'sister', zh: '姐姐', en: 'Sister', accountNumber: '390000000008' },
  { key: 'xiaowang', zh: '好友小王', en: 'Xiao Wang', accountNumber: '299000000009' },
  { key: 'xiaoli', zh: '好友小李', en: 'Xiao Li', accountNumber: '390000000010' },
  { key: 'friend', zh: 'Demo Friend', en: 'Demo Friend', accountNumber: 'DEMO0201000001' },
];

/**
 * Real photos: put a square image in public/avatars/ and list it here by contact key,
 * e.g. dad: 'dad.jpg'. Anyone without a photo gets an illustrated avatar.
 */
export const PHOTOS: Record<string, string> = {};

export function contactName(c: Contact, lang: Lang): string {
  return lang === 'zh' ? c.zh : c.en;
}

export function contactForAccount(accountNumber: string): Contact | undefined {
  return CONTACTS.find(c => c.accountNumber === accountNumber);
}

/** Illustration traits per contact so family members look like themselves. */
export const LOOKS: Record<string, { age: 'kid' | 'adult' | 'senior'; hair: 'short' | 'long' | 'bun' | 'bald' }> = {
  jackie: { age: 'adult', hair: 'long' },
  dad: { age: 'adult', hair: 'short' },
  mom: { age: 'adult', hair: 'long' },
  'grandpa-w': { age: 'senior', hair: 'bald' },
  'grandma-w': { age: 'senior', hair: 'bun' },
  'grandpa-l': { age: 'senior', hair: 'short' },
  'grandma-l': { age: 'senior', hair: 'bun' },
  brother: { age: 'adult', hair: 'short' },
  sister: { age: 'adult', hair: 'long' },
  xiaowang: { age: 'adult', hair: 'short' },
  xiaoli: { age: 'adult', hair: 'long' },
  friend: { age: 'adult', hair: 'short' },
};
