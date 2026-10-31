import { useMemo } from 'react';
import { useThrottledValue } from '../../hooks/useThrottledValue';
import {
  collectArtifacts,
  nextAssistantMessageIndex,
  parseArtifacts,
  type Artifact,
  type ArtifactSource,
} from '../../utils/artifacts';

/** Live artifact parsing is O(answer length); at most ~3 passes/s. */
const LIVE_PARSE_MS = 340;

interface Options {
  messages: ArtifactSource[] | undefined;
  liveText: string;
  streaming: boolean;
}

/**
 * Artifacts for the current session, merging the persisted history with the
 * still-streaming answer.
 *
 * The old panel re-ran `collectArtifacts` over the whole conversation *and*
 * `parseArtifacts` over the whole live answer on every token flush, which is
 * what made the panel lag during long generations. Here history is memoized
 * on the message list and live text is throttled.
 */
export function useLiveArtifacts({
  messages,
  liveText,
  streaming,
}: Options): Artifact[] {
  const historical = useMemo(() => collectArtifacts(messages), [messages]);

  const throttledLive = useThrottledValue(
    streaming ? liveText : '',
    streaming ? LIVE_PARSE_MS : 0,
  );

  const live = useMemo(() => {
    if (!streaming || !throttledLive) return [];
    const last = messages?.[messages.length - 1];
    const alreadyPersisted =
      last?.role !== 'user' &&
      typeof last?.content === 'string' &&
      last.content.trim() === throttledLive.trim();
    if (alreadyPersisted) return [];
    return parseArtifacts(
      throttledLive,
      nextAssistantMessageIndex(messages),
      { streaming: true },
    );
  }, [messages, streaming, throttledLive]);

  return useMemo(() => {
    if (live.length === 0) return historical;
    const seen = new Set(historical.map(artifact => artifact.id));
    const merged = [...historical];
    for (const artifact of live) {
      if (seen.has(artifact.id)) continue;
      seen.add(artifact.id);
      merged.push(artifact);
    }
    return merged;
  }, [historical, live]);
}
