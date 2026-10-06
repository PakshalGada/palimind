import { useCallback, useEffect, useRef, useState } from 'react';
import { Network, Play, Square } from 'lucide-react';
import { api } from '../api';
import { useApp } from '../AppContext';
import { Badge, Button, Chip, Field, Modal, SegmentedControl, TextArea, TextInput } from '../ui/primitives';
import './AgentGraph.css';

interface GraphNode {
  agent_id: number;
  label: string;
  task: string;
  status: 'waiting' | 'working' | 'complete' | 'failed';
  steps: string[];
  output: string;
}

type OrchestrationMode = 'fan_out' | 'arena';

/**
 * Visual multi-agent activity graph (Phase 4.2). Runs an orchestration for the
 * selected agent and renders the fan-out, live steps, blackboard and final
 * synthesis. Open it with the `palimind:open-agent-graph` event.
 */
export default function AgentGraph() {
  const { selectedAgentId, addToast } = useApp();
  const [open, setOpen] = useState(false);
  const [task, setTask] = useState('');
  const [mode, setMode] = useState<OrchestrationMode>('fan_out');
  const [numAgents, setNumAgents] = useState(4);
  const [running, setRunning] = useState(false);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [synthesis, setSynthesis] = useState('');
  const [conflicts, setConflicts] = useState(0);
  const abortRef = useRef(false);

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener('palimind:open-agent-graph', onOpen);
    return () => window.removeEventListener('palimind:open-agent-graph', onOpen);
  }, []);

  const upsert = useCallback((agentId: number, patch: Partial<GraphNode>) => {
    setNodes((prev) => {
      const existing = prev.find((n) => n.agent_id === agentId);
      if (existing) {
        return prev.map((n) => (n.agent_id === agentId ? { ...n, ...patch } : n));
      }
      return [
        ...prev,
        {
          agent_id: agentId,
          label: `Agent ${agentId}`,
          task: '',
          status: 'waiting',
          steps: [],
          output: '',
          ...patch,
        },
      ];
    });
  }, []);

  const run = async () => {
    if (!selectedAgentId) {
      addToast('Select an agent first.');
      return;
    }
    if (!task.trim()) {
      addToast('Describe the task to orchestrate.');
      return;
    }
    abortRef.current = false;
    setNodes([]);
    setSynthesis('');
    setConflicts(0);
    setRunning(true);
    try {
      await api.agents.orchestrateStream(
        selectedAgentId,
        task.trim(),
        (ev) => {
          if (abortRef.current) return;
          if (ev.type === 'orchestrator:plan') {
            const agents = (ev.agents as { agent_id: number; label: string; task: string }[]) || [];
            setNodes(
              agents.map((a) => ({
                agent_id: a.agent_id,
                label: a.label,
                task: a.task,
                status: 'waiting',
                steps: [],
                output: '',
              })),
            );
          } else if (ev.type === 'orchestrator:agent_start') {
            upsert(ev.agent_id as number, { status: 'working', label: String(ev.label || '') });
          } else if (ev.type === 'orchestrator:agent_step') {
            setNodes((prev) =>
              prev.map((n) =>
                n.agent_id === ev.agent_id ? { ...n, steps: [...n.steps, String(ev.text || '')] } : n,
              ),
            );
          } else if (ev.type === 'orchestrator:blackboard') {
            upsert(ev.agent_id as number, {
              output: String(ev.output || ''),
              label: String(ev.label || ''),
            });
          } else if (ev.type === 'orchestrator:agent_complete') {
            upsert(ev.agent_id as number, { status: 'complete' });
          } else if (ev.type === 'orchestrator:conflict') {
            setConflicts(((ev.conflicts as unknown[]) || []).length);
          } else if (ev.type === 'orchestrator:complete') {
            setSynthesis(String(ev.output || ''));
          } else if (ev.type === 'agent:completed') {
            setSynthesis(String(ev.output || ''));
          } else if (ev.type === 'error') {
            addToast(String(ev.text || 'Orchestration error'));
          }
        },
        { mode, num_agents: numAgents },
      );
    } catch (e) {
      addToast(e instanceof Error ? e.message : String(e));
    }
    setRunning(false);
  };

  const stop = () => {
    abortRef.current = true;
    setRunning(false);
  };

  return (
    <Modal
      open={open}
      onClose={() => setOpen(false)}
      title="Agent activity graph"
      subtitle="Parallel orchestration with shared blackboard and synthesis"
      width={920}
    >
      <div className="ag">
        <div className="ag-controls">
          <Field label="Task">
            <TextArea
              rows={2}
              value={task}
              placeholder="e.g. Research the current state of local-first AI and write a comparison"
              onChange={(e) => setTask(e.target.value)}
              disabled={running}
            />
          </Field>
          <div className="ag-controls__row">
            <Field label="Mode">
              <SegmentedControl<OrchestrationMode>
                value={mode}
                onChange={setMode}
                options={[
                  { value: 'fan_out', label: 'Fan-out' },
                  { value: 'arena', label: 'Arena' },
                ]}
              />
            </Field>
            <Field label="Agents">
              <TextInput
                type="number"
                min={1}
                max={8}
                value={numAgents}
                onChange={(e) => setNumAgents(Math.max(1, Math.min(8, parseInt(e.target.value) || 1)))}
                disabled={running}
              />
            </Field>
            {running ? (
              <Button variant="danger" onClick={stop}>
                <Square size={14} /> Stop
              </Button>
            ) : (
              <Button variant="primary" onClick={run} disabled={!selectedAgentId}>
                <Play size={14} /> Run
              </Button>
            )}
          </div>
          {!selectedAgentId && <div className="ag-hint">Select an agent to orchestrate.</div>}
        </div>

        <div className="ag-graph">
          <div className="ag-root">
            <Network size={16} />
            <span>Orchestrator</span>
            {conflicts > 0 && <Badge tone="warn">{conflicts} conflicts</Badge>}
          </div>
          {nodes.length === 0 && <div className="ag-empty">No active orchestration.</div>}
          <div className="ag-nodes">
            {nodes.map((n) => (
              <div key={n.agent_id} className={`ag-node ag-node--${n.status}`}>
                <div className="ag-node__head">
                  <span className="ag-node__label">{n.label}</span>
                  <Badge tone={n.status === 'complete' ? 'success' : n.status === 'working' ? 'accent' : 'muted'}>
                    {n.status}
                  </Badge>
                </div>
                <div className="ag-node__task">{n.task}</div>
                {n.steps.length > 0 && (
                  <div className="ag-node__steps">
                    {n.steps.slice(-4).map((s, i) => (
                      <div key={i} className="ag-node__step">
                        {s}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {synthesis && (
          <div className="ag-synthesis">
            <div className="ag-synthesis__head">
              <Chip tone="accent">Synthesis</Chip>
            </div>
            <pre className="ag-synthesis__body">{synthesis}</pre>
          </div>
        )}
      </div>
    </Modal>
  );
}
