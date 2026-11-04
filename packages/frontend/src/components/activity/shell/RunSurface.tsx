import type { ToolStep } from '../model';
import type { ActivityStore } from '../store';
import type { ActivityAgentAvatar } from '../../../AppContext';
import { useActivityState } from '../hooks';
import type { GrantDecision } from './PermissionGrant';
import { ThinkingIndicator } from './ThinkingIndicator';
import { AgentMode, DefaultMode, type ModeProps } from '../modes/DefaultMode';
import { DeepResearchMode } from '../modes/DeepResearchMode';
import { KnowledgeBaseMode } from '../modes/KnowledgeBaseMode';
import { MoeMode } from '../modes/MoeMode';

export function RunSurface({
  store,
  avatar,
  history = false,
  onRetry,
  onRetryRun,
  onResolveApproval,
  children,
}: {
  store: ActivityStore;
  /** The chat assistant's avatar; defaults to a stable built-in bot. */
  avatar?: ActivityAgentAvatar | null;
  /** Persisted history: collapsed, no replay animation. */
  history?: boolean;
  onRetry?: (step: ToolStep) => void;
  onRetryRun?: () => void;
  onResolveApproval?: (step: ToolStep, decision: GrantDecision) => void;
  children?: React.ReactNode;
}) {
  const state = useActivityState(store);
  if (!state) return <ThinkingIndicator />;
  const props: ModeProps = {
    state,
    store,
    avatar,
    history,
    onRetry,
    onRetryRun,
    onResolveApproval,
    children,
  };
  if (state.mode === 'moe') return <MoeMode {...props} />;
  if (state.mode === 'deep_research') return <DeepResearchMode {...props} />;
  if (state.mode === 'knowledge_base') return <KnowledgeBaseMode {...props} />;
  if (state.mode === 'agent') return <AgentMode {...props} />;
  return <DefaultMode {...props} />;
}
