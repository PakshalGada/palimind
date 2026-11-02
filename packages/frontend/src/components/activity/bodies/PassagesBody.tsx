import { useState } from 'react';
import type { Passage, ToolStep } from '../model';
import { Icon } from '../icons';
import { Highlight } from '../primitives/Highlight';
import { normalizePassages } from '../toolOutput';

const LIMIT = 12;

function argString(args: unknown, key: string): string {
  if (!args || typeof args !== 'object') return '';
  const value = (args as Record<string, unknown>)[key];
  return typeof value === 'string' ? value : '';
}

function termsOf(query: string): string[] {
  return query
    .split(/\s+/)
    .map((term) => term.replace(/[^\p{L}\p{N}]/gu, ''))
    .filter((term) => term.length > 3)
    .slice(0, 6);
}

export default function PassagesBody({
  step,
  passages,
}: {
  step: ToolStep;
  passages: readonly Passage[];
}) {
  const [showAll, setShowAll] = useState(false);
  const fromStep = normalizePassages(step.output);
  const items = fromStep.length ? fromStep : passages;
  const query = argString(step.args, 'query') || argString(step.args, 'q');
  if (items.length === 0) {
    return <div className="act-empty">{step.status === 'running' ? 'Searching' : 'No results'}</div>;
  }
  const visible = showAll ? items : items.slice(0, LIMIT);
  const files = new Set(items.map((item) => item.docName)).size;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="act-section-title">
        {items.length} passages in {files} {files === 1 ? 'file' : 'files'}
      </div>
      {visible.map((passage) => (
        <div key={passage.id} className="act-passage">
          <div className="act-passage__head">
            <Icon name="file-text" size={13} />
            <span className="act-docchip__name">{passage.docName}</span>
            {passage.page != null && <span className="act-chip act-tabular">p. {passage.page}</span>}
            {passage.score != null && (
              <span className="act-chip act-tabular" title="Relevance score">
                {passage.score.toFixed(2)}
              </span>
            )}
          </div>
          <div className="act-passage__text">
            <Highlight text={passage.text} terms={termsOf(query)} />
          </div>
        </div>
      ))}
      {items.length > LIMIT && !showAll && (
        <button type="button" className="act-btn act-btn--ghost" onClick={() => setShowAll(true)}>
          Show all
        </button>
      )}
    </div>
  );
}
