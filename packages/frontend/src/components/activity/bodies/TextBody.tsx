import { useState } from 'react';
import type { ToolStep } from '../model';
import { parseOutput, textOf } from '../toolOutput';

export default function TextBody({ step }: { step: ToolStep }) {
  const [expanded, setExpanded] = useState(false);
  const value = parseOutput(step.output);
  const text = typeof value === 'string' ? value : textOf(value);
  if (!text.trim()) return <div className="act-empty">No output</div>;
  const lines = text.split('\n');
  return (
    <div className="act-body">
      <div className={`act-preview-text ${expanded ? '' : 'act-line-clamp-3'}`}>
        {expanded ? text : lines.slice(0, 3).join('\n')}
      </div>
      {lines.length > 3 && (
        <button
          type="button"
          className="act-btn act-btn--ghost"
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
}
