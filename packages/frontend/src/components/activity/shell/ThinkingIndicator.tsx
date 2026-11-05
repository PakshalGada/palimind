import { LiveTimer } from '../primitives/LiveTimer';
import { PixelIcon } from '../../pixel/PixelIcon';

/**
 * The optimistic preamble. Deliberately containerless: a pixel spark, one
 * status line and a timer. No dots, no halo, no card.
 */
export function ThinkingIndicator({ startedAt }: { startedAt?: number }) {
  return (
    <div className="act-thinking act-thinking--live" role="status" aria-label="Thinking">
      <span className="act-thinking__glyph" aria-hidden="true">
        <PixelIcon name="spark" size={16} state="busy" />
      </span>
      <span className="act-thinking__label">Thinking</span>
      {startedAt != null && (
        <span className="act-thinking__timer">
          <LiveTimer startedAt={startedAt} active />
        </span>
      )}
      <span className="act-visually-hidden">Thinking</span>
    </div>
  );
}
