import { useEffect, useRef, useState } from 'react';
import type { ReasoningState } from '../model';
import { useBuffer } from '../hooks';
import { Icon } from '../icons';
import { Disclosure } from '../primitives/Disclosure';
import { LiveTimer, StaticDuration } from '../primitives/LiveTimer';
import { ShimmerText } from '../primitives/ShimmerText';
import type { ActivityStore } from '../store';

function ReasoningText({
  store,
  fallback,
}: {
  store: ActivityStore;
  fallback: string;
}) {
  const snapshot = useBuffer(store, 'reasoning');
  const text = snapshot.text || fallback || 'Thinking';
  const [pinned, setPinned] = useState(true);
  const textRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = textRef.current;
    if (!element || !pinned) return;
    element.scrollTop = element.scrollHeight;
  }, [text, pinned]);

  return (
    <div
      className="act-reason__text"
      ref={textRef}
      onScroll={(event) => {
        const element = event.currentTarget;
        setPinned(element.scrollHeight - element.scrollTop - element.clientHeight <= 4);
      }}
    >
      {text}
    </div>
  );
}

export function ReasoningBlock({
  reasoning,
  startedAt,
  store,
}: {
  reasoning: ReasoningState;
  startedAt: number;
  store: ActivityStore;
}) {
  const [manual, setManual] = useState<boolean | null>(null);
  const active = !reasoning.done;
  const open = manual ?? active;
  const duration = reasoning.durationMs;

  return (
    <div className="act-reason">
      <Disclosure
        open={open}
        onOpenChange={setManual}
        summaryClassName="act-reason__head"
        contentClassName=""
        summary={
          <>
            <Icon name="brain" size={14} />
            <span className="act-row__label">
              {active ? (
                <ShimmerText>Thinking</ShimmerText>
              ) : (
                <span>
                  Thought for{' '}
                  {duration != null ? (
                    <StaticDuration ms={duration} />
                  ) : (
                    <LiveTimer startedAt={startedAt} active={false} />
                  )}
                </span>
              )}
            </span>
            {active && <LiveTimer startedAt={reasoning.startedAt ?? startedAt} active />}
          </>
        }
      >
        <ReasoningText store={store} fallback={reasoning.text} />
      </Disclosure>
    </div>
  );
}
