import { useEffect, useMemo } from 'react';
import { COMMANDS } from '../commands/catalog';
import { hasCommandHandler, runCommand } from '../commands/registry';
import type { ShortcutOverrides } from '../utils/shortcuts';
import { canonicalizeShortcut, eventToShortcut } from '../utils/shortcuts';

/**
 * While true the global shortcut handler ignores every key. Used by the
 * shortcut recorder so the combination being captured is not also executed.
 */
let suspended = false;
export function setShortcutsSuspended(value: boolean): void {
  suspended = value;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  return target.isContentEditable;
}

interface Options {
  /** Overrides loaded from settings, keyed by command id. */
  overrides: ShortcutOverrides;
  /** When true, all bindings are ignored (e.g. another modal is recording). */
  disabled?: boolean;
}

/**
 * Installs the global keydown listener that maps bindings to commands. Only
 * commands with a registered handler are intercepted, so unbound/disabled
 * commands never swallow browser or OS keys.
 */
export function useKeyboardShortcuts({ overrides, disabled }: Options): void {
  const bindingMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const cmd of COMMANDS) {
      const combo = overrides[cmd.id] ?? cmd.defaultShortcut;
      if (!combo) continue;
      const canonical = canonicalizeShortcut(combo);
      if (!canonical) continue;
      // First binding wins so a user override on one command can't be
      // shadowed by a later default.
      if (!map.has(canonical)) map.set(canonical, cmd.id);
    }
    return map;
  }, [overrides]);

  useEffect(() => {
    if (disabled) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (suspended) return;
      const combo = eventToShortcut(e);
      if (!combo) return;
      const commandId = bindingMap.get(combo);
      if (!commandId) return;
      if (!hasCommandHandler(commandId)) return;

      // Modifier chords are safe to intercept even inside a text field; plain
      // keys (if a user binds one) are not, so leave those to the field.
      const hasModifier = e.ctrlKey || e.metaKey || e.altKey;
      if (!hasModifier && isEditableTarget(e.target)) return;

      e.preventDefault();
      e.stopPropagation();
      runCommand(commandId);
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [bindingMap, disabled]);
}
