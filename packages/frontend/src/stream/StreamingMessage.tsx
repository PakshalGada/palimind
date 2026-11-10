import MessageContent from '../components/MessageContent';
import MessageBlocks from '../components/MessageBlocks';
import { SourcesPanel } from '@/components/sources/SourcesPanel';
import type { StreamState, VideoTarget } from './types';

/**
 * The answer half of the live turn. Sources sit under the answer; the activity
 * panel above owns process, approvals and tool detail.
 */
function formatTokens(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0';
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(Math.round(value));
}

function formatCost(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return 'local · $0';
  return `≈$${value < 0.01 ? value.toFixed(4) : value.toFixed(2)}`;
}

function prefill(text: string): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent('palimind:prefill-composer', { detail: { text } }));
}

/** Token/cost, escalation and follow-up UI shared by the live answer footer. */
export function LiveRunFooter({
  usage,
  escalation,
  suggestions,
  settled,
  onSuggestion = prefill,
}: {
  usage: StreamState['usage'];
  escalation: string | null;
  suggestions: string[];
  settled: boolean;
  onSuggestion?: (text: string) => void;
}) {
  return (
    <>
      {(usage || escalation) && (
        <div className="live-run-meta">
          {escalation && <span className="live-run-meta__chip">{escalation}</span>}
          {usage && (
            <span className="live-run-meta__chip act-tabular">
              {formatTokens(usage.prompt_tokens)} in ·{' '}
              {formatTokens(usage.completion_tokens)} out ·{' '}
              {formatCost(Number(usage.estimated_cost_usd ?? 0))}
            </span>
          )}
        </div>
      )}
      {settled && suggestions.length > 0 && (
        <div className="live-followups" aria-label="Suggested follow-ups">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="live-followups__chip"
              onClick={() => onSuggestion(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

export default function StreamingMessage({
  state,
  messageIndex,
  onOpenArtifact,
  onOpenVideo,
  bubbles = false,
}: {
  state: StreamState;
  messageIndex: number;
  onOpenArtifact: (artifactId: string) => void;
  onOpenVideo?: (target: VideoTarget) => void;
  /** Short message bubbles are an Agents-view treatment only. */
  bubbles?: boolean;
}) {
  const hasAnswer = Boolean(state.answer || state.error);
  const content = state.error
    ? `${state.answer}${state.answer ? '\n\n' : ''}**Error:** ${state.error}`
    : state.answer;
  return (
    <div className="live-answer">
      {hasAnswer &&
        (bubbles ? (
          <MessageBlocks
            content={content}
            citations={state.citations ?? undefined}
            messageIndex={messageIndex}
            streaming={state.status === 'streaming'}
            onOpenArtifact={onOpenArtifact}
          />
        ) : (
          <MessageContent
            content={content}
            citations={state.citations ?? undefined}
            messageIndex={messageIndex}
            streaming={state.status === 'streaming'}
            onOpenArtifact={onOpenArtifact}
          />
        ))}
      <SourcesPanel
        citations={state.citations}
        textCitations={state.textCitations}
        mediaCitations={state.mediaCitations}
        legacySources={state.sources}
        onOpenVideo={onOpenVideo}
      />
      <LiveRunFooter
        usage={state.usage}
        escalation={state.escalation}
        suggestions={state.suggestions}
        settled={state.status !== 'streaming'}
      />
    </div>
  );
}
