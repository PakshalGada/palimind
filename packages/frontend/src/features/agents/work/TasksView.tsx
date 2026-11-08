import { useCallback, useEffect, useMemo, useState } from 'react';
import { Plus, RotateCcw, Send, Square, X } from 'lucide-react';
import { api } from '../../../api';
import { useApp } from '../../../AppContext';
import { Button, Chip, EmptyState } from '../../../ui/primitives';
import type { AgentListItem } from '../../../types';
import './TasksView.css';

interface AgentTask {
  id: string;
  agent_id: string;
  agent_name: string;
  title: string;
  input: string;
  status: string;
  result?: string;
  error?: string;
  priority?: number;
  parent_task_id?: string;
  created_at?: number;
  updated_at?: number;
  deliveries?: { id: string; text: string; sender_kind?: string; created_at?: number }[];
}

type Filter = 'open' | 'running' | 'done' | 'all';

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'open', label: 'Open' },
  { id: 'running', label: 'Running' },
  { id: 'done', label: 'Done' },
  { id: 'all', label: 'All' },
];

function taskTone(status: string): 'success' | 'warn' | 'danger' | 'muted' | 'default' {
  if (status === 'done' || status === 'completed') return 'success';
  if (status === 'running' || status === 'queued' || status === 'in_progress') return 'warn';
  if (status === 'failed' || status === 'error') return 'danger';
  if (status === 'closed' || status === 'cancelled') return 'muted';
  return 'default';
}

function relTime(ts?: number): string {
  if (!ts) return '';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

export default function TasksView({ agents }: { agents: AgentListItem[] }) {
  const { addToast, setAgentsView, setSelectedAgentId, setSelectedTeamId } = useApp();
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [filter, setFilter] = useState<Filter>('open');
  const [selected, setSelected] = useState<string | null>(null);
  const [reply, setReply] = useState('');
  const [creating, setCreating] = useState(false);
  const [draftAgent, setDraftAgent] = useState('');
  const [draftTitle, setDraftTitle] = useState('');
  const [draftInput, setDraftInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const batches = await Promise.all(
        agents.map(async (agent) => {
          const data = await api.agentTasks.list(agent.id, true).catch(() => ({ tasks: [] }));
          return (data.tasks || []).map((task) => ({
            ...(task as unknown as AgentTask),
            agent_id: agent.id,
            agent_name: agent.display_name || agent.name,
          }));
        }),
      );
      setTasks(batches.flat());
    } finally {
      setLoading(false);
    }
  }, [agents]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 12_000);
    const onChange = () => void load();
    window.addEventListener('palimind:agents-changed', onChange);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('palimind:agents-changed', onChange);
    };
  }, [load]);

  const visible = useMemo(() => {
    const isOpen = (task: AgentTask) =>
      !['done', 'completed', 'closed', 'cancelled'].includes(task.status);
    return tasks
      .filter((task) => {
        if (filter === 'open') return isOpen(task);
        if (filter === 'running') return task.status === 'running' || task.status === 'queued';
        if (filter === 'done') return !isOpen(task);
        return true;
      })
      .sort((a, b) => (b.updated_at || b.created_at || 0) - (a.updated_at || a.created_at || 0));
  }, [filter, tasks]);

  const current = tasks.find((task) => task.id === selected) ?? null;

  const act = async (task: AgentTask, action: 'stop' | 'close' | 'reopen') => {
    setBusy(true);
    try {
      await api.agentTasks[action](task.agent_id, task.id);
      await load();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not update the task', { tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    if (!current || !reply.trim()) return;
    setBusy(true);
    try {
      await api.agentTasks.send(current.agent_id, current.id, reply.trim());
      setReply('');
      await load();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not send the message', { tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    if (!draftAgent || !draftTitle.trim()) return;
    setBusy(true);
    try {
      const res = await api.agentTasks.create(draftAgent, {
        title: draftTitle.trim(),
        input: draftInput.trim() || draftTitle.trim(),
      });
      if (res.error) {
        addToast(res.error, { tone: 'error' });
        return;
      }
      setCreating(false);
      setDraftTitle('');
      setDraftInput('');
      await load();
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } finally {
      setBusy(false);
    }
  };

  const openInChat = (task: AgentTask) => {
    setAgentsView('chat');
    setSelectedTeamId(null);
    setSelectedAgentId(task.agent_id);
  };

  return (
    <div className="ag-tasks">
      <header className="ag-tasks__bar">
        <div className="ag-segmented" role="tablist" aria-label="Task filters">
          {FILTERS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={filter === item.id}
              className={filter === item.id ? 'is-on' : ''}
              onClick={() => setFilter(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <Button size="sm" variant="primary" onClick={() => setCreating(true)}>
          <Plus size={13} /> New task
        </Button>
      </header>

      <div className="ag-tasks__body">
        <div className="ag-tasks__list">
          {visible.map((task) => (
            <button
              key={`${task.agent_id}-${task.id}`}
              type="button"
              className={`ag-tasks__row${selected === task.id ? ' is-active' : ''}`}
              onClick={() => setSelected(task.id)}
            >
              <span className="ag-tasks__row-head">
                <strong>{task.title || task.input || 'Task'}</strong>
                <Chip tone={taskTone(task.status)}>{task.status}</Chip>
              </span>
              <span className="ag-tasks__row-meta">
                {task.agent_name} · {relTime(task.updated_at || task.created_at)}
              </span>
            </button>
          ))}
          {!loading && visible.length === 0 && (
            <EmptyState
              title={filter === 'done' ? 'No finished tasks' : 'No tasks yet'}
              description="Tasks are queued agent runs you can steer, stop and reply to."
            />
          )}
        </div>

        <div className="ag-tasks__detail">
          {current ? (
            <>
              <header className="ag-tasks__detail-head">
                <div>
                  <h3>{current.title || 'Task'}</h3>
                  <span>
                    {current.agent_name} · {current.status}
                  </span>
                </div>
                <div className="ag-tasks__actions">
                  {['running', 'queued'].includes(current.status) && (
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(current, 'stop')}>
                      <Square size={12} /> Stop
                    </Button>
                  )}
                  {['done', 'completed', 'closed'].includes(current.status) ? (
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(current, 'reopen')}>
                      <RotateCcw size={12} /> Reopen
                    </Button>
                  ) : (
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(current, 'close')}>
                      <X size={12} /> Close
                    </Button>
                  )}
                  <Button size="sm" variant="secondary" onClick={() => openInChat(current)}>
                    Open in chat
                  </Button>
                </div>
              </header>

              <div className="ag-tasks__scroll">
                <section className="ag-tasks__block">
                  <span className="ag-tasks__label">Request</span>
                  <p>{current.input || current.title}</p>
                </section>
                {current.result && (
                  <section className="ag-tasks__block">
                    <span className="ag-tasks__label">Result</span>
                    <pre>{current.result}</pre>
                  </section>
                )}
                {current.error && (
                  <section className="ag-tasks__block is-error">
                    <span className="ag-tasks__label">Error</span>
                    <p>{current.error}</p>
                  </section>
                )}
                {(current.deliveries || []).length > 0 && (
                  <section className="ag-tasks__block">
                    <span className="ag-tasks__label">Messages</span>
                    {(current.deliveries || []).map((delivery) => (
                      <p key={delivery.id} className="ag-tasks__delivery">
                        <em>{delivery.sender_kind || 'agent'}</em>
                        {delivery.text}
                      </p>
                    ))}
                  </section>
                )}
              </div>

              <div className="ag-tasks__composer">
                <input
                  value={reply}
                  placeholder="Reply to this task…"
                  onChange={(event) => setReply(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) void send();
                  }}
                />
                <Button size="sm" variant="primary" disabled={busy || !reply.trim()} onClick={() => void send()}>
                  <Send size={12} />
                </Button>
              </div>
            </>
          ) : (
            <div className="ag-tasks__placeholder">
              <p>Select a task to see its request, result and messages.</p>
            </div>
          )}
        </div>
      </div>

      {creating && (
        <div className="ag-tasks__modal" role="dialog" aria-modal="true" aria-label="New task">
          <button type="button" className="ag-tasks__scrim" onClick={() => setCreating(false)} aria-label="Close" />
          <div className="ag-tasks__dialog">
            <header>
              <h3>New task</h3>
              <button type="button" onClick={() => setCreating(false)} aria-label="Close">
                <X size={15} />
              </button>
            </header>
            <label>
              Agent
              <select value={draftAgent} onChange={(event) => setDraftAgent(event.target.value)}>
                <option value="">Choose an agent</option>
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.display_name || agent.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Title
              <input value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} />
            </label>
            <label>
              Request
              <textarea
                rows={4}
                value={draftInput}
                placeholder="What should the agent do?"
                onChange={(event) => setDraftInput(event.target.value)}
              />
            </label>
            <div className="ag-tasks__dialog-actions">
              <Button size="sm" variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
              <Button size="sm" variant="primary" disabled={busy || !draftAgent || !draftTitle.trim()} onClick={() => void create()}>
                Create task
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
