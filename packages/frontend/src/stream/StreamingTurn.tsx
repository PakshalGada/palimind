import MessageContent from '../components/MessageContent';
import { useApp } from '../AppContext';
import { nextAssistantMessageIndex } from '../utils/artifacts';
import { api } from '../api';
import { useChatStreamActions, useChatStreamContext } from './context';
import StreamingMessage from './StreamingMessage';
import { RunSurface } from '@/components/activity/shell/RunSurface';
import { PersistRun } from '@/components/activity/shell/PersistRun';
import type { GrantDecision } from '@/components/activity/shell/PermissionGrant';
import type { ToolStep } from '@/components/activity/model';

/**
 * The live turn: the user echo, the shared activity surface, then the answer.
 * Process is secondary; the answer remains the hero below the panel.
 */
export default function StreamingTurn({ activeSessionId }: { activeSessionId: string | null }) {
  const { state, activityStore, openVideo } = useChatStreamContext();
  const { retry } = useChatStreamActions();
  const { sessions, openArtifact } = useApp();
  const session = sessions.find((item) => item.id === activeSessionId);
  const messageIndex = nextAssistantMessageIndex(session?.messages);

  if (state.status === 'idle') return null;
  if (state.sessionId !== null && state.sessionId !== activeSessionId) return null;

  const resolveApproval = (step: ToolStep, decision: GrantDecision) => {
    activityStore.resolveApproval(step.id, decision);
    const meta = step.approval;
    if (!meta?.agentId) return;
    api.agents
      .approve(meta.agentId, decision !== 'deny', '', meta.runId)
      .catch(() => undefined);
  };

  return (
    <>
      <PersistRun
        store={activityStore}
        sessionId={state.sessionId ?? activeSessionId}
        messageIndex={messageIndex}
      />

      <div className="message user-message">
        <div className="message-wrapper">
          <MessageContent content={state.userText} />
        </div>
      </div>

      <div className="message system-message live-run-message">
        <div className="message-wrapper">
          <RunSurface
            store={activityStore}
            onResolveApproval={resolveApproval}
            onRetryRun={retry}
          >
            <StreamingMessage
              state={state}
              messageIndex={messageIndex}
              onOpenArtifact={openArtifact}
              onOpenVideo={openVideo}
            />
          </RunSurface>
        </div>
      </div>
    </>
  );
}
