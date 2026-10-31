// Flat illustrations drawn in code: contact avatars, the shield mascot and the home header scene.
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

/** Aegis, the friendly shield. Calm = eyes closed, like it is breathing; happy = open smile. */
export function Mascot({ size = 96, mood = 'calm' }: { size?: number; mood?: 'calm' | 'happy' }) {
  return (
    <svg className="mascot" viewBox="0 0 120 120" width={size} height={size} style={{ width: size, height: size }} aria-hidden="true">
      <path className="m-body" d="M60 8 18 23v31c0 27 18 48 42 56 24-8 42-29 42-56V23z" />
      <path className="m-shine" d="M33 30 60 20v8l-27 10z" />
      {mood === 'calm' ? (
        <g className="m-face" fill="none" strokeWidth="5" strokeLinecap="round">
          <path d="M38 56c4 5 11 5 15 0" />
          <path d="M67 56c4 5 11 5 15 0" />
          <path d="M48 74c7 5 17 5 24 0" />
        </g>
      ) : (
        <g className="m-face" strokeWidth="5" strokeLinecap="round">
          <circle cx="46" cy="55" r="4.5" stroke="none" />
          <circle cx="74" cy="55" r="4.5" stroke="none" />
          <path d="M46 70c8 9 20 9 28 0" fill="none" />
        </g>
      )}
      <circle className="m-cheek" cx="38" cy="66" r="5" />
      <circle className="m-cheek" cx="82" cy="66" r="5" />
    </svg>
  );
}

/** Flat header scene: a soft Shenzhen skyline with hills, sun and the mascot. */
export function HeroScene() {
  return (
    <svg className="hero-scene" viewBox="0 0 390 230" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
      <rect className="h-sky" width="390" height="230" />
      <circle className="h-sun" cx="300" cy="62" r="24" />
      <g className="h-cloud">
        <path d="M330 104a10 10 0 0 1 19-3 8 8 0 0 1 14 4h-33z" />
        <path d="M226 34a12 12 0 0 1 23-4 9 9 0 0 1 17 5h-40z" />
      </g>
      <g transform="translate(151 60) scale(.7)">
      <g className="h-city">
        <rect x="70" y="112" width="22" height="70" rx="3" />
        <rect x="98" y="96" width="18" height="86" rx="3" />
        <path d="M128 182V84l9-26 9 26v98z" />
        <rect x="154" y="108" width="26" height="74" rx="3" />
        <rect x="186" y="122" width="16" height="60" rx="3" />
        <path d="M236 182v-64q12-14 24 0v64z" />
        <rect x="268" y="104" width="20" height="78" rx="3" />
        <rect x="294" y="126" width="28" height="56" rx="3" />
      </g>
      <g className="h-windows">
        <rect x="132" y="96" width="10" height="3" rx="1.5" />
        <rect x="132" y="108" width="10" height="3" rx="1.5" />
        <rect x="132" y="120" width="10" height="3" rx="1.5" />
        <rect x="159" y="118" width="16" height="3" rx="1.5" />
        <rect x="159" y="130" width="16" height="3" rx="1.5" />
        <rect x="272" y="116" width="12" height="3" rx="1.5" />
        <rect x="272" y="128" width="12" height="3" rx="1.5" />
      </g>
      </g>
      <path className="h-hill-far" d="M0 176c60-26 120-30 190-14s140 10 200-12v80H0z" />
      <path className="h-hill" d="M0 196c70-30 150-22 210-4 60 17 120 6 180-14v52H0z" />
      <g className="h-tree">
        <rect x="34" y="176" width="3" height="14" rx="1.5" />
        <circle cx="35.5" cy="172" r="9" />
        <rect x="352" y="170" width="3" height="14" rx="1.5" />
        <circle cx="353.5" cy="166" r="10" />
      </g>
      <g transform="translate(170 150) scale(.42)">
        <path className="m-body" d="M60 8 18 23v31c0 27 18 48 42 56 24-8 42-29 42-56V23z" />
        <g className="m-face" fill="none" strokeWidth="6" strokeLinecap="round">
          <path d="M38 56c4 5 11 5 15 0" />
          <path d="M67 56c4 5 11 5 15 0" />
          <path d="M48 74c7 5 17 5 24 0" />
        </g>
      </g>
      <g className="h-bird" fill="none" strokeWidth="2" strokeLinecap="round">
        <path d="M200 70q5-5 10 0q5-5 10 0" />
        <path d="M232 86q4-4 8 0q4-4 8 0" />
      </g>
    </svg>
  );
}
