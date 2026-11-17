import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Check,
  Loader2,
  Sparkles,
  X,
} from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';

/**
 * First-run onboarding checklist.
 *
 * Four steps that attack the #1 local-first failure modes, in order:
 *   1. backend connected  → probed live + `palimind:connection` events
 *   2. pick a model       → Ollama reachable and at least one model pulled
 *   3. index a folder     → at least one knowledge base registered
 *   4. ask a question     → persisted on the first user message
 *
 * Completion persists across restarts: steps 1–3 are re-derived from the
 * server each mount, step 4 from localStorage, so checkmarks survive reloads
 * without a server-side store. The card hides itself when complete or
 * explicitly dismissed.
 */

const STORAGE_KEY = 'palimind:onboarding-v1';
const ASKED_KEY = 'palimind:onboarding-asked';
const PROBE_INTERVAL_MS = 12_000;

interface Persisted {
  dismissed?: boolean;
}

function readPersisted(): Persisted {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as Persisted;
  } catch {
    return {};
  }
}

function mergePersisted(patch: Persisted): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...readPersisted(), ...patch }));
  } catch {
    // storage unavailable
  }
}

interface OnboardingState {
  backend: boolean;
  model: boolean;
  folder: boolean;
  asked: boolean;
  dismissed: boolean;
  checking: boolean;
}

interface StepAction {
  label: string;
  run: () => void;
}

interface OnboardingStep {
  id: 'backend' | 'model' | 'folder' | 'ask';
  label: string;
  hint: string;
  done: boolean;
  action?: StepAction;
}

export default function OnboardingChecklist() {
  const { setActiveView } = useApp();
  const [state, setState] = useState<OnboardingState>(() => ({
    backend: false,
    model: false,
    folder: false,
    asked:
      typeof localStorage !== 'undefined' && localStorage.getItem(ASKED_KEY) === '1',
    dismissed: readPersisted().dismissed === true,
    checking: false,
  }));
  const stateRef = useRef(state);
  stateRef.current = state;

  const refresh = useCallback(async () => {
    setState(prev => ({ ...prev, checking: true }));
    const [fields, models, sessions] = await Promise.allSettled([
      api.fields.list(),
      api.models.list(),
      api.sessions.list('field'),
    ]);
    const askedFlag = localStorage.getItem(ASKED_KEY) === '1';
    const asked =
      askedFlag ||
      (sessions.status === 'fulfilled' &&
        (sessions.value.sessions ?? []).some(
          (session: { messages?: { role: string }[] }) =>
            (session.messages ?? []).some((message: { role: string }) => message.role === 'user'),
        ));
    setState(prev => ({
      ...prev,
      // Any successful API response proves the engine is up (api.ts also
      // fires `palimind:connection` on failures, handled by the listener).
      backend: fields.status === 'fulfilled',
      model:
        models.status === 'fulfilled' &&
        models.value.status !== 'offline' &&
        (models.value.models?.length ?? 0) > 0,
      folder:
        fields.status === 'fulfilled' && (fields.value.fields?.length ?? 0) > 0,
      asked,
      checking: false,
    }));
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Re-probe on the signals that can flip a step while the card is visible.
  useEffect(() => {
    const onFieldAdded = () => void refresh();
    const onConnection = (event: Event) => {
      const detail = (event as CustomEvent<{ ok?: boolean }>).detail;
      if (detail?.ok) void refresh();
    };
    const onMessageSent = () => {
      try {
        localStorage.setItem(ASKED_KEY, '1');
      } catch {
        // ignore
      }
      setState(prev => ({ ...prev, asked: true }));
    };
    window.addEventListener('palimind:field-added', onFieldAdded);
    window.addEventListener('palimind:connection', onConnection);
    window.addEventListener('palimind:message-sent', onMessageSent);
    return () => {
      window.removeEventListener('palimind:field-added', onFieldAdded);
      window.removeEventListener('palimind:connection', onConnection);
      window.removeEventListener('palimind:message-sent', onMessageSent);
    };
  }, [refresh]);

  // Keep probing until everything is checked (and stop once it is).
  const allDone =
    state.backend && state.model && state.folder && state.asked;
  useEffect(() => {
    if (state.dismissed || allDone) return;
    const timer = window.setInterval(() => void refresh(), PROBE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [state.dismissed, allDone, refresh]);

  const dismiss = useCallback(() => {
    mergePersisted({ dismissed: true });
    setState(prev => ({ ...prev, dismissed: true }));
  }, []);

  const pickModel = useCallback(() => {
    // The model picker lives in the composer, so go to chat first, then
    // open it once the listener has mounted.
    setActiveView('chat');
    window.setTimeout(() => {
      window.dispatchEvent(new CustomEvent('palimind:open-model-switcher'));
    }, 80);
  }, [setActiveView]);

  const steps: OnboardingStep[] = useMemo(
    () => [
      {
        id: 'backend' as const,
        label: 'Connect the local engine',
        hint: state.backend
          ? 'Engine reachable — everything runs on this machine'
          : 'Start the PaliMind backend and retry',
        done: state.backend,
        action: state.backend
          ? undefined
          : { label: 'Retry', run: () => void refresh() },
      },
      {
        id: 'model' as const,
        label: 'Pick a model',
        hint: state.model
          ? 'A local model is installed and ready'
          : 'Choose an installed model, or pull one (e.g. llama3.2)',
        done: state.model,
        action: state.model ? undefined : { label: 'Choose', run: pickModel },
      },
      {
        id: 'folder' as const,
        label: 'Index a knowledge base',
        hint: state.folder
          ? 'Your documents are indexed and searchable'
          : 'Select a folder of documents to index locally',
        done: state.folder,
        action: state.folder
          ? undefined
          : {
              label: 'Choose folder',
              run: () =>
                window.dispatchEvent(new CustomEvent('palimind:open-dir-picker')),
            },
      },
      {
        id: 'ask' as const,
        label: 'Ask your first question',
        hint: state.asked
          ? 'You are all set — answers stay private'
          : 'Send a message in chat to finish setup',
        done: state.asked,
        action: state.asked
          ? undefined
          : { label: 'Start chat', run: () => setActiveView('chat') },
      },
    ],
    [state.backend, state.model, state.folder, state.asked, pickModel, refresh, setActiveView],
  );

  if (state.dismissed || allDone) return null;

  const doneCount = steps.filter(step => step.done).length;

  return (
    <div className="onboarding-card" role="group" aria-label="Getting started checklist">
      <div className="onboarding-head">
        <span className="onboarding-title">
          <Sparkles size={13} />
          Get set up
        </span>
        <span className="onboarding-progress" aria-live="polite">
          {state.checking ? <Loader2 size={11} className="onboarding-spin" /> : null}
          {doneCount}/{steps.length} done
        </span>
        <button
          type="button"
          className="onboarding-dismiss"
          title="Hide setup checklist"
          aria-label="Hide setup checklist"
          onClick={dismiss}
        >
          <X size={13} />
        </button>
      </div>
      <ul className="onboarding-steps">
        {steps.map(step => (
          <li
            key={step.id}
            className={`onboarding-step${step.done ? ' is-done' : ''}`}
          >
            <span className="onboarding-check" aria-hidden="true">
              {step.done ? <Check size={11} /> : null}
            </span>
            <span className="onboarding-step-text">
              <span className="onboarding-step-label">{step.label}</span>
              <span className="onboarding-step-hint">{step.hint}</span>
            </span>
            {!step.done && step.action && (
              <button
                type="button"
                className="onboarding-step-action"
                onClick={step.action.run}
              >
                {step.action.label}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
