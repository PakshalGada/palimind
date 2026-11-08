import type { ToolStep } from '../model';
import { uiOf, type ToolUI } from '../toolOutput';

/**
 * Generic renderer for the typed tool-UI contract. A tool returns
 * `{"ui": {"type": "table" | "keyvalue" | "chart" | "text", ...}}` and this
 * component renders it without a per-tool React component.
 */
export default function UIBody({ step }: { step: ToolStep }) {
  const ui = uiOf(step.output);
  if (!ui) return <div className="act-empty">No renderable output</div>;
  return (
    <div className={`act-ui${ui.tone ? ` act-ui--${ui.tone}` : ''}`}>
      {ui.title && <div className="act-section-title">{ui.title}</div>}
      {ui.type === 'text' && <p className="act-ui__text">{ui.text}</p>}
      {ui.type === 'keyvalue' && <KeyValue ui={ui} />}
      {ui.type === 'table' && <Table ui={ui} />}
      {ui.type === 'chart' && <Chart ui={ui} />}
    </div>
  );
}

function KeyValue({ ui }: { ui: ToolUI }) {
  const items = ui.items ?? [];
  if (items.length === 0) return <div className="act-empty">No values</div>;
  return (
    <dl className="act-ui__kv">
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Table({ ui }: { ui: ToolUI }) {
  const columns = ui.columns ?? [];
  const rows = ui.rows ?? [];
  if (rows.length === 0) return <div className="act-empty">No rows</div>;
  return (
    <div className="act-ui__table-wrap">
      <table className="act-ui__table">
        {columns.length > 0 && (
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{String(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Chart({ ui }: { ui: ToolUI }) {
  const labels = ui.labels ?? [];
  const values = ui.values ?? [];
  const max = Math.max(1, ...values);
  if (labels.length === 0) return <div className="act-empty">No chart data</div>;
  return (
    <div className="act-ui__chart">
      {labels.map((label, index) => (
        <div key={`${label}-${index}`} className="act-ui__chart-row">
          <span>{label}</span>
          <span className="act-ui__chart-track">
            <span
              className="act-ui__chart-fill"
              style={{ width: `${Math.max(2, ((values[index] ?? 0) / max) * 100)}%` }}
            />
          </span>
          <em>{values[index] ?? 0}</em>
        </div>
      ))}
    </div>
  );
}
