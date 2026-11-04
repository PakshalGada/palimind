import type { ReactNode } from 'react';

/**
 * Scan sweep over an icon: a 4px block steps across the glyph while a task is
 * running. Wraps any child; decorative only.
 */
export function PixelSweep({
  children,
  label = 'Working',
  className = '',
}: {
  children: ReactNode;
  label?: string;
  className?: string;
}) {
  return (
    <span className={`pixel-sweep ${className}`.trim()} role="status" aria-label={label}>
      {children}
      <span className="pixel-sweep__rail" aria-hidden="true">
        <span className="pixel-sweep__cursor" />
      </span>
    </span>
  );
}
