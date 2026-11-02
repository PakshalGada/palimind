import { startTransition, useCallback, useEffect, useReducer, useRef } from 'react';
import { useApp } from '../AppContext';
import { modeFromActivityMode } from '@/components/activity/adaptRun';
import { RunRecorder } from '@/components/activity/recorder';
import type { ActivityStore } from '@/components/activity/store';
import type { ActivityInfo } from './activity';
import { streamReducer } from './reducer';
import {
  citationPayloadFromEvent,
  initialStreamState,
  parseStreamEvent,
  type StreamEvent,
  type StreamState,
} from './types';

/** Re-render the markdown buffer at most every 64ms (or every 4 tokens). */
const FLUSH_MS = 64;
const FLUSH_TOKENS = 4;

function flushIntervalFor(length: number): number {
  if (length > 12_000) return 220;
  if (length > 4_000) return 130;
  return FLUSH_MS;
}

export interface SendRequest {
  text: string;
  userText?: string;
  mode: 'llm' | 'document';
  scope: string;
  sessionId: string | null;
  subMode?: string;
  files?: string[];
  activity: ActivityInfo;
  agentLoading?: { seed: string; name: string } | null;
}

export interface ChatStream {
  state: StreamState;
  send: (request: SendRequest) => void;
  stop: () => void;
  retry: () => void;
  isStreaming: boolean;
  liveText: string;
}

/**
 * Owns the chat EventSource, the accumulated stream state and the throttled
 * markdown flush. Activity events are forwarded to the shared normalized store;
 * rendering lives in the activity surface.
 */
export function useChatStream(activityStore: ActivityStore): ChatStream {
  const { setIsGenerating, refreshSessions } = useApp();
  const [state, dispatch] = useReducer(streamReducer, initialStreamState);

  const sourceRef = useRef<EventSource | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const flushTimerRef = useRef<number | null>(null);
  const rawRef = useRef('');
  const lastFlushAt = useRef(0);
  const tokensSinceFlush = useRef(0);
  const streamIdRef = useRef(0);
  const lastRequestRef = useRef<SendRequest | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const clearFlushTimer = useCallback(() => {
    if (flushTimerRef.current !== null) {
      window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
  }, []);

  const closeSource = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  const flushAnswer = useCallback(
    (force = false) => {
      tokensSinceFlush.current += 1;
      const now = performance.now();
      const interval = flushIntervalFor(rawRef.current.length);
      const due =
        force ||
        now - lastFlushAt.current >= interval ||
        tokensSinceFlush.current >= FLUSH_TOKENS;

      const scheduledFor = streamIdRef.current;
      const commit = () => {
        if (streamIdRef.current !== scheduledFor) return;
        const text = rawRef.current;
        if (force) dispatch({ type: 'setAnswer', text });
        else startTransition(() => dispatch({ type: 'setAnswer', text }));
      };

      if (due) {
        clearFlushTimer();
        lastFlushAt.current = now;
        tokensSinceFlush.current = 0;
        commit();
        return;
      }

      if (flushTimerRef.current === null) {
        flushTimerRef.current = window.setTimeout(() => {
          flushTimerRef.current = null;
          lastFlushAt.current = performance.now();
          tokensSinceFlush.current = 0;
          commit();
        }, interval);
      }
    },
    [clearFlushTimer],
  );

  useEffect(() => {
    return () => {
      sourceRef.current?.close();
      sourceRef.current = null;
      if (timerRef.current !== null) clearInterval(timerRef.current);
      if (flushTimerRef.current !== null) window.clearTimeout(flushTimerRef.current);
    };
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const send = useCallback(
    (request: SendRequest) => {
      lastRequestRef.current = request;
      closeSource();
      clearTimer();
      clearFlushTimer();

      const streamId = ++streamIdRef.current;
      const resetIfCurrent = () => {
        if (streamIdRef.current === streamId) dispatch({ type: 'reset' });
      };

      const mode = modeFromActivityMode(request.activity.mode);
      const runId = `run-${streamId}`;
      const recorder = new RunRecorder(activityStore, mode);
      activityStore.reset(null);
      recorder.start(runId, request.activity.title);

      rawRef.current = '';
      lastFlushAt.current = 0;
      tokensSinceFlush.current = 0;
      dispatch({
        type: 'start',
        userText: request.userText ?? request.text,
        sessionId: request.sessionId,
      });
      setIsGenerating(true);

      let answerStarted = false;
      let thoughtDuration: string | null = null;
      const startTime = Date.now();

      const beginAnswer = () => {
        if (answerStarted) return;
        answerStarted = true;
        recorder.beginAnswer();
        clearTimer();
        if (thoughtDuration === null) {
          thoughtDuration = `${((Date.now() - startTime) / 1000).toFixed(1)}s`;
          dispatch({ type: 'setDuration', duration: thoughtDuration });
        }
        dispatch({ type: 'answerStarted' });
      };

      const params = new URLSearchParams({
        q: request.text,
        chat_mode: request.mode,
        scope: request.scope,
      });
      if (request.subMode) params.set('llm_sub_mode', request.subMode);
      if (request.sessionId) params.set('session_id', request.sessionId);
      if (request.files?.length) params.set('files', request.files.join(','));

      const eventSource = new EventSource(`/api/chat?${params.toString()}`, {
        withCredentials: true,
      });
      sourceRef.current = eventSource;

      let finalized = false;

      const abortCtrl = new AbortController();
      abortRef.current = abortCtrl;
      abortCtrl.signal.addEventListener('abort', () => {
        if (finalized) return;
        finalized = true;
        closeSource();
        clearTimer();
        clearFlushTimer();
        flushAnswer(true);
        setIsGenerating(false);
        recorder.end('stopped');
        dispatch({ type: 'finish', status: 'done' });
        void refreshSessions().then(resetIfCurrent);
      });

      const finalize = (status: 'done' | 'error') => {
        if (finalized) return;
        finalized = true;
        clearTimer();
        clearFlushTimer();
        flushAnswer(true);
        closeSource();
        setIsGenerating(false);
        recorder.end(status);
        dispatch({ type: 'finish', status });
        void refreshSessions().then(resetIfCurrent);
      };

      const handleEvent = (event: StreamEvent) => {
        recorder.observe(event);
        switch (event.type) {
          case 'research_plan':
            window.dispatchEvent(
              new CustomEvent('palimind:research-plan', {
                detail: { plan_id: event.plan_id, plan: event.plan, query: request.text },
              }),
            );
            break;

          case 'sources': {
            const sources = event.sources ?? [];
            if (sources.length) {
              rawRef.current = `*Sources: ${sources.join(', ')}*\n\n`;
              flushAnswer(true);
            }
            dispatch({ type: 'setSources', sources });
            break;
          }

          case 'media_citations':
            dispatch({ type: 'setMediaCitations', citations: event.citations ?? [] });
            break;

          case 'citations':
            dispatch({ type: 'setTextCitations', citations: event.citations ?? [] });
            break;

          case 'citation_map': {
            const payload = citationPayloadFromEvent(event);
            dispatch({ type: 'setCitations', citations: payload });
            if (payload.text) {
              rawRef.current = payload.text;
              flushAnswer(true);
            }
            break;
          }

          case 'agent:plan':
            window.dispatchEvent(new CustomEvent('palimind:plan-pending', { detail: event }));
            break;

          case 'orchestrator':
            window.dispatchEvent(
              new CustomEvent('palimind:orchestrator-event', { detail: event.data }),
            );
            break;

          case 'agent:completed': {
            beginAnswer();
            clearTimer();
            const output = String(event.output ?? '').trim();
            if (output) {
              rawRef.current = output;
              flushAnswer(true);
            }
            break;
          }

          case 'agent:token':
            if (event.reset) {
              rawRef.current = '';
              flushAnswer(true);
              break;
            }
            if (event.text) {
              beginAnswer();
              rawRef.current += event.text;
              flushAnswer();
            }
            break;

          case 'token':
            if (event.text) {
              beginAnswer();
              rawRef.current += event.text;
              flushAnswer();
            }
            break;

          case 'answer_final':
            if (typeof event.text === 'string' && event.text) {
              rawRef.current = event.text;
              flushAnswer(true);
            }
            break;

          case 'error':
            clearTimer();
            finalize('error');
            break;

          case 'done':
            finalize('done');
            break;

          default:
            break;
        }
      };

      eventSource.onmessage = (message) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(message.data);
        } catch {
          return;
        }
        const event = parseStreamEvent(parsed);
        if (event) handleEvent(event);
      };

      eventSource.onerror = () => {
        finalize('error');
      };
    },
    [activityStore, closeSource, clearTimer, clearFlushTimer, flushAnswer, refreshSessions, setIsGenerating],
  );

  const retry = useCallback(() => {
    const request = lastRequestRef.current;
    if (request) send(request);
  }, [send]);

  return {
    state,
    send,
    stop,
    retry,
    isStreaming: state.status === 'streaming',
    liveText: state.answer,
  };
}
