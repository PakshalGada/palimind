import { useMemo } from 'react';
import {
  FolderOpen,
  Globe2,
  Settings2,
  Users,
  Hash,
} from 'lucide-react';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import { PixelGlyph } from '../../components/pixel/PixelGlyph';
import { pixelForStatus } from '../../components/pixel/pixelStatus';
import { botStateFor } from '../../bots/config';
import SessionMenu from './SessionMenu';
import type { AgentListItem, Channel, Team } from '../../types';
import './ConversationHeader.css';

export default function ConversationHeader({
  agent,
  team,
  channel,
  onSettings,
}: {
  agent?: AgentListItem | null;
  team?: Team | null;
  channel?: Channel | null;
  onSettings?: () => void;
}) {
  const { browserOpen, setBrowserOpen, setBrowserFullscreen, setSelectedAgentId } = useApp();

  const label = channel?.name || team?.display_name || team?.name || agent?.display_name || agent?.name || 'Conversation';
  const status = useMemo(() => {
    if (channel) return `${channel.member_count || 0} members · ${channel.status}`;
    if (team) return `${team.members.length} members${team.running ? ' · working' : ''}`;
    if (!agent) return '';
    if (agent.running || (agent.active_runs || 0) > 0) return 'working…';
    if (!agent.enabled) return 'disabled';
    return agent.title || `@${agent.name}`;
  }, [agent, team, channel]);

  const openSettings = () => {
    if (!agent) return;
    setSelectedAgentId(agent.id);
    window.dispatchEvent(
      new CustomEvent('palimind:open-agent-config', { detail: { agentId: agent.id } }),
    );
  };

  return (
    <header className="ag-chat-head">
      <div className="ag-chat-head__id">
        {channel ? (
          <span className="ag-chat-head__badge"><Hash size={17} /></span>
        ) : team ? (
          <span className="ag-chat-head__team">
            {team.members.slice(0, 3).map((member) => {
              const memberAgent = member.agent;
              return (
                <AgentAvatar
                  key={member.agent_id}
                  config={memberAgent?.avatar_config}
                  upload={memberAgent?.avatar_upload}
                  type={memberAgent?.avatar_type === 'upload' ? 'upload' : 'bot'}
                  size={22}
                />
              );
            })}
            {team.members.length === 0 && <Users size={18} />}
          </span>
        ) : agent ? (
          <AgentAvatar
            config={agent.avatar_config}
            type={agent.avatar_type === 'upload' ? 'upload' : 'bot'}
            upload={agent.avatar_upload}
            state={botStateFor(agent)}
            size={28}
          />
        ) : null}
        <div className="ag-chat-head__text">
          <h1 className="ag-chat-head__name">{label}</h1>
          <p className="ag-chat-head__meta">
            {agent && (agent.running || (agent.active_runs || 0) > 0) && (
              <PixelGlyph sprite={pixelForStatus('working')} cell={1.05} />
            )}
            {status}
          </p>
        </div>
      </div>

      <div className="ag-chat-head__actions">
        {agent && <SessionMenu agentId={agent.id} />}
        <button
          type="button"
          className={`ag-icon-btn${browserOpen ? ' is-on' : ''}`}
          title={browserOpen ? 'Hide browser' : 'Open browser'}
          aria-label={browserOpen ? 'Hide browser' : 'Open browser'}
          aria-pressed={browserOpen}
          onClick={() => {
            if (browserOpen) {
              setBrowserFullscreen(false);
              setBrowserOpen(false);
            } else {
              setBrowserOpen(true);
            }
          }}
        >
          <Globe2 size={15} />
        </button>
        {agent && (
          <>
            <button
              type="button"
              className="ag-icon-btn"
              title="Agent files"
              aria-label="Agent files"
              onClick={() => {
                setSelectedAgentId(agent.id);
                window.dispatchEvent(new CustomEvent('palimind:open-agent-files'));
              }}
            >
              <FolderOpen size={15} />
            </button>
            <button
              type="button"
              className="ag-icon-btn"
              title="Agent settings"
              aria-label="Agent settings"
              onClick={openSettings}
            >
              <Settings2 size={15} />
            </button>
          </>
        )}
        {!agent && onSettings && (
          <button
            type="button"
            className="ag-icon-btn"
            title="Conversation settings"
            aria-label="Conversation settings"
            onClick={onSettings}
          >
            <Settings2 size={15} />
          </button>
        )}
      </div>
    </header>
  );
}
