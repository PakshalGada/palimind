/**
 * The optimistic preamble: one breathing 8px dot, nothing else. When the run
 * starts it morphs in place into the caption row (same spot, same 24px
 * rhythm), so the hand-off never shifts the layout.
 */
import { PixelTicker } from '../../pixel/PixelTicker';

export function ThinkingIndicator() {
  return (
    <div className="act-thinking" aria-label="Thinking">
      <PixelTicker label="Thinking" />
      <span className="act-visually-hidden">Thinking</span>
    </div>
  );
}
