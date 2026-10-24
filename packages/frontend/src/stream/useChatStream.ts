import { useCallback, useEffect, useReducer, useRef } from 'react';
import { useApp } from '../AppContext';
import { createActivityTracker, type ActivityInfo } from './activity';
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

export interface SendRequest {
  /** Query sent to the backend (may be empty for attachments-only sends). */
  text: string;
  /** Text echoed in the live user bubble (defaults to `text`). */
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
  isStreaming: boolean;
  /** Current assistant text (throttled) — used by the artifact panel. */
  liveText: string;
}

/**
 * Owns the chat EventSource, the accumulated stream state and the throttled
 * markdown flush. Rendering lives in the stream components; this hook only
 * turns events into state.
 */
export function useChatStream(): ChatStream {
  const {
    setThinkingText,
    setAgentStates,
    setAgentLoading,
    setActivity,
    setIsGenerating,
    refreshSessions,
  } = useApp();

  const [state, dispatch] = useReducer(streamReducer, initialStreamState);

  const sourceRef = useRef<EventSource | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const flushTimerRef = useRef<number | null>(null);
  const rawRef = useRef('');
  const lastFlushAt = useRef(0);
  const tokensSinceFlush = useRef(0);
  /** Bumped per send so stale refresh callbacks cannot reset a newer stream. */
  const streamIdRef = useRef(0);

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

  /** Push the accumulated raw text into React state, throttled. */
  const flushAnswer = useCallback(
    (force = false) => {
      tokensSinceFlush.current += 1;
      const now = performance.now();
      const due =
        force ||
        now - lastFlushAt.current >= FLUSH_MS ||
        tokensSinceFlush.current >= FLUSH_TOKENS;

      if (due) {
        clearFlushTimer();
        lastFlushAt.current = now;
        tokensSinceFlush.current = 0;
        dispatch({ type: 'setAnswer', text: rawRef.current });
        return;
      }

      if (flushTimerRef.current === null) {
        flushTimerRef.current = window.setTimeout(() => {
          flushTimerRef.current = null;
          lastFlushAt.current = performance.now();
          tokensSinceFlush.current = 0;
          dispatch({ type: 'setAnswer', text: rawRef.current });
        }, FLUSH_MS);
      }
    },
    [clearFlushTimer],
  );

  // Close any connection on unmount.
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
      closeSource();
      clearTimer();
      clearFlushTimer();

      const streamId = ++streamIdRef.current;
      const resetIfCurrent = () => {
        if (streamIdRef.current === streamId) dispatch({ type: 'reset' });
      };

      rawRef.current = '';
      lastFlushAt.current = 0;
      tokensSinceFlush.current = 0;
      dispatch({
        type: 'start',
        userText: request.userText ?? request.text,
        sessionId: request.sessionId,
      });
      setIsGenerating(true);
      setThinkingText('Analyzing your request...');
      setAgentStates([]);
      setAgentLoading(null);

      const tracker = createActivityTracker(setActivity);
      tracker.reset(request.activity);
      if (request.agentLoading) setAgentLoading(request.agentLoading);

      let thinkingBase = 'Analyzing your request';
      let reasoningStarted = false;
      let agentsStarted = false;
      const startedAgents = new Set<number>();
      let answerStarted = false;
      let thoughtDuration: string | null = null;
      const startTime = Date.now();

      const addStep = (kind: string, title: string, detail = '') => {
        thinkingBase = title;
        tracker.addStep(kind, title, detail);
      };
      const addAgentStep = (aid: number, title: string, detail = '') => {
        thinkingBase = title;
        tracker.addAgentStep(aid, title, detail);
      };
      const beginAnswer = () => {
        if (answerStarted) return;
        answerStarted = true;
        tracker.completeActive();
        addStep('answer', 'Answer');
        clearTimer();
        setThinkingText('');
        if (thoughtDuration === null) {
          thoughtDuration = `${((Date.now() - startTime) / 1000).toFixed(1)}s`;
          dispatch({ type: 'setDuration', duration: thoughtDuration });
        }
        dispatch({ type: 'answerStarted' });
      };

      timerRef.current = setInterval(() => {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
        setThinkingText(`${thinkingBase} ${elapsed}s`);
      }, 500);

      const params = new URLSearchParams({
        q: request.text,
        chat_mode: request.mode,
        scope: request.scope,
      });
      if (request.subMode) params.set('llm_sub_mode', request.subMode);
      if (request.sessionId) params.set('session_id', request.sessionId);
      if (request.files?.length) params.set('files', request.files.join(','));

      const eventSource = new EventSource(`/api/chat?${params.toString()}`, { withCredentials: true });
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
        setThinkingText('');
        setAgentStates([]);
        setAgentLoading(null);
        setActivity(null);
        setIsGenerating(false);
        dispatch({ type: 'reset' });
        void refreshSessions().then(resetIfCurrent);
      });

      const finalize = (status: 'done' | 'error') => {
        if (finalized) return;
        finalized = true;
        clearTimer();
        clearFlushTimer();
        flushAnswer(true);
        closeSource();
        setThinkingText('');
        setAgentStates([]);
        setAgentLoading(null);
        setActivity(null);
        setIsGenerating(false);
        dispatch({ type: 'finish', status });
        void refreshSessions().then(resetIfCurrent);
      };

      const handleEvent = (event: StreamEvent) => {
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

          case 'reasoning': {
            const text = String(event.text ?? '').replace(/[>*_]/g, '').trim();
            setThinkingText(text);
            tracker.completeActive();
            addStep(tracker.reasonKind(text), text);
            break;
          }

          case 'thinking': {
            const text = String(event.text ?? '').trim();
            if (!text) break;
            dispatch({ type: 'appendThinking', text });
            if (!reasoningStarted) {
              tracker.completeActive();
              addStep('reason', 'Reasoning');
              reasoningStarted = true;
            }
            tracker.setActiveDetail(text);
            break;
          }

          case 'progress':
            setThinkingText(String(event.text ?? ''));
            break;

          case 'agent_progress': {
            const aid = event.agent_id;
            setAgentStates((prev) => {
              const existing = prev.find((a) => a.agent_id === aid);
              if (existing) {
                return prev.map((a) =>
                  a.agent_id === aid
                    ? {
                        ...a,
                        status: event.status || a.status,
                        task: event.task || a.task,
                      }
                    : a,
                );
              }
              return [
                ...prev,
                {
                  agent_id: aid,
                  label: event.label || `Agent ${aid}`,
                  task: event.task || '',
                  status: event.status || 'working',
                  steps: [],
                },
              ];
            });
            if ((event.status || 'working') === 'complete') {
              tracker.completeAgentStep(aid);
            } else if (!startedAgents.has(aid)) {
              startedAgents.add(aid);
              if (!agentsStarted) {
                agentsStarted = true;
                tracker.completeActive();
              }
              addAgentStep(aid, event.label || `Agent ${aid}`, event.task || '');
            }
            break;
          }

          case 'agent_thinking': {
            const aid = event.agent_id;
            const step = String(event.text ?? '');
            setAgentStates((prev) =>
              prev.map((a) =>
                a.agent_id === aid ? { ...a, steps: [...a.steps, step] } : a,
              ),
            );
            tracker.appendAgentChild(aid, step);
            break;
          }

          case 'agent:thought': {
            const text = String(event.text ?? '').replace(/\s+/g, ' ').trim();
            if (text && !text.startsWith('FINAL_ANSWER')) {
              setThinkingText(text.slice(0, 90));
              tracker.completeActive();
              addStep('thought', 'Thinking', text.slice(0, 400));
            }
            break;
          }

          case 'agent:tool_call':
            setThinkingText(`Using tool: ${String(event.tool || '…')}`);
            tracker.completeActive();
            addStep(
              'tool',
              String(event.tool || 'tool'),
              event.args != null ? JSON.stringify(event.args) : '',
            );
            break;

          case 'agent:effort':
            if (event.level) {
              addStep(
                'effort',
                'Reasoning effort',
                `${event.level} ${event.indicator || ''}`.trim(),
              );
            }
            break;

          case 'agent:plan':
            window.dispatchEvent(
              new CustomEvent('palimind:plan-pending', { detail: event }),
            );
            addStep('plan', 'Plan', `${event.steps?.length || 0} steps`);
            break;

          case 'agent:verification': {
            const report = event.report || {};
            addStep(
              'verification',
              'Verification',
              `${report.passed ? 'passed' : 'needs attention'} · ${Math.round((report.confidence || 0) * 100)}%`,
            );
            break;
          }

          case 'agent:needs_review':
            addStep('review', 'Human review suggested', 'Low-confidence result');
            break;

          case 'orchestrator':
            window.dispatchEvent(
              new CustomEvent('palimind:orchestrator-event', { detail: event.data }),
            );
            break;

          case 'agent:completed': {
            beginAnswer();
            clearTimer();
            setThinkingText('');
            const output = String(event.output ?? '').trim();
            if (output) {
              rawRef.current = output;
              flushAnswer(true);
            }
            break;
          }

          case 'agent:waiting_for_human':
            setThinkingText(`Awaiting approval: ${event.tool || 'action'}`);
            tracker.completeActive();
            addStep('approval', 'Approval required', String(event.tool || ''));
            dispatch({
              type: 'setApproval',
              approval: {
                agentId: String(event.agent_id ?? ''),
                tool: String(event.tool || 'action'),
                args: event.args,
                confidence: event.confidence,
                reasoning: event.reasoning,
              },
            });
            break;

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
            setThinkingText('');
            setAgentStates([]);
            setAgentLoading(null);
            setActivity(null);
            dispatch({ type: 'error', text: String(event.text ?? 'Unknown error') });
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
    [
      closeSource,
      clearTimer,
      clearFlushTimer,
      flushAnswer,
      refreshSessions,
      setActivity,
      setAgentLoading,
      setAgentStates,
      setIsGenerating,
      setThinkingText,
    ],
  );

  return {
    state,
    send,
    stop,
    isStreaming: state.status === 'streaming',
    liveText: state.answer,
  };
}
