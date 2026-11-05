import { useEffect, useRef, useState } from 'react';
import { PixelGlyph } from '../pixel/PixelGlyph';
import { PixelMeter } from '../pixel/PixelMeter';
import { PixelAssemble } from '../pixel/PixelAssemble';
import './boot.css';

const BRAND_ROWS = [
  '11111100',
  '10000110',
  '10000010',
  '10000110',
  '11111100',
  '10000000',
  '10000000',
  '10000000',
];

const STATUS = [
  'Opening workspace',
  'Waking local models',
  'Loading projects',
  'Almost ready',
];

/**
 * Branded first paint. It is decoupled from the app so the shell can mount
 * behind it and there is never a blank frame. A health check is best-effort:
 * after 4.5s the screen offers "Enter anyway" instead of hanging forever.
 */
export default function BootScreen({ onReady }: { onReady: () => void }) {
  const [statusIndex, setStatusIndex] = useState(0);
  const [offline, setOffline] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const done = useRef(false);

  const finish = () => {
    if (done.current) return;
    done.current = true;
    setLeaving(true);
    window.setTimeout(onReady, 240);
  };

  useEffect(() => {
    // The static first-paint shell in index.html hands over to this component.
    document.getElementById('boot-fallback')?.remove();
    const started = Date.now();
    const statusTimer = window.setInterval(() => {
      setStatusIndex((index) => (index + 1) % STATUS.length);
    }, 620);
    const watchdog = window.setTimeout(() => setOffline(true), 4500);

    let cancelled = false;
    const run = async () => {
      try {
        await fetch('/health', { credentials: 'include' });
      } catch {
        // The app still opens; the first API call shows a toast.
      }
      const wait = Math.max(0, 650 - (Date.now() - started));
      window.setTimeout(() => {
        if (cancelled) return;
        window.clearTimeout(watchdog);
        finish();
      }, wait);
    };
    void run();

    return () => {
      cancelled = true;
      window.clearInterval(statusTimer);
      window.clearTimeout(watchdog);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!offline) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === 'Escape') finish();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offline]);

  return (
    <div
      className={`boot-screen${leaving ? ' is-leaving' : ''}`}
      role="status"
      aria-label="Starting PaliMind"
    >
      <div className="boot-screen__grid" aria-hidden="true" />
      <div className="boot-screen__scan" aria-hidden="true" />
      <div className="boot-screen__card">
        <div className="boot-screen__mark">
          <PixelAssemble>
            <PixelGlyph rows={BRAND_ROWS} cell={5} />
          </PixelAssemble>
        </div>
        <div className="boot-screen__wordmark">
          <span>PALI</span>
          <span>MIND</span>
        </div>
        <div className="boot-screen__meter">
          <PixelMeter value={null} cells={7} ariaLabel="Loading" />
        </div>
        <div className="boot-screen__status">
          {offline ? 'Local engine is still starting' : STATUS[statusIndex]}
          <span className="boot-screen__dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        </div>
        {offline && (
          <button type="button" className="boot-screen__skip" onClick={finish}>
            Enter anyway <kbd>↵</kbd>
          </button>
        )}
        <div className="boot-screen__foot">Local-first · private · offline</div>
      </div>
    </div>
  );
}
