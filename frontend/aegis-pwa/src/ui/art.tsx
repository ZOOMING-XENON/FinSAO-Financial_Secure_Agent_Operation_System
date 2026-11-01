// Avatars in the app's flat style: a photo when one exists, otherwise initials on a flat circle.
import { useState } from 'react';
import { hashIndex } from '../core/format';
import { PHOTOS } from '../core/people';
import type { AvatarTone, Profile } from '../core/profile';
import { Icon } from './kit';

const TONES: AvatarTone[] = ['brand', 'ink', 'lilac', 'grey'];

/** "Grandpa Wang" → "GW", "爷爷" → "爷", "Jackie" → "J". */
export function initials(label: string): string {
  const s = label.trim();
  if (!s) return '?';
  if (/^[一-鿿]/.test(s)) return s[0];
  const words = s.split(/\s+/).filter(w => /^[A-Za-z0-9]/.test(w));
  return ((words[0]?.[0] ?? s[0]) + (words.length > 1 ? words[words.length - 1][0] : '')).toUpperCase();
}

function Disc({ tone, size, label, children }: { tone: AvatarTone; size: number; label: string; children: React.ReactNode }) {
  return (
    <span className={'person avt ' + tone} role="img" aria-label={label} style={{ width: size, height: size, fontSize: Math.round(size * 0.36) }}>
      {children}
    </span>
  );
}

function Photo({ src, label, size, onError }: { src: string; label: string; size: number; onError?: () => void }) {
  return <img className="person" src={src} alt={label} width={size} height={size} style={{ width: size, height: size }} onError={onError} />;
}

/** A contact: their photo if listed in PHOTOS, otherwise initials. */
export function PersonAvatar({ id, label, size = 56 }: { id: string; label: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  const photo = PHOTOS[id];
  if (photo && !broken) return <Photo src={`${import.meta.env.BASE_URL}avatars/${photo}`} label={label} size={size} onError={() => setBroken(true)} />;
  return (
    <Disc tone={TONES[hashIndex(id, TONES.length)]} size={size} label={label}>
      {initials(label)}
    </Disc>
  );
}

/** The signed-in person, as set on the Profile screen. */
export function ProfileAvatar({ profile, label, size = 56 }: { profile: Profile; label: string; size?: number }) {
  if (profile.photo) return <Photo src={profile.photo} label={label} size={size} />;
  return (
    <Disc tone={profile.tone} size={size} label={label}>
      {profile.icon === 'initials' ? initials(label) : <Icon name={profile.icon} />}
    </Disc>
  );
}
