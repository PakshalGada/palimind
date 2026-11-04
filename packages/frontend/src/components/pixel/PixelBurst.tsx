const BITS = [
  { dx: -10, dy: -8 },
  { dx: 9, dy: -11 },
  { dx: -13, dy: 3 },
  { dx: 12, dy: 5 },
  { dx: -4, dy: -14 },
];

/**
 * One-shot 2×2 block scatter — agent created, task completed, artifact saved.
 * Key it off a nonce (see `useOneShot`) so it can replay.
 */
export function PixelBurst({
  className = '',
  size = 4,
}: {
  className?: string;
  size?: number;
}) {
  return (
    <span className={`pixel-burst ${className}`.trim()} aria-hidden="true">
      {BITS.map((bit, i) => (
        <span
          key={i}
          className="pixel-burst__bit"
          style={
            {
              width: size,
              height: size,
              '--dx': `${bit.dx}px`,
              '--dy': `${bit.dy}px`,
              '--d': `${i * 18}ms`,
            } as React.CSSProperties
          }
        />
      ))}
    </span>
  );
}
