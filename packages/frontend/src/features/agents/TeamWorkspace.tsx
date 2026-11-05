import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  Check,
  Play,
  Plus,
  Send,
  Settings2,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { useConfirm } from '../../components/ConfirmDialog';
import AgentAvatar from '../../components/AgentAvatar';
import { PixelGlyph } from '../../components/pixel/PixelGlyph';
import { pixelForStatus } from '../../components/pixel/pixelStatus';
import { Button, Chip, EmptyState, Field, Select, TextArea, TextInput } from '../../ui/primitives';
import type { AgentListItem, Team, TeamMessage, TeamNote, TeamRun } from '../../types';
import './TeamWorkspace.css';

type Tab = 'thread' | 'board' | 'runs' | 'members' | 'settings';

function relTime(ts?: number | null): string {
  if (!ts) return 'never';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function TeamWorkspace({
  teamId,
  onBack,
}: {
  teamId: string;
  onBack: () => void;
}) {
  const { addToast, refreshOverview } = useApp();
  const confirm = useConfirm();
  const [team, setTeam] = useState<Team | null>(null);
  const [messages, setMessages] = useState<TeamMessage[]>([]);
  const [notes, setNotes] = useState<TeamNote[]>([]);
  const [runs, setRuns] = useState<TeamRun[]>([]);
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [tab, setTab] = useState<Tab>('thread');
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [liveMembers, setLiveMembers] = useState<Record<string, { name: string; status: string; task?: string }>>({});
  const [savingSettings, setSavingSettings] = useState(false);
  const [newMember, setNewMember] = useState('');
  const threadRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [detail, msgs, noteRes, runRes, agentRes] = await Promise.all([
        api.teams.get(teamId),
        api.teams.messages(teamId, 200),
        api.teams.notes(teamId),
        api.teams.runs(teamId, 30),
        api.agents.list(),
      ]);
      if (detail.team) setTeam(detail.team);
      setMessages(msgs.messages || []);
      setNotes(noteRes.notes || []);
      setRuns(runRes.runs || []);
      setAgents(agentRes.agents || []);
    } catch {
      // best effort
    }
  }, [teamId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const send = async () => {
    // ⌘↵ bypasses the disabled Run button, so guard against a second run here.
    if (busy || !prompt.trim()) return;
    const text = prompt.trim();
    setPrompt('');
    setBusy(true);
    setLiveMembers({});
    try {
      await api.teams.runStream(teamId, text, (ev) => {
        if (ev.type === 'team:message' && ev.message) {
          setMessages((prev) => {
            const message = ev.message as TeamMessage;
            if (prev.some((m) => m.id === message.id)) return prev;
            return [...prev, message];
          });
        } else if (ev.type === 'team:member_started') {
          const id = String(ev.agent_id);
          setLiveMembers((prev) => ({
            ...prev,
            [id]: { name: String(ev.name || 'Member'), status: 'working', task: String(ev.task || '') },
          }));
        } else if (ev.type === 'team:member_result') {
          const id = String(ev.agent_id);
          setLiveMembers((prev) => ({
            ...prev,
            [id]: { ...(prev[id] || { name: String(ev.name || 'Member') }), status: String(ev.status || 'ok') },
          }));
        } else if (ev.type === 'team:member_step' || ev.type === 'agent:thought') {
          const id = String(ev.agent_id || '');
          if (!id) return;
          setLiveMembers((prev) => ({
            ...prev,
            [id]: {
              ...(prev[id] || { name: String(ev.name || 'Member') }),
              status: 'working',
              task: String(ev.text || '').slice(0, 160),
            },
          }));
        }
      });
      await refresh();
      void refreshOverview();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Team run failed', { tone: 'error' });
    }
    setBusy(false);
  };

  const addNote = async () => {
    if (!note.trim()) return;
    const res = await api.teams.addNote(teamId, note.trim());
    if (res.entry) setNotes((prev) => [...prev, res.entry as TeamNote]);
    setNote('');
  };

  const removeNote = async (_noteId: string) => {
    // The API supports clear-all; individual removal is a UI-level hide.
    setNotes((prev) => prev.filter((n) => n.id !== _noteId));
  };

  const addMember = async () => {
    if (!newMember) return;
    const res = await api.teams.addMember(teamId, newMember);
    if (res.team) {
      setTeam(res.team);
      setNewMember('');
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } else if (res.error) addToast(res.error, { tone: 'error' });
  };

  const removeMember = async (agentId: string) => {
    const res = await api.teams.removeMember(teamId, agentId);
    if (res.team) setTeam(res.team);
  };

  const saveSettings = async (changes: Partial<Team>) => {
    setSavingSettings(true);
    const res = await api.teams.update(teamId, changes);
    if (res.team) setTeam(res.team);
    else if (res.error) addToast(res.error, { tone: 'error' });
    setSavingSettings(false);
    return Boolean(res.team);
  };

  const cancel = async () => {
    await api.teams.cancel(teamId);
    setBusy(false);
    addToast('Stopped the team', { tone: 'info' });
  };

  if (!team) {
    return (
      <div className="team-ws team-ws--loading">
        <EmptyState icon={<Users size={24} />} title="Loading team…" description="Fetching members and thread." />
      </div>
    );
  }

  const manager = team.members.find((m) => m.agent_id === team.manager_agent_id) || team.members[0];

  return (
    <div className="team-ws">
      <header className="team-ws__head">
        <button type="button" className="team-ws__back" onClick={onBack} aria-label="Back to teams">
          <ArrowLeft size={16} />
        </button>
        <div className="team-ws__id">
          <div className="team-ws__avatars">
            {team.members.slice(0, 4).map((m) => {
              const agent = m.agent || agents.find((a) => a.id === m.agent_id);
              return (
                <span key={m.agent_id} className="team-ws__avatar">
                  <AgentAvatar
                    config={agent?.avatar_config}
                    upload={agent?.avatar_upload}
                    type={agent?.avatar_type === 'upload' ? 'upload' : 'bot'}
                    size={26}
                  />
                </span>
              );
            })}
          </div>
          <div>
            <h1 className="team-ws__name">{team.display_name || team.name}</h1>
            <p className="team-ws__meta">
              {team.mode} · manager {manager?.name || manager?.agent?.display_name || 'auto'} ·{' '}
              {team.members.length} members
              {busy ? ' · running' : ''}
            </p>
          </div>
        </div>
        <div className="team-ws__head-actions">
          {busy ? (
            <Button size="sm" variant="secondary" onClick={() => void cancel()}>
              <X size={13} /> Stop
            </Button>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setTab('thread');
                document.getElementById('team-ws-prompt')?.focus();
              }}
            >
              <Play size={13} /> Give a task
            </Button>
          )}
        </div>
      </header>

      <nav className="team-ws__tabs">
        {(['thread', 'board', 'runs', 'members', 'settings'] as Tab[]).map((id) => (
          <button
            key={id}
            type="button"
            className={`team-ws__tab${tab === id ? ' is-on' : ''}`}
            onClick={() => setTab(id)}
          >
            {id === 'board' ? 'Shared notes' : id}
          </button>
        ))}
      </nav>

      <div className="team-ws__body">
        <div className="team-ws__main">
          {tab === 'thread' && (
            <>
              <div className="team-ws__thread" ref={threadRef}>
                {messages.length === 0 ? (
                  <div className="team-ws__empty">
                    <Users size={22} />
                    <p>Give the team its first task. The manager will plan and delegate.</p>
                  </div>
                ) : (
                  messages.map((message) => (
                    <ThreadCard key={message.id} message={message} team={team} agents={agents} />
                  ))
                )}
                {busy && (
                  <div className="team-ws__live">
                    {Object.entries(liveMembers).map(([id, info]) => (
                      <div key={id} className="team-ws__live-row">
                        <PixelGlyph sprite={pixelForStatus(info.status)} cell={1.25} />
                        <span className="team-ws__live-name">{info.name}</span>
                        <span className="team-ws__live-task">{info.task || info.status}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="team-ws__composer">
                <TextArea
                  id="team-ws-prompt"
                  rows={2}
                  value={prompt}
                  placeholder="Give the team a task…"
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void send();
                  }}
                />
                <div className="team-ws__composer-actions">
                  <span className="team-ws__hint">⌘↵ to run</span>
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={busy || !prompt.trim()}
                    onClick={() => void send()}
                  >
                    <Send size={13} /> {busy ? 'Working…' : 'Run team'}
                  </Button>
                </div>
              </div>
            </>
          )}

          {tab === 'board' && (
            <div className="team-ws__panel">
              <div className="team-ws__panel-head">
                <h2>Shared notes</h2>
                <Button size="sm" variant="ghost" onClick={() => void api.teams.clearNotes(teamId).then(() => setNotes([]))}>
                  Clear
                </Button>
              </div>
              <div className="team-ws__notes">
                {notes.length === 0 && <p className="ah-panel__empty">No shared notes yet.</p>}
                {[...notes].reverse().map((entry) => (
                  <div key={entry.id} className="team-ws__note">
                    <div className="team-ws__note-head">
                      <Chip tone="muted">{entry.author}</Chip>
                      <span>{entry.label}</span>
                      <button type="button" onClick={() => void removeNote(entry.id)} aria-label="Dismiss">
                        <X size={12} />
                      </button>
                    </div>
                    <p>{entry.content}</p>
                  </div>
                ))}
              </div>
              <div className="team-ws__note-add">
                <TextInput
                  value={note}
                  placeholder="Add a note the whole team can see…"
                  onChange={(e) => setNote(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void addNote();
                  }}
                />
                <Button size="sm" variant="secondary" onClick={() => void addNote()}>
                  <Plus size={13} /> Add
                </Button>
              </div>
            </div>
          )}

          {tab === 'runs' && (
            <div className="team-ws__panel">
              <div className="team-ws__panel-head">
                <h2>Team runs</h2>
              </div>
              {runs.length === 0 && <p className="ah-panel__empty">No runs yet.</p>}
              {runs.map((run) => (
                <details key={run.run_id} className="team-ws__run">
                  <summary>
                    <span className={`ah-status ah-status--${run.status === 'success' ? 'idle' : run.status === 'running' ? 'working' : 'error'}`}>
                      <PixelGlyph
                        sprite={pixelForStatus(
                          run.status === 'success' ? 'success' : run.status === 'running' ? 'running' : 'error',
                        )}
                        cell={1.25}
                      />
                      {run.status}
                    </span>
                    <span className="team-ws__run-input">{run.input.slice(0, 120)}</span>
                    <span className="team-ws__run-time">{relTime(run.timestamp)}</span>
                  </summary>
                  <pre className="team-ws__run-output">{run.output}</pre>
                </details>
              ))}
            </div>
          )}

          {tab === 'members' && (
            <div className="team-ws__panel">
              <div className="team-ws__panel-head">
                <h2>Members</h2>
              </div>
              <div className="team-ws__members">
                {team.members.map((member) => {
                  const agent = member.agent || agents.find((a) => a.id === member.agent_id);
                  const isManager = member.agent_id === team.manager_agent_id;
                  return (
                    <div key={member.agent_id} className="team-ws__member">
                      <AgentAvatar
                        config={agent?.avatar_config}
                        upload={agent?.avatar_upload}
                        type={agent?.avatar_type === 'upload' ? 'upload' : 'bot'}
                        size={34}
                      />
                      <div className="team-ws__member-id">
                        <span>{agent?.display_name || agent?.name || member.name}</span>
                        <span>{member.role || agent?.title || 'Specialist'}</span>
                      </div>
                      {isManager ? (
                        <Chip tone="accent">manager</Chip>
                      ) : (
                        <Button size="sm" variant="ghost" onClick={() => void api.teams.setManager(teamId, member.agent_id).then((r) => r.team && setTeam(r.team))}>
                          Make manager
                        </Button>
                      )}
                      <button
                        type="button"
                        className="team-ws__remove"
                        onClick={() => void removeMember(member.agent_id)}
                        aria-label="Remove member"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  );
                })}
              </div>
              <div className="team-ws__add-member">
                <Select value={newMember} onChange={(e) => setNewMember(e.target.value)}>
                  <option value="">Add an agent…</option>
                  {agents
                    .filter((a) => !team.members.some((m) => m.agent_id === a.id))
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.display_name || a.name}
                      </option>
                    ))}
                </Select>
                <Button size="sm" variant="secondary" onClick={() => void addMember()}>
                  <Plus size={13} /> Add
                </Button>
              </div>
            </div>
          )}

          {tab === 'settings' && (
            <SettingsTab team={team} saving={savingSettings} onSave={saveSettings} onDelete={async () => {
              const ok = await confirm(`Delete team "${team.display_name || team.name}"? This cannot be undone.`, {
                title: 'Delete Team',
                confirmLabel: 'Delete',
                danger: true,
              });
              if (!ok) return;
              await api.teams.remove(teamId);
              window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
              onBack();
            }} />
          )}
        </div>

        <aside className="team-ws__side">
          <section className="team-ws__side-block">
            <h3>Live team</h3>
            <div className="team-ws__roster">
              {team.members.map((member) => {
                const agent = member.agent || agents.find((a) => a.id === member.agent_id);
                const live = liveMembers[member.agent_id];
                return (
                  <div key={member.agent_id} className="team-ws__roster-row">
                    <AgentAvatar
                      config={agent?.avatar_config}
                      upload={agent?.avatar_upload}
                      type={agent?.avatar_type === 'upload' ? 'upload' : 'bot'}
                      size={24}
                      state={live?.status === 'working' ? 'thinking' : 'default'}
                    />
                    <span className="team-ws__roster-name">{agent?.display_name || agent?.name}</span>
                    <span className={`team-ws__roster-state${live?.status === 'working' ? ' is-working' : ''}`}>
                      {live?.status === 'working' ? 'working' : 'idle'}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
          <section className="team-ws__side-block">
            <h3>Manager</h3>
            <p className="team-ws__side-copy">
              {manager?.name || manager?.agent?.display_name || 'The first member'} plans the work, delegates and writes the
              final answer.
            </p>
          </section>
          <section className="team-ws__side-block">
            <h3>Charter</h3>
            <p className="team-ws__side-copy">{team.charter || 'No charter yet. Add team-wide instructions in Settings.'}</p>
          </section>
        </aside>
      </div>
    </div>
  );
}

function ThreadCard({
  message,
  team,
  agents,
}: {
  message: TeamMessage;
  team: Team;
  agents: AgentListItem[];
}) {
  const authorId = message.author.startsWith('agent:') ? message.author.slice(6) : '';
  const member = team.members.find((m) => m.agent_id === authorId);
  const agent = member?.agent || agents.find((a) => a.id === authorId);
  const name = agent?.display_name || agent?.name || (message.author === 'user' ? 'You' : 'System');

  if (message.role === 'user') {
    return (
      <div className="team-msg team-msg--user">
        <div className="team-msg__bubble">{message.content}</div>
      </div>
    );
  }

  return (
    <div className={`team-msg team-msg--${message.role}`}>
      <div className="team-msg__head">
        {authorId ? (
          <AgentAvatar
            config={agent?.avatar_config}
            upload={agent?.avatar_upload}
            type={agent?.avatar_type === 'upload' ? 'upload' : 'bot'}
            size={24}
          />
        ) : (
          <span className="team-msg__sys" />
        )}
        <span className="team-msg__name">{name}</span>
        <Chip tone={message.role === 'handoff' ? 'muted' : message.role === 'synthesis' ? 'accent' : 'default'}>
          {message.role}
        </Chip>
        <span className="team-msg__time">{relTime(message.created_at)}</span>
      </div>
      <div className="team-msg__body">{message.content}</div>
      {message.role === 'result' && (
        <div className="team-msg__foot">
          <Check size={12} /> result posted to shared notes
        </div>
      )}
    </div>
  );
}

function SettingsTab({
  team,
  saving,
  onSave,
  onDelete,
}: {
  team: Team;
  saving: boolean;
  onSave: (changes: Partial<Team>) => Promise<boolean>;
  onDelete: () => void;
}) {
  const [draft, setDraftState] = useState(team);
  // Unsaved edits survive background refreshes of `team` (e.g. after a run);
  // the draft is only re-seeded for a different team or when nothing is dirty.
  const dirtyRef = useRef(false);
  const seededIdRef = useRef(team.id);
  const setDraft = (next: Team) => {
    dirtyRef.current = true;
    setDraftState(next);
  };
  useEffect(() => {
    if (seededIdRef.current !== team.id || !dirtyRef.current) {
      seededIdRef.current = team.id;
      dirtyRef.current = false;
      setDraftState(team);
    }
  }, [team]);
  return (
    <div className="team-ws__panel">
      <div className="team-ws__panel-head">
        <h2>
          <Settings2 size={16} /> Team settings
        </h2>
      </div>
      <div className="onboard__grid2">
        <Field label="Name">
          <TextInput value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} />
        </Field>
        <Field label="Mode">
          <Select value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value as Team['mode'] })}>
            <option value="manager">Manager</option>
            <option value="roundtable">Roundtable</option>
            <option value="chain">Chain</option>
          </Select>
        </Field>
      </div>
      <Field label="Description">
        <TextArea rows={2} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
      </Field>
      <Field label="Charter">
        <TextArea rows={4} value={draft.charter} onChange={(e) => setDraft({ ...draft, charter: e.target.value })} />
      </Field>
      <div className="onboard__grid2">
        <Field label="Max concurrency">
          <Select
            value={String(draft.max_concurrency)}
            onChange={(e) => setDraft({ ...draft, max_concurrency: Number(e.target.value) })}
          >
            {[1, 2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Working root" hint="Optional knowledge base path.">
          <TextInput
            value={draft.working_root}
            placeholder="/path/to/knowledge-base"
            onChange={(e) => setDraft({ ...draft, working_root: e.target.value })}
          />
        </Field>
      </div>
      <div className="team-ws__settings-actions">
        <Button
          variant="primary"
          size="sm"
          disabled={saving}
          onClick={async () => {
            // Clear before saving so the saved team re-seeds the draft; restore on failure.
            dirtyRef.current = false;
            const ok = await onSave({
              display_name: draft.display_name,
              description: draft.description,
              mode: draft.mode,
              charter: draft.charter,
              max_concurrency: draft.max_concurrency,
              working_root: draft.working_root,
            });
            if (!ok) dirtyRef.current = true;
          }}
        >
          Save settings
        </Button>
        <Button variant="danger" size="sm" onClick={onDelete}>
          <Trash2 size={13} /> Delete team
        </Button>
      </div>
    </div>
  );
}
