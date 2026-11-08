import { useState } from 'react';
import {
  elapsedMs,
  formatRunDuration,
  isTerminal,
  type ActivityState,
  type PlanStep,
} from '../model';
import { Icon, type IconName } from '../icons';
import { StatusIcon } from '../primitives/StatusIcon';
import { RunTimeline } from '../shell/RunTimeline';
import { ActivityPanel } from '../shell/ActivityPanel';
import type { ModeProps } from './DefaultMode';
import { DefaultMode } from './DefaultMode';

const PHASES: { id: string; label: string; match: string[] }[] = [
  { id: 'plan', label: 'Plan', match: ['routing'] },
  { id: 'search', label: 'Search', match: ['searching'] },
  { id: 'read', label: 'Read', match: ['reading'] },
  { id: 'analyze', label: 'Analyze', match: ['analyzing', 'synthesizing'] },
  { id: 'write', label: 'Report', match: ['writing'] },
];

function phaseIndex(state: ActivityState): number {
  if (!state.phase) return 0;
  const index = PHASES.findIndex((phase) => phase.match.includes(state.phase as string));
  return index === -1 ? 0 : index;
}

function PlanIcon({ status }: { status: PlanStep['status'] }) {
  const name: IconName =
    status === 'running' ? 'loader-2' : status === 'done' ? 'check' : status === 'error' ? 'x' : 'circle';
  const data =
    status === 'done'
      ? 'success'
      : status === 'error'
        ? 'error'
        : status === 'running'
          ? 'running'
          : 'queued';
  return (
    <span className={`act-status act-status--${data}`}>
      <Icon name={name} size={13} className={status === 'running' ? 'act-spin' : ''} />
    </span>
  );
}

/**
 * Deep research: a plan-first surface. While running, the research plan and
 * parallel research agents are the body; once settled it collapses to one
 * "Research complete" line with an optional details timeline.
 */
export function DeepResearchMode({
  state,
  store,
  avatar,
  history,
  agentId,
  onRetry,
  onRetryRun,
  onResolveApproval,
  children,
}: ModeProps) {
  const [details, setDetails] = useState(false);
  const terminal = isTerminal(state.status);
  const steps = state.steps.filter((step) => !step.parentId);
  const index = phaseIndex(state);
  const experts = state.experts ?? [];

  if (steps.length === 0 && !state.plan?.length && !state.reasoning && !terminal) {
    return (
      <DefaultMode
        state={state}
        store={store}
        avatar={avatar}
        history={history}
        agentId={agentId}
        onRetry={onRetry}
        onRetryRun={onRetryRun}
        onResolveApproval={onResolveApproval}
      >
        {children}
      </DefaultMode>
    );
  }

  if (state.status === 'done') {
    return (
      <>
        <div className="act act-summary">
          <StatusIcon status="success" />
          <span className="act-summary__strong">Research complete</span>
          {state.sources.length > 0 && (
            <span className="act-chip act-tabular">
              {state.sources.length} {state.sources.length === 1 ? 'source' : 'sources'}
            </span>
          )}
          <span className="act-muted act-tabular">
            {state.endedAt != null ? formatRunDuration(elapsedMs(state)) : ''}
          </span>
          {steps.length > 0 && (
            <button
              type="button"
              className="act-btn act-btn--ghost"
              onClick={() => setDetails(!details)}
            >
              {details ? 'Hide details' : 'Details'}
            </button>
          )}
        </div>
        {details && (
          <div className="act act-panel act--static" style={{ marginTop: 8 }}>
            <RunTimeline
              key={state.runId}
              steps={steps}
              store={store}
              onRetry={onRetry}
              onResolveApproval={onResolveApproval}
            />
          </div>
        )}
        {children}
      </>
    );
  }

  const bodyExtra = (
    <>
      <div className="act-stepper" aria-hidden="true">
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

      {experts.length > 0 && (
        <>
          <div className="act-expert-count act-muted act-tabular">
            {experts.filter((expert) => expert.status === 'done').length}/{experts.length} research
            agents complete
          </div>
          <div className="act-experts act-stagger">
            {experts.map((expert) => (
              <div
                key={expert.id}
                className={`act-expert${expert.status === 'done' ? ' act-expert--done' : ''}`}
              >
                <span className="act-row__label">{expert.name}</span>
                <span className="act-expert__lane">
                  <span className="act-expert__fill" />
                </span>
                <span className="act-chip act-tabular">
                  {expert.status === 'done' ? 'done' : 'working'}
                </span>
                {expert.snippet && (
                  <p className="act-passage__text act-expert__live" title={expert.snippet}>
                    {expert.snippet.slice(-240)}
                  </p>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </>
  );

  return (
    <ActivityPanel
      state={state}
      store={store}
      avatar={avatar}
      history={history}
      agentId={agentId}
      bodyExtra={bodyExtra}
      onRetry={onRetry}
      onRetryRun={onRetryRun}
      onResolveApproval={onResolveApproval}
    >
      {children}
    </ActivityPanel>
  );
}
