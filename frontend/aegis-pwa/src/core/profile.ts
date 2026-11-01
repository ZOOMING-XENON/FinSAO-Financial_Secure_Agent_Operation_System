// The signed-in person's profile as shown in the app (name, picture, gender). Banking Core has
// no profile endpoint, so edits are kept on this device; defaults come from the demo persona.
import { useSyncExternalStore } from 'react';
import { PROFILE } from './people';

export type Gender = 'female' | 'male' | 'other' | 'unsaid';
export type AvatarTone = 'brand' | 'ink' | 'lilac' | 'grey';
export type AvatarIcon = 'initials' | 'i-shield' | 'i-spark' | 'i-target' | 'i-wallet' | 'i-globe' | 'i-bolt' | 'i-moon';

export interface Profile {
  name: string;
  nameZh: string;
  gender: Gender;
  birthday: string; // YYYY-MM-DD or ''
  phone: string;
  photo: string | null; // small JPEG data URL, resized on the device
  tone: AvatarTone;
  icon: AvatarIcon;
}

export const DEFAULT_PROFILE: Profile = {
  name: PROFILE.name,
  nameZh: PROFILE.nameZh,
  gender: 'female',
  birthday: '',
  phone: '',
  photo: null,
  tone: 'brand',
  icon: 'initials',
};

const KEY = 'aegis.profile';
const listeners = new Set<() => void>();
let current: Profile = read();

function read(): Profile {
  try {
    return { ...DEFAULT_PROFILE, ...(JSON.parse(localStorage.getItem(KEY) || '{}') as Partial<Profile>) };
  } catch {
    return DEFAULT_PROFILE;
  }
}

export function getProfile(): Profile {
  return current;
}

export function saveProfile(patch: Partial<Profile>) {
  current = { ...current, ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(current));
  } catch {
    /* storage full or unavailable: keep the change for this session */
  }
  listeners.forEach(l => l());
}

export function useProfile(): Profile {
  return useSyncExternalStore(
    l => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
}

/** The name to show for the current language; falls back to the English name. */
export function displayName(p: Profile, lang: 'zh' | 'en'): string {
  return (lang === 'zh' ? p.nameZh : p.name).trim() || p.name.trim() || p.nameZh.trim();
}

/** Shrinks a picked photo to a 256px square JPEG so it fits comfortably in local storage. */
export async function resizePhoto(file: File, size = 256): Promise<string> {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = reject;
      i.src = url;
    });
    const side = Math.min(img.naturalWidth, img.naturalHeight);
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    ctx.drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, size, size);
    return canvas.toDataURL('image/jpeg', 0.85);
  } finally {
    URL.revokeObjectURL(url);
  }
}
