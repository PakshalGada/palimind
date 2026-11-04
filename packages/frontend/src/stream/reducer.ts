import { initialStreamState, type StreamAction, type StreamState } from './types';

/**
 * Pure stream reducer. Every visible change bumps `revision`, which lets the
 * chat surface auto-scroll without diffing strings.
 */
export function streamReducer(state: StreamState, action: StreamAction): StreamState {
  const next = (patch: Partial<StreamState>): StreamState => ({
    ...state,
    ...patch,
    revision: state.revision + 1,
  });

  switch (action.type) {
    case 'start':
      return {
        ...initialStreamState,
        status: 'streaming',
        userText: action.userText,
        sessionId: action.sessionId,
        startedAt: Date.now(),
        revision: state.revision + 1,
      };
    case 'reset':
      return { ...initialStreamState, revision: state.revision + 1 };
    case 'setSession':
      // A turn never moves between sessions once bound; only a brand-new chat
      // (sessionId null) adopts the id the server created/used.
      if (state.status === 'idle' || state.sessionId !== null || !action.sessionId) return state;
      return next({ sessionId: action.sessionId });
    case 'setAnswer':
      if (action.text === state.answer) return state;
      return next({ answer: action.text });
    case 'appendThinking':
      if (!action.text) return state;
      return next({ thinking: state.thinking + action.text });
    case 'setSources':
      return next({ sources: action.sources });
    case 'setMediaCitations':
      return next({ mediaCitations: action.citations });
    case 'setTextCitations':
      return next({ textCitations: action.citations });
    case 'setCitations':
      return next({ citations: action.citations });
    case 'setApproval':
      return next({ approval: action.approval });
    case 'setDuration':
      return next({ thoughtDuration: action.duration });
    case 'answerStarted':
      if (state.answerStarted) return state;
      return next({ answerStarted: true });
    case 'error':
      return next({ error: action.text });
    case 'finish':
      return next({ status: action.status });
    default:
      return state;
  }
}

/**
 * Whether the live turn belongs in the conversation being viewed. A turn whose
 * session is not known yet (brand-new chat, before the server's `session`
 * event) only shows in the "no session" view it was started from, so switching
 * to another conversation mid-stream never displays it there.
 */
export function streamBelongsTo(state: StreamState, activeSessionId: string | null): boolean {
  return state.status !== 'idle' && state.sessionId === activeSessionId;
}
