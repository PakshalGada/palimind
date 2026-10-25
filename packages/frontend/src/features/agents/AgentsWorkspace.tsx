import { Bot } from 'lucide-react';
import { useApp } from '../../AppContext';
import AgentHeader from './AgentHeader';
import AgentListPanel from './AgentListPanel';
import ChatArea from '../../components/ChatArea';
import KanbanDashboard from '../../components/KanbanDashboard';
import { Button, EmptyState } from '../../ui/primitives';
import './AgentsWorkspace.css';

/**
 * The Agents workspace. The Chat / Tasks switcher lives in the left
 * sidebar (see Sidebar.tsx). The Chat view gets its own agent roster panel; the
 * tasks surface takes the full width.
 */
export default function AgentsWorkspace() {
  const { agentsView, selectedAgentId } = useApp();

  return (
    <div className="agents-main aw-root">
      <div className="aw-body">
        {agentsView === 'chat' ? (
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
        ) : (
          <KanbanDashboard />
        )}
      </div>
    </div>
  );
}
