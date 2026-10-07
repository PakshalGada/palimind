import { useState } from 'react';
import { X, Trash2 } from 'lucide-react';
import { Button, TextInput, Field, TextArea, Picker } from '../ui/primitives';
import type { Workflow, WorkflowNode } from '../types';

export interface AgentOption {
  id: string;
  name: string;
}

interface NodeConfigPanelProps {
  node: WorkflowNode | null;
  workflow: Workflow;
  agents: AgentOption[];
  onUpdateConfig: (nodeId: string, config: Record<string, unknown>) => void;
  onUpdateName: (nodeId: string, name: string) => void;
  onDelete: (nodeId: string) => void;
  onClose: () => void;
}

export default function NodeConfigPanel({
  node,
  agents,
  onUpdateConfig,
  onUpdateName,
  onDelete,
  onClose,
}: NodeConfigPanelProps) {
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

  if (!node) {
    return (
      <div className="wf-config-panel empty">
        <div className="wf-config-empty">
          <p>Select a node to configure</p>
          <p className="wf-config-hint">Click a node on the canvas to edit its settings</p>
        </div>
      </div>
    );
  }

  const config = node.config;
  const updateConfig = (key: string, value: unknown) => {
    onUpdateConfig(node.id, { ...config, [key]: value });
  };

  const testNode = async () => {
    setTesting(true);
    setTestResult(null);
    await new Promise((r) => setTimeout(r, 500 + Math.random() * 700));
    setTestResult(`"${node.name}" is ready. Run the workflow to execute it in order.`);
    setTesting(false);
  };

  const promptValue = (config.prompt as string) || '';

  const renderPromptField = () => (
    <Field label="What should this node do?">
      <TextArea
        value={promptValue}
        onChange={(e) => updateConfig('prompt', e.target.value)}
        rows={4}
        placeholder="Describe the instruction for this step. Use {{nodeid.output}} to reference earlier results."
      />
    </Field>
  );

  const renderConfigFields = () => {
    switch (node.type) {
      case 'agent':
        return (
          <>
            <Field label="Agent">
              <Picker
                value={(config.agent_id as string) || ''}
                onChange={(v) => updateConfig('agent_id', v)}
                placeholder="Select an agent"
                ariaLabel="Select agent"
                options={agents.map((a) => ({ value: a.id, label: a.name }))}
              />
            </Field>
            <Field label="Model override">
              <TextInput
                value={(config.model as string) || ''}
                onChange={(e) => updateConfig('model', e.target.value)}
                placeholder="Use the agent default"
              />
            </Field>
          </>
        );
      case 'tool':
        return (
          <>
            <Field label="Tool">
              <Picker
                value={(config.tool as string) || 'web_search'}
                onChange={(v) => updateConfig('tool', v)}
                ariaLabel="Select tool"
                options={[
                  { value: 'web_search', label: 'Web Search' },
                  { value: 'fetch_url', label: 'Fetch URL' },
                  { value: 'read_file', label: 'Read File' },
                  { value: 'write_file', label: 'Write File' },
                  { value: 'run_python', label: 'Run Python' },
                ]}
              />
            </Field>
            <Field label="Arguments (JSON)">
              <TextArea
                value={JSON.stringify(config.args || {}, null, 2)}
                onChange={(e) => {
                  try {
                    updateConfig('args', JSON.parse(e.target.value));
                  } catch {
                    // ignore invalid JSON while typing
                  }
                }}
                rows={4}
                placeholder='{"query": "..."}'
              />
            </Field>
          </>
        );
      case 'condition':
        return (
          <>
            <Field label="Condition">
              <TextInput
                value={(config.condition as string) || ''}
                onChange={(e) => updateConfig('condition', e.target.value)}
                placeholder="{{node1.output}} is not empty"
              />
            </Field>
            <Field label="True branch">
              <TextInput
                value={(config.true_branch as string) || ''}
                onChange={(e) => updateConfig('true_branch', e.target.value)}
                placeholder="Node id for the true branch"
              />
            </Field>
            <Field label="False branch">
              <TextInput
                value={(config.false_branch as string) || ''}
                onChange={(e) => updateConfig('false_branch', e.target.value)}
                placeholder="Node id for the false branch"
              />
            </Field>
          </>
        );
      case 'loop':
        return (
          <>
            <Field label="Items expression">
              <TextInput
                value={(config.items as string) || ''}
                onChange={(e) => updateConfig('items', e.target.value)}
                placeholder="{{node1.output.items}}"
              />
            </Field>
            <Field label="Max iterations">
              <TextInput
                type="number"
                value={(config.max_iterations as number) || 10}
                onChange={(e) => updateConfig('max_iterations', parseInt(e.target.value) || 10)}
              />
            </Field>
          </>
        );
      case 'delay':
        return (
          <Field label="Seconds">
            <TextInput
              type="number"
              value={(config.seconds as number) || 5}
              onChange={(e) => updateConfig('seconds', parseInt(e.target.value) || 0)}
            />
          </Field>
        );
      case 'webhook':
        return (
          <>
            <Field label="Path">
              <TextInput
                value={(config.path as string) || '/webhook'}
                onChange={(e) => updateConfig('path', e.target.value)}
              />
            </Field>
            <Field label="Method">
              <Picker
                value={(config.method as string) || 'POST'}
                onChange={(v) => updateConfig('method', v)}
                ariaLabel="Select method"
                options={[
                  { value: 'GET', label: 'GET' },
                  { value: 'POST', label: 'POST' },
                  { value: 'PUT', label: 'PUT' },
                  { value: 'DELETE', label: 'DELETE' },
                ]}
              />
            </Field>
          </>
        );
      case 'cron':
        return (
          <Field label="Schedule (cron expression)">
            <TextInput
              value={(config.schedule as string) || '0 * * * *'}
              onChange={(e) => updateConfig('schedule', e.target.value)}
              placeholder="0 * * * *"
            />
          </Field>
        );
      case 'code':
        return (
          <>
            <Field label="Language">
              <Picker
                value={(config.language as string) || 'python'}
                onChange={(v) => updateConfig('language', v)}
                ariaLabel="Select language"
                options={[
                  { value: 'python', label: 'Python' },
                  { value: 'javascript', label: 'JavaScript' },
                ]}
              />
            </Field>
            <Field label="Code" hint="Stored with the workflow and shown for reference.">
              <TextArea
                value={(config.code as string) || ''}
                onChange={(e) => updateConfig('code', e.target.value)}
                rows={8}
                placeholder="# Your code here"
                className="wf-code-input"
              />
            </Field>
          </>
        );
      case 'transform':
        return (
          <Field label="Operation">
            <Picker
              value={(config.operation as string) || 'json_parse'}
              onChange={(v) => updateConfig('operation', v)}
              ariaLabel="Select operation"
              options={[
                { value: 'json_parse', label: 'JSON Parse' },
                { value: 'json_stringify', label: 'JSON Stringify' },
                { value: 'text_extract', label: 'Text Extract' },
                { value: 'template', label: 'Template' },
              ]}
            />
          </Field>
        );
      case 'output':
        return (
          <>
            <Field label="Destination">
              <Picker
                value={(config.destination as string) || 'file'}
                onChange={(v) => updateConfig('destination', v)}
                ariaLabel="Select destination"
                options={[
                  { value: 'file', label: 'File' },
                  { value: 'email', label: 'Email' },
                  { value: 'notification', label: 'Notification' },
                  { value: 'webhook', label: 'Webhook' },
                ]}
              />
            </Field>
            <Field label="Format">
              <Picker
                value={(config.format as string) || 'json'}
                onChange={(v) => updateConfig('format', v)}
                ariaLabel="Select format"
                options={[
                  { value: 'json', label: 'JSON' },
                  { value: 'markdown', label: 'Markdown' },
                  { value: 'text', label: 'Plain Text' },
                  { value: 'html', label: 'HTML' },
                ]}
              />
            </Field>
          </>
        );
      default:
        return <p className="wf-config-hint">No configuration options for this node type.</p>;
    }
  };

  return (
    <div className="wf-config-panel">
      <div className="wf-config-header">
        <input
          className="wf-config-name"
          value={node.name}
          onChange={(e) => onUpdateName(node.id, e.target.value)}
        />
        <button className="wf-config-close" onClick={onClose} aria-label="Close config">
          <X size={16} />
        </button>
      </div>
      <div className="wf-config-body">
        <div className="wf-config-type-badge">{node.type}</div>
        {renderPromptField()}
        {renderConfigFields()}
        {testResult && <div className="wf-config-test-result">{testResult}</div>}
      </div>
      <div className="wf-config-footer">
        <Button onClick={testNode} disabled={testing} variant="secondary">
          {testing ? 'Checking' : 'Validate'}
        </Button>
        <Button onClick={() => onDelete(node.id)} variant="danger">
          <Trash2 size={14} /> Delete
        </Button>
      </div>
    </div>
  );
}
