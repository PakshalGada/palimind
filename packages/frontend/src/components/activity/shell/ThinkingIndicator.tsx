import { ShimmerText } from '../primitives/ShimmerText';
import { LiveTimer } from '../primitives/LiveTimer';

export function ThinkingIndicator({
  startedAt,
  running = true,
}: {
  startedAt?: number;
  running?: boolean;
}) {
  if (!running || startedAt == null) {
    return (
      <div className="act-thinking" aria-label="Thinking">
        <span className="act-dot" aria-hidden="true" />
        <span className="act-visually-hidden">Thinking</span>
      </div>
    );
  }
  return (
    <div className="act-thinking">
      <span className="act-dot" aria-hidden="true" />
      <ShimmerText>Thinking</ShimmerText>
      <LiveTimer startedAt={startedAt} active />
    </div>
  );
}
