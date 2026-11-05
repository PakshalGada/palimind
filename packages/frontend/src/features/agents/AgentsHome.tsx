import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  Bell,
  CalendarClock,
  CheckCircle2,
  Clock,
  Plus,
  Send,
  Sparkles,
  Users,
  Zap,
} from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import { Button, Chip, EmptyState, SkeletonList, TextArea } from '../../ui/primitives';
import type { OverviewTarget, TargetStatus } from '../../types';
import './AgentsHome.css';

const STATUS_LABEL: Record<TargetStatus, string> = {
  idle: 'Idle',
  working: 'Working',
  waiting: 'Needs you',
  paused: 'Paused',
  scheduled: 'Scheduled',
  error: 'Error',
};

function relTime(ts?: number | null): string {
  if (!ts) return 'never';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function targetLabel(t: OverviewTarget): string {
  return t.display_name || t.name || 'Untitled';
}

function TargetCard({
  target,
  onOpen,
  onAsk,
}: {
  target: OverviewTarget;
  onOpen: () => void;
  onAsk: () => void;
}) {
  const isTeam = target.target_type === 'team';
  return (
    <article className={`ah-card ah-card--${target.status}`}>
      <div className="ah-card__top">
        {isTeam ? (
          <span className="ah-card__team-avatar">
            {(target.members || []).slice(0, 3).map((member) => (
              <AgentAvatar
                key={member.agent_id}
                config={member.agent?.avatar_config}
                upload={member.agent?.avatar_upload}
                type={member.agent?.avatar_type === 'upload' ? 'upload' : 'bot'}
                size={22}
              />
            ))}
            {!(target.members || []).length && <Users size={22} />}
          </span>
        ) : (
          <AgentAvatar
            config={target.avatar_config}
            type={target.avatar_type === 'upload' ? 'upload' : 'bot'}
            upload={target.avatar_upload}
            state={target.status === 'working' ? 'thinking' : 'default'}
            size={44}
          />
        )}
        <div className="ah-card__id">
          <span className="ah-card__name">{targetLabel(target)}</span>
          <span className="ah-card__role">
            {isTeam ? `${target.member_count || target.members?.length || 0} members` : target.title || 'Agent'}
          </span>
        </div>
        <span className={`ah-status ah-status--${target.status}`}>
          <span className="ah-status__dot" />
          {STATUS_LABEL[target.status]}
        </span>
      </div>
      <p className="ah-card__step">
        {target.status === 'working'
          ? target.current_step || 'Working…'
          : target.status === 'waiting'
            ? `${target.pending_approvals} action${target.pending_approvals === 1 ? '' : 's'} waiting for you`
            : target.description || 'Ready for work.'}
      </p>
      <div className="ah-card__meta">
        <span>
          <Clock size={12} /> {relTime(target.last_run_at)}
        </span>
        {target.status === 'scheduled' && (
          <span>
            <CalendarClock size={12} /> scheduled
          </span>
        )}
        {!!target.active_runs && target.active_runs > 0 && (
          <span>
            <Zap size={12} /> {target.active_runs} running
          </span>
        )}
      </div>
      <div className="ah-card__actions">
        <Button size="sm" variant="secondary" onClick={onAsk}>
          Ask
        </Button>
        <Button size="sm" variant="ghost" onClick={onOpen}>
          Open <ArrowRight size={12} />
        </Button>
      </div>
    </article>
  );
}

export default function AgentsHome() {
  const {
    overview,
    refreshOverview,
    selectedAgentId,
    setSelectedAgentId,
    setSelectedTeamId,
    setAgentsView,
    addToast,
  } = useApp();
  const [target, setTarget] = useState('agent:');
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<'run' | 'queue'>('run');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void refreshOverview();
    const timer = window.setInterval(() => void refreshOverview(), 7000);
    const onChanged = () => void refreshOverview();
    window.addEventListener('palimind:agents-changed', onChanged);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('palimind:agents-changed', onChanged);
    };
  }, [refreshOverview]);

  const targets = useMemo(() => {
    const agents = (overview?.agents || []).map((a) => ({
      key: `agent:${a.id}`,
      label: targetLabel(a),
      kind: 'agent' as const,
      id: a.id,
    }));
    const teams = (overview?.teams || []).map((t) => ({
      key: `team:${t.id}`,
      label: t.display_name || t.name,
      kind: 'team' as const,
      id: t.id,
    }));
    return [...teams, ...agents];
  }, [overview]);

  useEffect(() => {
    if (targets.length === 0) return;
    if (!targets.some((t) => t.key === target)) {
      const preferred = selectedAgentId ? `agent:${selectedAgentId}` : targets[0].key;
      setTarget(targets.some((t) => t.key === preferred) ? preferred : targets[0].key);
    }
  }, [targets, target, selectedAgentId]);

  const refreshAll = useCallback(() => {
    window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    void refreshOverview();
  }, [refreshOverview]);

  const openTarget = (t: OverviewTarget) => {
    if (t.target_type === 'team') {
      setSelectedTeamId(t.id);
      setAgentsView('teams');
    } else {
      setSelectedAgentId(t.id);
      setAgentsView('chat');
    }
  };

  const ask = (t: OverviewTarget) => {
    setTarget(`${t.target_type}:${t.id}`);
    setPrompt((p) => p || `Give ${targetLabel(t)} a task…`);
    requestAnimationFrame(() => {
      document.getElementById('agents-home-prompt')?.focus();
    });
  };

  const send = async () => {
    // ⌘↵ bypasses the disabled Send button, so guard against double sends here.
    if (busy || !prompt.trim() || !target) return;
    const [kind, id] = target.split(':');
    setBusy(true);
    try {
      if (mode === 'queue') {
        const res = await api.queue.enqueue({
          target_type: kind,
          target_id: id,
          input: prompt.trim(),
        });
        if (res.error) throw new Error(res.error);
        addToast('Queued. It will run when the target is free.', { tone: 'info' });
      } else if (kind === 'team') {
        await api.teams.runStream(id, prompt.trim(), () => {});
        addToast('Team run finished', { tone: 'success' });
      } else {
        let output = '';
        await api.agents.runStream(id, prompt.trim(), undefined, (ev) => {
          if (ev.type === 'agent:completed') output = String(ev.output || '');
        });
        addToast(output ? 'Run finished' : 'Run started', { tone: 'success' });
      }
      setPrompt('');
      refreshAll();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Run failed', { tone: 'error' });
    }
    setBusy(false);
  };

  const working = [...(overview?.teams || []), ...(overview?.agents || [])].filter(
    (t) => t.status === 'working',
  );
  const waiting = overview?.inbox || [];
  const rest = [...(overview?.teams || []), ...(overview?.agents || [])].filter(
    (t) => t.status !== 'working',
  );
  const isEmpty = (overview?.agents?.length || 0) === 0 && (overview?.teams?.length || 0) === 0;

  return (
    <div className="ah">
      <div className="ah-toolbar">
        <p className="ah-sub">
          {overview
            ? `${overview.counts.agents} teammates · ${overview.counts.teams} teams · ${overview.counts.working} working · ${overview.counts.waiting} waiting on you`
            : 'Loading your team…'}
        </p>
        <div className="ah-head__actions">
          <Button size="sm" variant="ghost" onClick={() => setAgentsView('runs')}>
            <Clock size={14} /> Runs
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-team'))}
          >
            <Users size={14} /> New team
          </Button>
        </div>
      </div>

      <div className="ah-scroll">
        {!overview ? (
          <SkeletonList rows={5} />
        ) : isEmpty ? (
          <div className="ah-empty">
            <EmptyState
              icon={<Sparkles size={28} />}
              title="Your team is empty"
              description="Create your first teammate from a ready-made role, or assemble a team of specialists."
              action={
                <div className="ah-empty__actions">
                  <Button
                    variant="primary"
                    onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-agent'))}
                  >
                    <Plus size={14} /> Create a teammate
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-team'))}
                  >
                    <Users size={14} /> Build a team
                  </Button>
                </div>
              }
            />
          </div>
        ) : (
          <>
            <section className="ah-composer">
              <div className="ah-composer__row">
                <span className="ah-composer__label">Hand work to</span>
                <select
                  className="ah-composer__select"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                >
                  {targets.map((t) => (
                    <option key={t.key} value={t.key}>
                      {t.kind === 'team' ? 'Team · ' : ''}
                      {t.label}
                    </option>
                  ))}
                </select>
                <select
                  className="ah-composer__select ah-composer__select--mode"
                  value={mode}
                  onChange={(e) => setMode(e.target.value as 'run' | 'queue')}
                >
                  <option value="run">Run now</option>
                  <option value="queue">Queue</option>
                </select>
              </div>
              <div className="ah-composer__input">
                <TextArea
                  id="agents-home-prompt"
                  rows={2}
                  placeholder="What should they do? Be specific about the outcome."
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void send();
                  }}
                />
                <Button
                  variant="primary"
                  size="sm"
                  className="ah-composer__send"
                  disabled={busy || !prompt.trim()}
                  onClick={() => void send()}
                >
                  <Send size={14} /> {busy ? 'Working…' : 'Send'}
                </Button>
              </div>
            </section>

            {working.length > 0 && (
              <section className="ah-section">
                <div className="ah-section__head">
                  <span className="ah-section__title">Working</span>
                  <span className="ah-section__count">{working.length}</span>
                </div>
                <div className="ah-grid">
                  {working.map((t) => (
                    <TargetCard key={`${t.target_type}:${t.id}`} target={t} onOpen={() => openTarget(t)} onAsk={() => ask(t)} />
                  ))}
                </div>
              </section>
            )}

            {waiting.length > 0 && (
              <section className="ah-section">
                <div className="ah-section__head">
                  <span className="ah-section__title">
                    <Bell size={14} /> Waiting on you
                  </span>
                  <span className="ah-section__count">{waiting.length}</span>
                </div>
                <div className="ah-waiting">
                  {waiting.slice(0, 6).map((item) => (
                    <div key={`${item.agent_id}:${item.run_id}`} className="ah-waiting__item">
                      <div className="ah-waiting__body">
                        <span className="ah-waiting__tool">{item.tool}</span>
                        <span className="ah-waiting__summary">
                          {item.summary || item.reasoning || `Agent ${item.agent_label || item.agent_id} needs approval`}
                        </span>
                      </div>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setAgentsView('teams');
                          window.dispatchEvent(new CustomEvent('palimind:open-inbox'));
                        }}
                      >
                        Review
                      </Button>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <section className="ah-section">
              <div className="ah-section__head">
                <span className="ah-section__title">Your team</span>
                <span className="ah-section__count">{rest.length}</span>
              </div>
              <div className="ah-grid">
                {rest.map((t) => (
                  <TargetCard key={`${t.target_type}:${t.id}`} target={t} onOpen={() => openTarget(t)} onAsk={() => ask(t)} />
                ))}
              </div>
            </section>

            <div className="ah-columns">
              <section className="ah-panel">
                <div className="ah-panel__head">
                  <CalendarClock size={14} /> Upcoming
                </div>
                {(overview?.upcoming || []).length === 0 ? (
                  <p className="ah-panel__empty">No scheduled routines yet.</p>
                ) : (
                  overview?.upcoming.slice(0, 5).map((r) => (
                    <div key={r.id} className="ah-row">
                      <span className="ah-row__name">{r.name}</span>
                      <Chip tone="muted">{r.run_mode}</Chip>
                    </div>
                  ))
                )}
              </section>
              <section className="ah-panel">
                <div className="ah-panel__head">
                  <CheckCircle2 size={14} /> Recent
                </div>
                {(overview?.recent || []).length === 0 ? (
                  <p className="ah-panel__empty">Nothing has run yet.</p>
                ) : (
                  overview?.recent.slice(0, 5).map((r) => (
                    <button
                      key={`${r.target_id}:${r.run_id}`}
                      type="button"
                      className="ah-row ah-row--button"
                      onClick={() => setAgentsView('runs')}
                    >
                      <span className="ah-row__name">{r.target_name}</span>
                      <span className="ah-row__meta">
                        {r.status} · {relTime(r.timestamp)}
                      </span>
                    </button>
                  ))
                )}
              </section>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
