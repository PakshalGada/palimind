import { useEffect, useState } from 'react';
import { listen } from '@tauri-apps/api/event';
import './desktop.css';

export interface GhostTarget {
  x: number;
  y: number;
  width?: number;
  height?: number;
  label?: string;
}

function num(value: string | null): number | undefined {
  if (value === null || value === '') return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function targetFromSearch(search: string): GhostTarget | null {
  const params = new URLSearchParams(search);
  if (params.get('window') !== 'cursor-ghost') return null;
  const x = num(params.get('x'));
  const y = num(params.get('y'));
  if (x === undefined || y === undefined) return null;
  return {
    x,
    y,
    width: num(params.get('w')),
    height: num(params.get('h')),
    label: params.get('label') || undefined,
  };
}

/** Presentational mark, used by the overlay window and the SSR smoke test. */
export function GhostCursorMark({ target }: { target: GhostTarget }) {
  const width = target.width && target.width > 0 ? target.width : 0;
  const height = target.height && target.height > 0 ? target.height : 0;
  return (
    <div className="cu-ghost" aria-hidden="true">
      {width > 0 && height > 0 && (
        <div
          className="cu-ghost__box"
          style={{ left: target.x, top: target.y, width, height }}
        />
      )}
      <div className="cu-ghost__ring" style={{ left: target.x, top: target.y }} />
      <div className="cu-ghost__dot" style={{ left: target.x, top: target.y }} />
      <div
        className="cu-ghost__label"
        style={{
          left: target.x + 18,
          top: target.y + 18,
        }}
      >
        {target.label || 'Target'}
      </div>
    </div>
  );
}

export default function GhostCursorOverlay() {
  const [target, setTarget] = useState<GhostTarget | null>(() =>
    targetFromSearch(window.location.search),
  );

  useEffect(() => {
    let cleanup: (() => void) | undefined;
    void listen<GhostTarget>('palimind:ghost-cursor', (event) => {
      setTarget(event.payload);
    }).then((unlisten) => {
      cleanup = unlisten;
    });
    return () => cleanup?.();
  }, []);

  if (!target) return null;
  return <GhostCursorMark target={target} />;
}
