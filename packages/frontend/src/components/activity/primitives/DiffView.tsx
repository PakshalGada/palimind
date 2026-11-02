import { useMemo, useState } from 'react';
import { diffLines } from '../../../utils/lineDiff';
import { CopyButton } from './CopyButton';

interface Row {
  kind: 'same' | 'add' | 'remove';
  text: string;
  left?: number;
  right?: number;
}

function rowsFromValues(before: string, after: string): Row[] {
  const diff = diffLines(before, after);
  const rows: Row[] = [];
  for (const row of diff.rows) {
    if (row.left && row.right) {
      rows.push({ kind: 'same', text: row.left.text, left: row.left.number, right: row.right.number });
    } else if (row.left) {
      rows.push({ kind: 'remove', text: row.left.text, left: row.left.number });
    } else if (row.right) {
      rows.push({ kind: 'add', text: row.right.text, right: row.right.number });
    }
  }
  return rows;
}

function rowsFromUnified(unified: string): Row[] {
  const rows: Row[] = [];
  let left = 1;
  let right = 1;
  for (const line of unified.replace(/\r\n/g, '\n').split('\n')) {
    if (line.startsWith('+')) {
      rows.push({ kind: 'add', text: line.slice(1), right: right++ });
    } else if (line.startsWith('-')) {
      rows.push({ kind: 'remove', text: line.slice(1), left: left++ });
    } else {
      const text = line.startsWith(' ') ? line.slice(1) : line;
      rows.push({ kind: 'same', text, left: left++, right: right++ });
    }
  }
  return rows;
}

const MAX_ROWS = 400;

export function DiffView({
  before,
  after,
  unified,
  path,
}: {
  before?: string;
  after?: string;
  unified?: string;
  path?: string;
}) {
  const [showAll, setShowAll] = useState(false);
  const rows = useMemo(
    () => (unified !== undefined ? rowsFromUnified(unified) : rowsFromValues(before ?? '', after ?? '')),
    [unified, before, after],
  );
  const added = rows.filter((row) => row.kind === 'add').length;
  const removed = rows.filter((row) => row.kind === 'remove').length;
  const visible = !showAll && rows.length > MAX_ROWS ? rows.slice(0, MAX_ROWS) : rows;
  const copyText = unified ?? rows.map((row) => `${row.kind === 'add' ? '+' : row.kind === 'remove' ? '-' : ' '}${row.text}`).join('\n');

  return (
    <div className="act-diff">
      <div className="act-code__head">
        <span className="act-row__label">{path ?? 'Diff'}</span>
        <span className="act-tabular" style={{ display: 'inline-flex', gap: 8 }}>
          <span style={{ color: 'var(--act-success)' }}>+{added}</span>
          <span style={{ color: 'var(--act-error)' }}>-{removed}</span>
        </span>
        <span style={{ marginInlineStart: 'auto', display: 'inline-flex', gap: 4 }}>
          {!showAll && rows.length > MAX_ROWS && (
            <button type="button" className="act-btn act-btn--ghost" onClick={() => setShowAll(true)}>
              Show all
            </button>
          )}
          <CopyButton value={copyText} />
        </span>
      </div>
      <div className="act-diff__body">
        {visible.map((row, index) => (
          <div key={index} className={`act-diff__line act-diff__line--${row.kind}`}>
            <span className="act-diff__num">{row.left ?? ''}</span>
            <span className="act-diff__num">{row.right ?? ''}</span>
            <span className="act-diff__sign">
              {row.kind === 'add' ? '+' : row.kind === 'remove' ? '-' : ' '}
            </span>
            <span>{row.text || ' '}</span>
          </div>
        ))}
        {rows.length === 0 && <div className="act-empty">No changes</div>}
      </div>
    </div>
  );
}
