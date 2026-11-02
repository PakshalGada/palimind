import MessageContent from '../components/MessageContent';
import { SourcesList } from '@/components/activity/citations/SourcesList';
import { MediaCitations } from '@/components/activity/citations/MediaCitations';
import { resultsFromSources } from '@/components/activity/recorder';
import type { StreamState, VideoTarget } from './types';

/**
 * The answer half of the live turn. Sources sit under the answer; the activity
 * panel above owns process, approvals and tool detail.
 */
export default function StreamingMessage({
  state,
  messageIndex,
  onOpenArtifact,
  onOpenVideo,
}: {
  state: StreamState;
  messageIndex: number;
  onOpenArtifact: (artifactId: string) => void;
  onOpenVideo?: (target: VideoTarget) => void;
}) {
  const hasAnswer = Boolean(state.answer || state.error);
  const content = state.error
    ? `${state.answer}${state.answer ? '\n\n' : ''}**Error:** ${state.error}`
    : state.answer;
  const { sources, passages } = resultsFromSources(
    state.citations,
    state.textCitations,
    state.mediaCitations,
  );

  return (
    <div className="live-answer">
      {hasAnswer && (
        <MessageContent
          content={content}
          citations={state.citations ?? undefined}
          messageIndex={messageIndex}
          streaming={state.status === 'streaming'}
          onOpenArtifact={onOpenArtifact}
        />
      )}
      <SourcesList sources={sources} passages={passages} />
      {onOpenVideo && (
        <MediaCitations citations={state.mediaCitations} onOpen={onOpenVideo} />
      )}
    </div>
  );
}
