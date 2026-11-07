import { useApp } from '../../AppContext';
import KanbanDashboard from '../../components/KanbanDashboard';
import ActivityView from './work/ActivityView';
import AutomationsView from './work/AutomationsView';
import type { AgentListItem, AgentsWorkTab, Team } from '../../types';
import './WorkSurface.css';

const TABS: { id: AgentsWorkTab; label: string }[] = [
  { id: 'activity', label: 'Activity' },
  { id: 'board', label: 'Board' },
  { id: 'automations', label: 'Automations' },
];

export default function WorkSurface({
  agents,
  teams,
}: {
  agents: AgentListItem[];
  teams: Team[];
}) {
  const { agentsWorkTab, setAgentsWorkTab } = useApp();

  return (
    <div className="ag-work">
      <header className="ag-work__head">
        <div className="ag-work__title">
          <span>Work</span>
          <p>Runs, tasks and the work that repeats.</p>
        </div>
        <div className="ag-segmented" role="tablist" aria-label="Work sections">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={agentsWorkTab === tab.id}
              className={agentsWorkTab === tab.id ? 'is-on' : ''}
              onClick={() => setAgentsWorkTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </header>
      <div className="ag-work__body">
        {agentsWorkTab === 'activity' && <ActivityView agents={agents} />}
        {agentsWorkTab === 'board' && <KanbanDashboard embedded />}
        {agentsWorkTab === 'automations' && <AutomationsView agents={agents} teams={teams} />}
      </div>
    </div>
  );
}
