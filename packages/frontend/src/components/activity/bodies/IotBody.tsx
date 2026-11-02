import type { ToolStep } from '../model';
import { CodeView } from '../primitives/CodeView';
import { parseOutput } from '../toolOutput';

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export default function IotBody({ step }: { step: ToolStep }) {
  const args = asRecord(step.args);
  const output = asRecord(parseOutput(step.output));
  const topic = String(args.topic ?? output.topic ?? '');
  const action = String(args.action ?? args.direction ?? output.action ?? 'publish');
  const qos = args.qos ?? output.qos;
  const payloadValue = args.payload ?? args.message ?? output.payload ?? '';
  const payload = typeof payloadValue === 'string' ? payloadValue : JSON.stringify(payloadValue, null, 2);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="act-section-title">
        {topic && <span className="act-chip">{topic}</span>}
        <span className="act-chip">{action}</span>
        {qos != null && <span className="act-chip act-tabular">QoS {String(qos)}</span>}
      </div>
      {payload && <CodeView code={payload} language="json" title="Payload" maxLines={20} />}
      {!payload && <div className="act-empty">No payload</div>}
    </div>
  );
}
