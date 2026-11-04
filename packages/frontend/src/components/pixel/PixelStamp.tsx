import { PixelGlyph } from './PixelGlyph';

/**
 * One-shot acknowledgement mark for a completed action (run finished,
 * artifact saved). Plays once and stays static.
 */
export function PixelStamp({
  tone = 'done',
  size = 16,
  label,
  className = '',
}: {
  tone?: 'done' | 'error';
  size?: number;
  label?: string;
  className?: string;
}) {
  const cell = size / 8;
  return (
    <span
      className={`pixel-stamp pixel-stamp--${tone} ${className}`.trim()}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <PixelGlyph sprite={tone === 'done' ? 'check' : 'cross'} cell={cell} />
    </span>
  );
}
