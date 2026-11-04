import { PixelGlyph } from './PixelGlyph';
import { LOADER_SPRITES } from './sprites';

/**
 * Live-activity indicator: a 2×2 checker that ticks around an 8×8 box at
 * roughly 4 fps. One per panel, never beside body copy or in long lists.
 */
export function PixelLoader({
  cell = 2,
  label = 'Working',
  className = '',
}: {
  cell?: number;
  label?: string;
  className?: string;
}) {
  const side = 8 * cell;
  return (
    <span
      className={`pixel-loader ${className}`.trim()}
      role="status"
      aria-label={label}
      style={{ width: side, height: side }}
    >
      {LOADER_SPRITES.map((rows, i) => (
        <PixelGlyph
          key={i}
          rows={rows}
          cell={cell}
          className={`pixel-loader__frame pixel-loader__frame--${i}`}
        />
      ))}
    </span>
  );
}
