import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { moneyParts } from '../core/money';
import { hashIndex, initials } from '../core/format';

export function Icon({ name, className }: { name: string; className?: string }) {
  return (
    <svg className={className} aria-hidden="true">
      <use href={'#' + name} />
    </svg>
  );
}

/** Big number with smaller decimals: ¥11,572.20 → ¥11,572<small>.20</small>. */
export function Amount({ value, currency = 'CNY', sign, className }: { value: string; currency?: string; sign?: '+' | '-'; className?: string }) {
  const p = moneyParts(value, currency);
  return (
    <span className={'amt' + (className ? ' ' + className : '')}>
      {sign ?? p.sign}
      <span className="cur">{p.symbol}</span>
      {p.whole}
      <span className="dec">.{p.dec}</span>
    </span>
  );
}

const AVATAR_BG = ['#4b5bff', '#e8508f', '#17a673', '#e98a4b', '#7b61ff', '#2f7bf5'];

export function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span className={'avatar' + (className ? ' ' + className : '')} style={{ background: AVATAR_BG[hashIndex(name, AVATAR_BG.length)] }} aria-hidden="true">
      {initials(name)}
    </span>
  );
}

export function Badge({ tone, children }: { tone: string; children: ReactNode }) {
  return <span className={'badge ' + tone}>{children}</span>;
}

export function Sheet({ open, onClose, children, label }: { open: boolean; onClose: () => void; children: ReactNode; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>('input, select')?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && closeRef.current();
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      prev?.focus?.();
    };
  }, [open]);
  if (!open) return null;
  return createPortal(
    <div className="scrim" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={label} ref={ref}>
        <div className="grab" />
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, i) => (
        <div className="skel" key={i} />
      ))}
    </>
  );
}

/** Gradient artwork for pots: generated, so no image assets are needed. */
const POT_ART = [
  'radial-gradient(80% 60% at 70% 20%, #f4d7ff 0%, transparent 60%), radial-gradient(90% 80% at 10% 90%, #ff5a3c 0%, transparent 60%), linear-gradient(160deg, #6a5cff, #2a0f5c 70%)',
  'radial-gradient(70% 60% at 20% 20%, #b9fff0 0%, transparent 60%), radial-gradient(90% 80% at 90% 90%, #0a7b8c 0%, transparent 60%), linear-gradient(160deg, #1fd1a5, #06323f 75%)',
  'radial-gradient(80% 60% at 80% 15%, #ffe9a8 0%, transparent 55%), radial-gradient(90% 80% at 10% 95%, #ff4f8b 0%, transparent 60%), linear-gradient(160deg, #ff9b54, #5c1236 75%)',
  'radial-gradient(70% 60% at 25% 15%, #d6e4ff 0%, transparent 55%), radial-gradient(90% 80% at 85% 95%, #3d5afe 0%, transparent 60%), linear-gradient(160deg, #7aa2ff, #0b1240 75%)',
];

export function potArt(id: string): string {
  return POT_ART[hashIndex(id, POT_ART.length)];
}
