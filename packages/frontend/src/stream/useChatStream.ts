import { startTransition, useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { useApp } from '../AppContext';
import { api } from '../api';
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

/** Upper bound on waiting for the server to save a stopped turn. */
const STOP_TIMEOUT_MS = 5_000;

/** Client-chosen stream id so Stop can address a stream before its first event. */
function makeStreamKey(): string {
  const cryptoApi = globalThis.crypto as Crypto | undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID().replace(/-/g, '');
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

/** Ask the server to stop the stream and persist its partial answer. */
async function stopOnServer(streamKey: string): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      api.chat.stop(streamKey).catch(() => undefined),
      new Promise<void>((resolve) => {
        timer = setTimeout(resolve, STOP_TIMEOUT_MS);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

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
  /** Enable live web search for this turn (all chat modes). */
  webSearch?: boolean;
  /** What the user typed when `text` is an expanded hidden skill prompt. */
  displayText?: string;
  /** Document-mode retrieval strategy: auto (default), off, or always. */
  ragMode?: 'auto' | 'off' | 'always';
  files?: string[];
  attachmentIds?: string[];
  /** Marker for a reply quote; stored on the user message. */
  replyTo?: number;
  activity: ActivityInfo;
  agentLoading?: { seed: string; name: string } | null;
}

export interface ChatStream {
  state: StreamState;
  send: (request: SendRequest) => void;
  stop: () => void;
  retry: () => void;
  isStreaming: boolean;
  /** The activity block of the in-flight (or last) request, for the caption avatar. */
  lastActivity: ActivityInfo | null;
  liveText: string;
}

/**
 * Owns the chat EventSource, the accumulated stream state and the throttled
 * markdown flush. Activity events are forwarded to the shared normalized store;
 * rendering lives in the activity surface.
 */
export function useChatStream(activityStore: ActivityStore): ChatStream {
  const { setIsGenerating, refreshSessions, activeSessionId, setActiveSessionId } = useApp();
  const activeSessionRef = useRef(activeSessionId);
  useEffect(() => {
    activeSessionRef.current = activeSessionId;
  }, [activeSessionId]);
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
  const [lastActivity, setLastActivity] = useState<ActivityInfo | null>(null);

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
      setLastActivity(request.activity ?? null);
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
      params.set('web_search', request.webSearch === false ? 'false' : 'true');
      if (request.sessionId) params.set('session_id', request.sessionId);
      if (request.displayText) params.set('display_query', request.displayText);
      if (request.ragMode) params.set('rag_mode', request.ragMode);
      if (request.files?.length) params.set('files', request.files.join(','));
      if (request.attachmentIds?.length) params.set('attachment_ids', request.attachmentIds.join(','));
      if (request.replyTo) params.set('reply_to', String(request.replyTo));
      // The server echoes this in its first `session` event; Stop uses it.
      let streamKey = makeStreamKey();
      params.set('stream_id', streamKey);

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
        // The server saves the partial answer before answering the stop call,
        // so the refresh below already contains it (no flash of lost text).
        void stopOnServer(streamKey)
          .then(() => refreshSessions())
          .then(resetIfCurrent);
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
        // Let the Agents workspace reveal the shared browser as soon as an
        // agent starts using it, instead of leaving the work invisible.
        if (event.type === 'agent:tool_call' && typeof event.tool === 'string') {
          if (event.tool.startsWith('browser_') || event.tool === 'desktop_browser') {
            window.dispatchEvent(
              new CustomEvent('palimind:browser-active', {
                detail: { tool: event.tool, args: event.args },
              }),
            );
          }
        }
        switch (event.type) {
          case 'session': {
            if (typeof event.stream_id === 'string' && event.stream_id) streamKey = event.stream_id;
            const id = typeof event.id === 'string' && event.id ? event.id : null;
            if (!id) break;
            dispatch({ type: 'setSession', sessionId: id });
            // A brand-new chat had no id; follow it into the session the server
            // created, unless the user has already moved to another chat.
            if (request.sessionId === null && activeSessionRef.current === null) {
              setActiveSessionId(id);
            }
            break;
          }

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

          case 'research_plan':
            // Deep research pauses for plan review; the modal approves or
            // cancels the pending plan through the research API.
            window.dispatchEvent(
              new CustomEvent('palimind:research-plan', { detail: event }),
            );
            break;

          case 'orchestrator':
            window.dispatchEvent(
              new CustomEvent('palimind:orchestrator-event', { detail: event.data }),
            );
            break;

          case 'agent:usage': {
            const prompt = Number(event.prompt_tokens ?? 0);
            const completion = Number(event.completion_tokens ?? 0);
            const cost = Number(event.estimated_cost_usd ?? 0);
            dispatch({
              type: 'setUsage',
              usage: {
                prompt_tokens: Number.isFinite(prompt) ? prompt : 0,
                completion_tokens: Number.isFinite(completion) ? completion : 0,
                estimated_cost_usd: Number.isFinite(cost) ? cost : 0,
              },
            });
            break;
          }

          case 'agent:escalation':
            dispatch({
              type: 'setEscalation',
              escalation: event.skipped
                ? `Escalation skipped${event.reason ? ` — ${event.reason}` : ''}`
                : `Escalated to ${String(event.to || 'a stronger model')}`,
            });
            break;

          case 'agent:suggestions':
            dispatch({
              type: 'setSuggestions',
              suggestions: (event.suggestions ?? []).filter(
                (item): item is string => typeof item === 'string' && item.trim().length > 0,
              ),
            });
            break;

          case 'agent:activity':
            dispatch({
              type: 'setActivity',
              label: typeof event.label === 'string' && event.label ? event.label : null,
            });
            break;

          case 'agent:model_notice':
            dispatch({
              type: 'setModelNotice',
              notice: {
                kind: String(event.kind || 'provider'),
                provider: String(event.provider || ''),
                model: String(event.model || ''),
                action: String(event.action || ''),
                message: String(event.message || 'The model is not available.'),
              },
            });
            break;

          case 'agent:completed': {
            beginAnswer();
            clearTimer();
            const output = String(event.output ?? '').trim();
            if (output) {
              rawRef.current = output;
              flushAnswer(true);
            }
            if (event.usage) {
              dispatch({
                type: 'setUsage',
                usage: {
                  prompt_tokens: Number(event.usage.prompt_tokens ?? 0),
                  completion_tokens: Number(event.usage.completion_tokens ?? 0),
                  estimated_cost_usd: Number(event.usage.estimated_cost_usd ?? 0),
                },
              });
            }
            if (event.suggestions?.length) {
              dispatch({ type: 'setSuggestions', suggestions: event.suggestions });
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
            dispatch({ type: 'error', text: String(event.text || 'Something went wrong.') });
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
        if (!finalized) dispatch({ type: 'error', text: 'Connection to the server was lost.' });
        finalize('error');
      };
    },
    [
      activityStore,
      closeSource,
      clearTimer,
      clearFlushTimer,
      flushAnswer,
      refreshSessions,
      setActiveSessionId,
      setIsGenerating,
    ],
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
    lastActivity,
    liveText: state.answer,
  };
}
