import type { CSSProperties } from 'react';
import { spriteCells, rowsToShapes, type PixelSprite } from './sprites';

export interface PixelGlyphProps {
  sprite?: PixelSprite;
  /** Raw 8×8 rows, used for generated frames (see PixelLoader). */
  rows?: string[];
  /** Pixels per sprite cell. 2 gives a 16×16 glyph. */
  cell?: number;
  /** Accessible name. Omit for decorative glyphs (they become aria-hidden). */
  label?: string;
  className?: string;
  style?: CSSProperties;
}

/** Static 8×8 pixel glyph. Decorative by default. */
export function PixelGlyph({
  sprite = 'spark',
  rows,
  cell = 2,
  label,
  className = '',
  style,
}: PixelGlyphProps) {
  const side = 8 * cell;
  const shapes = rows ? rowsToShapes(rows, cell) : spriteCells(sprite, cell);
  return (
    <svg
      className={`pixel-glyph ${className}`.trim()}
      width={side}
      height={side}
      viewBox={`0 0 ${side} ${side}`}
      fill="currentColor"
      shapeRendering="crispEdges"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
      style={style}
    >
      {shapes.map((s) => (
        <rect key={`${s.x}-${s.y}-${s.w}`} x={s.x} y={s.y} width={s.w} height={cell} />
      ))}
    </svg>
  );
}
