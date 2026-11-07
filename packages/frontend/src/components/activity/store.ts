import { BufferRegistry } from './buffers';
import {
  emptyActivity,
  type ActivityEvent,
  type ActivityState,
  type RunMode,
  type ToolStep,
} from './model';
import { reduceEvents } from './reducer';

type Listener = () => void;

/**
 * One run's state and subscriptions. Events are queued and applied at most
 * once per animation frame; every step gets its own listener so a token in one
 * tool cannot re-render its siblings.
 */
export class ActivityStore {
  private state: ActivityState | null;
  private queue: ActivityEvent[] = [];
  private frame: number | null = null;
  private listeners = new Set<Listener>();
  private stepListeners = new Map<string, Set<Listener>>();
  private allowedForRun = new Set<string>();
  /** True when the store was built from persisted history (reloads render
   *  pending approvals as "Requested earlier" instead of pulsing). */
  readonly restored: boolean;
  readonly buffers = new BufferRegistry();

  constructor(initial: ActivityState | null = null, restored = false) {
    this.state = initial;
    this.restored = restored;
  }

  getState = (): ActivityState | null => this.state;

  getStep = (id: string): ToolStep | undefined => {
    const step = this.state?.steps.find((entry) => entry.id === id);
    return step;
  };

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  subscribeStep = (id: string, listener: Listener): (() => void) => {
    let set = this.stepListeners.get(id);
    if (!set) {
      set = new Set();
      this.stepListeners.set(id, set);
    }
    set.add(listener);
    return () => {
      set?.delete(listener);
      if (set && set.size === 0) this.stepListeners.delete(id);
    };
  };

  dispatch(event: ActivityEvent): void {
    if (event.type === 'run.start') {
      // Start immediately so the optimistic thinking dot is replaced in the
      // same frame the run exists; everything else is batched.
      this.queue.push(event);
      this.flush();
      return;
    }
    this.queue.push(event);
    this.schedule();
  }

  dispatchAll(events: readonly ActivityEvent[]): void {
    this.queue.push(...events);
    this.schedule();
  }

  flush(): void {
    if (this.frame !== null) {
      cancelAnimationFrame(this.frame);
      this.frame = null;
    }
    if (this.queue.length === 0) return;
    const events = this.queue;
    this.queue = [];
    const previous = this.state;
    const base = previous ?? emptyActivity('run', 'default');
    const next = reduceEvents(base, events);
    if (previous && next === previous) return;
    this.state = next;
    this.notify(previous, next);
  }

  reset(state: ActivityState | null = null): void {
    this.queue = [];
    this.buffers.reset();
    this.allowedForRun.clear();
    const previous = this.state;
    this.state = state;
    this.notify(previous, state);
  }

  /** Mark a pending approval. Returns undefined when it was not pending. */
  resolveApproval(id: string, decision: 'once' | 'run' | 'deny'): ToolStep | undefined {
    this.flush();
    const step = this.getStep(id);
    // Already resolved (double click, key repeat): never submit twice.
    if (!step || step.status !== 'awaiting_approval') return undefined;
    if (decision === 'run') this.allowedForRun.add(step.name);
    this.dispatch({
      type: 'tool.approval',
      id,
      status: decision === 'deny' ? 'denied' : 'running',
      at: Date.now(),
    });
    // Apply now so the prompt closes before another input event and callers
    // reading getState() (history persistence) see the decision.
    this.flush();
    return step;
  }

  isAllowedForRun(name: string): boolean {
    return this.allowedForRun.has(name);
  }

  /** Seed a completed run for history without replay animation. */
  static fromState(state: ActivityState): ActivityStore {
    return new ActivityStore(state, true);
  }

  private schedule(): void {
    if (this.frame !== null) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = null;
      this.flush();
    });
  }

  private notify(previous: ActivityState | null, next: ActivityState | null): void {
    for (const listener of this.listeners) listener();
    const changed = changedStepIds(previous, next);
    for (const id of changed) {
      const set = this.stepListeners.get(id);
      if (!set) continue;
      for (const listener of set) listener();
    }
  }
}

function changedStepIds(
  previous: ActivityState | null,
  next: ActivityState | null,
): Set<string> {
  const changed = new Set<string>();
  if (!next) return changed;
  const before = new Map((previous?.steps ?? []).map((step) => [step.id, step]));
  for (const step of next.steps) {
    if (before.get(step.id) !== step) changed.add(step.id);
  }
  for (const id of before.keys()) {
    if (!next.steps.some((step) => step.id === id)) changed.add(id);
  }
  return changed;
}

export interface PersistedRun {
  version: 1;
  state: ActivityState;
}

const HISTORY_PREFIX = 'palimind:activity:';

export function activityStorageKey(sessionId: string, messageIndex: number): string {
  return `${HISTORY_PREFIX}${sessionId}:${messageIndex}`;
}

export function persistActivity(
  sessionId: string | null,
  messageIndex: number,
  state: ActivityState,
): void {
  if (!sessionId || typeof localStorage === 'undefined') return;
  try {
    const payload: PersistedRun = { version: 1, state };
    localStorage.setItem(activityStorageKey(sessionId, messageIndex), JSON.stringify(payload));
  } catch {
    // History stays available for the current session even if storage is full.
  }
}

export function readPersistedActivity(
  sessionId: string | null,
  messageIndex: number,
): ActivityState | null {
  if (!sessionId || typeof localStorage === 'undefined') return null;
  try {
    const raw = localStorage.getItem(activityStorageKey(sessionId, messageIndex));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedRun;
    if (parsed.version !== 1 || !parsed.state) return null;
    return normalizePersisted(parsed.state);
  } catch {
    return null;
  }
}

/** Drop any streamed text and force a completed, collapsed rendering. */
function normalizePersisted(state: ActivityState): ActivityState {
  return {
    ...state,
    status: state.status === 'idle' || state.status === 'thinking' ? 'done' : state.status,
    answerStarted: true,
    steps: state.steps.map((step) => {
      const status =
        step.status === 'running' || step.status === 'queued' ? 'cancelled' : step.status;
      return { ...step, status };
    }),
  };
}

export function modeForTitle(mode: RunMode): string {
  if (mode === 'agent') return 'Agent';
  if (mode === 'moe') return 'Mixture of experts';
  if (mode === 'deep_research') return 'Deep research';
  if (mode === 'knowledge_base') return 'Knowledge base';
  return 'Chat';
}
