/**
 * Runtime command registry.
 *
 * The catalog (./catalog) declares *what* commands exist; this module tracks
 * *which* of them can currently run and lets any component provide the
 * behaviour. It is a tiny observable singleton so that imperative callers
 * (global keyboard handler, command palette, message toolbar) can invoke a
 * command without threading callbacks through React context.
 */

export type CommandHandler = () => void | Promise<void>;

const handlers = new Map<string, CommandHandler>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version += 1;
  for (const fn of listeners) fn();
}

/** Monotonic counter bumped whenever the set of handlers changes. */
export function getCommandVersion(): number {
  return version;
}

/** Register (or replace) the handler for a command id. */
export function setCommandHandler(id: string, handler: CommandHandler): void {
  const had = handlers.has(id);
  handlers.set(id, handler);
  if (!had) emit();
}

/** Remove a command handler, but only if it is still the one passed in. */
export function clearCommandHandler(id: string, handler: CommandHandler): void {
  if (handlers.get(id) !== handler) return;
  handlers.delete(id);
  emit();
}

export function hasCommandHandler(id: string): boolean {
  return handlers.has(id);
}

export function runCommand(id: string): boolean {
  const handler = handlers.get(id);
  if (!handler) return false;
  void handler();
  return true;
}

export function subscribeCommands(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
