import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ActivityMode } from '../../../AppContext';
import type { CitationPayload } from '../../../types';
import type { MediaCitation, TextCitation } from '../../../stream/types';
import { api } from '../../../api';
import { adaptRun, modeFromActivityMode } from '../adaptRun';
import type { ToolStep } from '../model';
import { ActivityStore, persistActivity, readPersistedActivity } from '../store';
import { RunSurface } from './RunSurface';
import type { GrantDecision } from './PermissionGrant';

/**
 * A completed run restored next to a historical message. Persisted activity is
 * preferred; older messages fall back to the citation payload so the surface
 * still has sources to show.
 */
export function HistoryActivity({
  sessionId,
  messageIndex,
  mode,
  citations,
  textCitations,
  mediaCitations,
}: {
  sessionId: string | null;
  messageIndex: number;
  mode?: ActivityMode;
  citations?: CitationPayload;
  textCitations?: readonly TextCitation[];
  mediaCitations?: readonly MediaCitation[];
}) {
  const [persisted, setPersisted] = useState(() =>
    readPersistedActivity(sessionId, messageIndex),
  );

  useEffect(() => {
    setPersisted(readPersistedActivity(sessionId, messageIndex));
  }, [sessionId, messageIndex]);

  const state = useMemo(() => {
    if (persisted) return persisted;
    if (!citations && !textCitations?.length && !mediaCitations?.length) return null;
    return adaptRun({
      runId: `history-${sessionId ?? 'local'}-${messageIndex}`,
      mode: modeFromActivityMode(mode),
      startedAt: Date.now(),
      status: 'done',
      answerStarted: true,
      citations: citations ?? null,
      textCitations: textCitations ?? [],
      mediaCitations: mediaCitations ?? [],
    });
  }, [persisted, citations, textCitations, mediaCitations, sessionId, messageIndex, mode]);

  const store = useMemo(() => (state ? ActivityStore.fromState(state) : null), [state]);

  const resolveApproval = useCallback(
    (step: ToolStep, decision: GrantDecision) => {
      if (!store) return;
      if (!store.resolveApproval(step.id, decision)) return;
      const meta = step.approval;
      if (meta?.agentId) {
        api.agents.approve(meta.agentId, decision !== 'deny', '', meta.runId).catch(() => undefined);
      }
      const next = store.getState();
      if (next) persistActivity(sessionId, messageIndex, next);
    },
    [store, sessionId, messageIndex],
  );

  if (!store) return null;
  return <RunSurface store={store} history onResolveApproval={resolveApproval} />;
}
