// Hand-built SVG charts for Insights. Colours come from theme tokens; every chart has a
// tap/hover readout and an aria-label summary so identity never relies on colour alone.
import { useRef, useState, type PointerEvent } from 'react';
import { formatMoney, fromCents } from '../core/money';

const n = (c: bigint) => Number(c) / 100;
const short = (c: bigint) => {
  const y = n(c);
  return y >= 10000 ? `¥${(y / 1000).toFixed(0)}k` : y >= 1000 ? `¥${(y / 1000).toFixed(1)}k` : `¥${Math.round(y)}`;
};

export function PaceChart({ current, previous, budget, todayIdx, labels }: { current: bigint[]; previous: bigint[]; budget?: bigint; todayIdx: number; labels: { now: string; before: string; budget: string } }) {
  const W = 340;
  const H = 160;
  const P = { l: 6, r: 44, t: 14, b: 22 };
  const days = Math.max(current.length, previous.length, 28);
  const cur = current.slice(0, todayIdx + 1);
  const max = [...cur, ...previous, budget ?? 0n].reduce((m, v) => (v > m ? v : m), 1n);
  const yMax = n(max) * 1.1;
  const x = (i: number) => P.l + (i / (days - 1)) * (W - P.l - P.r);
  const y = (c: bigint) => H - P.b - (n(c) / yMax) * (H - P.t - P.b);
  const line = (arr: bigint[]) => arr.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('');
  const [hover, setHover] = useState<number | null>(null);
  const box = useRef<SVGSVGElement>(null);
  const onMove = (e: PointerEvent) => {
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    const px = ((e.clientX - r.left) / r.width) * W;
    setHover(Math.max(0, Math.min(days - 1, Math.round(((px - P.l) / (W - P.l - P.r)) * (days - 1)))));
  };
  const hi = hover ?? null;
  return (
    <div className="chart">
      <svg
        ref={box}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`${labels.now}: ${formatMoney(fromCents(cur[cur.length - 1] ?? 0n))}; ${labels.before}: ${formatMoney(fromCents(previous[Math.min(todayIdx, previous.length - 1)] ?? 0n))}`}
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {[0.25, 0.5, 0.75, 1].map(f => (
          <line key={f} className="grid" x1={P.l} x2={W - P.r} y1={H - P.b - f * (H - P.t - P.b)} y2={H - P.b - f * (H - P.t - P.b)} />
        ))}
        {budget && budget > 0n && (
          <g>
            <line className="budget-line" x1={P.l} x2={W - P.r} y1={y(budget)} y2={y(budget)} />
            <text className="axis" x={W - P.r + 4} y={y(budget) + 4}>
              {short(budget)}
            </text>
          </g>
        )}
        {previous.length > 1 && <path className="pace-prev" d={line(previous)} />}
        {cur.length > 1 && (
          <>
            <path className="pace-area" d={`${line(cur)}L${x(cur.length - 1)},${H - P.b}L${x(0)},${H - P.b}Z`} />
            <path className="pace-now" d={line(cur)} />
            <circle className="pace-dot" cx={x(cur.length - 1)} cy={y(cur[cur.length - 1])} r="4.5" />
          </>
        )}
        <text className="axis" x={P.l} y={H - 6}>
          1
        </text>
        <text className="axis" x={x(14)} y={H - 6} textAnchor="middle">
          15
        </text>
        <text className="axis" x={x(days - 1)} y={H - 6} textAnchor="end">
          {days}
        </text>
        {hi !== null && (
          <line className="cross" x1={x(hi)} x2={x(hi)} y1={P.t} y2={H - P.b} />
        )}
      </svg>
      {hi !== null && (
        <div className="tip" style={{ left: `${(x(hi) / W) * 100}%` }}>
          <b>{hi + 1}</b>
          {cur[hi] !== undefined && <span>{labels.now}: {formatMoney(fromCents(cur[hi]))}</span>}
          {previous[hi] !== undefined && <span>{labels.before}: {formatMoney(fromCents(previous[hi]))}</span>}
        </div>
      )}
      <div className="legend">
        <span><i className="sw now" />{labels.now}</span>
        <span><i className="sw prev" />{labels.before}</span>
        {budget && budget > 0n && <span><i className="sw bud" />{labels.budget}</span>}
      </div>
    </div>
  );
}

export function CashflowBars({ data, labels }: { data: { label: string; income: bigint; spent: bigint }[]; labels: { income: string; spent: string } }) {
  const W = 340;
  const H = 150;
  const P = { l: 4, r: 4, t: 10, b: 22 };
  const max = data.reduce((m, d) => (d.income > m ? d.income : d.spent > m ? d.spent : m), 1n);
  const slot = (W - P.l - P.r) / data.length;
  const bw = Math.min(16, slot / 3);
  const h = (c: bigint) => (n(c) / n(max)) * (H - P.t - P.b);
  const [hi, setHi] = useState<number | null>(null);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={data.map(d => `${d.label}: ${labels.income} ${formatMoney(fromCents(d.income))}, ${labels.spent} ${formatMoney(fromCents(d.spent))}`).join('; ')}>
        <line className="grid" x1={P.l} x2={W - P.r} y1={H - P.b} y2={H - P.b} />
        {data.map((d, i) => {
          const cx = P.l + slot * i + slot / 2;
          return (
            <g key={d.label} onPointerEnter={() => setHi(i)} onPointerDown={() => setHi(i)} onPointerLeave={() => setHi(null)}>
              <rect x={P.l + slot * i} y={P.t} width={slot} height={H - P.t - P.b} fill="transparent" />
              <rect className="bar-in" x={cx - bw - 1} y={H - P.b - h(d.income)} width={bw} height={Math.max(0, h(d.income))} rx="4" />
              <rect className="bar-out" x={cx + 1} y={H - P.b - h(d.spent)} width={bw} height={Math.max(0, h(d.spent))} rx="4" />
              <text className={'axis' + (hi === i ? ' strong' : '')} x={cx} y={H - 6} textAnchor="middle">
                {d.label}
              </text>
            </g>
          );
        })}
      </svg>
      {hi !== null && (
        <div className="tip" style={{ left: `${((P.l + slot * hi + slot / 2) / W) * 100}%` }}>
          <b>{data[hi].label}</b>
          <span>{labels.income}: {formatMoney(fromCents(data[hi].income))}</span>
          <span>{labels.spent}: {formatMoney(fromCents(data[hi].spent))}</span>
        </div>
      )}
      <div className="legend">
        <span><i className="sw in" />{labels.income}</span>
        <span><i className="sw out" />{labels.spent}</span>
      </div>
    </div>
  );
}

/** Ring of category shares in fixed category order, with the total in the middle. */
export function Donut({ parts, total, centerLabel }: { parts: { key: string; cents: bigint; label: string }[]; total: bigint; centerLabel: string }) {
  const R = 52;
  const C = 2 * Math.PI * R;
  let acc = 0;
  const sum = parts.reduce((s, p) => s + n(p.cents), 0) || 1;
  return (
    <svg className="donut" viewBox="0 0 140 140" role="img" aria-label={parts.map(p => `${p.label} ${Math.round((n(p.cents) / sum) * 100)}%`).join(', ')}>
      <circle cx="70" cy="70" r={R} className="donut-track" />
      {parts.map(p => {
        const len = (n(p.cents) / sum) * C;
        const gap = parts.length > 1 ? Math.min(3, len / 2) : 0;
        const el = (
          <circle
            key={p.key}
            cx="70"
            cy="70"
            r={R}
            fill="none"
            stroke={`var(--cat-${p.key})`}
            strokeWidth="16"
            strokeDasharray={`${Math.max(0, len - gap)} ${C}`}
            strokeDashoffset={-acc}
            transform="rotate(-90 70 70)"
          />
        );
        acc += len;
        return el;
      })}
      <text x="70" y="66" textAnchor="middle" className="donut-total">
        {short(total)}
      </text>
      <text x="70" y="84" textAnchor="middle" className="donut-label">
        {centerLabel}
      </text>
    </svg>
  );
}
