import { useEffect, useState } from 'react';
import { Sparkles, Plus, Users, Inbox, Globe2, HardDrive, Cloud, KeyRound } from 'lucide-react';
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
  const [readiness, setReadiness] = useState<{ local: boolean; opencode: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.agents
      .setupStatus()
      .then((status) => {
        if (cancelled) return;
        setReadiness({
          local: Boolean(status.local?.ready),
          opencode: Boolean(status.opencode?.ready),
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

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
      <h1>{agents.length === 0 ? 'Build your first teammate' : 'Talk to your team'}</h1>
      <p>
        {agents.length === 0
          ? 'Pick a role, choose a local model or your OpenCode key, and give it a first task. You can change everything later.'
          : 'Pick an agent, a team or a channel to start. Use @ in any chat to call another agent.'}
      </p>
      <div className="ag-welcome__status" aria-label="Model readiness">
        <span className={readiness?.local ? 'is-ready' : ''}>
          <HardDrive size={13} /> {readiness?.local ? 'Local model ready' : 'No local model found'}
        </span>
        <span className={readiness?.opencode ? 'is-ready' : ''}>
          {readiness?.opencode ? <Cloud size={13} /> : <KeyRound size={13} />}
          {readiness?.opencode ? 'OpenCode key ready' : 'OpenCode key not added'}
        </span>
      </div>
      <div className="ag-welcome__actions">
        <Button
          variant="primary"
          size="sm"
          onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-agent'))}
        >
          <Plus size={14} /> {agents.length === 0 ? 'Create your first agent' : 'New agent'}
        </Button>
        {agents.length > 0 && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-team'))}
          >
            <Users size={14} /> New team
          </Button>
        )}
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
      {agents.length === 0 && (
        <div className="ag-welcome__readiness-note">
          <span>Start local and private, or paste an OpenCode key in Settings → OpenCode.</span>
        </div>
      )}
    </div>
  );
}
