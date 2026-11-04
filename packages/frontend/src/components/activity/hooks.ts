import { useCallback, useRef, useSyncExternalStore } from 'react';
import { useEffect, useState } from 'react';
import type { StreamBuffer, BufferSnapshot } from './buffers';
import {
  loadActivitySettings,
  saveActivitySettings,
  type ActivitySettings,
  type ActivityState,
  type ToolStep,
} from './model';
import type { ActivityStore } from './store';

export function useActivityState(store: ActivityStore): ActivityState | null {
  return useSyncExternalStore(store.subscribe, store.getState, store.getState);
}

/** Select a slice; re-renders only when the selected value changes. */
export function useActivitySelector<T>(
  store: ActivityStore | null,
  selector: (state: ActivityState | null) => T,
  isEqual: (a: T, b: T) => boolean = Object.is,
): T {
  const cache = useRef<{ has: boolean; value: T }>({ has: false, value: undefined as T });
  const getSnapshot = useCallback(() => {
    const next = selector(store?.getState() ?? null);
    if (cache.current.has && isEqual(cache.current.value, next)) return cache.current.value;
    cache.current = { has: true, value: next };
    return next;
  }, [store, selector, isEqual]);
  const subscribe = useCallback(
    (listener: () => void) => store?.subscribe(listener) ?? (() => undefined),
    [store],
  );
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function useStep(store: ActivityStore, id: string): ToolStep | undefined {
  const getSnapshot = useCallback(() => store.getStep(id), [store, id]);
  return useSyncExternalStore(
    (listener) => store.subscribeStep(id, listener),
    getSnapshot,
    getSnapshot,
  );
}

export function useBuffer(store: ActivityStore, key: string): BufferSnapshot {
  const buffer: StreamBuffer = store.buffers.get(key);
  const subscribe = useCallback(
    (listener: () => void) => buffer.subscribe(listener),
    [buffer],
  );
  return useSyncExternalStore(subscribe, buffer.getSnapshot, buffer.getSnapshot);
}

/* ── one shared ticker for every live timer ─────────────────────────────── */

const ticker = {
  listeners: new Set<() => void>(),
  interval: null as ReturnType<typeof setInterval> | null,
  now: Date.now(),
  subscribe(listener: () => void) {
    ticker.listeners.add(listener);
    if (ticker.interval === null) {
      ticker.now = Date.now();
      ticker.interval = setInterval(() => {
        ticker.now = Date.now();
        for (const entry of ticker.listeners) entry();
      }, 500);
    }
    return () => {
      ticker.listeners.delete(listener);
      if (ticker.listeners.size === 0 && ticker.interval !== null) {
        clearInterval(ticker.interval);
        ticker.interval = null;
      }
    };
  },
  getSnapshot() {
    return ticker.now;
  },
};

export function useNow(active: boolean): number {
  const [frozen] = useState(() => Date.now());
  const subscribe = useCallback(
    (listener: () => void) => (active ? ticker.subscribe(listener) : () => undefined),
    [active],
  );
  const getSnapshot = useCallback(
    () => (active ? ticker.getSnapshot() : frozen),
    [active, frozen],
  );
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/* ── settings ───────────────────────────────────────────────────────────── */

export function useActivitySettings(): [
  ActivitySettings,
  (patch: Partial<ActivitySettings>) => void,
] {
  const [settings, setSettings] = useState<ActivitySettings>(() => loadActivitySettings());
  const update = useCallback((patch: Partial<ActivitySettings>) => {
    setSettings((previous) => {
      const next = { ...previous, ...patch };
      saveActivitySettings(next);
      return next;
    });
  }, []);
  return [settings, update];
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia(query).matches : false,
  );
  useEffect(() => {
    const media = window.matchMedia(query);
    const onChange = () => setMatches(media.matches);
    media.addEventListener('change', onChange);
    setMatches(media.matches);
    return () => media.removeEventListener('change', onChange);
  }, [query]);
  return matches;
}
