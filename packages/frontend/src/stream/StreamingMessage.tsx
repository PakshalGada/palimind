import MessageContent from '../components/MessageContent';
import { SourcesPanel } from '@/components/sources/SourcesPanel';
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
      <SourcesPanel
        citations={state.citations}
        textCitations={state.textCitations}
        mediaCitations={state.mediaCitations}
        legacySources={state.sources}
        onOpenVideo={onOpenVideo}
      />
    </div>
  );
}
