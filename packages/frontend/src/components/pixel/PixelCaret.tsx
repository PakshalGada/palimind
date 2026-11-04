/**
 * Streaming text cursor: a hard 6×10 block that blinks on `steps(2)`.
 * Purely decorative — screen readers get the streamed text, not the caret.
 */
export function PixelCaret({ className = '' }: { className?: string }) {
  return <span className={`pixel-caret ${className}`.trim()} aria-hidden="true" />;
}
