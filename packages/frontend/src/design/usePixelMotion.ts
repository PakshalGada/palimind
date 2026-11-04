import { useEffect } from 'react';

/**
 * Pixel accent preference + pause plumbing.
 *
 * The pixel layer is CSS-driven; this module only owns the two switches the
 * stylesheet reads:
 *
 *   html[data-pixel-accents="off"]  — the user turned decorative motion off.
 *   html[data-pixel-paused="true"]  — the document is hidden, so loops pause.
 *
 * Both are attributes rather than classes so they are trivially inspectable
 * and cannot collide with component classes.
 */
export const PIXEL_ACCENTS_KEY = 'palimind:pixel-accents';
export const MOTION_KEY = 'palimind:motion';

export type PixelAccents = 'on' | 'off';
export type MotionSetting = 'system' | 'full' | 'reduced';

export function readPixelAccents(): PixelAccents {
  if (typeof localStorage === 'undefined') return 'on';
  try {
    return localStorage.getItem(PIXEL_ACCENTS_KEY) === 'off' ? 'off' : 'on';
  } catch {
    return 'on';
  }
}

export function applyPixelAccents(value: PixelAccents): void {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.pixelAccents = value;
  try {
    localStorage.setItem(PIXEL_ACCENTS_KEY, value);
  } catch {
    // Storage may be unavailable; the attribute still applies this session.
  }
}

export function readMotion(): MotionSetting {
  if (typeof localStorage === 'undefined') return 'system';
  try {
    const value = localStorage.getItem(MOTION_KEY);
    return value === 'full' || value === 'reduced' ? value : 'system';
  } catch {
    return 'system';
  }
}

export function applyMotion(value: MotionSetting): void {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.motion = value;
  try {
    localStorage.setItem(MOTION_KEY, value);
  } catch {
    // Storage may be unavailable; the attribute still applies this session.
  }
}

/** Called once from the app root. */
export function usePixelMotion(): void {
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.pixelAccents = readPixelAccents();
    root.dataset.motion = readMotion();

    const sync = () => {
      root.dataset.pixelPaused = document.hidden ? 'true' : 'false';
    };
    sync();
    document.addEventListener('visibilitychange', sync);
    return () => document.removeEventListener('visibilitychange', sync);
  }, []);
}
