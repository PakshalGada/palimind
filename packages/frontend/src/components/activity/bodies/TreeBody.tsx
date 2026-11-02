import { useState } from 'react';
import type { ToolStep } from '../model';
import { Icon } from '../icons';
import { parseOutput } from '../toolOutput';

const LIMIT = 60;

interface Entry {
  path: string;
  depth: number;
  dir: boolean;
}

function entriesOf(value: unknown): Entry[] {
  const list: string[] = [];
  if (Array.isArray(value)) {
    for (const entry of value) {
      if (typeof entry === 'string') list.push(entry);
      else if (entry && typeof entry === 'object') {
        const record = entry as Record<string, unknown>;
        const path = record.path ?? record.name ?? record.file;
        if (typeof path === 'string') list.push(path);
      }
    }
  } else if (typeof value === 'string') {
    list.push(...value.split('\n').map((line) => line.replace(/^[\s│├└─]+/, '').trim()).filter(Boolean));
  }
  const seen = new Set<string>();
  return list
    .filter((path) => {
      if (seen.has(path)) return false;
      seen.add(path);
      return true;
    })
    .map((path) => {
      const trimmed = path.replace(/\/$/, '');
      const segments = trimmed.split(/[\\/]/).filter(Boolean);
      return {
        path: segments[segments.length - 1] || trimmed,
        depth: Math.min(segments.length - 1, 8),
        dir: path.endsWith('/') || !segments[segments.length - 1]?.includes('.'),
      };
    });
}

export default function TreeBody({ step }: { step: ToolStep }) {
  const [showAll, setShowAll] = useState(false);
  const entries = entriesOf(parseOutput(step.output));
  if (entries.length === 0) return <div className="act-empty">No results</div>;
  const visible = showAll ? entries : entries.slice(0, LIMIT);
  return (
    <div className="act-body act-body--flush">
      <div className="act-section-title">
        {entries.length} {entries.length === 1 ? 'file' : 'files'}
      </div>
      <div className="act-tree">
        {visible.map((entry, index) => (
          <div key={`${entry.path}-${index}`} className="act-tree__row" style={{ paddingInlineStart: entry.depth * 10 }}>
            <Icon name={entry.dir ? 'folder-open' : 'file'} size={13} />
            <span>{entry.path}</span>
          </div>
        ))}
      </div>
      {entries.length > LIMIT && !showAll && (
        <button type="button" className="act-btn act-btn--ghost" onClick={() => setShowAll(true)}>
          Show all
        </button>
      )}
    </div>
  );
}
