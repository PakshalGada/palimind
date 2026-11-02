import type { ToolStep } from '../model';
import type { ActivityStore } from '../store';
import { ActivityPanel } from '../shell/ActivityPanel';
import type { GrantDecision } from '../shell/PermissionGrant';
import { ThinkingIndicator } from '../shell/ThinkingIndicator';

export interface ModeProps {
  state: import('../model').ActivityState;
  store: ActivityStore;
  onRetry?: (step: ToolStep) => void;
  onRetryRun?: () => void;
  onResolveApproval?: (step: ToolStep, decision: GrantDecision) => void;
  children?: React.ReactNode;
}

export function DefaultMode({
  state,
  store,
  onRetry,
  onRetryRun,
  onResolveApproval,
  children,
}: ModeProps) {
  const idle = state.steps.length === 0 && !state.reasoning;
  return (
    <>
      {idle && state.status !== 'done' && state.status !== 'stopped' && state.status !== 'error' ? (
        <ThinkingIndicator startedAt={state.startedAt} />
      ) : (
        <ActivityPanel
          state={state}
          store={store}
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
