import { useEffect, useState } from 'react';
import { Bot } from 'lucide-react';
import { useApp } from '../../AppContext';
import AgentHeader from './AgentHeader';
import AgentListPanel from './AgentListPanel';
import ChatArea from '../../components/ChatArea';
import KanbanDashboard from '../../components/KanbanDashboard';
import { Button, EmptyState } from '../../ui/primitives';
import AgentsHome from './AgentsHome';
import TeamsPanel from './TeamsPanel';
import RunsView from './RunsView';
import AgentsInbox from './AgentsInbox';
import NewTeamModal from './NewTeamModal';
import AgentWorkspacePanel from './AgentWorkspacePanel';
import './AgentsWorkspace.css';
import './AgentOnboarding.css';

/**
 * The Agents workspace: a persistent tab bar over Home, one-on-one chat, team
 * workspaces, the task board and unified runs/routines.
 */
export default function AgentsWorkspace() {
  const { agentsView, setAgentsView, selectedAgentId, refreshInbox, refreshOverview, setSelectedTeamId } = useApp();
  const [inboxOpen, setInboxOpen] = useState(false);
  const [teamModalOpen, setTeamModalOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);

  useEffect(() => {
    void refreshOverview();
    void refreshInbox();
    const timer = window.setInterval(() => {
      void refreshInbox();
    }, 10000);
    return () => window.clearInterval(timer);
  }, [refreshOverview, refreshInbox]);

  useEffect(() => {
    const onInbox = () => setInboxOpen(true);
    const onNewTeam = () => setTeamModalOpen(true);
    const onFiles = () => setFilesOpen(true);
    window.addEventListener('palimind:open-inbox', onInbox);
    window.addEventListener('palimind:new-team', onNewTeam);
    window.addEventListener('palimind:open-agent-files', onFiles);
    return () => {
      window.removeEventListener('palimind:open-inbox', onInbox);
      window.removeEventListener('palimind:new-team', onNewTeam);
      window.removeEventListener('palimind:open-agent-files', onFiles);
    };
  }, []);

  return (
    <div className="agents-main aw-root">
      <div className="aw-body">
        {agentsView === 'home' && <AgentsHome />}

        {agentsView === 'teams' && <TeamsPanel />}

        {agentsView === 'runs' && <RunsView />}

        {agentsView === 'chat' && (
          <div className="aw-chat">
            <AgentListPanel />
            <div className="aw-chat-main">
              <AgentHeader />
              {selectedAgentId ? (
                <ChatArea />
              ) : (
                <EmptyState
                  className="aw-empty"
                  icon={<Bot size={24} />}
                  title="No agent selected"
                  description="Choose an agent from the panel, or create one to begin."
                  action={
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        window.dispatchEvent(new CustomEvent('palimind:new-agent'))
                      }
                    >
                      New agent
                    </Button>
                  }
                />
              )}
            </div>
          </div>
        )}

        {agentsView === 'kanban' && <KanbanDashboard />}
      </div>

      <AgentsInbox open={inboxOpen} onClose={() => setInboxOpen(false)} />
      <AgentWorkspacePanel open={filesOpen} onClose={() => setFilesOpen(false)} />
      <NewTeamModal
        open={teamModalOpen}
        onClose={() => setTeamModalOpen(false)}
        onCreated={(team) => {
          setTeamModalOpen(false);
          setAgentsView('teams');
          if (team) setSelectedTeamId(team.id);
          void refreshOverview();
          window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
        }}
      />
    </div>
  );
}
