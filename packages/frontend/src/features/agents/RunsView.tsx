import { useCallback, useEffect, useMemo, useState } from 'react';
import { CalendarClock, Clock, History, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { Button, Chip, Field, Modal, Select, TextArea, TextInput, Toggle } from '../../ui/primitives';
import type { AgentListItem, RecentRun, Routine, Team } from '../../types';
import './RunsView.css';

function relTime(ts?: number | null): string {
  if (!ts) return 'never';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function RunsView() {
  const { addToast, refreshOverview } = useApp();
  const [runs, setRuns] = useState<RecentRun[]>([]);
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [filter, setFilter] = useState('all');
  const [builder, setBuilder] = useState<Partial<Routine> | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [runRes, routineRes, agentRes, teamRes] = await Promise.all([
        api.agents.recentRuns(60),
        api.routines.list(),
        api.agents.list(),
        api.teams.list(),
      ]);
      setRuns(runRes.runs || []);
      setRoutines(routineRes.routines || []);
      setAgents(agentRes.agents || []);
      setTeams(teamRes.teams || []);
    } catch {
      // best effort
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 12000);
    const onChanged = () => void refresh();
    window.addEventListener('palimind:agents-changed', onChanged);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('palimind:agents-changed', onChanged);
    };
  }, [refresh]);

  const visibleRuns = useMemo(() => {
    if (filter === 'all') return runs;
    if (filter === 'error') return runs.filter((r) => r.status !== 'success');
    return runs.filter((r) => r.status === filter);
  }, [runs, filter]);

  const saveAsRoutine = (run: RecentRun) => {
    setBuilder({
      name: `${run.agent_name} routine`,
      target_type: run.agent_id.startsWith('team:') ? 'team' : 'agent',
      target_id: run.agent_id.startsWith('team:') ? run.agent_id.slice(5) : run.agent_id,
      input: run.input,
      run_mode: 'manual',
      tool_pack: 'auto',
      enabled: true,
      source_run_id: run.run_id,
    });
  };

  const toggleRoutine = async (routine: Routine) => {
    await api.routines.update(routine.id, { enabled: !routine.enabled });
    void refresh();
  };

  const runRoutine = async (routine: Routine) => {
    const res = await api.routines.run(routine.id);
    if (res.error) addToast(res.error, { tone: 'error' });
    else {
      addToast(`Running ${routine.name}`, { tone: 'success' });
      void refresh();
      void refreshOverview();
    }
  };

  return (
    <div className="runs">
      <header className="runs__head">
        <div>
          <h1 className="ah-title">Runs &amp; routines</h1>
          <p className="ah-sub">Every run across your agents and teams, and the work that repeats.</p>
        </div>
        <Button size="sm" variant="secondary" onClick={() => void refresh()}>
          <RefreshCw size={13} /> Refresh
        </Button>
      </header>

      <div className="runs__scroll">
        <section className="runs__section">
          <div className="runs__section-head">
            <h2>
              <History size={15} /> Recent runs
            </h2>
            <div className="runs__filters">
              {['all', 'success', 'error', 'cancelled'].map((f) => (
                <button
                  key={f}
                  type="button"
                  className={`runs__filter${filter === f ? ' is-on' : ''}`}
                  onClick={() => setFilter(f)}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>
          {visibleRuns.length === 0 ? (
            <p className="ah-panel__empty">No runs match this filter.</p>
          ) : (
            <div className="runs__list">
              {visibleRuns.map((run) => {
                const key = `${run.agent_id}:${run.run_id}`;
                const open = expanded === key;
                return (
                  <article key={key} className={`runs__item runs__item--${run.status}`}>
                    <button type="button" className="runs__item-head" onClick={() => setExpanded(open ? null : key)}>
                      <span className={`ah-status ah-status--${run.status === 'success' ? 'idle' : run.status === 'running' ? 'working' : 'error'}`}>
                        <span className="ah-status__dot" />
                        {run.status}
                      </span>
                      <span className="runs__item-name">{run.agent_name}</span>
                      <span className="runs__item-input">{run.input.slice(0, 110)}</span>
                      <span className="runs__item-time">{relTime(run.timestamp)}</span>
                    </button>
                    {open && (
                      <div className="runs__item-body">
                        <div className="runs__item-meta">
                          <Chip tone="muted">{run.duration ? `${run.duration.toFixed(1)}s` : '—'}</Chip>
                          {run.usage && (
                            <Chip tone="muted">
                              {run.usage.prompt_tokens + run.usage.completion_tokens} tokens
                            </Chip>
                          )}
                          {run.effort?.level && <Chip tone="muted">{run.effort.level}</Chip>}
                        </div>
                        <div className="runs__item-block">
                          <span>Input</span>
                          <pre>{run.input}</pre>
                        </div>
                        <div className="runs__item-block">
                          <span>Output</span>
                          <pre>{run.output}</pre>
                        </div>
                        <div className="runs__item-actions">
                          <Button size="sm" variant="secondary" onClick={() => saveAsRoutine(run)}>
                            <CalendarClock size={13} /> Save as routine
                          </Button>
                        </div>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="runs__section">
          <div className="runs__section-head">
            <h2>
              <CalendarClock size={15} /> Routines
            </h2>
            <Button size="sm" variant="secondary" onClick={() => setBuilder({ run_mode: 'manual', enabled: true })}>
              <Plus size={13} /> New routine
            </Button>
          </div>
          {routines.length === 0 ? (
            <p className="ah-panel__empty">No routines yet. Save a run as a routine, or create one here.</p>
          ) : (
            <div className="runs__routines">
              {routines.map((routine) => (
                <article key={routine.id} className="runs__routine">
                  <div className="runs__routine-id">
                    <span className="runs__routine-name">{routine.name}</span>
                    <span className="runs__routine-meta">
                      {routine.target_type} · {routine.run_mode}
                      {routine.schedule ? ` · ${routine.schedule}` : ''} · last {relTime(routine.last_run_at)}
                    </span>
                  </div>
                  <Toggle title="Enabled" checked={routine.enabled} onChange={() => void toggleRoutine(routine)} />
                  <Button size="sm" variant="secondary" onClick={() => void runRoutine(routine)}>
                    <Clock size={12} /> Run
                  </Button>
                  <button
                    type="button"
                    className="runs__delete"
                    onClick={() => void api.routines.remove(routine.id).then(() => void refresh())}
                    aria-label="Delete routine"
                  >
                    <Trash2 size={13} />
                  </button>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>

      <RoutineBuilder
        draft={builder}
        agents={agents}
        teams={teams}
        onClose={() => setBuilder(null)}
        onSaved={() => {
          setBuilder(null);
          void refresh();
          void refreshOverview();
          window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
        }}
        onError={(message) => addToast(message, { tone: 'error' })}
      />
    </div>
  );
}

function RoutineBuilder({
  draft,
  agents,
  teams,
  onClose,
  onSaved,
  onError,
}: {
  draft: Partial<Routine> | null;
  agents: AgentListItem[];
  teams: Team[];
  onClose: () => void;
  onSaved: () => void;
  onError: (message: string) => void;
}) {
  const [value, setValue] = useState<Partial<Routine>>(draft || {});
  useEffect(() => setValue(draft || {}), [draft]);
  if (!draft) return null;

  const save = async () => {
    if (!value.name || !value.target_id || !value.input) {
      onError('Name, target and prompt are required.');
      return;
    }
    const payload: Partial<Routine> = {
      ...value,
      target_type: value.target_type || 'agent',
      run_mode: value.run_mode || 'manual',
      tool_pack: value.tool_pack || 'auto',
      enabled: value.enabled ?? true,
    };
    const res = value.id ? await api.routines.update(value.id, payload) : await api.routines.create(payload);
    if (res.error) onError(res.error);
    else onSaved();
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Routine"
      subtitle="Save this work so it can run again on a schedule or on demand."
      width={620}
      footer={
        <div className="team-modal__foot">
          <Button size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" variant="primary" onClick={() => void save()}>
            Save routine
          </Button>
        </div>
      }
    >
      <div className="team-modal">
        <Field label="Name">
          <TextInput value={value.name || ''} onChange={(e) => setValue({ ...value, name: e.target.value })} />
        </Field>
        <div className="onboard__grid2">
          <Field label="Target type">
            <Select
              value={value.target_type || 'agent'}
              onChange={(e) => setValue({ ...value, target_type: e.target.value as 'agent' | 'team', target_id: '' })}
            >
              <option value="agent">Agent</option>
              <option value="team">Team</option>
            </Select>
          </Field>
          <Field label="Target">
            <Select value={value.target_id || ''} onChange={(e) => setValue({ ...value, target_id: e.target.value })}>
              <option value="">Choose…</option>
              {(value.target_type === 'team' ? teams : agents).map((t) => (
                <option key={t.id} value={t.id}>
                  {(t as Team).display_name || t.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Prompt">
          <TextArea rows={4} value={value.input || ''} onChange={(e) => setValue({ ...value, input: e.target.value })} />
        </Field>
        <div className="onboard__grid2">
          <Field label="Trigger">
            <Select
              value={value.run_mode || 'manual'}
              onChange={(e) => setValue({ ...value, run_mode: e.target.value as Routine['run_mode'] })}
            >
              <option value="manual">Manual</option>
              <option value="scheduled">Scheduled (cron)</option>
              <option value="watcher">File watcher</option>
            </Select>
          </Field>
          <Field label="Tool pack">
            <Select
              value={value.tool_pack || 'auto'}
              onChange={(e) => setValue({ ...value, tool_pack: e.target.value as Routine['tool_pack'] })}
            >
              {['auto', 'research', 'code', 'data', 'web', 'custom'].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {value.run_mode === 'scheduled' && (
          <Field label="Cron schedule" hint="Minute hour day-of-month month day-of-week · e.g. 0 9 * * 1">
            <TextInput
              value={value.schedule || ''}
              placeholder="0 9 * * 1"
              onChange={(e) => setValue({ ...value, schedule: e.target.value })}
            />
          </Field>
        )}
        {value.run_mode === 'watcher' && (
          <Field label="Watcher glob">
            <TextInput
              value={value.watcher_pattern || ''}
              placeholder="**/*.md"
              onChange={(e) => setValue({ ...value, watcher_pattern: e.target.value })}
            />
          </Field>
        )}
        <Field label="Working root" hint="Optional knowledge base path.">
          <TextInput
            value={value.working_root || ''}
            onChange={(e) => setValue({ ...value, working_root: e.target.value })}
          />
        </Field>
        <Toggle
          title="Enabled"
          description="Paused routines keep their settings."
          checked={value.enabled ?? true}
          onChange={(enabled) => setValue({ ...value, enabled })}
        />
      </div>
    </Modal>
  );
}
