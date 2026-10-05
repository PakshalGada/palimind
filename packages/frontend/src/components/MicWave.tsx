import { useEffect, useRef } from 'react';

/**
 * Animated waveform shown while recording. Bar heights are driven by the live
 * microphone level (RMS) so the user can see that audio is actually being
 * captured, not just that a button is pressed.
 *
 * Uses direct DOM manipulation via refs instead of React state to avoid
 * 60fps re-renders. This is much more performant for high-frequency updates.
 */
export default function MicWave({ levelRef, active }: { levelRef: { current: number }; active: boolean }) {
  const barsRef = useRef<(HTMLSpanElement | null)[]>([]);
  const barsDataRef = useRef<number[]>([0.15, 0.15, 0.15, 0.15, 0.15]);

  useEffect(() => {
    if (!active) {
      barsDataRef.current = [0.15, 0.15, 0.15, 0.15, 0.15];
      barsDataRef.current.forEach((h, i) => {
        const el = barsRef.current[i];
        if (el) el.style.transform = `scaleY(${h})`;
      });
      return;
    }
    let raf = 0;
    let lastUpdate = 0;
    const tick = (time: number) => {
      // Throttle to ~30fps to reduce CPU usage
      if (time - lastUpdate < 33) {
        raf = requestAnimationFrame(tick);
        return;
      }
      lastUpdate = time;
      const level = Math.max(0, Math.min(1, levelRef.current || 0));
      const bars = barsDataRef.current;
      for (let i = 0; i < bars.length; i++) {
        const center = 1 - Math.abs(i - 2) / 3;
        const jitter = 0.6 + Math.random() * 0.5;
        const target = Math.max(0.12, Math.min(1, level * center * jitter * 3.2));
        bars[i] = bars[i] * 0.4 + target * 0.6;
        const el = barsRef.current[i];
        if (el) el.style.transform = `scaleY(${Math.max(0.12, bars[i]).toFixed(3)})`;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, levelRef]);

  return (
    <span className="mic-waves" aria-hidden="true">
      {[0, 1, 2, 3, 4].map((i) => (
        <span
          key={i}
          ref={el => { barsRef.current[i] = el; }}
          className="mic-wave-bar"
          style={{ transform: 'scaleY(0.15)' }}
        />
      ))}
    </span>
  );
}
