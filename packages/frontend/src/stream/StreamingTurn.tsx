import ActivityChain from '../components/ActivityChain';
import MessageContent from '../components/MessageContent';
import { useApp } from '../AppContext';
import { nextAssistantMessageIndex } from '../utils/artifacts';
import { useChatStreamContext } from './context';
import StreamingMessage from './StreamingMessage';

/**
 * The live turn rendered while a response streams. Once the stream finishes,
 * the session refresh re-renders the same content through ChatArea's history
 * path (both use <MessageContent>).
 */
export default function StreamingTurn({ activeSessionId }: { activeSessionId: string | null }) {
  const { state, openVideo } = useChatStreamContext();
  const { sessions, openArtifact } = useApp();
  const session = sessions.find(item => item.id === activeSessionId);
  const messageIndex = nextAssistantMessageIndex(session?.messages);

  if (state.status === 'idle') return null;
  // A live turn belongs to the session it was started from. If the user
  // switches sessions mid-stream, keep the stream running but hide it here.
  if (state.sessionId !== null && state.sessionId !== activeSessionId) return null;

  return (
    <>
      <div className="message user-message">
        <div className="message-wrapper">
          <MessageContent content={state.userText} />
        </div>
      </div>

      <div className="cot-inline">
        <ActivityChain />
      </div>

      <StreamingMessage
        state={state}
        messageIndex={messageIndex}
        onOpenArtifact={openArtifact}
        onOpenVideo={openVideo}
      />
    </>
  );
}
