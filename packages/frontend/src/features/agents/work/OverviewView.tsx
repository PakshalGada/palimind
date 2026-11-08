import { useCallback, useEffect, useMemo, useState } from 'react';
import { MessageCircle, Play, Square, ArrowUpRight } from 'lucide-react';
import { api } from '../../../api';
import { useApp } from '../../../AppContext';
import AgentAvatar from '../../../components/AgentAvatar';
import { PixelGlyph } from '../../../components/pixel/PixelGlyph';
import { pixelForStatus } from '../../../components/pixel/pixelStatus';
import { Button, Chip } from '../../../ui/primitives';
import type { AgentListItem, AgentQuestion, OverviewTarget, RecentRun, Team } from '../../../types';
import './OverviewView.css';

function relTime(ts?: number | null): string {
  if (!ts) return '—';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function statusTone(status?: string): 'success' | 'warn' | 'danger' | 'muted' {
  if (status === 'working') return 'success';
  if (status === 'waiting' || status === 'paused') return 'warn';
  if (status === 'error') return 'danger';
  return 'muted';
}

interface UsageRow {
  prompt_tokens: number;
  completion_tokens: number;
  cost_estimate: number;
  calls: number;
}

interface UsageAggregate {
  total?: UsageRow;
  by_agent?: ({ agent_id: string } & UsageRow)[];
  by_day?: ({ day: string } & UsageRow)[];
  by_provider?: ({ provider: string } & UsageRow)[];
  unpriced_calls?: number;
}

function compactTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}

function tokensOf(
  row: { prompt_tokens?: number; completion_tokens?: number } | undefined,
): number {
  return (row?.prompt_tokens || 0) + (row?.completion_tokens || 0);
}

function Bars({
  rows,
  totalLabel,
}: {
  rows: { label: string; tokens: number; cost?: number }[];
  totalLabel: string;
}) {
  const max = Math.max(1, ...rows.map((row) => row.tokens));
  return (
    <div className="ag-insights__bars">
      {rows.length === 0 && <p className="ag-overview__empty">No usage recorded yet.</p>}
      {rows.map((row) => (
        <div key={row.label} className="ag-insights__bar-row">
          <span className="ag-insights__bar-label">{row.label}</span>
          <span className="ag-insights__bar-track">
            <span
              className="ag-insights__bar-fill"
              style={{ width: `${Math.max(2, (row.tokens / max) * 100)}%` }}
            />
          </span>
          <span className="ag-insights__bar-value">
            {compactTokens(row.tokens)}
            {row.cost !== undefined && row.cost > 0 && (
              <em>${row.cost.toFixed(4)}</em>
            )}
          </span>
        </div>
      ))}
      {rows.length > 0 && <span className="ag-insights__total">{totalLabel}</span>}
    </div>
  );
}

export default function OverviewView({
  agents,
  teams,
}: {
  agents: AgentListItem[];
  teams: Team[];
}) {
  const {
    overview,
    inbox,
    refreshOverview,
    addToast,
    setAgentsView,
    setSelectedAgentId,
    setSelectedTeamId,
  } = useApp();
  const [questions, setQuestions] = useState<AgentQuestion[]>([]);
  const [runs, setRuns] = useState<RecentRun[]>([]);
  const [usage, setUsage] = useState<UsageAggregate | null>(null);
  const [usageDays, setUsageDays] = useState(7);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const end = new Date();
      const start = new Date(end.getTime() - (usageDays - 1) * 86_400_000);
      const [q, r, u] = await Promise.all([
        api.agents.questions().catch(() => ({ questions: [] })),
        api.agents.recentRuns(60).catch(() => ({ runs: [] })),
        api.usage
          .get('', start.toISOString().slice(0, 10), end.toISOString().slice(0, 10))
          .catch(() => null),
      ]);
      setQuestions(q.questions || []);
      setRuns(r.runs || []);
      setUsage((u as UsageAggregate | null) ?? null);
      void refreshOverview();
    } catch {
      // best effort
    }
  }, [refreshOverview, usageDays]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10_000);
    const onChange = () => void refresh();
    window.addEventListener('palimind:agents-changed', onChange);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('palimind:agents-changed', onChange);
    };
  }, [refresh]);

  const targets: OverviewTarget[] = useMemo(
    () => [...(overview?.agents ?? []), ...(overview?.teams ?? [])],
    [overview],
  );
  const counts = overview?.counts;

  const todayTokens = useMemo(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return runs
      .filter((run) => (run.timestamp || 0) * 1000 >= start.getTime())
      .reduce(
        (sum, run) =>
          sum + (run.usage?.prompt_tokens || 0) + (run.usage?.completion_tokens || 0),
        0,
      );
  }, [runs]);

  const stageRows = useMemo(() => {
    const totals = new Map<string, number>();
    for (const run of runs) {
      for (const [stage, value] of Object.entries(run.usage_stages || {})) {
        totals.set(
          stage,
          (totals.get(stage) || 0) + (value.prompt_tokens || 0) + (value.completion_tokens || 0),
        );
      }
    }
    return [...totals.entries()]
      .map(([label, tokens]) => ({ label, tokens }))
      .sort((a, b) => b.tokens - a.tokens);
  }, [runs]);

  const agentRows = useMemo(() => {
    if (usage?.by_agent?.length) {
      return usage.by_agent
        .map((row) => ({
          label: nameFor(agents, row.agent_id) || 'Unattributed',
          tokens: tokensOf(row),
          cost: row.cost_estimate,
        }))
        .sort((a, b) => b.tokens - a.tokens)
        .slice(0, 8);
    }
    const totals = new Map<string, number>();
    for (const run of runs) {
      totals.set(run.agent_name, (totals.get(run.agent_name) || 0) + tokensOf(run.usage));
    }
    return [...totals.entries()]
      .map(([label, tokens]) => ({ label, tokens }))
      .sort((a, b) => b.tokens - a.tokens);
  }, [agents, runs, usage]);

  const periodTokens = tokensOf(usage?.total);
  const periodCost = usage?.total?.cost_estimate || 0;
  const periodCalls = usage?.total?.calls || 0;

  const waiting = useMemo(() => {
    const items: {
      id: string;
      kind: 'approval' | 'question';
      agentId: string;
      label: string;
      detail: string;
      runId?: string;
      question?: AgentQuestion;
    }[] = [];
    for (const item of inbox) {
      items.push({
        id: `approval-${item.agent_id}-${item.run_id}-${item.tool}`,
        kind: 'approval',
        agentId: item.agent_id,
        label: `${item.agent_label || item.agent_name || 'Agent'} needs approval`,
        detail: item.summary || item.tool,
        runId: item.run_id,
      });
    }
    for (const item of questions) {
      items.push({
        id: `question-${item.id}`,
        kind: 'question',
        agentId: item.agent_id,
        label: `${nameFor(agents, item.agent_id)} asked a question`,
        detail: item.question,
        runId: item.run_id,
        question: item,
      });
    }
    return items;
  }, [agents, inbox, questions]);

  const openTarget = (target: OverviewTarget) => {
    setAgentsView('chat');
    setSelectedAgentId(null);
    setSelectedTeamId(null);
    if (target.target_type === 'team') setSelectedTeamId(target.id);
    else setSelectedAgentId(target.id);
  };

  const stop = async (target: OverviewTarget) => {
    setBusy(target.id);
    try {
      await api.agents.cancel(target.id);
      addToast('Run stopped', { tone: 'success' });
      await refresh();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not stop the run', { tone: 'error' });
    } finally {
      setBusy(null);
    }
  };

  const runNow = async (target: OverviewTarget) => {
    setBusy(target.id);
    try {
      const res = await api.agents.runNow(target.id);
      if (res.error) addToast(res.error, { tone: 'error' });
      else addToast('Run started', { tone: 'success' });
      await refresh();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="ag-overview">
      <div className="ag-overview__stats">
        <Stat label="Agents" value={counts?.agents ?? agents.length} />
        <Stat label="Working" value={counts?.working ?? 0} tone="success" />
        <Stat label="Waiting on you" value={counts?.waiting ?? waiting.length} tone="warn" />
        <Stat label="Scheduled" value={counts?.scheduled ?? 0} />
        <Stat label="Tokens today" value={todayTokens.toLocaleString()} />
      </div>

      <section className="ag-overview__panel ag-insights">
        <header>
          <h3>Usage · last {usageDays} days</h3>
          <div className="ag-insights__range">
            <select value={usageDays} onChange={(event) => setUsageDays(Number(event.target.value))}>
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
            </select>
            <span>{periodCalls} calls</span>
          </div>
        </header>
        <div className="ag-insights__stats">
          <div>
            <span>Tokens</span>
            <strong>{compactTokens(periodTokens || todayTokens)}</strong>
          </div>
          <div>
            <span>Prompt</span>
            <strong>{compactTokens(usage?.total?.prompt_tokens || 0)}</strong>
          </div>
          <div>
            <span>Completion</span>
            <strong>{compactTokens(usage?.total?.completion_tokens || 0)}</strong>
          </div>
          <div>
            <span>Est. cost</span>
            <strong>${periodCost.toFixed(4)}</strong>
          </div>
          {(usage?.unpriced_calls || 0) > 0 && (
            <div>
              <span>Unpriced</span>
              <strong>{usage?.unpriced_calls}</strong>
            </div>
          )}
        </div>
        <div className="ag-insights__grid">
          <div className="ag-insights__col">
            <div className="ag-insights__col-head">By stage</div>
            <Bars rows={stageRows} totalLabel="Stages come from the latest runs' event usage." />
          </div>
          <div className="ag-insights__col">
            <div className="ag-insights__col-head">By agent</div>
            <Bars rows={agentRows} totalLabel="Recorded provider calls in this period." />
          </div>
        </div>
      </section>

      <section className="ag-overview__panel">
        <header>
          <h3>Waiting on you</h3>
          <span>{waiting.length}</span>
        </header>
        {waiting.length === 0 ? (
          <p className="ag-overview__empty">Nothing is blocked. Agents are working or idle.</p>
        ) : (
          <ul className="ag-overview__waiting">
            {waiting.slice(0, 6).map((item) => (
              <li key={item.id}>
                <span className={`ag-overview__kind is-${item.kind}`}>
                  {item.kind === 'question' ? <MessageCircle size={13} /> : <Square size={13} />}
                  {item.kind}
                </span>
                <div>
                  <strong>{item.label}</strong>
                  <span>{item.detail}</span>
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    window.dispatchEvent(
                      new CustomEvent('palimind:open-inbox', { detail: { agentId: item.agentId } }),
                    )
                  }
                >
                  Open
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="ag-overview__panel">
        <header>
          <h3>Agents</h3>
          <span>{targets.length}</span>
        </header>
        <div className="ag-overview__grid">
          {targets.map((target) => (
            <article key={`${target.target_type}-${target.id}`} className="ag-overview__card">
              <div className="ag-overview__card-head">
                {target.target_type === 'team' ? (
                  <span className="ag-overview__team">
                    {teams.find((team) => team.id === target.id)?.members.slice(0, 3).map((member) => (
                      <AgentAvatar
                        key={member.agent_id}
                        config={member.agent?.avatar_config}
                        upload={member.agent?.avatar_upload}
                        type={member.agent?.avatar_type === 'upload' ? 'upload' : 'bot'}
                        size={22}
                      />
                    ))}
                  </span>
                ) : (
                  <AgentAvatar
                    config={target.avatar_config}
                    type={target.avatar_type === 'upload' ? 'upload' : 'bot'}
                    upload={target.avatar_upload}
                    size={26}
                  />
                )}
                <div>
                  <strong>{target.display_name || target.name}</strong>
                  <span>
                    {target.target_type === 'team'
                      ? `${target.member_count ?? 0} members`
                      : target.title || `@${target.name}`}
                  </span>
                </div>
                <Chip tone={statusTone(target.status)}>
                  {target.status === 'waiting' && <PixelGlyph sprite={pixelForStatus('waiting')} cell={1} />}
                  {target.status}
                </Chip>
              </div>
              <p className="ag-overview__step">
                {target.current_step || target.last_run_status || 'No run yet'}
              </p>
              <div className="ag-overview__card-foot">
                <span>{relTime(target.last_run_at ?? target.next_run)}</span>
                <div>
                  {target.running ? (
                    <button
                      type="button"
                      className="ag-overview__icon"
                      title="Stop"
                      disabled={busy === target.id}
                      onClick={() => void stop(target)}
                    >
                      <Square size={13} />
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="ag-overview__icon"
                      title="Run now"
                      disabled={busy === target.id}
                      onClick={() => void runNow(target)}
                    >
                      <Play size={13} />
                    </button>
                  )}
                  <button
                    type="button"
                    className="ag-overview__icon"
                    title="Open"
                    onClick={() => openTarget(target)}
                  >
                    <ArrowUpRight size={13} />
                  </button>
                </div>
              </div>
              {(target.pending_approvals > 0 || (target.pending_questions ?? 0) > 0) && (
                <span className="ag-overview__badge">
                  {target.pending_approvals + (target.pending_questions ?? 0)} waiting
                </span>
              )}
            </article>
          ))}
          {targets.length === 0 && <p className="ag-overview__empty">Create an agent to get started.</p>}
        </div>
      </section>

      <section className="ag-overview__panel">
        <header>
          <h3>Recent runs</h3>
          <span>{runs.length}</span>
        </header>
        <div className="ag-overview__runs">
          {runs.slice(0, 8).map((run) => (
            <button
              key={`${run.agent_id}-${run.run_id}`}
              type="button"
              className="ag-overview__run"
              onClick={() => {
                setAgentsView('chat');
                setSelectedTeamId(null);
                setSelectedAgentId(run.agent_id);
              }}
            >
              <span className={`ag-overview__dot is-${run.status}`} />
              <span className="ag-overview__run-agent">{run.agent_name}</span>
              <span className="ag-overview__run-input">{run.input}</span>
              <span className="ag-overview__run-meta">
                {run.usage
                  ? `${(run.usage.prompt_tokens + run.usage.completion_tokens).toLocaleString()} tok`
                  : ''}{' '}
                · {relTime(run.timestamp)}
              </span>
            </button>
          ))}
          {runs.length === 0 && <p className="ag-overview__empty">No runs yet.</p>}
        </div>
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: 'success' | 'warn';
}) {
  return (
    <div className={`ag-overview__stat${tone ? ` is-${tone}` : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function nameFor(agents: AgentListItem[], id: string): string {
  const agent = agents.find((item) => item.id === id);
  return agent?.display_name || agent?.name || 'An agent';
}
