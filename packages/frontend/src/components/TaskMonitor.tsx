import { useCallback, useEffect, useState } from 'react';
import { Bell, Play, Plus, Trash2 } from 'lucide-react';
import { api } from '../api';
import { useApp } from '../AppContext';
import { Badge, Button, Chip, EmptyState, Field, Modal, Select, Tabs, TextInput } from '../ui/primitives';
import type { AgentListItem, BackgroundTask, Goal, GoalNotification } from '../types';
import './TaskMonitor.css';

type Tab = 'goals' | 'tasks' | 'notifications';

function fmt(ts: number | null | undefined): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString();
}

/**
 * Goals & background task monitor (Phase 4.5). Create goals, queue one-shot or
 * `/loop` tasks, watch progress and read completion notifications. Open with
 * the `palimind:open-task-monitor` event.
 */
export default function TaskMonitor() {
  const { selectedAgentId, addToast } = useApp();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>('goals');
  const [goals, setGoals] = useState<Goal[]>([]);
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [notifications, setNotifications] = useState<GoalNotification[]>([]);
  const [agents, setAgents] = useState<AgentListItem[]>([]);

  const [goalName, setGoalName] = useState('');
  const [goalObjective, setGoalObjective] = useState('');
  const [goalCriteria, setGoalCriteria] = useState('');
  const [taskPrompt, setTaskPrompt] = useState('/loop 5m check tests');
  const [taskGoal, setTaskGoal] = useState('');
  const [taskAgent, setTaskAgent] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [g, t, n] = await Promise.all([
        api.agents.goals.list(),
        api.agents.tasks.list(),
        api.agents.notifications.list(),
      ]);
      setGoals(g.goals || []);
      setTasks(t.tasks || []);
      setNotifications(n.notifications || []);
    } catch {
      // best effort
    }
  }, []);

  useEffect(() => {
    const onOpen = () => {
      setOpen(true);
      void refresh();
    };
    window.addEventListener('palimind:open-task-monitor', onOpen);
    return () => window.removeEventListener('palimind:open-task-monitor', onOpen);
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    void refresh();
    api.agents
      .list()
      .then((d) => setAgents(d.agents || []))
      .catch(() => {});
    const timer = setInterval(() => void refresh(), 8000);
    return () => clearInterval(timer);
  }, [open, refresh]);

  useEffect(() => {
    if (selectedAgentId && !taskAgent) setTaskAgent(selectedAgentId);
  }, [selectedAgentId, taskAgent]);

  const createGoal = async () => {
    if (!goalName.trim()) {
      addToast('Give the goal a name.');
      return;
    }
    const res = await api.agents.goals.create({
      name: goalName.trim(),
      objective: goalObjective,
      success_criteria: goalCriteria,
      agent_id: selectedAgentId || '',
    });
    if (res.error) addToast(res.error);
    else {
      setGoalName('');
      setGoalObjective('');
      setGoalCriteria('');
      addToast('Goal created.');
      await refresh();
    }
  };

  const createTask = async () => {
    if (!taskPrompt.trim()) {
      addToast('Describe the task or use /loop 5m …');
      return;
    }
    const res = await api.agents.tasks.create({
      agent_id: taskAgent || selectedAgentId || '',
      command: taskPrompt.trim().startsWith('/loop') ? taskPrompt.trim() : undefined,
      prompt: taskPrompt.trim().startsWith('/loop') ? undefined : taskPrompt.trim(),
      goal_id: taskGoal || undefined,
    });
    if (res.error) addToast(res.error);
    else {
      addToast('Task queued.');
      await refresh();
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => setOpen(false)}
      title="Goals & background tasks"
      subtitle="Autonomous objectives, scheduled runs and completion alerts"
      width={900}
    >
      <div className="tm">
        <Tabs<Tab>
          value={tab}
          onChange={setTab}
          tabs={[
            { id: 'goals', label: 'Goals', count: goals.length },
            { id: 'tasks', label: 'Tasks', count: tasks.length },
            {
              id: 'notifications',
              label: 'Notifications',
              count: notifications.filter((n) => !n.read).length,
            },
          ]}
        />

        {tab === 'goals' && (
          <div className="tm-section">
            <div className="tm-create">
              <Field label="Goal name">
                <TextInput value={goalName} onChange={(e) => setGoalName(e.target.value)} placeholder="Ship v2" />
              </Field>
              <Field label="Objective">
                <TextInput
                  value={goalObjective}
                  onChange={(e) => setGoalObjective(e.target.value)}
                  placeholder="What success looks like"
                />
              </Field>
              <Field label="Success criteria">
                <TextInput
                  value={goalCriteria}
                  onChange={(e) => setGoalCriteria(e.target.value)}
                  placeholder="e.g. all tests green and docs updated"
                />
              </Field>
              <Button size="sm" variant="primary" onClick={createGoal}>
                <Plus size={14} /> Add goal
              </Button>
            </div>
            {goals.length === 0 && <EmptyState title="No goals yet" />}
            {goals.map((g) => (
              <div key={g.id} className="tm-goal">
                <div className="tm-goal__head">
                  <span className="tm-goal__name">{g.name}</span>
                  <Badge tone={g.status === 'completed' ? 'success' : g.status === 'active' ? 'accent' : 'muted'}>
                    {g.status}
                  </Badge>
                  <div className="tm-goal__actions">
                    <Button
                      size="sm"
                      title="Advance progress"
                      onClick={async () => {
                        await api.agents.goals.setProgress(g.id, Math.min(1, g.progress + 0.25));
                        await refresh();
                      }}
                    >
                      +25%
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      title="Delete goal"
                      onClick={async () => {
                        await api.agents.goals.remove(g.id);
                        await refresh();
                      }}
                    >
                      <Trash2 size={13} />
                    </Button>
                  </div>
                </div>
                {g.objective && <div className="tm-goal__obj">{g.objective}</div>}
                <div className="tm-progress">
                  <div className="tm-progress__bar" style={{ width: `${Math.round(g.progress * 100)}%` }} />
                </div>
                <div className="tm-goal__meta">
                  <span>{Math.round(g.progress * 100)}%</span>
                  {g.success_criteria && <span>· {g.success_criteria}</span>}
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === 'tasks' && (
          <div className="tm-section">
            <div className="tm-create">
              <Field label="Task or /loop command" hint="Use /loop 5m check tests for recurring work.">
                <TextInput value={taskPrompt} onChange={(e) => setTaskPrompt(e.target.value)} />
              </Field>
              <Field label="Agent">
                <Select value={taskAgent} onChange={(e) => setTaskAgent(e.target.value)}>
                  <option value="">(select)</option>
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Goal">
                <Select value={taskGoal} onChange={(e) => setTaskGoal(e.target.value)}>
                  <option value="">None</option>
                  {goals.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button size="sm" variant="primary" onClick={createTask}>
                <Play size={14} /> Queue
              </Button>
            </div>
            {tasks.length === 0 && <EmptyState title="No background tasks" />}
            {tasks.map((t) => (
              <div key={t.id} className="tm-task">
                <div className="tm-task__head">
                  <Chip tone="muted">{t.kind === 'loop' ? `${t.interval_seconds}s loop` : 'once'}</Chip>
                  <Badge
                    tone={
                      t.status === 'done'
                        ? 'success'
                        : t.status === 'failed'
                          ? 'danger'
                          : t.status === 'running'
                            ? 'accent'
                            : 'muted'
                    }
                  >
                    {t.status}
                  </Badge>
                  <div className="tm-task__actions">
                    {t.status === 'pending' && (
                      <Button
                        size="sm"
                        onClick={async () => {
                          await api.agents.tasks.cancel(t.id);
                          await refresh();
                        }}
                      >
                        Cancel
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="danger"
                      onClick={async () => {
                        await api.agents.tasks.remove(t.id);
                        await refresh();
                      }}
                    >
                      <Trash2 size={13} />
                    </Button>
                  </div>
                </div>
                <div className="tm-task__prompt">{t.prompt}</div>
                <div className="tm-task__meta">
                  <span>runs: {t.run_count}</span>
                  <span>next: {fmt(t.next_run)}</span>
                  <span>expires: {fmt(t.expires_at)}</span>
                </div>
                {t.last_output && <pre className="tm-task__output">{t.last_output}</pre>}
              </div>
            ))}
          </div>
        )}

        {tab === 'notifications' && (
          <div className="tm-section">
            <div className="tm-notif__bar">
              <Chip>{notifications.filter((n) => !n.read).length} unread</Chip>
              <Button size="sm" onClick={() => api.agents.notifications.markRead().then(refresh)}>
                Mark all read
              </Button>
              <Button size="sm" variant="danger" onClick={() => api.agents.notifications.clear().then(refresh)}>
                Clear
              </Button>
            </div>
            {notifications.length === 0 && (
              <EmptyState icon={<Bell size={20} />} title="No notifications" />
            )}
            {notifications.map((n) => (
              <div key={n.id} className={`tm-notif${n.read ? '' : ' is-unread'}`}>
                <Badge tone={n.kind.includes('failed') ? 'danger' : 'accent'}>{n.kind}</Badge>
                <span className="tm-notif__text">{n.text}</span>
                <span className="tm-notif__time">{fmt(n.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}
