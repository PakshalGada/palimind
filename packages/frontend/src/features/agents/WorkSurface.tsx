import { useApp } from '../../AppContext';
import KanbanDashboard from '../../components/KanbanDashboard';
import ActivityView from './work/ActivityView';
import AutomationsView from './work/AutomationsView';
import OverviewView from './work/OverviewView';
import TasksView from './work/TasksView';
import type { AgentListItem, AgentsWorkTab, Team } from '../../types';
import './WorkSurface.css';

const TABS: { id: AgentsWorkTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'activity', label: 'Activity' },
  { id: 'tasks', label: 'Tasks' },
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
          <p>Mission control, runs, tasks and the work that repeats.</p>
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
        {agentsWorkTab === 'overview' && <OverviewView agents={agents} teams={teams} />}
        {agentsWorkTab === 'activity' && <ActivityView agents={agents} />}
        {agentsWorkTab === 'tasks' && <TasksView agents={agents} />}
        {agentsWorkTab === 'board' && <KanbanDashboard embedded />}
        {agentsWorkTab === 'automations' && <AutomationsView agents={agents} teams={teams} />}
      </div>
    </div>
  );
}
