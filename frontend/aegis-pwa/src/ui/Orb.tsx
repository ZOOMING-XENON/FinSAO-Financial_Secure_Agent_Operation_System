// Aegis's voice: a living orb drawn on canvas. It breathes when idle and reacts to the
// microphone level while listening. The level is read from the mic only for animation;
// no audio is stored or sent anywhere by this component.
import { useEffect, useRef } from 'react';

export interface OrbLevel {
  current: number; // 0..1, written by the voice session
}

const LAYERS = [
  { color: [106, 77, 255], speed: 0.55, lobes: 3, phase: 0 },
  { color: [255, 95, 162], speed: -0.8, lobes: 4, phase: 1.7 },
  { color: [46, 196, 182], speed: 0.95, lobes: 5, phase: 3.1 },
  { color: [61, 139, 255], speed: -0.45, lobes: 2, phase: 4.4 },
];

export function VoiceOrb({ size, level, active }: { size: number; level?: OrbLevel; active: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const activeRef = useRef(active);
  activeRef.current = active;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    let raf = 0;
    let amp = 0.05;
    const start = performance.now();
    const c = size / 2;
    const draw = (now: number) => {
      const t = (now - start) / 1000;
      const target = activeRef.current ? 0.14 + Math.min(1, (level?.current ?? 0) * 1.6) * 0.55 : 0.05;
      amp += (target - amp) * 0.12;
      ctx.clearRect(0, 0, size, size);
      const base = size * (activeRef.current ? 0.3 : 0.32) * (1 + amp * 0.25);
      // soft glow
      const glow = ctx.createRadialGradient(c, c, base * 0.4, c, c, size * 0.5);
      glow.addColorStop(0, `rgba(140, 110, 255, ${0.28 + amp * 0.4})`);
      glow.addColorStop(1, 'rgba(140, 110, 255, 0)');
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, size, size);
      // Additive blending only on the dark voice screen; on light pages it would wash out to white.
      ctx.globalCompositeOperation = activeRef.current ? 'lighter' : 'source-over';
      const live = activeRef.current;
      for (const L of LAYERS) {
        const rot = t * L.speed + L.phase;
        // Each colour orbits a little off-centre so the hues stay distinct instead of mixing to grey.
        const ox = c + Math.cos(rot * 0.7) * base * (0.16 + amp * 0.25);
        const oy = c + Math.sin(rot * 0.9) * base * (0.16 + amp * 0.25);
        ctx.beginPath();
        for (let i = 0; i <= 96; i++) {
          const a = (i / 96) * Math.PI * 2;
          const wobble =
            Math.sin(a * L.lobes + rot * 2.2) * amp * 0.55 +
            Math.sin(a * (L.lobes + 2) - rot * 3.1) * amp * 0.25 +
            Math.sin(t * 1.3 + L.phase) * 0.03;
          const r = base * (0.78 + wobble);
          const x = ox + Math.cos(a + rot) * r;
          const y = oy + Math.sin(a + rot) * r;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        const [R, G, B] = L.color;
        const g = ctx.createRadialGradient(ox, oy, 0, ox, oy, base * 1.1);
        g.addColorStop(0, `rgba(${R},${G},${B},${live ? 0.55 : 0.85})`);
        g.addColorStop(0.7, `rgba(${R},${G},${B},${live ? 0.35 : 0.55})`);
        g.addColorStop(1, `rgba(${R},${G},${B},0)`);
        ctx.fillStyle = g;
        ctx.fill();
      }
      ctx.globalCompositeOperation = 'source-over';
      const gloss = ctx.createRadialGradient(c - base * 0.35, c - base * 0.4, 0, c - base * 0.35, c - base * 0.4, base * 0.55);
      gloss.addColorStop(0, 'rgba(255,255,255,0.55)');
      gloss.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = gloss;
      ctx.beginPath();
      ctx.arc(c - base * 0.35, c - base * 0.4, base * 0.55, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalCompositeOperation = 'source-over';
      if (!reduced) raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [size, level]);

  return <canvas ref={ref} className="voice-orb" style={{ width: size, height: size }} aria-hidden="true" />;
}

/** Opens the microphone only to measure loudness for the orb. Returns a stop function. */
export async function startMicLevel(level: OrbLevel): Promise<() => void> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ac = new AC();
    const src = ac.createMediaStreamSource(stream);
    const analyser = ac.createAnalyser();
    analyser.fftSize = 512;
    src.connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);
    let raf = 0;
    const tick = () => {
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += ((v - 128) / 128) ** 2;
      level.current = Math.sqrt(sum / buf.length) * 3;
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => {
      cancelAnimationFrame(raf);
      stream.getTracks().forEach(tr => tr.stop());
      ac.close().catch(() => undefined);
      level.current = 0;
    };
  } catch {
    return () => {
      level.current = 0;
    };
  }
}
