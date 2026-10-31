// Contact avatars drawn in code: a photo when one is listed, otherwise a flat illustrated portrait.
import { useState } from 'react';
import { hashIndex } from '../core/format';
import { LOOKS, PHOTOS } from '../core/people';

const BG = ['#ffd7c2', '#ffe6a8', '#cdebd9', '#ffc9d6', '#d9e4ff', '#f6d3b3'];
const SHIRT = ['#ff7a59', '#2f8f7a', '#7a5cfa', '#e8508f', '#f2a93b', '#3b82c4'];
const SKIN = ['#f6cba3', '#edb98a', '#d9a06f', '#f3d2b3'];
const HAIR = ['#2b1a12', '#4a2c1d', '#1f1a17'];

/** A contact's photo if one is listed in PHOTOS, otherwise a flat illustrated portrait. */
export function PersonAvatar({ id, label, size = 56 }: { id: string; label: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  const photo = PHOTOS[id];
  if (photo && !broken) {
    return (
      <img
        className="person"
        src={`${import.meta.env.BASE_URL}avatars/${photo}`}
        alt={label}
        width={size}
        height={size}
        style={{ width: size, height: size }}
        onError={() => setBroken(true)}
      />
    );
  }
  const look = LOOKS[id] ?? { age: 'adult', hair: hashIndex(id, 2) ? 'short' : 'long' };
  const h = (n: number) => hashIndex(id + n, 97);
  const bg = BG[h(1) % BG.length];
  const shirt = SHIRT[h(2) % SHIRT.length];
  const skin = SKIN[h(3) % SKIN.length];
  const hair = look.age === 'senior' ? '#d6cfc8' : HAIR[h(4) % HAIR.length];
  return (
    <svg className="person" viewBox="0 0 64 64" width={size} height={size} style={{ width: size, height: size }} role="img" aria-label={label}>
      <circle cx="32" cy="32" r="32" fill={bg} />
      {look.hair === 'long' && <path d="M17 30c0-11 7-18 15-18s15 7 15 18v16H17z" fill={hair} />}
      <path d="M10 64c2-12 11-18 22-18s20 6 22 18z" fill={shirt} />
      <rect x="27.5" y="38" width="9" height="10" rx="4" fill={skin} />
      <circle cx="32" cy="30" r="12" fill={skin} />
      {look.hair === 'short' && <path d="M20 29c0-9 5-14 12-14s12 5 12 13c-3-4-8-6-12-6s-9 2-12 7z" fill={hair} />}
      {look.hair === 'long' && <path d="M20 29c1-8 6-13 12-13s11 5 12 13c-4-5-8-7-12-7s-8 2-12 7z" fill={hair} />}
      {look.hair === 'bun' && (
        <>
          <circle cx="32" cy="15" r="5" fill={hair} />
          <path d="M20 29c0-8 5-13 12-13s12 5 12 13c-3-4-8-6-12-6s-9 2-12 6z" fill={hair} />
        </>
      )}
      {look.hair === 'bald' && <path d="M20 31c0-3 1-5 2-6M44 31c0-3-1-5-2-6" stroke={hair} strokeWidth="3" strokeLinecap="round" fill="none" />}
      <circle cx="27.5" cy="31" r="1.5" fill="#2b1a12" />
      <circle cx="36.5" cy="31" r="1.5" fill="#2b1a12" />
      <path d="M28.5 36c2 1.8 5 1.8 7 0" stroke="#2b1a12" strokeWidth="1.6" strokeLinecap="round" fill="none" />
      {look.age === 'senior' && (
        <g stroke="#2b1a12" strokeWidth="1.2" fill="none">
          <circle cx="27.5" cy="31" r="3.4" />
          <circle cx="36.5" cy="31" r="3.4" />
          <path d="M30.9 31h2.2" />
        </g>
      )}
      <circle cx="24.5" cy="35" r="1.8" fill="#ff8a7a" opacity=".35" />
      <circle cx="39.5" cy="35" r="1.8" fill="#ff8a7a" opacity=".35" />
    </svg>
  );
}
