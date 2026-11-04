import { createContext, useContext } from 'react';
import type { ActivityStore } from '@/components/activity/store';
import type { ChatStream } from './useChatStream';
import type { ActivityInfo } from './activity';
import type { StreamState, VideoTarget } from './types';

/** Frequently-changing stream state — consumed by the message surface. */
export interface ChatStreamStateValue {
  state: StreamState;
  isStreaming: boolean;
  /** Current assistant text (throttled) — artifacts read this live. */
  liveText: string;
  openVideo: (target: VideoTarget) => void;
  activityStore: ActivityStore;
  /** The activity block of the in-flight (or last) request, when any. */
  lastActivity: ActivityInfo | null;
}

/** Stable actions — consumed by the composer (never re-renders per token). */
export interface ChatStreamActions {
  send: ChatStream['send'];
  stop: () => void;
  retry: () => void;
}

/**
 * The raw activity surface handles — the store and the last request's activity
 * block. The reference is stable across tokens, so consumers that subscribe
 * store slices themselves (like the composer caption) never re-render per
 * token either.
 */
export interface ActivitySurfaceValue {
  store: ActivityStore;
  lastActivity: ChatStream['lastActivity'];
}

export const ChatStreamContext = createContext<ChatStreamStateValue | null>(null);
export const ChatStreamActionsContext = createContext<ChatStreamActions | null>(null);
export const ActivitySurfaceContext = createContext<ActivitySurfaceValue | null>(null);

export function useChatStreamContext(): ChatStreamStateValue {
  const ctx = useContext(ChatStreamContext);
  if (!ctx) throw new Error('useChatStreamContext must be used within ChatStreamProvider');
  return ctx;
}

export function useChatStreamActions(): ChatStreamActions {
  const ctx = useContext(ChatStreamActionsContext);
  if (!ctx) throw new Error('useChatStreamActions must be used within ChatStreamProvider');
  return ctx;
}

/** Stable handles to the activity store — safe for token-rate subscriptions. */
export function useActivitySurface(): ActivitySurfaceValue {
  const ctx = useContext(ActivitySurfaceContext);
  if (!ctx) throw new Error('useActivitySurface must be used within ChatStreamProvider');
  return ctx;
}

/** Like useActivitySurface, but null outside the provider (e.g. isolated composers). */
export function useOptionalActivitySurface(): ActivitySurfaceValue | null {
  return useContext(ActivitySurfaceContext);
}
