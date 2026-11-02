import { useEffect, useState } from 'react';
import { errorCount, isTerminal, type ActivityState, type Expert } from '../model';
import { Icon } from '../icons';
import { LiveTimer } from '../primitives/LiveTimer';
import { ShimmerText } from '../primitives/ShimmerText';
import { StatusIcon } from '../primitives/StatusIcon';
import { ReasoningBlock } from '../shell/ReasoningBlock';
import type { ModeProps } from './DefaultMode';
import { DefaultMode } from './DefaultMode';

function initials(name: string): string {
  const words = name.replace(/[^\p{L}\p{N}\s]/gu, '').split(/\s+/).filter(Boolean);
  if (words.length === 0) return '?';
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[1][0]}`.toUpperCase();
}

function ExpertAvatar({ name }: { name: string }) {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="10" cy="10" r="9" fill="var(--act-recessed-strong)" />
      <text
        x="10"
        y="13"
        textAnchor="middle"
        fontSize="8"
        fill="var(--act-secondary)"
        fontFamily="var(--font-heading)"
      >
        {initials(name)}
      </text>
    </svg>
  );
}

function Lane({ expert }: { expert: Expert }) {
  return (
    <div className={`act-expert ${expert.status === 'done' ? 'act-expert--done' : ''}`.trim()}>
      <ExpertAvatar name={expert.name} />
      <span className="act-row__label act-muted">{expert.name}</span>
      <span className="act-expert__lane">
        <span className="act-expert__fill" />
      </span>
      {expert.snippet && (
        <details style={{ gridColumn: '1 / -1' }}>
          <summary className="act-muted" style={{ fontSize: 11, cursor: 'pointer' }}>
            Contribution
          </summary>
          <p className="act-passage__text" style={{ marginTop: 4 }}>
            {expert.snippet}
          </p>
        </details>
      )}
    </div>
  );
}

function combining(state: ActivityState): boolean {
  const experts = state.experts ?? [];
  return experts.length > 0 && experts.every((expert) => expert.status === 'done') && !state.answerStarted;
}

export function MoeMode({ state, store, onRetry, onResolveApproval, children }: ModeProps) {
  const [manual, setManual] = useState<boolean | null>(null);

  useEffect(() => {
    setManual(null);
  }, [state.runId]);
  const experts = state.experts ?? [];
  if (experts.length === 0 && state.phase !== 'routing') {
    return (
      <DefaultMode
        state={state}
        store={store}
        onRetry={onRetry}
        onResolveApproval={onResolveApproval}
      >
        {children}
      </DefaultMode>
    );
  }
  const active = !isTerminal(state.status);
  const isCombining = combining(state);
  const open = manual ?? (active && !state.answerStarted);
  const label = isCombining ? 'Combining' : state.phase === 'routing' || experts.length === 0 ? 'Routing' : active ? 'Working' : 'Worked';
  const errors = errorCount(state);

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
            <StatusIcon status={active ? 'running' : state.status === 'error' ? 'error' : 'success'} />
            <span className="act-panel__title">
              <span className="act-panel__label">
                {active ? <ShimmerText>{label}</ShimmerText> : label}
              </span>
              <LiveTimer startedAt={state.startedAt} endedAt={state.endedAt} active={active} />
            </span>
            <span className="act-panel__toolicons" aria-hidden="true">
              {experts.slice(0, 5).map((expert) => (
                <ExpertAvatar key={expert.id} name={expert.name} />
              ))}
            </span>
            <span className="act-panel__meta">
              <span className="act-chip act-tabular">{experts.length} experts</span>
              {state.sources.length > 0 && (
                <span className="act-chip act-tabular">{state.sources.length} sources</span>
              )}
              {errors > 0 && (
                <span className="act-chip act-chip--error">
                  <Icon name="triangle-alert" size={12} />
                  {errors}
                </span>
              )}
            </span>
            <span className="act-chevron" data-open={open} aria-hidden="true">
              <Icon name="chevron-right" size={14} />
            </span>
          </button>
        </div>
        <div className="act-panel__body act-disclosure" data-open={open}>
          <div className="act-disclosure__inner">
            <div className={`act-experts act-stagger ${isCombining ? 'act-experts--combining' : ''}`.trim()}>
              {experts.map((expert) => (
                <Lane key={expert.id} expert={expert} />
              ))}
            </div>
            {state.reasoning && (
              <ReasoningBlock key={`${state.runId}-reasoning`} reasoning={state.reasoning} startedAt={state.startedAt} store={store} />
            )}
            {isCombining && (
              <div className="act-muted act-ticker" style={{ marginTop: 6 }}>
                <span className="act-ticker__line">Combining</span>
              </div>
            )}
          </div>
        </div>
      </div>
      {children}
    </>
  );
}
