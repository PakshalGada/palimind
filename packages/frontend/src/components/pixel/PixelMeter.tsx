import type { ReactNode } from 'react';

/**
 * Discrete progress meter: eight cells, never a smooth bar. Filled cells are
 * solid ink; the newest one fades in. Pass `value: null` for an indeterminate
 * cycle.
 */
export function PixelMeter({
  value,
  cells = 8,
  label,
  showPercent = false,
  ariaLabel,
  className = '',
}: {
  value: number | null;
  cells?: number;
  label?: ReactNode;
  showPercent?: boolean;
  ariaLabel?: string;
  className?: string;
}) {
  const indeterminate = value == null;
  const pct = indeterminate ? undefined : Math.round(Math.min(1, Math.max(0, value)) * 100);
  const filled = pct === undefined ? 0 : Math.round((pct / 100) * cells);

  return (
    <div className={`pixel-meter${indeterminate ? ' is-indeterminate' : ''} ${className}`.trim()}>
      {label != null && <div className="pixel-meter__label">{label}</div>}
      <div
        className="pixel-meter__cells"
        role="progressbar"
        aria-label={ariaLabel}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        {Array.from({ length: cells }, (_, i) => {
          const on = !indeterminate && i < filled;
          return (
            <span
              key={i}
              className={`pixel-meter__cell${on ? ' is-on' : ''}${on && i === filled - 1 ? ' is-latest' : ''}`}
            />
          );
        })}
      </div>
      {showPercent && !indeterminate && <span className="pixel-meter__value">{pct}%</span>}
    </div>
  );
}
