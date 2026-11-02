import { useEffect, useMemo, useState } from 'react';
import { isTerminal, type Passage } from '../model';
import { Icon } from '../icons';
import { Highlight } from '../primitives/Highlight';
import { LiveTimer } from '../primitives/LiveTimer';
import { StatusIcon } from '../primitives/StatusIcon';
import { Highlight as MarkText } from '../primitives/Highlight';
import type { ModeProps } from './DefaultMode';

function termsOf(state: import('../model').ActivityState): string[] {
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

export function KnowledgeBaseMode({ state, children }: ModeProps) {
  const [manual, setManual] = useState<boolean | null>(null);

  useEffect(() => {
    setManual(null);
  }, [state.runId]);
  const terminal = isTerminal(state.status);
  const active = !terminal;
  const open = manual ?? (active && !state.answerStarted);
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

  const files = groups.length;
  const passages = state.passages.length;
  const notFound = terminal && passages === 0 && state.sources.length === 0;
  const label = notFound
    ? 'Not found in your documents'
    : state.answerStarted
      ? 'Reading'
      : passages > 0
        ? `Found ${passages} passages`
        : 'Searching documents';

  if (passages === 0 && state.sources.length === 0 && !terminal) {
    return (
      <>
        <div className="act-thinking">
          <span className="act-dot" aria-hidden="true" />
          <span>Searching documents</span>
          <LiveTimer startedAt={state.startedAt} active />
        </div>
        {children}
      </>
    );
  }

  return (
    <>
      <div className="act act-panel">
        <div className="act-panel__head">
          <button
            type="button"
            className="act-panel__toggle"
            aria-expanded={open}
            onClick={() => setManual(!open)}
          >
            <StatusIcon status={notFound ? 'cancelled' : active ? 'running' : 'success'} />
            <span className="act-panel__title">
              <span className="act-panel__label">{label}</span>
              {active && <LiveTimer startedAt={state.startedAt} active />}
            </span>
            <span className="act-panel__meta">
              {passages > 0 && (
                <span className="act-chip act-tabular">
                  {passages} passages in {files} {files === 1 ? 'file' : 'files'}
                </span>
              )}
            </span>
            {!notFound && (
              <span className="act-chevron" data-open={open} aria-hidden="true">
                <Icon name="chevron-right" size={14} />
              </span>
            )}
          </button>
        </div>
        {!notFound && (
          <div className="act-panel__body act-disclosure" data-open={open}>
            <div className="act-disclosure__inner">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {groups.map(([name, group]) => (
                  <DocChip key={`${state.runId}-${name}`} name={name} passages={group} terms={terms} />
                ))}
              </div>
              {state.reasoning && (
                <div className="act-passage__text" style={{ marginTop: 8 }}>
                  <Highlight text={state.reasoning.text.slice(0, 400)} terms={terms} />
                </div>
              )}
            </div>
          </div>
        )}
        {notFound && (
          <div className="act-panel__body">
            <div className="act-empty">Not found in your documents</div>
          </div>
        )}
      </div>
      {children}
    </>
  );
}
