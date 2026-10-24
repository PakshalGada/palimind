import { createContext, useContext } from 'react';
import type { ChatStream } from './useChatStream';
import type { StreamState, VideoTarget } from './types';

/** Frequently-changing stream state — consumed by the message surface. */
export interface ChatStreamStateValue {
  state: StreamState;
  isStreaming: boolean;
  /** Current assistant text (throttled) — artifacts read this live. */
  liveText: string;
  openVideo: (target: VideoTarget) => void;
}

/** Stable actions — consumed by the composer (never re-renders per token). */
export interface ChatStreamActions {
  send: ChatStream['send'];
  stop: () => void;
}

export const ChatStreamContext = createContext<ChatStreamStateValue | null>(null);
export const ChatStreamActionsContext = createContext<ChatStreamActions | null>(null);

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
