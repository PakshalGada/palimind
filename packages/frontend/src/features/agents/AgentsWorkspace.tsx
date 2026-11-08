import { useEffect, useState } from 'react';
import { Menu } from 'lucide-react';
import { useApp } from '../../AppContext';
import ConversationRail from './ConversationRail';
import ChatSurface from './ChatSurface';
import WorkSurface from './WorkSurface';
import SettingsDrawer from './SettingsDrawer';
import NewChannelModal from './NewChannelModal';
import AgentsInbox from './AgentsInbox';
import AgentWorkspacePanel from './AgentWorkspacePanel';
import NewTeamModal from './NewTeamModal';
import BrowserDock from './browser/BrowserDock';
import { useAgentRoster } from './hooks/useAgentRoster';
import './agentdesk.css';

/**
 * Agents workspace: one conversation rail, two surfaces (Chat and Work), and
 * a browser dock that agents and the user share. There are no per-feature
 * top-level tabs; teams and channels are conversations.
 */
export default function AgentsWorkspace() {
  const {
    agentsView,
    setAgentsView,
    selectedAgentId,
    setSelectedAgentId,
    setSelectedTeamId,
    selectedTeamId,
    selectedChannelId,
    setSelectedChannelId,
    refreshInbox,
    refreshOverview,
    setAgentsSettingsOpen,
    agentsSettingsOpen,
    browserOpen,
    setBrowserOpen,
  } = useApp();
  const { agents, teams, channels, takeovers, refresh } = useAgentRoster();
  const [inboxOpen, setInboxOpen] = useState(false);
  const [teamModalOpen, setTeamModalOpen] = useState(false);
  const [channelModalOpen, setChannelModalOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);

  useEffect(() => {
    void refreshOverview();
    void refreshInbox();
    const timer = window.setInterval(() => void refreshInbox(), 10_000);
    return () => window.clearInterval(timer);
  }, [refreshOverview, refreshInbox]);

  useEffect(() => {
    const onInbox = () => setInboxOpen(true);
    const onNewTeam = () => setTeamModalOpen(true);
    const onFiles = () => setFilesOpen(true);
    const onSettings = () => setAgentsSettingsOpen(true);
    const onBrowserActive = () => setBrowserOpen(true);
    window.addEventListener('palimind:open-inbox', onInbox);
    window.addEventListener('palimind:new-team', onNewTeam);
    window.addEventListener('palimind:open-agent-files', onFiles);
    window.addEventListener('palimind:open-agents-settings', onSettings);
    window.addEventListener('palimind:browser-active', onBrowserActive);
    return () => {
      window.removeEventListener('palimind:open-inbox', onInbox);
      window.removeEventListener('palimind:new-team', onNewTeam);
      window.removeEventListener('palimind:open-agent-files', onFiles);
      window.removeEventListener('palimind:open-agents-settings', onSettings);
      window.removeEventListener('palimind:browser-active', onBrowserActive);
    };
  }, [setAgentsSettingsOpen, setBrowserOpen]);

  // Open on a conversation rather than an empty canvas. Only do this in Chat
  // so switching to Work does not change the selected agent behind the scenes.
  useEffect(() => {
    if (agentsView !== 'chat') return;
    if (selectedAgentId || selectedTeamId || selectedChannelId) return;
    if (agents.length > 0) setSelectedAgentId(agents[0].id);
  }, [
    agents,
    agentsView,
    selectedAgentId,
    selectedTeamId,
    selectedChannelId,
    setSelectedAgentId,
  ]);

  return (
    <div className="ag-shell">
      <ConversationRail
        agents={agents}
        teams={teams}
        channels={channels}
        takeovers={takeovers}
        onNewChannel={() => setChannelModalOpen(true)}
        open={railOpen}
        onNavigate={() => setRailOpen(false)}
      />
      {railOpen && (
        <button
          type="button"
          className="ag-rail-scrim"
          aria-label="Close navigation"
          onClick={() => setRailOpen(false)}
        />
      )}
      <button
        type="button"
        className="ag-rail-toggle"
        title="Agents"
        aria-label="Open agents navigation"
        onClick={() => setRailOpen(true)}
      >
        <Menu size={16} />
      </button>

      <div className="ag-surface">
        {agentsView === 'work' ? (
          <WorkSurface agents={agents} teams={teams} />
        ) : (
          <ChatSurface
            agents={agents}
            teams={teams}
            channels={channels}
            takeovers={takeovers}
          />
        )}
        {agentsView === 'chat' && browserOpen && <BrowserDock agentId={selectedAgentId} />}
      </div>

      <AgentsInbox open={inboxOpen} onClose={() => setInboxOpen(false)} />
      <AgentWorkspacePanel open={filesOpen} onClose={() => setFilesOpen(false)} />
      <SettingsDrawer
        open={agentsSettingsOpen}
        agents={agents}
        onClose={() => setAgentsSettingsOpen(false)}
      />
      <NewTeamModal
        open={teamModalOpen}
        onClose={() => setTeamModalOpen(false)}
        onCreated={(team) => {
          setTeamModalOpen(false);
          setAgentsView('chat');
          setSelectedChannelId(null);
          if (team) setSelectedTeamId(team.id);
          void refresh();
          void refreshOverview();
          window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
        }}
      />
      <NewChannelModal
        open={channelModalOpen}
        agents={agents}
        onClose={() => setChannelModalOpen(false)}
        onCreated={(id) => {
          setChannelModalOpen(false);
          setAgentsView('chat');
          setSelectedTeamId(null);
          setSelectedAgentId(null);
          setSelectedChannelId(id);
          void refresh();
        }}
      />
    </div>
  );
}
