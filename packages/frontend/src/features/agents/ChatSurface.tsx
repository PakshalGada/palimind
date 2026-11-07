import { useEffect, useState } from 'react';
import { Sparkles, Plus, Users, Inbox, Globe2 } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { Button } from '../../ui/primitives';
import DirectChat from './DirectChat';
import TeamChat from './TeamChat';
import ChannelChat from './ChannelChat';
import TeamSettingsModal from './TeamSettingsModal';
import type { AgentListItem, BrowserTakeover, Channel, Team } from '../../types';
import './ChatSurface.css';

export default function ChatSurface({
  agents,
  teams,
  channels,
  takeovers,
}: {
  agents: AgentListItem[];
  teams: Team[];
  channels: Channel[];
  takeovers: BrowserTakeover[];
}) {
  const {
    selectedAgentId,
    selectedTeamId,
    selectedChannelId,
    setBrowserOpen,
    setBrowserFullscreen,
  } = useApp();
  const [teamSettings, setTeamSettings] = useState(false);

  const agent = selectedAgentId ? agents.find((item) => item.id === selectedAgentId) || null : null;
  const team = selectedTeamId ? teams.find((item) => item.id === selectedTeamId) || null : null;
  const channel = selectedChannelId
    ? channels.find((item) => item.id === selectedChannelId) || null
    : null;

  const takeover = agent
    ? takeovers.find(
        (item) => item.agent_id === agent.id && (item.status === 'pending' || item.status === 'active'),
      ) || null
    : null;

  useEffect(() => {
    const onHandedBack = (event: Event) => {
      const detail = (event as CustomEvent<{ agentId?: string }>).detail;
      if (!agent || detail?.agentId !== agent.id) return;
      window.dispatchEvent(
        new CustomEvent('palimind:agent-send', {
          detail: { text: "I've finished in the browser. Continue where you left off." },
        }),
      );
    };
    window.addEventListener('palimind:browser-handed-back', onHandedBack);
    return () => window.removeEventListener('palimind:browser-handed-back', onHandedBack);
  }, [agent]);

  const takeOver = async () => {
    if (!agent) return;
    try {
      if (takeover) await api.browser.acceptTakeover(takeover.id);
      else await api.browser.claimControl(agent.id);
    } catch {
      // the browser dock will retry
    }
    setBrowserOpen(true);
    setBrowserFullscreen(false);
    window.dispatchEvent(new CustomEvent('palimind:browser-takeover'));
  };

  if (channel) {
    return (
      <ChannelChat
        channelId={channel.id}
        agents={agents}
      />
    );
  }

  if (team) {
    return (
      <>
        <TeamChat
          teamId={team.id}
          agents={agents}
          onOpenSettings={() => setTeamSettings(true)}
        />
        <TeamSettingsModal
          team={team}
          agents={agents}
          open={teamSettings}
          onClose={() => setTeamSettings(false)}
          onChanged={() => window.dispatchEvent(new CustomEvent('palimind:agents-changed'))}
        />
      </>
    );
  }

  if (agent) {
    return <DirectChat agent={agent} agents={agents} takeover={takeover} onTakeover={() => void takeOver()} />;
  }

  return (
    <div className="ag-welcome">
      <span className="ag-welcome__mark">
        <Sparkles size={26} />
      </span>
      <h1>Talk to your team</h1>
      <p>
        Pick an agent, a team or a channel to start. Use <code>@</code> in any
        chat to call another agent.
      </p>
      <div className="ag-welcome__actions">
        <Button
          variant="primary"
          size="sm"
          onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-agent'))}
        >
          <Plus size={14} /> New agent
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-team'))}
        >
          <Users size={14} /> New team
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => window.dispatchEvent(new CustomEvent('palimind:open-inbox'))}
        >
          <Inbox size={14} /> Inbox
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setBrowserOpen(true)}
        >
          <Globe2 size={14} /> Browser
        </Button>
      </div>
    </div>
  );
}
