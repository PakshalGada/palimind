import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, Clock, RefreshCw, RotateCcw } from 'lucide-react';
import { api } from '../../../api';
import { useApp } from '../../../AppContext';
import AgentAvatar from '../../../components/AgentAvatar';
import { PixelGlyph } from '../../../components/pixel/PixelGlyph';
import { pixelForStatus } from '../../../components/pixel/pixelStatus';
import { stepsFromTrace } from '../../../components/activity/adaptRun';
import type { AgentListItem, RecentRun } from '../../../types';
import './ActivityView.css';

type Filter = 'all' | 'running' | 'failed' | 'lanes';

interface Lane {
  id: string;
  title?: string;
  status?: string;
  input?: string;
  result?: string;
  error?: string;
  agent_id?: string;
}

function relTime(ts?: number | null): string {
  if (!ts) return '—';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function ActivityView({ agents }: { agents: AgentListItem[] }) {
  const { addToast, refreshOverview } = useApp();
  const [runs, setRuns] = useState<RecentRun[]>([]);
  const [lanes, setLanes] = useState<Lane[]>([]);
  const [filter, setFilter] = useState<Filter>('all');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [expandedLane, setExpandedLane] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.agents.recentRuns(60);
      setRuns(data.runs || []);
    } catch {
      // best effort
    } finally {
      setLoading(false);
    }
  }, []);

  const loadLanes = useCallback(async () => {
    const results = await Promise.all(
      agents.slice(0, 20).map(async (agent) => {
        try {
          const data = await api.agentTasks.list(agent.id, true);
          return (data.tasks || []).map((task) => ({ ...task, agent_id: agent.id })) as Lane[];
        } catch {
          return [];
        }
      }),
    );
    setLanes(results.flat());
  }, [agents]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 12_000);
    const onChanged = () => void refresh();
    window.addEventListener('palimind:agents-changed', onChanged);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('palimind:agents-changed', onChanged);
    };
  }, [refresh]);

  useEffect(() => {
    if (filter === 'lanes') void loadLanes();
  }, [filter, loadLanes]);

  const laneAction = async (lane: Lane, action: 'stop' | 'close' | 'reopen') => {
    if (!lane.agent_id) return;
    try {
      await api.agentTasks[action](lane.agent_id, lane.id);
      await loadLanes();
      void refreshOverview();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not update the lane', { tone: 'error' });
    }
  };

  const visible = useMemo(() => {
    if (filter === 'running') return runs.filter((run) => run.status === 'running');
    if (filter === 'failed') return runs.filter((run) => run.status !== 'success');
    return runs;
  }, [filter, runs]);

  const agentFor = (run: RecentRun) =>
    agents.find((agent) => agent.id === run.agent_id || agent.name === run.agent_name);

  const resume = async (run: RecentRun) => {
    const key = `${run.agent_id}:${run.run_id}`;
    setBusy(key);
    try {
      await api.agents.resumeRun(run.agent_id, run.run_id);
      addToast('Run resumed', { tone: 'success' });
      await refresh();
      void refreshOverview();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not resume run', { tone: 'error' });
    } finally {
      setBusy(null);
    }
  };

  const saveRoutine = async (run: RecentRun) => {
    try {
      await api.routines.create({
        name: `${run.agent_name} routine`,
        target_type: run.agent_id.startsWith('team:') ? 'team' : 'agent',
        target_id: run.agent_id.startsWith('team:') ? run.agent_id.slice(5) : run.agent_id,
        input: run.input,
        run_mode: 'manual',
        tool_pack: 'auto',
        enabled: true,
      });
      addToast('Saved as a routine', { tone: 'success' });
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not save routine', { tone: 'error' });
    }
  };

  return (
    <div className="ag-activity">
      <div className="ag-activity__bar">
        <div className="ag-segmented" role="tablist" aria-label="Activity filters">
          {(['all', 'running', 'failed', 'lanes'] as Filter[]).map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={filter === item}
              className={filter === item ? 'is-on' : ''}
              onClick={() => setFilter(item)}
            >
              {item}
            </button>
          ))}
        </div>
        <button type="button" className="ag-quiet-btn" onClick={() => void refresh()}>
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      <div className="ag-activity__list">
        {filter === 'lanes' ? (
          lanes.length === 0 ? (
            <p className="ag-activity__empty">No background lanes.</p>
          ) : (
            lanes.map((lane) => {
              const agent = agents.find((item) => item.id === lane.agent_id);
              const open = expandedLane === lane.id;
              return (
                <article key={lane.id} className={`ag-run${open ? ' is-open' : ''}`}>
                  <button
                    type="button"
                    className="ag-run-row"
                    onClick={() => setExpandedLane(open ? null : lane.id)}
                  >
                    <span className="ag-run-row__status">
                      <PixelGlyph
                        sprite={pixelForStatus(lane.status === 'running' ? 'working' : lane.error ? 'error' : 'idle')}
                        cell={1.1}
                      />
                    </span>
                    <span className="ag-run-row__agent">
                      <AgentAvatar
                        config={agent?.avatar_config}
                        upload={agent?.avatar_upload}
                        type={agent?.avatar_type === 'upload' ? 'upload' : 'bot'}
                        size={20}
                      />
                      {agent?.display_name || agent?.name || 'Agent'}
                    </span>
                    <span className="ag-run-row__input">{lane.title || lane.input || 'Task'}</span>
                    <span className="ag-run-row__meta">{lane.status || 'queued'}</span>
                    <ChevronDown size={13} className={`ag-run__chev${open ? ' is-open' : ''}`} />
                  </button>
                  {open && (
                    <div className="ag-run-detail">
                      {lane.input && (
                        <div className="ag-run-detail__block">
                          <span>Task</span>
                          <pre>{lane.input}</pre>
                        </div>
                      )}
                      {lane.result && (
                        <div className="ag-run-detail__block">
                          <span>Result</span>
                          <pre>{lane.result}</pre>
                        </div>
                      )}
                      {lane.error && <p className="ag-settings__error">{lane.error}</p>}
                      <div className="ag-run-detail__actions">
                        <button type="button" className="ag-quiet-btn" onClick={() => void laneAction(lane, 'stop')}>
                          Stop
                        </button>
                        <button type="button" className="ag-quiet-btn" onClick={() => void laneAction(lane, 'close')}>
                          Close
                        </button>
                        <button type="button" className="ag-quiet-btn" onClick={() => void laneAction(lane, 'reopen')}>
                          Reopen
                        </button>
                      </div>
                    </div>
                  )}
                </article>
              );
            })
          )
        ) : loading ? (
          <p className="ag-activity__empty">Loading activity…</p>
        ) : visible.length === 0 ? (
          <p className="ag-activity__empty">Nothing has run yet.</p>
        ) : (
          visible.map((run) => {
            const key = `${run.agent_id}:${run.run_id}`;
            const open = expanded === key;
            const agent = agentFor(run);
            return (
              <article key={key} className={`ag-run${open ? ' is-open' : ''}`}>
                <button
                  type="button"
                  className="ag-run-row"
                  onClick={() => setExpanded(open ? null : key)}
                >
                  <span className={`ag-run-row__status is-${run.status}`}>
                    <PixelGlyph
                      sprite={pixelForStatus(
                        run.status === 'success'
                          ? 'success'
                          : run.status === 'running'
                            ? 'running'
                            : 'error',
                      )}
                      cell={1.1}
                    />
                  </span>
                  <span className="ag-run-row__agent">
                    <AgentAvatar
                      config={agent?.avatar_config}
                      upload={agent?.avatar_upload}
                      type={agent?.avatar_type === 'upload' ? 'upload' : 'bot'}
                      size={20}
                    />
                    {run.agent_name}
                  </span>
                  <span className="ag-run-row__input">{run.input.slice(0, 130)}</span>
                  <span className="ag-run-row__meta">
                    <Clock size={11} /> {relTime(run.timestamp)}
                  </span>
                  <ChevronDown size={13} className={`ag-run__chev${open ? ' is-open' : ''}`} />
                </button>
                {open && (
                  <div className="ag-run-detail">
                    <div className="ag-run-detail__meta">
                      <span>{run.status}</span>
                      {run.duration ? <span>{run.duration.toFixed(1)}s</span> : null}
                      {run.usage ? <span>{run.usage.prompt_tokens + run.usage.completion_tokens} tokens</span> : null}
                      {run.effort?.level ? <span>{run.effort.level}</span> : null}
                      {run.model_route?.model ? <span>{run.model_route.model}</span> : null}
                    </div>
                    <div className="ag-run-detail__block">
                      <span>Input</span>
                      <pre>{run.input}</pre>
                    </div>
                    <div className="ag-run-detail__block">
                      <span>Output</span>
                      <pre>{run.output || '(no output)'}</pre>
                    </div>
                    {run.trace && run.trace.length > 0 && (
                      <div className="ag-run-detail__block">
                        <span>Tool trace</span>
                        <div className="ag-run-trace">
                          {stepsFromTrace(run.trace).map((step) => (
                            <div key={step.id} className={`ag-run-trace__row is-${step.status}`}>
                              <span>{step.status === 'success' ? '✓' : step.status === 'error' ? '×' : '·'}</span>
                              <code>{step.name}</code>
                              {step.output ? <em>{String(step.output).slice(0, 120)}</em> : null}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="ag-run-detail__actions">
                      {run.resumable && (
                        <button
                          type="button"
                          className="ag-quiet-btn"
                          disabled={busy === key}
                          onClick={() => void resume(run)}
                        >
                          <RotateCcw size={12} /> {busy === key ? 'Resuming…' : 'Resume'}
                        </button>
                      )}
                      <button type="button" className="ag-quiet-btn" onClick={() => void saveRoutine(run)}>
                        Save as routine
                      </button>
                    </div>
                  </div>
                )}
              </article>
            );
          })
        )}
      </div>
    </div>
  );
}
