import { useMemo, useState, type MouseEvent } from 'react';
import {
  Bot,
  Hash,
  MoreHorizontal,
  Plus,
  Search,
  Settings2,
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
  } = useApp();
  const confirm = useConfirm();
  const [query, setQuery] = useState('');
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [newMenu, setNewMenu] = useState<{ x: number; y: number } | null>(null);

  const q = query.trim().toLowerCase();
  const filteredAgents = useMemo(
    () =>
      agents
        .filter((agent) =>
          !q
            ? true
            : `${agent.display_name || ''} ${agent.name} ${agent.title || ''}`
                .toLowerCase()
                .includes(q),
        )
        .sort((a, b) => (b.last_run_at || 0) - (a.last_run_at || 0)),
    [agents, q],
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
                    <span className="ag-rail__row-name">{agent.display_name || agent.name}</span>
                    <span className={`ag-rail__row-meta${status ? ' is-live' : ''}`}>
                      {status === 'working' ? 'working…' : agent.title || `@${agent.name}`}
                    </span>
                  </span>
                  <span className="ag-rail__row-trail">
                    {status === 'working' && (
                      <PixelGlyph sprite={pixelForStatus('working')} cell={1.1} />
                    )}
                    <span>{relTime(agent.last_run_at)}</span>
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
