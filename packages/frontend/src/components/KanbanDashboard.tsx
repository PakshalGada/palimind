import { useState, useCallback, useEffect } from 'react';
import {
  Plus,
  Search,
  Filter,
  CalendarDays,
  List,
  Columns3,
  BarChart3,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Play,
  Circle,
  Trash2,
  Pencil,
  X,
  User,
  Send,
} from 'lucide-react';
import { useApp } from '../AppContext';
import { api } from '../api';
import { Button, Badge, Modal, TextInput, TextArea, Field, Picker, EmptyState } from '../ui/primitives';
import type { KanbanTask, KanbanStatus, KanbanPriority, KanbanColumn } from '../types';
import './KanbanDashboard.css';

const COLUMNS: KanbanColumn[] = [
  { id: 'todo', title: 'To-Do', color: 'var(--text-muted)' },
  { id: 'in_progress', title: 'In Progress', color: 'var(--text-main)' },
  { id: 'pending_approval', title: 'Pending Approval', color: 'var(--text-secondary)' },
  { id: 'completed', title: 'Completed', color: 'var(--text-main)' },
  { id: 'failed', title: 'Failed', color: 'var(--text-muted)' },
];

const STATUS_ICONS: Record<KanbanStatus, React.ReactNode> = {
  todo: <Circle size={13} />,
  in_progress: <Play size={13} />,
  pending_approval: <AlertTriangle size={13} />,
  completed: <CheckCircle2 size={13} />,
  failed: <XCircle size={13} />,
};

const PRIORITIES: KanbanPriority[] = ['low', 'medium', 'high', 'critical'];

function PriorityMark({ priority }: { priority: KanbanPriority }) {
  const level = PRIORITIES.indexOf(priority) + 1;
  return (
    <span className={`kb-priority kb-priority--${priority}`} title={`${priority} priority`}>
      {[1, 2, 3].map((i) => (
        <i key={i} className={i <= level ? 'on' : ''} />
      ))}
    </span>
  );
}

type ViewMode = 'kanban' | 'list' | 'calendar' | 'timeline' | 'statistics';

function statusTitle(status: KanbanStatus): string {
  return COLUMNS.find((c) => c.id === status)?.title || status;
}

function agentLabel(task: KanbanTask): string {
  return task.agent_name || 'Unassigned';
}

export default function KanbanDashboard() {
  const { addToast } = useApp();
  const [view, setView] = useState<ViewMode>('kanban');
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterAgent, setFilterAgent] = useState('');
  const [filterPriority, setFilterPriority] = useState('');
  const [showQuickAdd, setShowQuickAdd] = useState(false);
  const [quickAddTitle, setQuickAddTitle] = useState('');
  const [quickAddPrompt, setQuickAddPrompt] = useState('');
  const [quickAddAgent, setQuickAddAgent] = useState('');
  const [quickAddPriority, setQuickAddPriority] = useState<KanbanPriority>('medium');
  const [draggedTask, setDraggedTask] = useState<string | null>(null);
  const [dragOverColumn, setDragOverColumn] = useState<KanbanStatus | null>(null);
  const [editingTask, setEditingTask] = useState<KanbanTask | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [agents, setAgents] = useState<{ id: string; name: string }[]>([]);
  const [runningTaskId, setRunningTaskId] = useState<string | null>(null);

  const loadTasks = useCallback(async () => {
    try {
      const data = await api.tasks.list();
      setTasks(data.tasks || []);
    } catch {
      setTasks([]);
    }
  }, []);

  useEffect(() => {
    void loadTasks();
    api.agents
      .list()
      .then((d) => setAgents((d.agents || []).map((a) => ({ id: a.id, name: a.name }))))
      .catch(() => {});
  }, [loadTasks]);

  const stats = (() => {
    const completed = tasks.filter((t) => t.status === 'completed').length;
    const failed = tasks.filter((t) => t.status === 'failed').length;
    const durations = tasks.filter((t) => t.duration).map((t) => t.duration as number);
    const avgDuration = durations.length > 0 ? durations.reduce((a, b) => a + b, 0) / durations.length : 0;
    const perDay: { date: string; count: number }[] = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const dateStr = d.toISOString().split('T')[0];
      const count = tasks.filter((t) => new Date(t.created_at * 1000).toISOString().split('T')[0] === dateStr).length;
      perDay.push({ date: dateStr, count });
    }
    return { total: tasks.length, completed, failed, avgDuration, perDay };
  })();

  const filteredTasks = tasks.filter((t) => {
    if (
      searchQuery &&
      !t.title.toLowerCase().includes(searchQuery.toLowerCase()) &&
      !t.description.toLowerCase().includes(searchQuery.toLowerCase()) &&
      !(t.prompt || '').toLowerCase().includes(searchQuery.toLowerCase())
    )
      return false;
    if (filterAgent && t.agent_id !== filterAgent) return false;
    if (filterPriority && t.priority !== filterPriority) return false;
    return true;
  });

  const persistStatus = useCallback(async (taskId: string, newStatus: KanbanStatus) => {
    try {
      const res = await api.tasks.update(taskId, { status: newStatus });
      if (res.task) setTasks((prev) => prev.map((t) => (t.id === taskId ? res.task! : t)));
    } catch {
      // keep local state
    }
  }, []);

  const moveTask = useCallback(
    (taskId: string, newStatus: KanbanStatus) => {
      setTasks((prev) =>
        prev.map((t) => (t.id === taskId ? { ...t, status: newStatus } : t)),
      );
      void persistStatus(taskId, newStatus);
    },
    [persistStatus],
  );

  const createTask = useCallback(async () => {
    if (!quickAddTitle.trim()) {
      addToast('Give the task a title');
      return;
    }
    const payload: Partial<KanbanTask> = {
      title: quickAddTitle.trim(),
      prompt: quickAddPrompt.trim() || quickAddTitle.trim(),
      agent_id: quickAddAgent || '',
      agent_name: agents.find((a) => a.id === quickAddAgent)?.name || '',
      priority: quickAddPriority,
      status: 'todo',
    };
    try {
      const res = await api.tasks.create(payload);
      if (res.task) setTasks((prev) => [res.task!, ...prev]);
    } catch {
      addToast('Failed to create task');
      return;
    }
    setQuickAddTitle('');
    setQuickAddPrompt('');
    setShowQuickAdd(false);
    addToast('Task created');
  }, [quickAddTitle, quickAddPrompt, quickAddAgent, quickAddPriority, agents, addToast]);

  const deleteTask = useCallback(
    async (taskId: string) => {
      setTasks((prev) => prev.filter((t) => t.id !== taskId));
      setSelectedTaskId((cur) => (cur === taskId ? null : cur));
      try {
        await api.tasks.delete(taskId);
      } catch {
        // local only
      }
      addToast('Task deleted');
    },
    [addToast],
  );

  const updateTask = useCallback(
    async (updated: KanbanTask) => {
      try {
        const res = await api.tasks.update(updated.id, updated);
        if (res.task) setTasks((prev) => prev.map((t) => (t.id === updated.id ? res.task! : t)));
      } catch {
        setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
      }
      setEditingTask(null);
      addToast('Task updated');
    },
    [addToast],
  );

  const runTask = useCallback(
    async (taskId: string) => {
      const task = tasks.find((t) => t.id === taskId);
      if (task && !task.agent_id) {
        addToast('Assign an agent before running');
        return;
      }
      setRunningTaskId(taskId);
      setTasks((prev) => prev.map((t) => (t.id === taskId ? { ...t, status: 'in_progress' } : t)));
      try {
        const res = await api.tasks.run(taskId);
        if (res.task) {
          setTasks((prev) => prev.map((t) => (t.id === taskId ? res.task! : t)));
        }
        addToast(res.error ? `Task failed: ${res.error}` : 'Task completed');
      } catch {
        addToast('Task run failed');
        void loadTasks();
      } finally {
        setRunningTaskId(null);
      }
    },
    [tasks, addToast, loadTasks],
  );

  const selectedTask = tasks.find((t) => t.id === selectedTaskId) || null;

  return (
    <div className="kb-panel">
      <div className="kb-topbar">
        <div className="kb-topbar-left">
          <span className="kb-title">Task Board</span>
          <Badge>{tasks.length} tasks</Badge>
        </div>
        <div className="kb-topbar-center">
          <div className="kb-view-switcher">
            {(
              [
                ['kanban', Columns3, 'Board'],
                ['list', List, 'List'],
                ['calendar', CalendarDays, 'Calendar'],
                ['timeline', Clock, 'Timeline'],
                ['statistics', BarChart3, 'Stats'],
              ] as [ViewMode, typeof Columns3, string][]
            ).map(([v, Icon, label]) => (
              <button key={v} className={`kb-view-btn ${view === v ? 'active' : ''}`} onClick={() => setView(v)}>
                <Icon size={14} />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="kb-topbar-right">
          <div className="kb-search">
            <Search size={14} />
            <input placeholder="Search tasks" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
          </div>
          <button
            className={`kb-icon-btn ${showFilters ? 'active' : ''}`}
            onClick={() => setShowFilters((f) => !f)}
            aria-label="Filters"
          >
            <Filter size={14} />
          </button>
          <Button onClick={() => setShowQuickAdd(true)} variant="primary">
            <Plus size={14} /> New Task
          </Button>
        </div>
      </div>

      {showFilters && (
        <div className="kb-filters">
          <Picker
            value={filterAgent}
            onChange={setFilterAgent}
            placeholder="All Agents"
            ariaLabel="Filter by agent"
            options={[{ value: '', label: 'All Agents' }, ...agents.map((a) => ({ value: a.id, label: a.name }))]}
          />
          <Picker
            value={filterPriority}
            onChange={setFilterPriority}
            placeholder="All Priorities"
            ariaLabel="Filter by priority"
            options={[{ value: '', label: 'All Priorities' }, ...PRIORITIES.map((p) => ({ value: p, label: p }))]}
          />
          <Button
            onClick={() => {
              setFilterAgent('');
              setFilterPriority('');
              setSearchQuery('');
            }}
            variant="secondary"
          >
            Clear
          </Button>
        </div>
      )}

      <div className="kb-main">
        {view === 'kanban' && (
          <div className="kb-board">
            {COLUMNS.map((col) => {
              const colTasks = filteredTasks.filter((t) => t.status === col.id);
              return (
                <div
                  key={col.id}
                  className={`kb-column ${dragOverColumn === col.id ? 'drag-over' : ''}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOverColumn(col.id);
                  }}
                  onDragLeave={() => setDragOverColumn(null)}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (draggedTask) moveTask(draggedTask, col.id);
                    setDraggedTask(null);
                    setDragOverColumn(null);
                  }}
                >
                  <div className="kb-column-header">
                    <span className="kb-column-title">
                      <span className="kb-column-dot" style={{ background: col.color }} />
                      {col.title}
                    </span>
                    <Badge>{colTasks.length}</Badge>
                  </div>
                  <div className="kb-column-body">
                    {colTasks.map((task) => (
                      <div
                        key={task.id}
                        className={`kb-card ${selectedTaskId === task.id ? 'selected' : ''}`}
                        draggable
                        onDragStart={() => setDraggedTask(task.id)}
                        onDragEnd={() => {
                          setDraggedTask(null);
                          setDragOverColumn(null);
                        }}
                        onClick={() => setSelectedTaskId(task.id)}
                      >
                        <div className="kb-card-header">
                          <PriorityMark priority={task.priority} />
                          <button
                            className="kb-card-menu"
                            onClick={(e) => {
                              e.stopPropagation();
                              void deleteTask(task.id);
                            }}
                            aria-label="Delete task"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                        <div className="kb-card-title">{task.title}</div>
                        <div className="kb-card-meta">
                          <span className="kb-card-agent">
                            <User size={10} /> {agentLabel(task)}
                          </span>
                          <span className="kb-card-date">
                            {new Date(task.created_at * 1000).toLocaleDateString()}
                          </span>
                        </div>
                        {runningTaskId === task.id && (
                          <div className="kb-card-running">
                            <span className="kb-spinner" /> Running…
                          </div>
                        )}
                      </div>
                    ))}
                    {colTasks.length === 0 && <div className="kb-column-empty">No tasks</div>}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {view === 'list' && (
          <div className="kb-list-view">
            {filteredTasks.length === 0 ? (
              <EmptyState
                icon={<List size={22} />}
                title="No tasks yet"
                description="Create a task, assign an agent, and run it."
              />
            ) : (
              <table className="kb-table">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Agent</th>
                    <th>Status</th>
                    <th>Priority</th>
                    <th>Created</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filteredTasks.map((task) => (
                    <tr key={task.id} onClick={() => setSelectedTaskId(task.id)}>
                      <td>{task.title}</td>
                      <td>{agentLabel(task)}</td>
                      <td>
                        <span className={`kb-status kb-status--${task.status}`}>
                          {STATUS_ICONS[task.status]} {statusTitle(task.status)}
                        </span>
                      </td>
                      <td>
                        <PriorityMark priority={task.priority} />
                      </td>
                      <td>{new Date(task.created_at * 1000).toLocaleDateString()}</td>
                      <td>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            void deleteTask(task.id);
                          }}
                          aria-label="Delete task"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {view === 'calendar' && (
          <div className="kb-calendar-view">
            <div className="kb-calendar-grid">
              {Array.from({ length: 35 }, (_, i) => {
                const date = new Date();
                date.setDate(date.getDate() - date.getDay() + i);
                const dateStr = date.toISOString().split('T')[0];
                const dayTasks = filteredTasks.filter(
                  (t) => new Date(t.created_at * 1000).toISOString().split('T')[0] === dateStr,
                );
                return (
                  <div key={i} className="kb-calendar-day">
                    <div className="kb-calendar-day-num">{date.getDate()}</div>
                    {dayTasks.slice(0, 3).map((t) => (
                      <div key={t.id} className="kb-calendar-task">
                        {t.title}
                      </div>
                    ))}
                    {dayTasks.length > 3 && <div className="kb-calendar-more">+{dayTasks.length - 3} more</div>}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {view === 'timeline' && (
          <div className="kb-timeline-view">
            {filteredTasks.length === 0 ? (
              <EmptyState icon={<Clock size={22} />} title="Nothing scheduled" description="Tasks appear here in order." />
            ) : (
              <div className="kb-timeline">
                {[...filteredTasks]
                  .sort((a, b) => a.created_at - b.created_at)
                  .map((task) => (
                    <div key={task.id} className="kb-timeline-item">
                      <div className="kb-timeline-marker" />
                      <div className="kb-timeline-content">
                        <div className="kb-timeline-title">{task.title}</div>
                        <div className="kb-timeline-meta">
                          {new Date(task.created_at * 1000).toLocaleString()} · {agentLabel(task)}
                        </div>
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}

        {view === 'statistics' && (
          <div className="kb-stats-view">
            <div className="kb-stats-grid">
              <div className="kb-stat-card">
                <div className="kb-stat-value">{stats.total}</div>
                <div className="kb-stat-label">Total Tasks</div>
              </div>
              <div className="kb-stat-card">
                <div className="kb-stat-value">{stats.completed}</div>
                <div className="kb-stat-label">Completed</div>
              </div>
              <div className="kb-stat-card">
                <div className="kb-stat-value">{stats.failed}</div>
                <div className="kb-stat-label">Failed</div>
              </div>
              <div className="kb-stat-card">
                <div className="kb-stat-value">{(stats.avgDuration / 60).toFixed(1)}m</div>
                <div className="kb-stat-label">Avg Duration</div>
              </div>
            </div>
            <div className="kb-stats-chart">
              <h3>Tasks per Day</h3>
              <div className="kb-chart">
                {stats.perDay.map((d) => (
                  <div key={d.date} className="kb-chart-bar-group">
                    <div className="kb-chart-bar" style={{ height: `${Math.max(4, d.count * 20)}px` }} />
                    <div className="kb-chart-label">
                      {new Date(d.date).toLocaleDateString('en', { weekday: 'short' })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {selectedTask && (
          <div className="kb-detail-panel">
            <div className="kb-detail-header">
              <input
                className="kb-detail-title"
                value={editingTask?.title ?? selectedTask.title}
                onChange={(e) => setEditingTask({ ...selectedTask, title: e.target.value })}
                readOnly={!editingTask}
              />
              <button
                className="kb-detail-close"
                onClick={() => {
                  setSelectedTaskId(null);
                  setEditingTask(null);
                }}
                aria-label="Close"
              >
                <X size={16} />
              </button>
            </div>
            <div className="kb-detail-body">
              <div className="kb-detail-row">
                <label>Status</label>
                {editingTask ? (
                  <Picker
                    value={editingTask.status}
                    ariaLabel="Task status"
                    onChange={(v) => setEditingTask({ ...selectedTask, status: v as KanbanStatus })}
                    options={COLUMNS.map((c) => ({ value: c.id, label: c.title }))}
                  />
                ) : (
                  <span className={`kb-status kb-status--${selectedTask.status}`}>
                    {STATUS_ICONS[selectedTask.status]} {statusTitle(selectedTask.status)}
                  </span>
                )}
              </div>
              <div className="kb-detail-row">
                <label>Priority</label>
                {editingTask ? (
                  <Picker
                    value={editingTask.priority}
                    ariaLabel="Task priority"
                    onChange={(v) => setEditingTask({ ...selectedTask, priority: v as KanbanPriority })}
                    options={PRIORITIES.map((p) => ({ value: p, label: p }))}
                  />
                ) : (
                  <PriorityMark priority={selectedTask.priority} />
                )}
              </div>
              <div className="kb-detail-row">
                <label>Agent</label>
                {editingTask ? (
                  <Picker
                    value={editingTask.agent_id}
                    ariaLabel="Assign agent"
                    placeholder="Unassigned"
                    onChange={(v) =>
                      setEditingTask({
                        ...selectedTask,
                        agent_id: v,
                        agent_name: agents.find((a) => a.id === v)?.name || '',
                      })
                    }
                    options={[{ value: '', label: 'Unassigned' }, ...agents.map((a) => ({ value: a.id, label: a.name }))]}
                  />
                ) : (
                  <span>{agentLabel(selectedTask)}</span>
                )}
              </div>
              <div className="kb-detail-row">
                <label>Prompt</label>
                {editingTask ? (
                  <TextArea
                    value={editingTask.prompt}
                    onChange={(e) => setEditingTask({ ...selectedTask, prompt: e.target.value })}
                    rows={5}
                    placeholder="What should the agent do?"
                  />
                ) : (
                  <div className="kb-detail-prompt">{selectedTask.prompt || '—'}</div>
                )}
              </div>
              <div className="kb-detail-row">
                <label>Description</label>
                <TextArea
                  value={editingTask?.description ?? selectedTask.description}
                  onChange={(e) => setEditingTask({ ...selectedTask, description: e.target.value })}
                  rows={3}
                  readOnly={!editingTask}
                  placeholder={editingTask ? 'Optional notes' : ''}
                />
              </div>
              {selectedTask.output && (
                <div className="kb-detail-row">
                  <label>Agent output</label>
                  <div className="kb-detail-output">{selectedTask.output}</div>
                </div>
              )}
              <div className="kb-detail-row">
                <label>Created</label>
                <span>{new Date(selectedTask.created_at * 1000).toLocaleString()}</span>
              </div>
              {selectedTask.duration ? (
                <div className="kb-detail-row">
                  <label>Duration</label>
                  <span>{(selectedTask.duration / 60).toFixed(1)} minutes</span>
                </div>
              ) : null}
              {(selectedTask.history || []).length > 0 && (
                <div className="kb-detail-row">
                  <label>History</label>
                  <div className="kb-history">
                    {(selectedTask.history || []).slice(-6).map((h) => (
                      <div key={h.id} className="kb-history-item">
                        <span>{new Date(h.timestamp * 1000).toLocaleString()}</span>
                        <span>
                          {statusTitle(h.from_status)} → {statusTitle(h.to_status)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="kb-detail-footer">
              {editingTask ? (
                <>
                  <Button onClick={() => updateTask(editingTask)} variant="primary">
                    Save
                  </Button>
                  <Button onClick={() => setEditingTask(null)} variant="secondary">
                    Cancel
                  </Button>
                </>
              ) : (
                <>
                  <Button onClick={() => setEditingTask(selectedTask)} variant="secondary">
                    <Pencil size={14} /> Edit
                  </Button>
                  <Button
                    onClick={() => runTask(selectedTask.id)}
                    variant="primary"
                    disabled={runningTaskId === selectedTask.id}
                  >
                    {runningTaskId === selectedTask.id ? (
                      <>
                        <span className="kb-spinner" /> Running
                      </>
                    ) : (
                      <>
                        <Send size={14} /> Run task
                      </>
                    )}
                  </Button>
                  <Button onClick={() => deleteTask(selectedTask.id)} variant="danger">
                    <Trash2 size={14} /> Delete
                  </Button>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="kb-stats-bar">
        <span>
          <CheckCircle2 size={12} /> {stats.completed} completed
        </span>
        <span>
          <XCircle size={12} /> {stats.failed} failed
        </span>
        <span>
          <Clock size={12} /> {(stats.avgDuration / 60).toFixed(1)}m avg
        </span>
        <span>
          <BarChart3 size={12} /> {stats.total} total
        </span>
      </div>

      <Modal open={showQuickAdd} onClose={() => setShowQuickAdd(false)} title="New Task">
        <div className="kb-quickadd">
          <Field label="Title">
            <TextInput
              value={quickAddTitle}
              onChange={(e) => setQuickAddTitle(e.target.value)}
              placeholder="What needs to be done?"
              autoFocus
            />
          </Field>
          <Field label="Agent">
            <Picker
              value={quickAddAgent}
              onChange={setQuickAddAgent}
              placeholder="Unassigned"
              ariaLabel="Assign agent"
              options={[{ value: '', label: 'Unassigned' }, ...agents.map((a) => ({ value: a.id, label: a.name }))]}
            />
          </Field>
          <Field label="Priority">
            <Picker
              value={quickAddPriority}
              onChange={(v) => setQuickAddPriority(v as KanbanPriority)}
              ariaLabel="Task priority"
              options={PRIORITIES.map((p) => ({ value: p, label: p }))}
            />
          </Field>
          <Field label="Prompt" hint="The instruction sent to the assigned agent when the task runs.">
            <TextArea
              value={quickAddPrompt}
              onChange={(e) => setQuickAddPrompt(e.target.value)}
              rows={4}
              placeholder="Write the prompt for the agent"
            />
          </Field>
          <div className="kb-quickadd-actions">
            <Button onClick={createTask} variant="primary">
              Create Task
            </Button>
            <Button onClick={() => setShowQuickAdd(false)} variant="secondary">
              Cancel
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
