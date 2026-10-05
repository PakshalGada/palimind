import { useEffect, useRef, useSyncExternalStore } from 'react';
import {
  clearCommandHandler,
  getCommandVersion,
  hasCommandHandler,
  setCommandHandler,
  subscribeCommands,
  type CommandHandler,
} from './registry';

/**
 * Register a handler for a catalog command for as long as the component is
 * mounted. The handler is kept in a ref so passing an inline closure does not
 * re-register on every render (which would churn the registry).
 */
export function useCommandHandler(id: string, handler: CommandHandler): void {
  const ref = useRef(handler);
  ref.current = handler;

  useEffect(() => {
    const stable: CommandHandler = () => ref.current();
    setCommandHandler(id, stable);
    return () => clearCommandHandler(id, stable);
  }, [id]);
}

/** Register several handlers at once. */
export function useCommandHandlers(map: Record<string, CommandHandler>): void {
  const ref = useRef(map);
  ref.current = map;

  const ids = Object.keys(map).sort().join('|');
  useEffect(() => {
    const stable: Record<string, CommandHandler> = {};
    const registered: string[] = [];
    for (const id of Object.keys(ref.current)) {
      const fn: CommandHandler = () => ref.current[id]();
      stable[id] = fn;
      setCommandHandler(id, fn);
      registered.push(id);
    }
    return () => {
      for (const id of registered) clearCommandHandler(id, stable[id]);
    };
  }, [ids]);
}

/** Reactive registry version; changes whenever handlers are added/removed. */
export function useCommandRegistryVersion(): number {
  return useSyncExternalStore(subscribeCommands, getCommandVersion, getCommandVersion);
}

/** Reactive snapshot of the set of command ids that currently have handlers. */
export function useAvailableCommands(): (id: string) => boolean {
  // Re-render whenever a handler is added or removed, then expose the
  // (module-stable) predicate.
  useCommandRegistryVersion();
  return hasCommandHandler;
}
