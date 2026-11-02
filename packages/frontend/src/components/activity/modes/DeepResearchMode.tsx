import { useEffect, useMemo, useState } from 'react';
import {
  elapsedMs,
  formatRunDuration,
  isTerminal,
  type ActivityState,
  type PlanStep,
} from '../model';
import { Icon, type IconName } from '../icons';
import { LiveTimer } from '../primitives/LiveTimer';
import { SourceStack } from '../primitives/SourceStack';
import { StatusIcon } from '../primitives/StatusIcon';
import { getToolDefinition, previewForTool } from '../toolRegistry';
import { RunTimeline } from '../shell/RunTimeline';
import type { ModeProps } from './DefaultMode';
import { DefaultMode } from './DefaultMode';

const PHASES: { id: string; label: string; match: string[] }[] = [
  { id: 'plan', label: 'Plan', match: ['routing'] },
  { id: 'search', label: 'Search', match: ['searching'] },
  { id: 'read', label: 'Read', match: ['reading'] },
  { id: 'analyze', label: 'Analyze', match: ['analyzing', 'synthesizing'] },
  { id: 'write', label: 'Write', match: ['writing'] },
];

function phaseIndex(state: ActivityState): number {
  if (!state.phase) return 0;
  const index = PHASES.findIndex((phase) => phase.match.includes(state.phase as string));
  return index === -1 ? 0 : index;
}

function PlanIcon({ status }: { status: PlanStep['status'] }) {
  const name: IconName =
    status === 'running' ? 'loader-2' : status === 'done' ? 'check' : status === 'error' ? 'x' : 'circle';
  return (
    <span className={`act-status act-status--${status === 'done' ? 'success' : status === 'error' ? 'error' : status === 'running' ? 'running' : ''}`}>
      <Icon name={name} size={13} className={status === 'running' ? 'act-spin' : ''} />
    </span>
  );
}

function tickerLine(state: ActivityState): string {
  const running = [...state.steps].reverse().find((step) => step.status === 'running');
  if (running) {
    const definition = getToolDefinition(running.name);
    const preview = previewForTool(running.name, running.args);
    return preview ? `${definition.running} ${preview}` : definition.running;
  }
  if (state.phase) {
    const label = PHASES[phaseIndex(state)]?.label;
    return label ? `Working on ${label.toLowerCase()}` : 'Working';
  }
  return 'Researching';
}

export function DeepResearchMode({
  state,
  store,
  onRetry,
  onRetryRun,
  onResolveApproval,
  children,
}: ModeProps) {
  const [manual, setManual] = useState<boolean | null>(null);

  useEffect(() => {
    setManual(null);
  }, [state.runId]);
  const [details, setDetails] = useState(false);
  const terminal = isTerminal(state.status);
  const active = !terminal;
  const open = manual ?? active;
  const steps = useMemo(() => state.steps.filter((step) => !step.parentId), [state.steps]);
  const index = phaseIndex(state);

  if (steps.length === 0 && !state.plan?.length && !state.reasoning) {
    return (
      <DefaultMode state={state} store={store} onRetry={onRetry} onResolveApproval={onResolveApproval}>
        {children}
      </DefaultMode>
    );
  }

  if (terminal && state.status !== 'error') {
    return (
      <>
        <div className="act act-summary">
          <StatusIcon status="success" />
          <span className="act-summary__strong">Research complete</span>
          <span className="act-chip act-tabular">{state.sources.length} sources</span>
          <span className="act-muted act-tabular">
            {state.endedAt != null ? formatRunDuration(elapsedMs(state)) : ''}
          </span>
          {steps.length > 0 && (
            <button type="button" className="act-btn act-btn--ghost" onClick={() => setDetails(!details)}>
              {details ? 'Hide details' : 'Details'}
            </button>
          )}
        </div>
        {details && (
          <div className="act act-panel" style={{ marginTop: 8 }}>
            <RunTimeline key={state.runId} steps={steps} store={store} onRetry={onRetry} onResolveApproval={onResolveApproval} />
          </div>
        )}
        {children}
      </>
    );
  }

  return (
    <>
      <div className="act act-panel">
        <div className="act-panel__head">
          <button
            type="button"
            className="act-panel__toggle"
            aria-expanded={open}
            onClick={() => setManual(!open)}
          >
            <StatusIcon status={active ? 'running' : 'error'} />
            <span className="act-panel__title">
              <span className="act-panel__label">Research</span>
              <LiveTimer startedAt={state.startedAt} endedAt={state.endedAt} active={active} />
            </span>
            <span className="act-panel__toolicons">
              {state.sources.length > 0 && <SourceStack items={state.sources} />}
            </span>
            <span className="act-panel__meta">
              {state.sources.length > 0 && (
                <span className="act-chip act-tabular">{state.sources.length} sources</span>
              )}
              {state.status === 'error' && onRetryRun && (
                <button type="button" className="act-btn act-btn--ghost" onClick={onRetryRun}>
                  Retry
                </button>
              )}
              <span className="act-chip act-tabular">
                {steps.length} {steps.length === 1 ? 'tool' : 'tools'}
              </span>
            </span>
            <span className="act-chevron" data-open={open} aria-hidden="true">
              <Icon name="chevron-right" size={14} />
            </span>
          </button>
        </div>
        <div className="act-panel__body act-disclosure" data-open={open}>
          <div className="act-disclosure__inner">
            <div className="act-stepper">
              {PHASES.map((phase, phaseIndexValue) => (
                <span
                  key={phase.id}
                  className={`act-stepper__step ${
                    phaseIndexValue < index
                      ? 'act-stepper__step--done'
                      : phaseIndexValue === index
                        ? 'act-stepper__step--active'
                        : ''
                  }`.trim()}
                >
                  <Icon name={phaseIndexValue < index ? 'check' : 'circle'} size={10} />
                  {phase.label}
                </span>
              ))}
            </div>

            {state.plan && state.plan.length > 0 && (
              <ul className="act-plan" style={{ marginTop: 8 }}>
                {state.plan.map((step) => (
                  <li key={step.id} className={`act-plan__item act-plan__item--${step.status}`}>
                    <PlanIcon status={step.status} />
                    <span>{step.label}</span>
                  </li>
                ))}
              </ul>
            )}

            <div className="act-ticker" style={{ marginTop: 8 }} aria-hidden="true">
              <span className="act-ticker__line" key={tickerLine(state)}>
                {tickerLine(state)}
              </span>
            </div>

            <div style={{ marginTop: 8 }}>
              <button type="button" className="act-btn act-btn--ghost" onClick={() => setDetails(!details)}>
                {details ? 'Hide details' : 'Details'}
              </button>
            </div>

            {details && steps.length > 0 && (
              <RunTimeline
                key={state.runId}
                steps={steps.slice(0, 100)}
                store={store}
                onRetry={onRetry}
                onResolveApproval={onResolveApproval}
              />
            )}
            {steps.length > 100 && <div className="act-empty">Showing first 100 steps</div>}
          </div>
        </div>
      </div>
      {children}
    </>
  );
}
