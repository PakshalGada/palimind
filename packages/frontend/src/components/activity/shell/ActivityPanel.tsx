import { useEffect, useId, useMemo, useState } from 'react';
import {
  elapsedMs,
  errorCount,
  formatRunDuration,
  hasPendingApproval,
  isTerminal,
  type ActivityState,
  type ToolStep,
} from '../model';
import { useActivitySettings } from '../hooks';
import { Icon } from '../icons';
import { LiveTimer } from '../primitives/LiveTimer';
import { SourceStack } from '../primitives/SourceStack';
import { StatusIcon } from '../primitives/StatusIcon';
import type { ActivityStore } from '../store';
import { getToolDefinition } from '../toolRegistry';
import { ReasoningBlock } from './ReasoningBlock';
import { RunTimeline } from './RunTimeline';
import { ThinkingIndicator } from './ThinkingIndicator';
import type { GrantDecision } from './PermissionGrant';

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

export function ActivityPanel({
  state,
  store,
  onRetry,
  onRetryRun,
  onResolveApproval,
  children,
}: {
  state: ActivityState;
  store: ActivityStore;
  onRetry?: (step: ToolStep) => void;
  onRetryRun?: () => void;
  onResolveApproval?: (step: ToolStep, decision: GrantDecision) => void;
  children?: React.ReactNode;
}) {
  const [settings, updateSettings] = useActivitySettings();
  const [manual, setManual] = useState<boolean | null>(null);
  const bodyId = useId();

  useEffect(() => {
    setManual(null);
  }, [state.runId]);
  const steps = useMemo(() => state.steps.filter((step) => !step.parentId), [state.steps]);
  const pending = hasPendingApproval(state);
  const terminal = isTerminal(state.status);
  const running = !terminal && state.status !== 'idle';
  const errors = errorCount(state);
  const tools = distinctTools(steps);
  const hasContent = steps.length > 0 || Boolean(state.reasoning);
  const canGantt = steps.length >= 3 || overlaps(steps);

  const autoOpen = pending
    ? true
    : settings.collapse === 'expanded'
      ? true
      : settings.collapse === 'collapsed'
        ? false
        : running && !state.answerStarted;
  const open = manual ?? autoOpen;

  const label = pending
    ? 'Needs approval'
    : state.status === 'stopped'
      ? 'Stopped'
      : state.status === 'error'
        ? 'Failed'
        : running
          ? steps.length === 0
            ? 'Thinking'
            : 'Working'
          : steps.length === 0
            ? 'Thought'
            : 'Worked';

  const announcement = pending
    ? 'Needs approval'
    : terminal
      ? `${label}${state.endedAt != null ? ` ${formatRunDuration(elapsedMs(state))}` : ''}`
      : label;

  if (!hasContent) {
    return (
      <>
        {running && <ThinkingIndicator startedAt={state.startedAt} />}
        {children}
      </>
    );
  }

  return (
    <>
      <div className={`act act-panel ${state.status === 'error' ? 'act-panel--error' : ''}`.trim()}>
        <div className="act-panel__head">
          <button
            type="button"
            className="act-panel__toggle"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setManual(!open)}
          >
            <StatusIcon status={pending ? 'awaiting_approval' : running ? 'running' : state.status === 'error' ? 'error' : state.status === 'stopped' ? 'cancelled' : 'success'} />
            <span className="act-panel__title">
              <span className="act-panel__label">{label}</span>
              {running ? (
                <LiveTimer startedAt={state.startedAt} active />
              ) : (
                state.endedAt != null && (
                  <span className="act-muted act-tabular">
                    for {formatRunDuration(elapsedMs(state))}
                  </span>
                )
              )}
            </span>
          <span className="act-panel__toolicons" aria-hidden="true">
            {tools.slice(0, 4).map((name) => (
              <Icon key={name} name={getToolDefinition(name).icon} size={13} />
            ))}
            {tools.length > 4 && <span className="act-tabular">+{tools.length - 4}</span>}
          </span>
          <span className="act-panel__meta">
            {state.sources.length > 0 && (
              <>
                <SourceStack items={state.sources} />
                <span key={state.sources.length} className="act-chip act-tabular act-count-tick">
                  {state.sources.length} sources
                </span>
              </>
            )}
            {state.passages.length > 0 && (
              <span className="act-chip act-tabular">
                {state.passages.length} passages in{' '}
                {new Set(state.passages.map((passage) => passage.docName)).size} files
              </span>
            )}
            {steps.length > 0 && (
              <span className="act-chip act-tabular">
                {steps.length} {steps.length === 1 ? 'tool' : 'tools'}
              </span>
            )}
            {errors > 0 && (
              <span className="act-chip act-chip--error act-tabular">
                <Icon name="triangle-alert" size={12} />
                {errors}
              </span>
            )}
          </span>
          <span className="act-chevron" data-open={open} aria-hidden="true">
            <Icon name="chevron-right" size={14} />
          </span>
        </button>
        <span className="act-panel__settings">
          {state.status === 'error' && onRetryRun && (
            <button type="button" className="act-btn act-btn--ghost" onClick={onRetryRun}>
              Retry
            </button>
          )}
          {canGantt && (
            <button
              type="button"
              className="act-btn act-btn--ghost"
              onClick={() =>
                updateSettings({ timeline: settings.timeline === 'rail' ? 'gantt' : 'rail' })
              }
            >
              {settings.timeline === 'rail' ? 'Timeline' : 'Rail'}
            </button>
          )}
          <select
            className="act-select"
            aria-label="Activity panel behaviour"
            value={settings.collapse}
            onChange={(event) =>
              updateSettings({
                collapse: event.target.value as 'auto' | 'expanded' | 'collapsed',
              })
            }
          >
            <option value="auto">Auto</option>
            <option value="expanded">Always expanded</option>
            <option value="collapsed">Always collapsed</option>
          </select>
        </span>
      </div>

      <div className="act-panel__body act-disclosure" data-open={open}>
        <div className="act-disclosure__inner">
          <div role="region" id={bodyId} aria-label="Run activity">
            {state.reasoning && (
              <ReasoningBlock
                key={`${state.runId}-reasoning`}
                reasoning={state.reasoning}
                startedAt={state.startedAt}
                store={store}
              />
            )}
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
