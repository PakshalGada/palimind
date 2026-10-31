import { useEffect, useMemo, useRef } from 'react';
import { useApp } from '../AppContext';
import { useChatStreamContext } from '../stream/context';
import { collectArtifacts, nextAssistantMessageIndex, parseArtifacts } from '../utils/artifacts';

/**
 * Opens the artifact panel as soon as the model closes a new artifact fence.
 * Historical artifacts are marked as seen so loading a conversation does not
 * pop the panel, and closing the panel suppresses re-opening the same artifact.
 */
export default function ArtifactAutoOpen() {
  const { sessions, activeSessionId, setArtifactPanelOpen } = useApp();
  const { liveText, state } = useChatStreamContext();
  const seen = useRef<Set<string>>(new Set());
  const initialised = useRef(false);
  const sessionKey = activeSessionId || 'new';
  const previousSession = useRef(sessionKey);
  /** Full artifact scans are O(answer length); don't run one per token flush. */
  const lastScan = useRef({ at: 0, length: 0 });

  const session = useMemo(
    () => sessions.find(item => item.id === activeSessionId),
    [sessions, activeSessionId],
  );

  const historical = useMemo(() => collectArtifacts(session?.messages ?? []), [session?.messages]);

  useEffect(() => {
    const changed = previousSession.current !== sessionKey;
    if (changed) {
      previousSession.current = sessionKey;
      seen.current = new Set();
    }
    const fresh = historical.filter(artifact => !seen.current.has(artifact.id));
    for (const artifact of historical) seen.current.add(artifact.id);
    if (!initialised.current) {
      initialised.current = true;
      return;
    }
    if (!changed && fresh.length > 0) {
      setArtifactPanelOpen(true);
    }
  }, [historical, sessionKey, setArtifactPanelOpen]);

  useEffect(() => {
    if (state.status !== 'streaming' || !liveText) return;
    const now = performance.now();
    // ~4 scans/second while text is flowing is plenty to notice a closed fence.
    if (now - lastScan.current.at < 250) return;
    lastScan.current = { at: now, length: liveText.length };
    const artifacts = parseArtifacts(
      liveText,
      nextAssistantMessageIndex(session?.messages),
      { streaming: true },
    );
    const fresh = artifacts.filter(
      artifact => !artifact.streaming && !seen.current.has(artifact.id),
    );
    if (fresh.length === 0) return;
    for (const artifact of fresh) seen.current.add(artifact.id);
    setArtifactPanelOpen(true);
  }, [liveText, state.status, setArtifactPanelOpen, session?.messages]);

  return null;
}
