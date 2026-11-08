import { useMemo, useState } from 'react';
import { isTerminal, type Passage, type ActivityState } from '../model';
import { Icon } from '../icons';
import { Highlight as MarkText } from '../primitives/Highlight';
import { ActivityPanel } from '../shell/ActivityPanel';
import type { ModeProps } from './DefaultMode';

function termsOf(state: ActivityState): string[] {
  const running = [...state.steps].reverse().find((step) => step.name === 'document_search');
  if (!running || !running.args || typeof running.args !== 'object') return [];
  const record = running.args as Record<string, unknown>;
  const query = typeof record.query === 'string' ? record.query : '';
  return query
    .split(/\s+/)
    .map((term) => term.replace(/[^\p{L}\p{N}]/gu, ''))
    .filter((term) => term.length > 3)
    .slice(0, 6);
}

function DocChip({ name, passages, terms }: { name: string; passages: Passage[]; terms: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="act-doc-chip-wrap">
      <button type="button" className="act-docchip" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name="file-text" size={13} />
        <span className="act-docchip__name">{name}</span>
        <span className="act-chip act-tabular">{passages.length}</span>
      </button>
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
          {passages.map((passage) => (
            <div key={passage.id} className="act-passage">
              <div className="act-passage__head">
                {passage.page != null && <span className="act-chip act-tabular">p. {passage.page}</span>}
                {passage.score != null && (
                  <span className="act-chip act-tabular">{passage.score.toFixed(2)}</span>
                )}
              </div>
              <div className="act-passage__text">
                <MarkText text={passage.text} terms={terms} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Knowledge base: document chips with matched passages are the body; the
 * caption row owns the live status. A no-hit run settles with a single
 * "Not found in your documents" surface and no body.
 */
export function KnowledgeBaseMode({
  state,
  store,
  avatar,
  history,
  agentId,
  onRetry,
  onRetryRun,
  onResolveApproval,
  children,
}: ModeProps) {
  const terms = useMemo(() => termsOf(state), [state]);
  const groups = useMemo(() => {
    const map = new Map<string, Passage[]>();
    for (const passage of state.passages) {
      const group = map.get(passage.docName) ?? [];
      group.push(passage);
      map.set(passage.docName, group);
    }
    return [...map.entries()];
  }, [state.passages]);

  const terminal = isTerminal(state.status);
  const notFound =
    terminal && state.passages.length === 0 && state.sources.length === 0;

  const bodyExtra =
    groups.length > 0 ? (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {groups.map(([name, group]) => (
          <DocChip key={`${state.runId}-${name}`} name={name} passages={group} terms={terms} />
        ))}
      </div>
    ) : undefined;

  return (
    <>
      <ActivityPanel
        state={state}
        store={store}
        avatar={avatar}
        history={history}
        agentId={agentId}
        bodyExtra={bodyExtra}
        onRetry={onRetry}
        onRetryRun={onRetryRun}
        onResolveApproval={onResolveApproval}
      >
        {notFound && <div className="act-empty">Not found in your documents</div>}
      </ActivityPanel>
      {children}
    </>
  );
}
