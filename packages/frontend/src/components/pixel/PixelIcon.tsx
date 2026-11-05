import { PixelGlyph } from './PixelGlyph';
import type { PixelSprite } from './sprites';

/**
 * 8×8 pixel icon with the app's icon size ladder. Sizes stay integer multiples
 * of 8 so the SVG never lands on half pixels.
 */
export function PixelIcon({
  name,
  size = 16,
  label,
  state = 'idle',
  className = '',
}: {
  name: PixelSprite;
  size?: 8 | 16 | 24 | 32 | 40;
  label?: string;
  state?: 'idle' | 'active' | 'busy' | 'done';
  className?: string;
}) {
  const cell = size / 8;
  return (
    <span
      className={`pixel-icon pixel-icon--${state} ${className}`.trim()}
      data-state={state}
    >
      <PixelGlyph sprite={name} cell={cell} label={label} />
    </span>
  );
}
