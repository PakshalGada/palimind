import type { ReactNode } from 'react';

/**
 * Build-in reveal for a sprite: four stepped clip frames. Used once on app
 * start for the brand mark, so the product seems to "assemble" itself.
 */
export function PixelAssemble({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  return <span className={`pixel-assemble ${className}`.trim()}>{children}</span>;
}
