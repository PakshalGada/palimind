import { useMemo, useRef, useState } from 'react';
import type { TableData } from '../toolOutput';
import { CopyButton } from './CopyButton';

const ROW_HEIGHT = 26;
const VIEWPORT = 320;
const OVERSCAN = 6;

function cell(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function DataTable({ data, title }: { data: TableData; title?: string }) {
  const [scrollTop, setScrollTop] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const total = data.rows.length;
  const virtual = total > 50;
  const start = virtual ? Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN) : 0;
  const count = virtual ? Math.ceil(VIEWPORT / ROW_HEIGHT) + OVERSCAN * 2 : total;
  const end = Math.min(total, start + count);
  const visible = useMemo(() => data.rows.slice(start, end), [data.rows, start, end]);

  const tsv = useMemo(
    () =>
      [data.columns.join('\t'), ...data.rows.map((row) => data.columns.map((column) => cell(row[column])).join('\t'))].join(
        '\n',
      ),
    [data],
  );

  return (
    <div className="act-body act-body--flush">
      <div className="act-code__head">
        <span className="act-row__label">{title ?? 'Results'}</span>
        <span style={{ marginInlineStart: 'auto' }}>
          <CopyButton value={tsv} label="Copy as TSV" />
        </span>
      </div>
      <div
        className="act-table"
        ref={scrollRef}
        onScroll={virtual ? (event) => setScrollTop(event.currentTarget.scrollTop) : undefined}
        style={virtual ? { maxHeight: VIEWPORT } : undefined}
      >
        <table>
          <thead>
            <tr>
              {data.columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {virtual && start > 0 && (
              <tr className="act-table__spacer" style={{ height: start * ROW_HEIGHT }}>
                <td colSpan={Math.max(1, data.columns.length)} />
              </tr>
            )}
            {visible.map((row, index) => (
              <tr key={start + index}>
                {data.columns.map((column) => (
                  <td key={column} title={cell(row[column])}>
                    {cell(row[column])}
                  </td>
                ))}
              </tr>
            ))}
            {virtual && end < total && (
              <tr className="act-table__spacer" style={{ height: (total - end) * ROW_HEIGHT }}>
                <td colSpan={Math.max(1, data.columns.length)} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="act-table__footer">
        <span className="act-tabular">
          {total} {total === 1 ? 'row' : 'rows'}
        </span>
        {virtual && <span>Virtualized</span>}
      </div>
    </div>
  );
}
