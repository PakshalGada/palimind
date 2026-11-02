import type { ToolStep } from '../model';
import type { ActivityStore } from '../store';
import { CodeView } from '../primitives/CodeView';
import { DataTable } from '../primitives/DataTable';
import { Terminal } from '../primitives/Terminal';
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

interface RunOutput {
  exitCode?: number;
  stdout: string;
  stderr: string;
  images: string[];
  table: ReturnType<typeof normalizeTable> | null;
}

function runOutputOf(step: ToolStep): RunOutput {
  const value = parseOutput(step.output);
  const record =
    value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  const exit = record.exit_code ?? record.exitCode ?? record.returncode;
  const stdout =
    typeof value === 'string'
      ? value
      : typeof record.stdout === 'string'
        ? record.stdout
        : typeof record.output === 'string'
          ? record.output
          : '';
  const stderr = typeof record.stderr === 'string' ? record.stderr : '';
  const rawImages = Array.isArray(record.images) ? record.images : [];
  const images = rawImages
    .map((entry) => (typeof entry === 'string' ? entry : ''))
    .filter((entry) => entry.startsWith('data:image') || /\.(png|jpe?g|webp|gif)$/i.test(entry));
  const rows = Array.isArray(record.rows) ? record.rows : Array.isArray(record.table) ? record.table : null;
  return {
    exitCode: typeof exit === 'number' ? exit : undefined,
    stdout,
    stderr,
    images,
    table: rows ? normalizeTable(rows) : null,
  };
}

export default function CodeRunBody({
  step,
  store,
}: {
  step: ToolStep;
  store: ActivityStore;
}) {
  const code = argString(step.args, ['code', 'source', 'script', 'snippet']);
  const command = argString(step.args, ['command', 'cmd', 'shell']);
  const output = runOutputOf(step);
  const buffer = step.streamedOutputRef ? store.buffers.get(step.streamedOutputRef) : undefined;
  const running = step.status === 'running';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {code ? (
        <CodeView code={code} language="python" title="Python" lineNumbers maxLines={40} />
      ) : command ? (
        <CodeView code={command} language="bash" title="Command" maxLines={20} />
      ) : null}
      <Terminal
        buffer={buffer}
        text={[output.stdout, output.stderr].filter(Boolean).join('\n')}
        title="Output"
        exitCode={output.exitCode}
        running={running}
      />
      {output.images.map((src, index) => (
        <img
          key={index}
          src={src}
          alt={`Output ${index + 1}`}
          loading="lazy"
          style={{ maxWidth: '100%', borderRadius: 6 }}
        />
      ))}
      {output.table && output.table.rows.length > 0 && (
        <DataTable data={output.table} title="Result" />
      )}
      {!running && !output.stdout && !output.stderr && step.status === 'success' && (
        <div className="act-empty">No output</div>
      )}
    </div>
  );
}
