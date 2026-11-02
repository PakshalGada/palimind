import { useState } from 'react';
import type { ToolStep } from '../model';
import { Favicon } from '../primitives/Favicon';
import { normalizeResults } from '../toolOutput';
import { getToolDefinition } from '../toolRegistry';

const LIMIT = 25;

function metaLine(step: ToolStep, kind: string | undefined): string {
  return kind ?? step.name;
}

export default function SearchBody({ step }: { step: ToolStep }) {
  const [showAll, setShowAll] = useState(false);
  const results = normalizeResults(step.output);
  const definition = getToolDefinition(step.name);
  if (results.length === 0) {
    return <div className="act-empty">No results</div>;
  }
  const visible = showAll ? results : results.slice(0, LIMIT);
  return (
    <div className="act-results act-stagger">
      {visible.map((item) => {
        const meta = item.meta;
        const details: string[] = [];
        if (meta?.authors?.length) details.push(meta.authors.slice(0, 3).join(', '));
        if (meta?.year) details.push(String(meta.year));
        if (meta?.venue) details.push(meta.venue);
        if (definition.itemKind === 'github' && meta?.stars != null) details.push(`${meta.stars} stars`);
        if (definition.itemKind === 'hn') {
          if (meta?.points != null) details.push(`${meta.points} points`);
          if (meta?.comments != null) details.push(`${meta.comments} comments`);
        }
        if (definition.itemKind === 'stack' && meta?.points != null) details.push(`${meta.points} votes`);
        if (definition.itemKind === 'filing' && meta?.form) details.push(meta.form);
        if (meta?.filer) details.push(meta.filer);
        if (meta?.citations != null) details.push(`${meta.citations} citations`);
        if (meta?.date) details.push(meta.date.slice(0, 10));

        const content = (
          <>
            <Favicon domain={item.domain} title={item.title} />
            <span className="act-result__body">
              <span className="act-result__title">{item.title}</span>
              {item.domain && <span className="act-result__domain">{item.domain}</span>}
              {item.snippet && (
                <span className="act-result__snippet act-line-clamp-2">{item.snippet}</span>
              )}
              {details.length > 0 && <span className="act-result__meta">{details.join(' · ')}</span>}
            </span>
          </>
        );

        return item.url ? (
          <a
            key={item.id}
            className="act-result"
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            title={metaLine(step, details.join(' · '))}
          >
            {content}
          </a>
        ) : (
          <div key={item.id} className="act-result">
            {content}
          </div>
        );
      })}
      {results.length > LIMIT && !showAll && (
        <button type="button" className="act-btn act-btn--ghost" onClick={() => setShowAll(true)}>
          Show all
        </button>
      )}
    </div>
  );
}
