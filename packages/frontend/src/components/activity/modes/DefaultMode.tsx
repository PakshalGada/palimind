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
  onRetry?: (step: ToolStep) => void;
  onRetryRun?: () => void;
  onResolveApproval?: (step: ToolStep, decision: GrantDecision) => void;
  children?: React.ReactNode;
}

export function DefaultMode({
  state,
  store,
  avatar,
  history,
  onRetry,
  onRetryRun,
  onResolveApproval,
  children,
}: ModeProps) {
  const idle = state.steps.length === 0 && !state.reasoning;
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
