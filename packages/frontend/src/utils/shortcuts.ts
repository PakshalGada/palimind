/**
 * Keyboard shortcut parsing, matching, formatting and persistence.
 *
 * Bindings are stored in a compact canonical form, e.g. `Mod+Shift+C`, where
 * `Mod` is the platform-primary modifier (Ctrl on Windows/Linux, Cmd on macOS).
 * `Ctrl` and `Meta` are both accepted as aliases of `Mod` so a binding written
 * for one platform keeps working on the other.
 */

export const SHORTCUT_OVERRIDES_KEY = 'palimind:shortcut-overrides';

export interface ParsedShortcut {
  key: string;
  mod: boolean;
  shift: boolean;
  alt: boolean;
}

const KEY_ALIASES: Record<string, string> = {
  esc: 'escape',
  return: 'enter',
  ' ': 'space',
  spacebar: 'space',
  del: 'delete',
  arrowup: 'arrowup',
  arrowdown: 'arrowdown',
  arrowleft: 'arrowleft',
  arrowright: 'arrowright',
};

function normalizeKey(raw: string): string {
  const lower = raw.toLowerCase();
  return KEY_ALIASES[lower] ?? lower;
}

/** Parse a canonical binding string into its parts. */
export function parseShortcut(combo: string): ParsedShortcut | null {
  if (!combo) return null;
  const parts = combo.split('+').map((p) => p.trim()).filter(Boolean);
  if (parts.length === 0) return null;
  const parsed: ParsedShortcut = { key: '', mod: false, shift: false, alt: false };
  for (const part of parts) {
    const p = part.toLowerCase();
    if (p === 'mod' || p === 'ctrl' || p === 'control' || p === 'meta' || p === 'cmd' || p === 'command') {
      parsed.mod = true;
    } else if (p === 'shift') {
      parsed.shift = true;
    } else if (p === 'alt' || p === 'option') {
      parsed.alt = true;
    } else {
      parsed.key = normalizeKey(part);
    }
  }
  if (!parsed.key) return null;
  return parsed;
}

/** Canonicalise a binding string (order: mod, alt, shift, key). */
export function canonicalizeShortcut(combo: string): string {
  const p = parseShortcut(combo);
  if (!p) return '';
  const parts: string[] = [];
  if (p.mod) parts.push('mod');
  if (p.alt) parts.push('alt');
  if (p.shift) parts.push('shift');
  parts.push(p.key);
  return parts.join('+');
}

/** Build the canonical binding for a keydown event, or null for modifier-only. */
export function eventToShortcut(e: KeyboardEvent): string | null {
  const key = e.key;
  if (!key) return null;
  if (['Control', 'Shift', 'Alt', 'Meta', 'OS'].includes(key)) return null;
  const parts: string[] = [];
  if (e.ctrlKey || e.metaKey) parts.push('mod');
  if (e.altKey) parts.push('alt');
  if (e.shiftKey) parts.push('shift');
  parts.push(normalizeKey(key));
  return parts.join('+');
}

export function matchesShortcut(combo: string, e: KeyboardEvent): boolean {
  const canonical = canonicalizeShortcut(combo);
  if (!canonical) return false;
  return canonical === eventToShortcut(e);
}

function isMac(): boolean {
  if (typeof navigator === 'undefined') return false;
  const platform = navigator.platform || '';
  const ua = navigator.userAgent || '';
  return /mac|iphone|ipad|ipod/i.test(platform) || /Mac OS X/i.test(ua);
}

/** Human-readable binding, platform aware. */
export function formatShortcut(combo: string): string {
  const p = parseShortcut(combo);
  if (!p) return '';
  const mac = isMac();
  const parts: string[] = [];
  if (p.mod) parts.push(mac ? '⌘' : 'Ctrl');
  if (p.alt) parts.push(mac ? '⌥' : 'Alt');
  if (p.shift) parts.push(mac ? '⇧' : 'Shift');

  let keyLabel = p.key;
  if (keyLabel === 'space') keyLabel = 'Space';
  else if (keyLabel === 'escape') keyLabel = 'Esc';
  else if (keyLabel === 'enter') keyLabel = 'Enter';
  else if (keyLabel === 'arrowup') keyLabel = '↑';
  else if (keyLabel === 'arrowdown') keyLabel = '↓';
  else if (keyLabel === 'arrowleft') keyLabel = '←';
  else if (keyLabel === 'arrowright') keyLabel = '→';
  else if (keyLabel.length === 1) keyLabel = keyLabel.toUpperCase();
  else keyLabel = keyLabel.charAt(0).toUpperCase() + keyLabel.slice(1);

  parts.push(keyLabel);
  return mac ? parts.join('') : parts.join(' + ');
}

export type ShortcutOverrides = Record<string, string>;

export function loadShortcutOverrides(): ShortcutOverrides {
  if (typeof localStorage === 'undefined') return {};
  try {
    const raw = localStorage.getItem(SHORTCUT_OVERRIDES_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return {};
    const out: ShortcutOverrides = {};
    for (const [id, combo] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof combo === 'string') out[id] = combo;
    }
    return out;
  } catch {
    return {};
  }
}

export function saveShortcutOverrides(overrides: ShortcutOverrides): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(SHORTCUT_OVERRIDES_KEY, JSON.stringify(overrides));
  } catch {
    // storage unavailable — overrides remain in-memory for this session
  }
}
