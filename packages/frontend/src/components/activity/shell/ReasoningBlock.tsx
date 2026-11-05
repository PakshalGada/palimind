import { useEffect, useRef, useState } from 'react';
import type { ReasoningState } from '../model';
import { formatRunDuration } from '../model';
import { useBuffer } from '../hooks';
import { Icon } from '../icons';
import { PixelIcon } from '../../pixel/PixelIcon';
import { PixelCaret } from '../../pixel/PixelCaret';
import { PixelLoader } from '../../pixel/PixelLoader';
import { LiveTimer } from '../primitives/LiveTimer';
import type { ActivityStore } from '../store';

/**
 * Live trace: the last three lines of the buffer, soft top fade, muted 12px,
 * auto-pinned to the tail. Upward scroll unpins; scrolling back down repins.
 * This component is the only subscriber while reasoning streams, so the panel
 * itself never re-renders per token.
 */
function LiveTrace({
  store,
  fallback,
  startedAt,
  showHeader,
}: {
  store: ActivityStore;
  fallback: string;
  startedAt: number;
  showHeader: boolean;
}) {
  const snapshot = useBuffer(store, 'reasoning');
  const text = snapshot.text || fallback;
  const [pinned, setPinned] = useState(true);
  const textRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = textRef.current;
    if (!element || !pinned) return;
    element.scrollTop = element.scrollHeight;
  }, [text, pinned]);

  return (
    <div className="act-reason act-reason--live">
      {showHeader && (
        <div className="act-reason__caption">
          <span className="act-reason__glyph" aria-hidden="true">
            <PixelIcon name="spark" size={16} state="busy" />
          </span>
          <span className="act-reason__caption-text">Thinking</span>
          <span className="act-reason__loader" aria-hidden="true">
            <PixelLoader cell={1.5} label="Thinking" />
          </span>
          <LiveTimer startedAt={startedAt} active />
        </div>
      )}
      <div
        className="act-reason__tail"
        ref={textRef}
        onScroll={(event) => {
          const element = event.currentTarget;
          setPinned(element.scrollHeight - element.scrollTop - element.clientHeight <= 4);
        }}
      >
        <span className="act-reason__tail-text">{text}</span>
        <PixelCaret />
      </div>
    </div>
  );
}

/** Settled trace body: the buffer, or the persisted text for history runs. */
function SettledTrace({
  store,
  fallback,
  open,
}: {
  store: ActivityStore;
  fallback: string;
  open: boolean;
}) {
  const buffer = useBuffer(store, 'reasoning');
  const fullText = buffer.text || fallback;
  return (
    <div className="act-disclosure act-reason__trace" data-open={open}>
      <div className="act-disclosure__inner">
        <div className="act-reason__body">
          <pre className="act-reason__full">{fullText || ' '}</pre>
        </div>
      </div>
    </div>
  );
}

/**
 * Settled: one muted line — "Thought for 8s" — that re-opens the full,
 * recessed trace. No progress word once the answer started; the caption row
 * owns progress then.
 */
export function ReasoningBlock({
  reasoning,
  startedAt,
  store,
  showHeader = true,
}: {
  reasoning: ReasoningState;
  startedAt: number;
  store: ActivityStore;
  showHeader?: boolean;
}) {
  const [manual, setManual] = useState<boolean | null>(null);
  const active = !reasoning.done;

  if (active) {
    return (
      <LiveTrace
        store={store}
        fallback={reasoning.text}
        startedAt={reasoning.startedAt ?? startedAt}
        showHeader={showHeader}
      />
    );
  }

  const open = manual ?? false;
  const duration = reasoning.durationMs;
  const label =
    duration != null ? `Thought for ${formatRunDuration(duration)}` : 'Thought';

  return (
    <div className="act-reason">
      <button
        type="button"
        className="act-reason__settled"
        aria-expanded={open}
        onClick={() => setManual(!open)}
      >
        <span className="act-reason__settled-icon" aria-hidden="true">
          <PixelIcon name="check" size={16} state="done" />
        </span>
        <span>{label}</span>
        <span className="act-chevron" data-open={open} aria-hidden="true">
          <Icon name="chevron-right" size={13} />
        </span>
      </button>
      <SettledTrace store={store} fallback={reasoning.text} open={open} />
    </div>
  );
}
