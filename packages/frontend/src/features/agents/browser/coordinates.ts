export interface RectLike {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Map a pointer position on the rendered browser frame to the Playwright
 * viewport. The frame keeps the viewport aspect ratio, so this is linear; the
 * clamp protects against sub-pixel overflow at the edges.
 */
export function toPagePoint(
  clientX: number,
  clientY: number,
  rect: RectLike,
  viewport: { width: number; height: number },
): { x: number; y: number } {
  const width = Math.max(1, rect.width);
  const height = Math.max(1, rect.height);
  const x = ((clientX - rect.left) / width) * viewport.width;
  const y = ((clientY - rect.top) / height) * viewport.height;
  return {
    x: Math.max(0, Math.min(viewport.width, x)),
    y: Math.max(0, Math.min(viewport.height, y)),
  };
}

/** URL shown in the address bar: add https when the user omits a scheme. */
export function normalizeAddress(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}
