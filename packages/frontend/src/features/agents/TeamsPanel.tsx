import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Plus, Users } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import { Button, Chip, EmptyState } from '../../ui/primitives';
import type { Team } from '../../types';
import TeamWorkspace from './TeamWorkspace';
import './TeamWorkspace.css';

export default function TeamsPanel() {
  const { selectedTeamId, setSelectedTeamId } = useApp();
  const [teams, setTeams] = useState<Team[]>([]);

  const refresh = useCallback(async () => {
    try {
      const data = await api.teams.list();
      setTeams(data.teams || []);
    } catch {
      // best effort
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    const onChanged = () => void refresh();
    window.addEventListener('palimind:agents-changed', onChanged);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('palimind:agents-changed', onChanged);
    };
  }, [refresh]);

  useEffect(() => {
    const open = (e: Event) => {
      const id = (e as CustomEvent).detail?.teamId as string | undefined;
      if (id) setSelectedTeamId(id);
    };
    window.addEventListener('palimind:open-team', open);
    return () => window.removeEventListener('palimind:open-team', open);
  }, [setSelectedTeamId]);

  if (selectedTeamId) {
    return <TeamWorkspace key={selectedTeamId} teamId={selectedTeamId} onBack={() => setSelectedTeamId(null)} />;
  }

  return (
    <div className="teams-panel">
      <header className="teams-panel__head">
        <div>
          <h1 className="ah-title">Teams</h1>
          <p className="ah-sub">
            Groups of specialists with a manager, a shared thread and durable shared notes.
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-team'))}
        >
          <Plus size={14} /> New team
        </Button>
      </header>

      <div className="teams-panel__scroll">
        {teams.length === 0 ? (
          <EmptyState
            icon={<Users size={26} />}
            title="No teams yet"
            description="Put two or more agents together. The manager delegates, teammates work, and you see every handoff in one thread."
            action={
              <Button
                variant="primary"
                onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-team'))}
              >
                <Plus size={14} /> Create a team
              </Button>
            }
          />
        ) : (
          <div className="teams-grid">
            {teams.map((team) => (
              <button
                key={team.id}
                type="button"
                className={`team-card${team.running ? ' is-running' : ''}`}
                onClick={() => setSelectedTeamId(team.id)}
              >
                <div className="team-card__head">
                  <span className="team-card__icon">
                    <Users size={20} />
                  </span>
                  <div className="team-card__id">
                    <span className="team-card__name">{team.display_name || team.name}</span>
                    <span className="team-card__desc">{team.description || 'No description yet.'}</span>
                  </div>
                  <ArrowRight size={15} className="team-card__arrow" />
                </div>
                <div className="team-card__members">
                  {team.members.slice(0, 5).map((member) => {
                    const agent = member.agent;
                    return (
                      <span key={member.agent_id} className="team-card__avatar" title={agent?.display_name || agent?.name}>
                        <AgentAvatar
                          config={agent?.avatar_config}
                          upload={agent?.avatar_upload}
                          type={agent?.avatar_type === 'upload' ? 'upload' : 'bot'}
                          size={24}
                        />
                      </span>
                    );
                  })}
                  {team.members.length > 5 && <span className="team-card__more">+{team.members.length - 5}</span>}
                </div>
                <div className="team-card__foot">
                  <Chip tone="muted">{team.mode}</Chip>
                  <span>{team.members.length} members</span>
                  {team.running && <Chip tone="success">running</Chip>}
                  {!!team.pending_approvals && <Chip tone="warn">{team.pending_approvals} waiting</Chip>}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
