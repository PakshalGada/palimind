import { useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  hasPendingApproval,
  isTerminal,
  type ActivityState,
  type PlanStep,
  type QuestionState,
  type ToolStep,
} from '../model';
import { api } from '../../../api';
import { captionFor } from '../caption';
import AgentAvatar from '../../AgentAvatar';
import { botStateForRun, configFromSeed, type BotAvatarConfig } from '../../../bots/config';
import { useActivitySettings, useMediaQuery } from '../hooks';
import { PixelIcon } from '../../pixel/PixelIcon';
import type { PixelSprite } from '../../pixel/sprites';
import { Icon } from '../icons';
import { Kbd } from '../primitives/Kbd';
import { LiveTimer } from '../primitives/LiveTimer';
import { SourceStack } from '../primitives/SourceStack';
import { StatusIcon } from '../primitives/StatusIcon';
import type { ActivityStore } from '../store';
import { getToolDefinition } from '../toolRegistry';
import { ReasoningBlock } from './ReasoningBlock';
import { RunTimeline } from './RunTimeline';
import { ThinkingIndicator } from './ThinkingIndicator';
import { PhaseSpine } from './PhaseSpine';
import type { GrantDecision } from './PermissionGrant';
import type { ActivityAgentAvatar } from '../../../AppContext';

const DEFAULT_SEED = 'palimind-assistant';
const DEFAULT_AVATAR: BotAvatarConfig = configFromSeed(DEFAULT_SEED);

const TOOL_PIXEL: Record<string, PixelSprite> = {
  search: 'search',
  page: 'book',
  feed: 'graph',
  file: 'folder',
  tree: 'projects',
  matches: 'search',
  diff: 'terminal',
  passages: 'book',
  graph: 'graph',
  data: 'package',
  'code-run': 'terminal',
  text: 'book',
  subagent: 'bot',
  browser: 'graph',
  iot: 'terminal',
  weather: 'sun',
  visual: 'projects',
  generic: 'spark',
};

function distinctTools(steps: readonly ToolStep[]): string[] {
  const names: string[] = [];
  for (const step of steps) {
    if (!names.includes(step.name)) names.push(step.name);
  }
  return names;
}

function overlaps(steps: readonly ToolStep[]): boolean {
  const intervals = steps
    .filter((step) => step.startedAt != null)
    .map((step) => ({
      start: step.startedAt as number,
      end: step.endedAt ?? (step.startedAt as number) + (step.durationMs ?? 0),
    }));
  return intervals.some((left, index) =>
    intervals.slice(index + 1).some((right) => left.start < right.end && right.start < left.end),
  );
}

/** The agent's live checklist (`todo_write`), editable while the run is live. */
function TodoChecklist({
  steps,
  store,
  agentId,
  runId,
  editable,
}: {
  steps: readonly PlanStep[];
  store: ActivityStore;
  agentId?: string;
  runId?: string;
  editable?: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState('');
  const canEdit = Boolean(editable && agentId && runId);

  if (steps.length === 0) return null;
  const done = steps.filter((step) => step.status === 'done').length;

  const apply = (next: { id: string; label: string; status: PlanStep['status'] }[]) => {
    store.dispatch({ type: 'plan.edit', steps: next });
    if (!agentId || !runId) return;
    api.agents
      .setPlan(agentId, runId, next.map((item) => ({ label: item.label, status: item.status })))
      .catch(() => undefined);
  };

  const toggle = (target: PlanStep) => {
    if (!canEdit) return;
    apply(
      steps.map((step) =>
        step.id === target.id
          ? { ...step, status: step.status === 'done' ? 'pending' : 'done' }
          : step,
      ),
    );
  };

  const add = () => {
    const label = draft.trim();
    if (!label || !canEdit) return;
    apply([
      ...steps.map((step) => ({ id: step.id, label: step.label, status: step.status })),
      { id: `user-${Date.now()}`, label, status: 'pending' },
    ]);
    setDraft('');
    setAdding(false);
  };

  return (
    <div className="act-todo">
      <div className="act-todo__head act-muted act-tabular">
        Plan · {done}/{steps.length} done
        {canEdit && <span className="act-todo__hint">you can edit this</span>}
      </div>
      <ul className="act-plan">
        {steps.map((step) => (
          <li
            key={step.id}
            className={`act-plan__item act-plan__item--${step.status}${canEdit ? ' is-editable' : ''}`}
          >
            <button
              type="button"
              className="act-plan__toggle"
              aria-label={step.status === 'done' ? 'Reopen item' : 'Mark item done'}
              title={canEdit ? (step.status === 'done' ? 'Reopen' : 'Mark done') : undefined}
              disabled={!canEdit}
              onClick={() => toggle(step)}
            >
              <span
                className={`act-status act-status--${
                  step.status === 'done'
                    ? 'success'
                    : step.status === 'error'
                      ? 'error'
                      : step.status === 'running'
                        ? 'running'
                        : 'queued'
                }`}
              >
                <Icon
                  name={
                    step.status === 'done'
                      ? 'check'
                      : step.status === 'error'
                        ? 'x'
                        : step.status === 'running'
                          ? 'loader-2'
                          : canEdit
                            ? 'square'
                            : 'circle'
                  }
                  size={13}
                  className={step.status === 'running' ? 'act-spin' : ''}
                />
              </span>
            </button>
            <span>{step.label}</span>
          </li>
        ))}
      </ul>
      {canEdit && (
        <div className="act-plan__add">
          {adding ? (
            <input
              autoFocus
              value={draft}
              placeholder="Add a step…"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') add();
                if (event.key === 'Escape') {
                  setAdding(false);
                  setDraft('');
                }
              }}
              onBlur={() => {
                if (!draft.trim()) setAdding(false);
              }}
            />
          ) : (
            <button type="button" onClick={() => setAdding(true)}>
              + Add step
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** A question the agent is blocked on, answered inline in the run. */
function QuestionCard({
  question,
  store,
  agentId,
}: {
  question: QuestionState;
  store: ActivityStore;
  agentId?: string;
}) {
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (answer: string, choice = '') => {
    if (busy) return;
    setBusy(true);
    try {
      if (agentId) await api.agents.answer(agentId, question.id, answer, choice);
      store.dispatch({
        type: 'question.answer',
        status: 'answered',
        answer: answer || choice,
      });
      setValue('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="act-question" role="group" aria-label="Agent question">
      <div className="act-question__head">
        <Icon name="message-circle" size={14} />
        <span>Agent needs your input</span>
      </div>
      <p className="act-question__text">{question.text}</p>
      {question.options.length > 0 && (
        <div className="act-question__options">
          {question.options.map((option) => (
            <button
              key={option}
              type="button"
              disabled={busy}
              onClick={() => void submit(option, option)}
            >
              {option}
            </button>
          ))}
        </div>
      )}
      {question.allowFreeText && (
        <div className="act-question__free">
          <input
            value={value}
            placeholder="Type your answer…"
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && value.trim()) void submit(value.trim());
            }}
          />
          <button
            type="button"
            className="act-chip act-chip--action"
            disabled={busy || !value.trim()}
            onClick={() => void submit(value.trim())}
          >
            Answer
          </button>
        </div>
      )}
    </div>
  );
}

function isTypingTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element) return false;
  const tag = element.tagName;
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    element.isContentEditable
  );
}

export function ActivityPanel({
  state,
  store,
  avatar,
  history = false,
  bodyExtra,
  agentId,
  onRetry,
  onRetryRun,
  onResolveApproval,
  children,
}: {
  state: ActivityState;
  store: ActivityStore;
  /** The chat assistant's avatar — defaults to a stable built-in bot. */
  avatar?: ActivityAgentAvatar | null;
  /** Rendered from persisted history: collapsed, no replay animation. */
  history?: boolean;
  /** The running agent, used to edit the plan while the run is live. */
  agentId?: string;
  onRetry?: (step: ToolStep) => void;
  onRetryRun?: () => void;
  onResolveApproval?: (step: ToolStep, decision: GrantDecision, args?: Record<string, unknown>) => void;
  /** Mode-specific body (stepper, plan, lanes, doc chips) rendered in the body. */
  bodyExtra?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const [settings, updateSettings] = useActivitySettings();
  const [manual, setManual] = useState<boolean | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const bodyId = useId();
  const menuId = useId();
  const overflowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setManual(null);
    setMenuOpen(false);
  }, [state.runId]);

  const steps = useMemo(() => state.steps.filter((step) => !step.parentId), [state.steps]);
  const pending = hasPendingApproval(state);
  const terminal = isTerminal(state.status);
  const running = !terminal && state.status !== 'idle';
  const tools = distinctTools(steps);
  const hasContent = steps.length > 0 || Boolean(state.reasoning);
  const canGantt = steps.length >= 3 || overlaps(steps);
  const narrow = useMediaQuery('(max-width: 560px)');
  const staticRun = history || store.restored;

  // Keyboard shortcut: T toggles rail/gantt (live panel only, never while typing).
  useEffect(() => {
    if (staticRun) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 't' && event.key !== 'T') return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;
      if (!canGantt || narrow) return;
      updateSettings({ timeline: settings.timeline === 'rail' ? 'gantt' : 'rail' });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [canGantt, narrow, settings.timeline, updateSettings, staticRun]);

  // Overflow menu: close on Escape and on outside pointer.
  useEffect(() => {
    if (!menuOpen) return;
    const trigger = overflowRef.current?.querySelector('button') ?? null;
    const onPointer = (event: PointerEvent) => {
      if (overflowRef.current && !overflowRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMenuOpen(false);
        trigger?.focus();
      }
    };
    window.addEventListener('pointerdown', onPointer, true);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('pointerdown', onPointer, true);
      window.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  // Collaboration rules: a pending approval never folds — not even for
  // restored history.
  const autoOpen = pending
    ? true
    : history
      ? false
      : settings.collapse === 'expanded'
        ? true
        : settings.collapse === 'collapsed'
          ? false
          : running && !state.answerStarted;
  const open = manual ?? autoOpen;

  const caption = captionFor(state);
  // The open body renders the settled "Thought for 8s" line; the head must
  // not repeat it. The aria-live announcement keeps the full caption.
  const headCaption =
    open && state.reasoning?.done ? captionFor(state, { reasoningShown: true }) : caption;
  const captionLive = caption.live;
  const nodeStatus = pending
    ? 'awaiting_approval'
    : state.status === 'error'
      ? 'error'
      : state.status === 'stopped'
        ? 'cancelled'
        : running
          ? 'running'
          : 'success';

  const announcement = pending ? 'Needs approval' : caption.text;

  if (!hasContent) {
    // A run with no reasoning and no tools renders only the minimal 32px
    // optimistic dot — never an empty card. Once the answer starts, the
    // answer is the content.
    return (
      <>
        {running && !state.answerStarted && (
          <ThinkingIndicator startedAt={state.startedAt} />
        )}
        {children}
      </>
    );
  }

  const passagesInFiles = state.passages.length > 0
    ? new Set(state.passages.map((passage) => passage.docName)).size
    : 0;

  const avatarConfig =
    avatar?.type === 'upload' ? undefined : avatar?.config ?? DEFAULT_AVATAR;

  const staticRunClass = staticRun ? ' act--static' : '';
  const liveInline = running && !state.answerStarted && !staticRun;
  const reasoningOnly =
    liveInline &&
    steps.length === 0 &&
    Boolean(state.reasoning && !state.reasoning.done);
  const showReasonHeader = !liveInline || steps.length === 0;

  return (
    <>
      <div
        className={`act act-panel${liveInline ? ' act-panel--inline' : ''}${
          state.status === 'error' ? ' act-panel--error' : ''
        }${staticRunClass}`.trim()}
      >
        {!reasoningOnly && (
        <div className="act-panel__head">
          <button
            type="button"
            className="act-caption"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setManual(!open)}
          >
            {avatar?.type === 'upload' && avatar.upload ? (
              <span className="act-caption__avatar" aria-hidden="true">
                <img src={avatar.upload} alt="" width={18} height={18} />
              </span>
            ) : avatarConfig ? (
              <span className="act-caption__avatar" aria-hidden="true">
                <AgentAvatar
                  config={avatarConfig}
                  type="bot"
                  size={18}
                  state={botStateForRun(state)}
                  interactive={false}
                  paused={staticRun}
                />
              </span>
            ) : (
              <StatusIcon status={nodeStatus} size={13} />
            )}
            <span className="act-caption__text">
              {caption.kind === 'failed' && (
                <Icon name="triangle-alert" size={12} className="act-caption__error-icon" />
              )}
              <span className="act-caption__label">
                {captionLive ? (
                  <span className="act-shimmer">{headCaption.text}</span>
                ) : (
                  headCaption.text
                )}
              </span>
              {running && (
                <span className="act-caption__timer">
                  <LiveTimer startedAt={state.startedAt} active />
                </span>
              )}
            </span>
            <span className="act-caption__strip" aria-hidden="true">
              {tools.slice(0, 3).map((name) => (
                <span key={name} className="act-caption__toolicon">
                  <PixelIcon
                    name={TOOL_PIXEL[getToolDefinition(name).family] ?? 'spark'}
                    size={16}
                    state="idle"
                  />
                </span>
              ))}
              {tools.length > 3 && (
                <span className="act-caption__toolicon act-tabular">+{tools.length - 3}</span>
              )}
            </span>
            {state.sources.length > 0 && (
              <span className="act-caption__sources">
                <SourceStack items={state.sources} />
                <span key={state.sources.length} className="act-chip act-tabular act-count-tick">
                  {state.sources.length} {state.sources.length === 1 ? 'source' : 'sources'}
                </span>
              </span>
            )}
            {state.sources.length === 0 && passagesInFiles > 0 && (
              <span className="act-chip act-tabular act-caption__sources">
                {state.passages.length} {state.passages.length === 1 ? 'passage' : 'passages'} in{' '}
                {passagesInFiles} {passagesInFiles === 1 ? 'file' : 'files'}
              </span>
            )}
            <span className="act-chevron" data-open={open} aria-hidden="true">
              <Icon name="chevron-right" size={14} />
            </span>
          </button>

          {!liveInline && (
          <div className="act-overflow" ref={overflowRef}>
            <button
              type="button"
              className="act-iconbtn"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-controls={menuId}
              aria-label="Activity options"
              onClick={() => setMenuOpen((value) => !value)}
            >
              <Icon name="more-horizontal" size={15} />
            </button>
            {menuOpen && (
              <div role="menu" id={menuId} className="act-menu">
                <div className="act-menu__label">Panel behaviour</div>
                {(
                  [
                    ['auto', 'Auto'],
                    ['expanded', 'Always expanded'],
                    ['collapsed', 'Always collapsed'],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={settings.collapse === value}
                    className="act-menu__item"
                    onClick={() => {
                      updateSettings({ collapse: value });
                      setMenuOpen(false);
                    }}
                  >
                    <span className="act-menu__check">
                      {settings.collapse === value && <Icon name="check" size={12} />}
                    </span>
                    {label}
                  </button>
                ))}
                <div className="act-menu__sep" role="separator" />
                <button
                  type="button"
                  role="menuitem"
                  className="act-menu__item"
                  disabled={!canGantt || narrow}
                  onClick={() => {
                    updateSettings({
                      timeline: settings.timeline === 'rail' ? 'gantt' : 'rail',
                    });
                    setMenuOpen(false);
                  }}
                >
                  <span className="act-menu__check" />
                  {settings.timeline === 'rail' ? 'Timeline view' : 'Rail view'}
                  <span className="act-menu__kbd"><Kbd>T</Kbd></span>
                </button>
                {state.status === 'error' && onRetryRun && (
                  <>
                    <div className="act-menu__sep" role="separator" />
                    <button
                      type="button"
                      role="menuitem"
                      className="act-menu__item"
                      onClick={() => {
                        onRetryRun();
                        setMenuOpen(false);
                      }}
                    >
                      <span className="act-menu__check" />
                      Retry
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
          )}
        </div>
        )}

        {(running || open) && <PhaseSpine phase={state.phase} />}

        <div className="act-panel__body act-disclosure" data-open={open}>
          <div className="act-disclosure__inner">
            <div role="region" id={bodyId} aria-label="Run activity">
              {state.reasoning && (
                <ReasoningBlock
                  key={`${state.runId}-reasoning`}
                  reasoning={state.reasoning}
                  startedAt={state.startedAt}
                  store={store}
                  showHeader={showReasonHeader}
                />
              )}
              {state.mode === 'agent' && state.question?.status === 'pending' && (
                <QuestionCard question={state.question} store={store} agentId={agentId} />
              )}
              {state.mode === 'agent' && state.question?.status === 'answered' && (
                <div className="act-question act-question--settled">
                  <Icon name="check" size={13} />
                  <span>{state.question.text}</span>
                  {state.question.answer && <strong>{state.question.answer}</strong>}
                </div>
              )}
              {state.mode === 'agent' && state.plan && state.plan.length > 0 && (
                <TodoChecklist
                  steps={state.plan}
                  store={store}
                  agentId={agentId}
                  runId={state.runId}
                  editable={!history && !isTerminal(state.status)}
                />
              )}
              {bodyExtra}
              {steps.length > 0 && (
                <RunTimeline
                  key={state.runId}
                  steps={steps}
                  store={store}
                  view={settings.timeline}
                  onRetry={onRetry}
                  onResolveApproval={onResolveApproval}
                />
              )}
            </div>
          </div>
        </div>

        <span className="act-visually-hidden" aria-live="polite" aria-atomic="true">
          {announcement}
        </span>
      </div>
      {children}
    </>
  );
}
