import { useMemo, useState } from 'react';
import { Play } from 'lucide-react';
import { api } from '../../api';
import { Button, Chip } from '../../ui/primitives';
import type { ToolMeta } from '../../types';

interface SchemaProperty {
  type?: string;
  description?: string;
  default?: unknown;
  items?: unknown;
}

function propertiesOf(tool: ToolMeta): Record<string, SchemaProperty> {
  const params = tool.parameters as { properties?: Record<string, SchemaProperty> } | undefined;
  return params?.properties || {};
}

/**
 * Run a tool by hand against the agent's workspace. Useful for debugging a
 * failing tool or checking what an agent can actually reach.
 */
export default function ToolPlayground({
  agentId,
  tools,
}: {
  agentId?: string;
  tools: Record<string, ToolMeta>;
}) {
  const ids = useMemo(() => Object.keys(tools).sort(), [tools]);
  const [toolId, setToolId] = useState('');
  const [values, setValues] = useState<Record<string, string>>({});
  const [freeform, setFreeform] = useState('');
  const [output, setOutput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const tool = toolId ? tools[toolId] : null;
  const properties = tool ? propertiesOf(tool) : {};

  const choose = (id: string) => {
    setToolId(id);
    setValues({});
    setFreeform('');
    setOutput('');
    setError('');
  };

  const buildArgs = (): Record<string, unknown> => {
    if (freeform.trim()) {
      try {
        const parsed = JSON.parse(freeform);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          return parsed as Record<string, unknown>;
        }
      } catch {
        throw new Error('Arguments must be a JSON object.');
      }
    }
    const args: Record<string, unknown> = {};
    for (const [key, prop] of Object.entries(properties)) {
      const raw = values[key];
      if (raw === undefined || raw === '') continue;
      if (prop.type === 'integer' || prop.type === 'number') args[key] = Number(raw);
      else if (prop.type === 'boolean') args[key] = raw === 'true';
      else if (prop.type === 'array' || prop.type === 'object') {
        try {
          args[key] = JSON.parse(raw);
        } catch {
          args[key] = raw;
        }
      } else args[key] = raw;
    }
    return args;
  };

  const run = async () => {
    if (!agentId || !toolId) return;
    setBusy(true);
    setError('');
    setOutput('');
    try {
      const args = buildArgs();
      const res = await api.agents.invokeTool(agentId, toolId, args);
      if (res.error) setError(res.error);
      else setOutput(res.output ?? '');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not run the tool.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="ax-form__section ax-playground">
      <h4 className="ax-form__title">Tool playground</h4>
      <p className="ax-form__hint">
        Run one tool in this agent&apos;s workspace. Nothing is queued as a run.
      </p>
      {!agentId && <div className="ax-tier__empty">Save the agent first to test its tools.</div>}
      {agentId && (
        <>
          <select value={toolId} onChange={(event) => choose(event.target.value)}>
            <option value="">Choose a tool…</option>
            {ids.map((id) => (
              <option key={id} value={id}>
                {id} · tier {tools[id].tier}
              </option>
            ))}
          </select>

          {tool && (
            <>
              <p className="ax-playground__desc">{tool.description}</p>
              {Object.entries(properties).map(([key, prop]) => (
                <label key={key} className="ax-playground__field">
                  <span>
                    {key}
                    {prop.type && <em>{prop.type}</em>}
                  </span>
                  {prop.type === 'boolean' ? (
                    <select
                      value={values[key] ?? String(prop.default ?? '')}
                      onChange={(event) => setValues((cur) => ({ ...cur, [key]: event.target.value }))}
                    >
                      <option value="">default</option>
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  ) : prop.type === 'array' || prop.type === 'object' ? (
                    <textarea
                      rows={2}
                      value={values[key] ?? ''}
                      placeholder={prop.description || `JSON ${prop.type}`}
                      onChange={(event) => setValues((cur) => ({ ...cur, [key]: event.target.value }))}
                    />
                  ) : (
                    <input
                      value={values[key] ?? ''}
                      placeholder={prop.description || key}
                      onChange={(event) => setValues((cur) => ({ ...cur, [key]: event.target.value }))}
                    />
                  )}
                </label>
              ))}
              <label className="ax-playground__field">
                <span>
                  raw JSON <em>overrides the fields</em>
                </span>
                <textarea
                  rows={3}
                  value={freeform}
                  placeholder='{"query": "..."}'
                  onChange={(event) => setFreeform(event.target.value)}
                />
              </label>
              <div className="ax-playground__actions">
                <Button size="sm" variant="primary" disabled={busy || !toolId} onClick={() => void run()}>
                  <Play size={12} /> Run tool
                </Button>
                {tool.requires_approval && <Chip tone="warn">normally needs approval</Chip>}
              </div>
              {error && <pre className="ax-playground__error">{error}</pre>}
              {output && <pre className="ax-playground__output">{output.slice(0, 12_000)}</pre>}
            </>
          )}
        </>
      )}
    </section>
  );
}
