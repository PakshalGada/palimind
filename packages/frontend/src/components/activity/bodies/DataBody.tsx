import type { ToolStep } from '../model';
import { CodeView } from '../primitives/CodeView';
import { DataTable } from '../primitives/DataTable';
import { normalizeTable, parseOutput } from '../toolOutput';

function argString(args: unknown, keys: string[]): string {
  if (!args || typeof args !== 'object') return '';
  const record = args as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

export default function DataBody({ step }: { step: ToolStep }) {
  const sql =
    argString(step.args, ['sql', 'query', 'statement']) ||
    argString(step.args, ['path', 'file']);
  const value = parseOutput(step.output);
  const errorText =
    typeof value === 'string' && /^error:/i.test(value.trim()) ? value.trim() : '';
  const table = normalizeTable(value);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {sql && <CodeView code={sql} language="sql" title="Query" lineNumbers maxLines={20} />}
      {errorText ? (
        <div className="act-row__error">{errorText}</div>
      ) : table.rows.length > 0 ? (
        <DataTable data={table} />
      ) : (
        <div className="act-empty">{step.status === 'running' ? 'Running query' : 'No rows'}</div>
      )}
    </div>
  );
}
