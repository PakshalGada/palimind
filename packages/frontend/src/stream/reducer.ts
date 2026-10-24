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
        revision: state.revision + 1,
      };
    case 'reset':
      return { ...initialStreamState, revision: state.revision + 1 };
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
