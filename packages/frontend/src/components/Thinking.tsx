import type { CSSProperties } from 'react';
import { PixelLoader } from './pixel/PixelLoader';

/**
 * Small loading mark used by legacy call sites. It now renders the pixel
 * corner-walk instead of the old orbiting dots/rings, so the app has one
 * loading language: stepped pixel motion.
 */
export type ThinkingVariant = 'orbit' | 'trace' | 'mesh' | 'ripple' | 'beacon' | 'bars';

interface ThinkingProps {
  variant?: ThinkingVariant;
  size?: number;
  className?: string;
  style?: CSSProperties;
  title?: string;
}

export default function Thinking({
  size = 18,
  className = '',
  style,
  title,
}: ThinkingProps) {
  const cell = size >= 16 ? 2 : 1.5;
  return (
    <span
      className={`tk tk--pixel${className ? ` ${className}` : ''}`}
      style={{ width: size, height: size, display: 'inline-flex', ...style }}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <PixelLoader cell={cell} label={title ?? 'Loading'} />
    </span>
  );
}
