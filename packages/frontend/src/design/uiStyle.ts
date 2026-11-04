/**
 * Interface style: the pixel skin or the classic rounded look.
 *
 * Orthogonal to the light/dark palette — `html[data-ui-style="pixel"]`
 * re-skins geometry, type and motion on top of whichever palette is active.
 * index.html applies the stored value before first paint (keep the key and
 * default in sync with it).
 */
export const UI_STYLE_KEY = 'palimind:ui-style';

export type UiStyle = 'pixel' | 'classic';

export const DEFAULT_UI_STYLE: UiStyle = 'pixel';

export function readUiStyle(): UiStyle {
  if (typeof localStorage === 'undefined') return DEFAULT_UI_STYLE;
  try {
    const value = localStorage.getItem(UI_STYLE_KEY);
    return value === 'pixel' || value === 'classic' ? value : DEFAULT_UI_STYLE;
  } catch {
    return DEFAULT_UI_STYLE;
  }
}

export function applyUiStyle(value: UiStyle, persist = true): void {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.uiStyle = value;
  if (!persist) return;
  try {
    localStorage.setItem(UI_STYLE_KEY, value);
  } catch {
    // Storage may be unavailable; the attribute still applies this session.
  }
}
