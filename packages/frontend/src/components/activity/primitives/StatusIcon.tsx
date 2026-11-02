import type { ToolStatus } from '../model';
import { Icon, type IconName } from '../icons';

type Status = ToolStatus | 'running' | 'success' | 'error' | 'pending';

const GLYPHS: Record<string, { icon: IconName; spin?: boolean }> = {
  queued: { icon: 'circle' },
  pending: { icon: 'circle' },
  running: { icon: 'loader-2', spin: true },
  awaiting_approval: { icon: 'lock' },
  success: { icon: 'check' },
  error: { icon: 'x' },
  denied: { icon: 'x' },
  cancelled: { icon: 'square' },
  paused: { icon: 'pause' },
  stopped: { icon: 'square' },
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
  return (
    <span className={`act-status act-status--${status}`} data-status={status}>
      <span
        key={status}
        className={`act-status__glyph ${glyph.spin && animate ? 'act-spin' : ''}`}
      >
        <Icon name={glyph.icon} size={size} label={label} strokeWidth={glyph.spin ? 2 : 1.8} />
      </span>
    </span>
  );
}
