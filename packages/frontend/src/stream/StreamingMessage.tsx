import MessageContent from '../components/MessageContent';
import ApprovalCard from './ApprovalCard';
import { MediaCitations, TextCitations } from './StreamCitations';
import ThinkingBlock from './ThinkingBlock';
import ThoughtDurationBadge from './ThoughtDurationBadge';
import type { StreamState, VideoTarget } from './types';

/**
 * Assistant half of the live turn: thinking, citation chips, the streamed
 * answer and the approval prompt. Markdown goes through the same
 * <MessageContent> used for history.
 */
export default function StreamingMessage({
  state,
  onOpenVideo,
}: {
  state: StreamState;
  onOpenVideo: (target: VideoTarget) => void;
}) {
  const hasAnswer = Boolean(state.answer || state.error);
  const hasCitations = state.mediaCitations.length > 0 || state.textCitations.length > 0;
  const content = state.error
    ? `${state.answer}${state.answer ? '\n\n' : ''}**Error:** ${state.error}`
    : state.answer;

  return (
    <>
      {hasCitations && (
        <div className="stream-citations-block">
          <MediaCitations citations={state.mediaCitations} onOpen={onOpenVideo} />
          <TextCitations citations={state.textCitations} />
        </div>
      )}

      {state.thinking && (
        <div className="message system-message">
          <div className="message-wrapper">
            <ThinkingBlock text={state.thinking} />
          </div>
        </div>
      )}

      {(hasAnswer || state.approval) && (
        <div className="message system-message">
          <div className="message-wrapper">
            {state.thoughtDuration && <ThoughtDurationBadge duration={state.thoughtDuration} />}
            {hasAnswer && (
              <MessageContent
                content={content}
                citations={state.citations ?? undefined}
              />
            )}
            {state.approval && <ApprovalCard prompt={state.approval} />}
          </div>
        </div>
      )}
    </>
  );
}
