import { Bot } from 'lucide-react';
import { useApp } from '../../AppContext';
import AgentHeader from './AgentHeader';
import AgentListPanel from './AgentListPanel';
import ChatArea from '../../components/ChatArea';
import WorkflowBuilder from '../../components/WorkflowBuilder';
import KanbanDashboard from '../../components/KanbanDashboard';
import './AgentsWorkspace.css';

/**
 * The Agents workspace. The Chat / Workflows / Tasks switcher lives in the left
 * sidebar (see Sidebar.tsx). The Chat view gets its own agent roster panel; the
 * workflows and tasks surfaces take the full width.
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
                <div className="aw-empty">
                  <Bot size={26} />
                  <p>No agent selected</p>
                  <span>Choose an agent from the panel, or create one to begin.</span>
                </div>
              )}
            </div>
          </div>
        ) : agentsView === 'workflows' ? (
          <WorkflowBuilder />
        ) : (
          <KanbanDashboard />
        )}
      </div>
    </div>
  );
}
