import type { ToolStatus } from '../model';
import { PixelGlyph } from '../../pixel/PixelGlyph';
import { PixelLoader } from '../../pixel/PixelLoader';
import type { PixelSprite } from '../../pixel/sprites';

type Status = ToolStatus | 'running' | 'success' | 'error' | 'pending';

const GLYPHS: Record<string, { sprite: PixelSprite; cell?: number }> = {
  queued: { sprite: 'dot', cell: 1.5 },
  pending: { sprite: 'dot', cell: 1.5 },
  running: { sprite: 'checker', cell: 1.5 },
  awaiting_approval: { sprite: 'diamond', cell: 1.5 },
  success: { sprite: 'check', cell: 1.5 },
  error: { sprite: 'cross', cell: 1.5 },
  denied: { sprite: 'cross', cell: 1.5 },
  cancelled: { sprite: 'pause', cell: 1.5 },
  paused: { sprite: 'pause', cell: 1.5 },
  stopped: { sprite: 'pause', cell: 1.5 },
};

export function StatusIcon({
  status,
  label,
  size = 14,
  animate = true,
}: {
  status: Status;
  /** Only for a status icon that carries the whole meaning. */
  label?: string;
  size?: number;
  animate?: boolean;
}) {
  const glyph = GLYPHS[status] ?? GLYPHS.queued;
  void size;
  return (
    <span className={`act-status act-status--${status}`} data-status={status}>
      <span
        key={status}
        className={`act-status__glyph ${animate ? 'act-status__glyph--live' : ''}`}
      >
        {status === 'running' && animate ? (
          <span aria-hidden="true">
            <PixelLoader cell={1.5} label={label ?? 'Running'} />
          </span>
        ) : (
          <PixelGlyph sprite={glyph.sprite} cell={glyph.cell ?? 1.5} label={label} />
        )}
      </span>
    </span>
  );
}
