import { isTerminal, type ActivityState, type Expert } from '../model';
import { ActivityPanel } from '../shell/ActivityPanel';
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
  return (
    experts.length > 0 &&
    experts.every((expert) => expert.status === 'done') &&
    !state.answerStarted
  );
}

export function MoeMode({
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
  const experts = state.experts ?? [];
  if (experts.length === 0 && state.phase !== 'routing') {
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
  const isCombining = combining(state);
  const terminal = isTerminal(state.status);

  const bodyExtra = (
    <>
      <div className="act-expert-count act-muted act-tabular" aria-hidden="true">
        {experts.length} {experts.length === 1 ? 'expert' : 'experts'}
        {isCombining && !terminal && <span className="act-expert-count__combining"> · Combining</span>}
      </div>
      <div className="act-experts act-stagger">
        {experts.map((expert) => (
          <Lane key={expert.id} expert={expert} />
        ))}
      </div>
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
