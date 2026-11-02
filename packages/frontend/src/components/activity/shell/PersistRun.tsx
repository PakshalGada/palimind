import { useEffect, useRef } from 'react';
import { isTerminal } from '../model';
import { useActivityState } from '../hooks';
import { persistActivity, type ActivityStore } from '../store';

/** Persists the settled run exactly once so history renders identically. */
export function PersistRun({
  store,
  sessionId,
  messageIndex,
}: {
  store: ActivityStore;
  sessionId: string | null;
  messageIndex: number;
}) {
  const state = useActivityState(store);
  const last = useRef('');

  useEffect(() => {
    if (!state || !sessionId) return;
    if (!isTerminal(state.status)) return;
    const key = `${state.runId}:${state.status}:${messageIndex}`;
    if (last.current === key) return;
    last.current = key;
    const reasoningBuffer = store.buffers.get('reasoning');
    const reasoningText = reasoningBuffer.getSnapshot().text;
    const persisted =
      state.reasoning && reasoningText
        ? { ...state, reasoning: { ...state.reasoning, text: reasoningText } }
        : state;
    persistActivity(sessionId, messageIndex, persisted);
  }, [state, sessionId, messageIndex, store]);

  return null;
}
