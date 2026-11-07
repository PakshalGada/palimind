import { useCallback, useEffect, useState } from 'react';
import { api } from '../../../api';
import type { AgentListItem, BrowserTakeover, Channel, Team } from '../../../types';

interface Roster {
  agents: AgentListItem[];
  teams: Team[];
  channels: Channel[];
  takeovers: BrowserTakeover[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * One roster for the Agents rail. The Chat surface, Settings drawer and Work
 * surface all read the same agents/teams/channels lists so names and avatars
 * never drift between panels.
 */
export function useAgentRoster(): Roster {
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [takeovers, setTakeovers] = useState<BrowserTakeover[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [agentRes, teamRes, channelRes, takeoverRes] = await Promise.allSettled([
      api.agents.list(),
      api.teams.list(),
      api.channels.list(false),
      api.browser.takeovers('', 'pending'),
    ]);
    if (agentRes.status === 'fulfilled') {
      setAgents((agentRes.value.agents || []).filter((agent) => agent.enabled !== false));
      setError(null);
    } else {
      setError(
        agentRes.reason instanceof Error ? agentRes.reason.message : 'Could not load your team.',
      );
    }
    if (teamRes.status === 'fulfilled') setTeams(teamRes.value.teams || []);
    if (channelRes.status === 'fulfilled') {
      setChannels((channelRes.value.channels || []) as unknown as Channel[]);
    }
    if (takeoverRes.status === 'fulfilled') {
      setTakeovers((takeoverRes.value.takeovers || []) as unknown as BrowserTakeover[]);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 6_000);
    const onChanged = () => void refresh();
    window.addEventListener('palimind:agents-changed', onChanged);
    window.addEventListener('palimind:browser-takeover', onChanged);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('palimind:agents-changed', onChanged);
      window.removeEventListener('palimind:browser-takeover', onChanged);
    };
  }, [refresh]);

  return { agents, teams, channels, takeovers, loading, error, refresh };
}
