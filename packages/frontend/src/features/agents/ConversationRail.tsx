import { useMemo, useState, type MouseEvent } from 'react';
import {
  Bot,
  Hash,
  MoreHorizontal,
  Pin,
  Play,
  Plus,
  Search,
  Settings2,
  Square,
  Users,
} from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import ContextMenu from '../../components/ContextMenu';
import { useConfirm } from '../../components/ConfirmDialog';
import { PixelGlyph } from '../../components/pixel/PixelGlyph';
import { pixelForStatus } from '../../components/pixel/pixelStatus';
import { botStateFor } from '../../bots/config';
import type { AgentListItem, BrowserTakeover, Channel, Team } from '../../types';
import './ConversationRail.css';

interface RailProps {
  agents: AgentListItem[];
  teams: Team[];
  channels: Channel[];
  takeovers: BrowserTakeover[];
  onNewChannel: () => void;
  open?: boolean;
  onNavigate?: () => void;
}

type MenuState = {
  x: number;
  y: number;
  agent: AgentListItem;
};

type StatusFilter = 'all' | 'working' | 'waiting' | 'scheduled' | 'idle';

const STATUS_FILTERS: { id: StatusFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'working', label: 'Working' },
  { id: 'waiting', label: 'Waiting' },
  { id: 'scheduled', label: 'Scheduled' },
  { id: 'idle', label: 'Idle' },
];

const PIN_KEY = 'palimind:agent-pins';

function readPins(): string[] {
  try {
    const raw = localStorage.getItem(PIN_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

function writePins(ids: string[]): void {
  try {
    localStorage.setItem(PIN_KEY, JSON.stringify(ids));
  } catch {
    // storage is optional
  }
}

function relTime(ts?: number | null): string {
  if (!ts) return '';
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return 'now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

function statusLabel(agent: AgentListItem): string {
  if (agent.running || (agent.active_runs || 0) > 0) return 'working';
  if (!agent.enabled) return 'off';
  return '';
}

export default function ConversationRail({
  agents,
  teams,
  channels,
  takeovers,
  onNewChannel,
  open = false,
  onNavigate,
}: RailProps) {
  const {
    selectedAgentId,
    selectedTeamId,
    selectedChannelId,
    setSelectedAgentId,
    setSelectedTeamId,
    setSelectedChannelId,
    setAgentsView,
    inbox,
    overview,
    addToast,
  } = useApp();
  const confirm = useConfirm();
  const [query, setQuery] = useState('');
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [newMenu, setNewMenu] = useState<{ x: number; y: number } | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [pins, setPins] = useState<string[]>(() => readPins());

  const statusById = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of overview?.agents ?? []) map.set(item.id, item.status);
    return map;
  }, [overview]);

  const previewById = useMemo(() => {
    const map = new Map<string, string>();
    for (const run of overview?.recent ?? []) {
      if (run.target_type === 'agent' && !map.has(run.target_id)) {
        map.set(run.target_id, (run.input || run.output || '').replace(/\s+/g, ' ').slice(0, 80));
      }
    }
    return map;
  }, [overview]);

  const togglePin = (agentId: string) => {
    setPins((current) => {
      const next = current.includes(agentId)
        ? current.filter((id) => id !== agentId)
        : [...current, agentId];
      writePins(next);
      return next;
    });
  };

  const quickRun = async (agent: AgentListItem) => {
    try {
      const res = await api.agents.runNow(agent.id);
      if (res.error) addToast(res.error, { tone: 'error' });
      else addToast('Run started', { tone: 'success' });
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not start the run', { tone: 'error' });
    }
  };

  const quickStop = async (agent: AgentListItem) => {
    try {
      await api.agents.cancel(agent.id);
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not stop the run', { tone: 'error' });
    }
  };

  const q = query.trim().toLowerCase();
  const filteredAgents = useMemo(
    () =>
      agents
        .filter((agent) => {
          if (q) {
            const haystack = `${agent.display_name || ''} ${agent.name} ${agent.title || ''}`;
            if (!haystack.toLowerCase().includes(q)) return false;
          }
          if (statusFilter !== 'all') {
            const status = statusById.get(agent.id) || (agent.running ? 'working' : 'idle');
            if (status !== statusFilter) return false;
          }
          return true;
        })
        .sort((a, b) => {
          const pinned = Number(pins.includes(b.id)) - Number(pins.includes(a.id));
          if (pinned !== 0) return pinned;
          return (b.last_run_at || 0) - (a.last_run_at || 0);
        }),
    [agents, q, statusById, statusFilter, pins],
  );
  const filteredTeams = useMemo(
    () =>
      teams.filter((team) =>
        !q ? true : `${team.display_name || ''} ${team.name} ${team.description || ''}`.toLowerCase().includes(q),
      ),
    [teams, q],
  );
  const filteredChannels = useMemo(
    () => channels.filter((channel) => (!q ? true : channel.name.toLowerCase().includes(q))),
    [channels, q],
  );

  const needsYou = inbox.length + takeovers.length;

  const selectAgent = (id: string) => {
    setSelectedTeamId(null);
    setSelectedChannelId(null);
    setSelectedAgentId(id);
    setAgentsView('chat');
    onNavigate?.();
  };

  const selectTeam = (id: string) => {
    setSelectedChannelId(null);
    setSelectedAgentId(null);
    setSelectedTeamId(id);
    setAgentsView('chat');
    onNavigate?.();
  };

  const selectChannel = (id: string) => {
    setSelectedTeamId(null);
    setSelectedAgentId(null);
    setSelectedChannelId(id);
    setAgentsView('chat');
    onNavigate?.();
  };

  const openSettings = (agent: AgentListItem) => {
    setSelectedAgentId(agent.id);
    window.dispatchEvent(
      new CustomEvent('palimind:open-agent-config', { detail: { agentId: agent.id } }),
    );
  };

  const deleteAgent = async (agent: AgentListItem) => {
    const ok = await confirm(
      `Delete agent "${agent.display_name || agent.name}"? This removes its memory, chats and runs.`,
      { title: 'Delete agent', confirmLabel: 'Delete', danger: true },
    );
    if (!ok) return;
    try {
      await api.agents.remove(agent.id);
      if (selectedAgentId === agent.id) setSelectedAgentId(null);
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } catch {
      // best effort
    }
  };

  const showMenu = (event: MouseEvent, agent: AgentListItem) => {
    event.preventDefault();
    event.stopPropagation();
    setMenu({ x: event.clientX, y: event.clientY, agent });
  };

  const newAgent = () =>
    window.dispatchEvent(new CustomEvent('palimind:new-agent'));
  const newTeam = () =>
    window.dispatchEvent(new CustomEvent('palimind:new-team'));

  return (
    <aside className={`ag-rail${open ? ' is-open' : ''}`} aria-label="Agents and conversations">
      <div className="ag-rail__head">
        <span className="ag-rail__title">Agents</span>
        <button
          type="button"
          className="ag-rail__new"
          title="New"
          aria-label="New agent, team or channel"
          onClick={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            setNewMenu({ x: Math.max(8, rect.right - 170), y: rect.bottom + 4 });
          }}
        >
          <Plus size={15} />
        </button>
      </div>

      <label className="ag-rail__search">
        <Search size={13} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search agents, teams, channels"
          aria-label="Search conversations"
        />
      </label>

      <div className="ag-rail__filters" role="tablist" aria-label="Filter agents by status">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.id}
            type="button"
            role="tab"
            aria-selected={statusFilter === filter.id}
            className={statusFilter === filter.id ? 'is-on' : ''}
            onClick={() => setStatusFilter(filter.id)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {needsYou > 0 && (
        <button
          type="button"
          className="ag-rail__needs"
          onClick={() => window.dispatchEvent(new CustomEvent('palimind:open-inbox'))}
        >
          <span className="ag-rail__needs-dot">
            <PixelGlyph sprite={pixelForStatus('waiting')} cell={1.15} />
          </span>
          <span className="ag-rail__needs-text">
            {needsYou} waiting on you
            {takeovers.length > 0 ? ' · browser' : ''}
          </span>
          <span className="ag-rail__count">{needsYou}</span>
        </button>
      )}

      <div className="ag-rail__scroll">
        {filteredAgents.length > 0 && (
          <section className="ag-rail__section" aria-label="Direct agent chats">
            <div className="ag-rail__section-head">Direct</div>
            {filteredAgents.map((agent) => {
              const status = statusLabel(agent);
              return (
                <button
                  key={agent.id}
                  type="button"
                  className={`ag-rail__row${selectedAgentId === agent.id && !selectedTeamId && !selectedChannelId ? ' is-active' : ''}`}
                  onClick={() => selectAgent(agent.id)}
                  onContextMenu={(event) => showMenu(event, agent)}
                >
                  <AgentAvatar
                    config={agent.avatar_config}
                    type={agent.avatar_type === 'upload' ? 'upload' : 'bot'}
                    upload={agent.avatar_upload}
                    state={botStateFor(agent)}
                    size={26}
                  />
                  <span className="ag-rail__row-body">
                    <span className="ag-rail__row-name">
                      {pins.includes(agent.id) && <Pin size={10} className="ag-rail__pin" />}
                      {agent.display_name || agent.name}
                    </span>
                    <span className={`ag-rail__row-meta${status ? ' is-live' : ''}`}>
                      {status === 'working'
                        ? 'working…'
                        : previewById.get(agent.id) || agent.title || `@${agent.name}`}
                    </span>
                  </span>
                  <span className="ag-rail__row-trail">
                    {status === 'working' && (
                      <PixelGlyph sprite={pixelForStatus('working')} cell={1.1} />
                    )}
                    <span>{relTime(agent.last_run_at)}</span>
                  </span>
                  <span className="ag-rail__quick">
                    {status === 'working' ? (
                      <span
                        role="button"
                        tabIndex={-1}
                        title="Stop run"
                        aria-label={`Stop ${agent.name}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          void quickStop(agent);
                        }}
                      >
                        <Square size={12} />
                      </span>
                    ) : (
                      <span
                        role="button"
                        tabIndex={-1}
                        title="Run now"
                        aria-label={`Run ${agent.name}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          void quickRun(agent);
                        }}
                      >
                        <Play size={12} />
                      </span>
                    )}
                  </span>
                  <span
                    className="ag-rail__row-menu"
                    role="button"
                    tabIndex={-1}
                    aria-label={`Options for ${agent.name}`}
                    onClick={(event) => showMenu(event, agent)}
                  >
                    <MoreHorizontal size={14} />
                  </span>
                </button>
              );
            })}
          </section>
        )}

        {filteredTeams.length > 0 && (
          <section className="ag-rail__section" aria-label="Team chats">
            <div className="ag-rail__section-head">
              <span>Teams</span>
              <button type="button" title="New team" aria-label="New team" onClick={newTeam}>
                <Plus size={12} />
              </button>
            </div>
            {filteredTeams.map((team) => (
              <button
                key={team.id}
                type="button"
                className={`ag-rail__row${selectedTeamId === team.id ? ' is-active' : ''}`}
                onClick={() => selectTeam(team.id)}
              >
                <span className="ag-rail__team-avatar">
                  {team.members.slice(0, 2).map((member) => {
                    const agent = member.agent;
                    return (
                      <AgentAvatar
                        key={member.agent_id}
                        config={agent?.avatar_config}
                        upload={agent?.avatar_upload}
                        type={agent?.avatar_type === 'upload' ? 'upload' : 'bot'}
                        size={19}
                      />
                    );
                  })}
                  {team.members.length === 0 && <Users size={18} />}
                </span>
                <span className="ag-rail__row-body">
                  <span className="ag-rail__row-name">{team.display_name || team.name}</span>
                  <span className="ag-rail__row-meta">
                    {team.members.length} members{team.running ? ' · working' : ''}
                  </span>
                </span>
                {team.running && <PixelGlyph sprite={pixelForStatus('working')} cell={1.1} />}
              </button>
            ))}
          </section>
        )}

        {filteredChannels.length > 0 && (
          <section className="ag-rail__section" aria-label="Channel chats">
            <div className="ag-rail__section-head">
              <span>Channels</span>
              <button type="button" title="New channel" aria-label="New channel" onClick={onNewChannel}>
                <Plus size={12} />
              </button>
            </div>
            {filteredChannels.map((channel) => (
              <button
                key={channel.id}
                type="button"
                className={`ag-rail__row${selectedChannelId === channel.id ? ' is-active' : ''}`}
                onClick={() => selectChannel(channel.id)}
              >
                <span className="ag-rail__channel-icon">
                  <Hash size={16} />
                </span>
                <span className="ag-rail__row-body">
                  <span className="ag-rail__row-name">{channel.name}</span>
                  <span className="ag-rail__row-meta">
                    {channel.member_count || 0} members
                  </span>
                </span>
              </button>
            ))}
          </section>
        )}

        {!q && filteredAgents.length === 0 && filteredTeams.length === 0 && filteredChannels.length === 0 && (
          <div className="ag-rail__empty">
            <Bot size={20} />
            <p>No agents yet.</p>
            <button type="button" onClick={newAgent}>
              Create your first agent
            </button>
          </div>
        )}
        {q && filteredAgents.length === 0 && filteredTeams.length === 0 && filteredChannels.length === 0 && (
          <p className="ag-rail__empty-text">Nothing matches “{query}”.</p>
        )}
      </div>

      <div className="ag-rail__foot">
        <button type="button" onClick={() => window.dispatchEvent(new CustomEvent('palimind:open-inbox'))}>
          <Users size={14} />
          Inbox
          {needsYou > 0 && <span className="ag-rail__count">{needsYou}</span>}
        </button>
        <button
          type="button"
          onClick={() => window.dispatchEvent(new CustomEvent('palimind:open-agents-settings'))}
        >
          <Settings2 size={14} />
          Settings
        </button>
      </div>

      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          onClose={() => setMenu(null)}
          items={[
            {
              label: pins.includes(menu.agent.id) ? 'Unpin' : 'Pin to top',
              action: () => togglePin(menu.agent.id),
            },
            { label: 'Settings', action: () => openSettings(menu.agent) },
            {
              label: 'Files',
              action: () => {
                setSelectedAgentId(menu.agent.id);
                window.dispatchEvent(new CustomEvent('palimind:open-agent-files'));
              },
            },
            {
              label: 'Run now',
              action: () => {
                void api.agents.runNow(menu.agent.id).then(() => {
                  window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
                });
              },
            },
            {
              label: 'Delete agent',
              action: () => void deleteAgent(menu.agent),
              isDanger: true,
            },
          ]}
        />
      )}
      {newMenu && (
        <ContextMenu
          x={newMenu.x}
          y={newMenu.y}
          onClose={() => setNewMenu(null)}
          items={[
            { label: 'New agent', action: newAgent },
            { label: 'New team', action: newTeam },
            { label: 'New channel', action: onNewChannel },
          ]}
        />
      )}
    </aside>
  );
}
