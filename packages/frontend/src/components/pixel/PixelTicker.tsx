/**
 * Marching pixel ticker: three 2×2 blocks that light left → right on `steps`.
 * Used for "thinking" states that have no token stream yet.
 */
export function PixelTicker({
  blocks = 3,
  label = 'Thinking',
  className = '',
}: {
  blocks?: number;
  label?: string;
  className?: string;
}) {
  return (
    <span className={`pixel-ticker ${className}`.trim()} role="status" aria-label={label}>
      {Array.from({ length: blocks }, (_, i) => (
        <span
          key={i}
          className="pixel-ticker__block"
          style={{ animationDelay: `${i * 150}ms` }}
          aria-hidden="true"
        />
      ))}
    </span>
  );
}
