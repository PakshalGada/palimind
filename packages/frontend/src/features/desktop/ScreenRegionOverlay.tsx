import { useEffect, useRef, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { emit } from '@tauri-apps/api/event';
import type { DesktopRegion } from './ComputerUsePanel';
import './desktop.css';

interface Point {
  x: number;
  y: number;
}

export default function ScreenRegionOverlay() {
  const [start, setStart] = useState<Point | null>(null);
  const [current, setCurrent] = useState<Point | null>(null);
  const [dragging, setDragging] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const rect = start && current
    ? {
        x: Math.min(start.x, current.x),
        y: Math.min(start.y, current.y),
        width: Math.abs(current.x - start.x),
        height: Math.abs(current.y - start.y),
      }
    : null;

  const close = async () => {
    try {
      await invoke('hide_region_overlay');
    } catch {
      window.close();
    }
  };

  const confirm = async (mode: 'ask' | 'act') => {
    if (!rect || rect.width < 4 || rect.height < 4) {
      setStart(null);
      setCurrent(null);
      return;
    }
    const payload: DesktopRegion = {
      ...rect,
      dpr: window.devicePixelRatio || 1,
      mode,
    };
    // Emit while this window still has a JS context; the popup hides the
    // overlay and waits a beat before capturing so the overlay cannot appear
    // in the screenshot.
    try {
      await emit('palimind:region-selected', payload);
    } catch {
      // Browser fallback: pass the selection back through storage.
      localStorage.setItem('palimind:desktop-region', JSON.stringify(payload));
    }
    window.setTimeout(() => void close(), 250);
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        void close();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // Escape handling is independent of the drag state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      ref={rootRef}
      className="cu-overlay"
      onMouseDown={(event) => {
        const point = { x: event.clientX, y: event.clientY };
        setStart(point);
        setCurrent(point);
        setDragging(true);
      }}
      onMouseMove={(event) => {
        if (!dragging) return;
        setCurrent({ x: event.clientX, y: event.clientY });
      }}
      onMouseUp={() => setDragging(false)}
    >
      <div className="cu-overlay__hint">Drag to select an area · Esc to cancel</div>
      {rect && (
        <>
          <div
            className="cu-overlay__shade"
            style={{
              clipPath: `polygon(0 0, 100% 0, 100% 100%, 0 100%, 0 0, ${rect.x}px ${rect.y}px, ${rect.x}px ${rect.y + rect.height}px, ${rect.x + rect.width}px ${rect.y + rect.height}px, ${rect.x + rect.width}px ${rect.y}px, ${rect.x}px ${rect.y}px)`,
            }}
          />
          <div
            className="cu-overlay__rect"
            style={{
              left: rect.x,
              top: rect.y,
              width: rect.width,
              height: rect.height,
            }}
          >
            <span className="cu-overlay__size">
              {Math.round(rect.width)} × {Math.round(rect.height)}
            </span>
          </div>
          <div
            className="cu-overlay__toolbar"
            style={{
              left: Math.min(rect.x + rect.width + 8, window.innerWidth - 230),
              top: Math.min(rect.y + 8, window.innerHeight - 60),
            }}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button type="button" onClick={() => void confirm('ask')}>
              Ask
            </button>
            <button type="button" onClick={() => void confirm('act')}>
              Act
            </button>
            <button
              type="button"
              onClick={() => {
                setStart(null);
                setCurrent(null);
              }}
            >
              Retake
            </button>
            <button type="button" onClick={() => void close()}>
              Cancel
            </button>
          </div>
        </>
      )}
    </div>
  );
}
