import { useState } from 'react';
import type { ToolStep } from '../model';
import { CodeView } from '../primitives/CodeView';
import { Favicon } from '../primitives/Favicon';
import { parseOutput, textOf } from '../toolOutput';
import { hostOf, previewForTool } from '../toolRegistry';

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export default function PageBody({ step }: { step: ToolStep }) {
  const [expanded, setExpanded] = useState(false);
  const value = parseOutput(step.output);
  const output = record(value);
  const text = typeof value === 'string' ? value : textOf(output.content ?? output.text ?? value);
  const url = typeof output.url === 'string' ? output.url : '';
  const title =
    (typeof output.title === 'string' && output.title) ||
    url ||
    previewForTool(step.name, step.args) ||
    'Page';
  const status = typeof output.status === 'number' ? output.status : undefined;
  const pages = typeof output.pages === 'number' ? output.pages : undefined;
  const size = typeof output.size === 'number' ? output.size : undefined;
  const lines = text.split('\n');

  return (
    <div className="act-body">
      <div className="act-passage__head">
        <Favicon domain={url ? hostOf(url) : undefined} title={title} />
        <span className="act-row__label" style={{ color: 'var(--act-text)' }}>
          {title}
        </span>
        {status !== undefined && <span className="act-chip act-tabular">{status}</span>}
        {size !== undefined && <span className="act-chip act-tabular">{Math.round(size / 1024)} KB</span>}
        {pages !== undefined && <span className="act-chip act-tabular">{pages} pages</span>}
      </div>
      {pages !== undefined && pages > 0 && pages < 40 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
          {Array.from({ length: pages }, (_, index) => (
            <span key={index} className="act-chip act-tabular">
              p. {index + 1}
            </span>
          ))}
        </div>
      )}
      {text ? (
        <>
          <div className={`act-preview-text ${expanded ? '' : 'act-line-clamp-6'}`} style={{ marginTop: 8 }}>
            {expanded ? text : lines.slice(0, 6).join('\n')}
          </div>
          {lines.length > 6 && (
            <button
              type="button"
              className="act-btn act-btn--ghost"
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? 'Show less' : 'Show more'}
            </button>
          )}
        </>
      ) : (
        !text && step.status === 'running' && <CodeView code="Fetching" title="Content" copy={false} />
      )}
    </div>
  );
}
