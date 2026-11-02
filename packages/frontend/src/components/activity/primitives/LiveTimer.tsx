import { formatRunDuration } from '../model';
import { useNow } from '../hooks';

export function LiveTimer({
  startedAt,
  endedAt,
  active,
  className = 'act-timer',
}: {
  startedAt: number;
  endedAt?: number;
  active: boolean;
  className?: string;
}) {
  const running = active && endedAt == null;
  const now = useNow(running);
  const end = endedAt ?? now;
  return (
    <span className={`${className} act-tabular act-muted`} aria-hidden="true">
      {formatRunDuration(Math.max(0, end - startedAt))}
    </span>
  );
}

export function StaticDuration({ ms }: { ms: number }) {
  return <span className="act-timer act-tabular act-muted">{formatRunDuration(ms)}</span>;
}
