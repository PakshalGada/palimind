import { useEffect, useState } from 'react';

/**
 * Animated waveform shown while recording. Bar heights are driven by the live
 * microphone level (RMS) so the user can see that audio is actually being
 * captured, not just that a button is pressed.
 */
export default function MicWave({ levelRef, active }: { levelRef: { current: number }; active: boolean }) {
  const [bars, setBars] = useState<number[]>([0.15, 0.15, 0.15, 0.15, 0.15]);

  useEffect(() => {
    if (!active) {
      setBars([0.15, 0.15, 0.15, 0.15, 0.15]);
      return;
    }
    let raf = 0;
    const tick = () => {
      const level = Math.max(0, Math.min(1, levelRef.current || 0));
      setBars((prev) =>
        prev.map((p, i) => {
          const center = 1 - Math.abs(i - 2) / 3; // taller towards the middle
          const jitter = 0.6 + Math.random() * 0.5;
          const target = Math.max(0.12, Math.min(1, level * center * jitter * 3.2));
          return p * 0.4 + target * 0.6; // smooth decay towards target
        }),
      );
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, levelRef]);

  return (
    <span className="mic-waves" aria-hidden="true">
      {bars.map((h, i) => (
        <span
          key={i}
          className="mic-wave-bar"
          style={{ transform: `scaleY(${Math.max(0.12, h).toFixed(3)})` }}
        />
      ))}
    </span>
  );
}
