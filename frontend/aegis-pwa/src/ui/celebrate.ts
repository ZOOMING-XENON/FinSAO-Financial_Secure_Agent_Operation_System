// Small moments of delight: confetti bursts and a light haptic tap.
const COLORS = ['#6a4dff', '#ff5fa2', '#2ec4b6', '#ffb347', '#3d8bff', '#ffd43b'];

export function haptic(pattern: number | number[] = 12) {
  try {
    navigator.vibrate?.(pattern);
  } catch {
    /* not supported */
  }
}

/** Full-screen confetti. `big` for goals reached, small bursts for milestones. */
export function celebrate(big = true) {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return haptic(30);
  const canvas = document.createElement('canvas');
  canvas.className = 'confetti';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.appendChild(canvas);
  const ctx = canvas.getContext('2d');
  if (!ctx) return canvas.remove();
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const W = window.innerWidth;
  const H = window.innerHeight;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  ctx.scale(dpr, dpr);
  const count = big ? 180 : 60;
  const parts = Array.from({ length: count }, () => ({
    x: W / 2 + (Math.random() - 0.5) * (big ? W * 0.6 : 120),
    y: big ? H * 0.35 : H * 0.45,
    vx: (Math.random() - 0.5) * (big ? 14 : 8),
    vy: -Math.random() * (big ? 16 : 10) - 4,
    w: 6 + Math.random() * 6,
    h: 8 + Math.random() * 10,
    r: Math.random() * Math.PI,
    vr: (Math.random() - 0.5) * 0.3,
    c: COLORS[Math.floor(Math.random() * COLORS.length)],
    circle: Math.random() < 0.3,
  }));
  const start = performance.now();
  const life = big ? 2600 : 1500;
  const frame = (now: number) => {
    const el = now - start;
    ctx.clearRect(0, 0, W, H);
    for (const p of parts) {
      p.vy += 0.35;
      p.vx *= 0.99;
      p.x += p.vx;
      p.y += p.vy;
      p.r += p.vr;
      ctx.save();
      ctx.globalAlpha = Math.max(0, 1 - el / life);
      ctx.translate(p.x, p.y);
      ctx.rotate(p.r);
      ctx.fillStyle = p.c;
      if (p.circle) {
        ctx.beginPath();
        ctx.arc(0, 0, p.w / 2, 0, Math.PI * 2);
        ctx.fill();
      } else ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      ctx.restore();
    }
    if (el < life) requestAnimationFrame(frame);
    else canvas.remove();
  };
  requestAnimationFrame(frame);
  haptic(big ? [20, 40, 20, 40, 60] : 15);
}
