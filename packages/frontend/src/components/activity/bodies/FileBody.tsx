import type { ToolStep } from '../model';
import { CodeView } from '../primitives/CodeView';
import { parseOutput, textOf } from '../toolOutput';
import { previewForTool } from '../toolRegistry';

function argNumber(args: unknown, keys: string[]): number | undefined {
  if (!args || typeof args !== 'object') return undefined;
  const record = args as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    const parsed = typeof value === 'number' ? value : Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

export default function FileBody({ step }: { step: ToolStep }) {
  const value = parseOutput(step.output);
  const content = typeof value === 'string' ? value : textOf(value);
  const path = previewForTool(step.name, step.args) || 'File';
  const start = argNumber(step.args, ['start', 'offset', 'line_start', 'from']);
  const end = argNumber(step.args, ['end', 'limit', 'line_end', 'to']);
  const range =
    start !== undefined && end !== undefined
      ? `lines ${start}-${start + end - 1}`
      : start !== undefined
        ? `from line ${start}`
        : undefined;
  if (!content.trim()) return <div className="act-empty">No output</div>;
  return (
    <div>
      <div className="act-section-title">
        <span>{path}</span>
        {range && <span className="act-tabular">{range}</span>}
      </div>
      <CodeView code={content} title={path} lineNumbers maxLines={40} />
    </div>
  );
}
