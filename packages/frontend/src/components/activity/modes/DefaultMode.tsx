import type { ToolStep } from '../model';
import type { ActivityStore } from '../store';
import type { ActivityAgentAvatar } from '../../../AppContext';
import { ActivityPanel } from '../shell/ActivityPanel';
import type { GrantDecision } from '../shell/PermissionGrant';
import { ThinkingIndicator } from '../shell/ThinkingIndicator';

export interface ModeProps {
  state: import('../model').ActivityState;
  store: ActivityStore;
  /** The chat assistant's avatar config; defaults to a stable built-in bot. */
  avatar?: ActivityAgentAvatar | null;
  /** Persisted history: collapsed with no replay animation. */
  history?: boolean;
  /** The named agent, when known (enables live plan editing). */
  agentId?: string;
  onRetry?: (step: ToolStep) => void;
  onRetryRun?: () => void;
  onResolveApproval?: (step: ToolStep, decision: GrantDecision, args?: Record<string, unknown>) => void;
  children?: React.ReactNode;
}

export function DefaultMode({
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
  const idle = state.steps.length === 0 && !state.reasoning && !state.search;
  return (
    <>
      {idle && state.status !== 'done' && state.status !== 'stopped' && state.status !== 'error' ? (
        <ThinkingIndicator />
      ) : (
        <ActivityPanel
          state={state}
          store={store}
          avatar={avatar}
          history={history}
          agentId={agentId}
          onRetry={onRetry}
          onRetryRun={onRetryRun}
          onResolveApproval={onResolveApproval}
        />
      )}
      {children}
    </>
  );
}

export function AgentMode(props: ModeProps) {
  return <DefaultMode {...props} />;
}
