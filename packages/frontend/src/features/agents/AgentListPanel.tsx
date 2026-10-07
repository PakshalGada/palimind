import { useCallback, useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import ContextMenu from '../../components/ContextMenu';
import { useConfirm } from '../../components/ConfirmDialog';
import type { AgentListItem } from '../../types';
import './AgentListPanel.css';

interface MenuState {
  x: number;
  y: number;
  items: { label: string; action: () => void; isDanger?: boolean }[];
}

/**
 * Roster of agents shown as a dedicated side panel inside the Chat view of the
 * Agents workspace. Selecting an agent switches the active agent conversation.
 */
export default function AgentListPanel() {
  const { selectedAgentId, setSelectedAgentId } = useApp();
  const confirm = useConfirm();
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [menu, setMenu] = useState<MenuState | null>(null);

  const fetchAgents = useCallback(async () => {
    try {
      const data = await api.agents.list();
      if (!data.agents) return;
      setAgents(data.agents);
      const stillValid = selectedAgentId && data.agents.some((a) => a.id === selectedAgentId);
      if (!stillValid) setSelectedAgentId(data.agents[0]?.id ?? null);
    } catch {
      // best effort
    }
  }, [selectedAgentId, setSelectedAgentId]);

  useEffect(() => {
    void fetchAgents();
    const onChanged = () => void fetchAgents();
    window.addEventListener('palimind:agents-changed', onChanged);
    return () => window.removeEventListener('palimind:agents-changed', onChanged);
  }, [fetchAgents]);

  const openConfig = (agent: AgentListItem) => {
    setSelectedAgentId(agent.id);
    window.dispatchEvent(new CustomEvent('palimind:open-agent-config', { detail: { agentId: agent.id } }));
  };

  const deleteAgent = async (agent: AgentListItem) => {
    const ok = await confirm(`Delete agent "${agent.name}"? This cannot be undone.`, {
      title: 'Delete Agent',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.agents.remove(agent.id);
      setAgents((prev) => prev.filter((a) => a.id !== agent.id));
      if (selectedAgentId === agent.id) setSelectedAgentId(null);
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } catch {
      // ignore
    }
  };

  const showMenu = (e: React.MouseEvent, agent: AgentListItem) => {
    e.preventDefault();
    e.stopPropagation();
    setMenu({
      x: e.clientX,
      y: e.clientY,
      items: [
        { label: 'Info', action: () => openConfig(agent) },
        { label: 'Delete Agent', action: () => void deleteAgent(agent), isDanger: true },
      ],
    });
  };

  return (
    <aside className="aw-agent-panel" aria-label="Agents">
      <div className="aw-agent-panel__head">
        <span>Agents</span>
        <button
          className="icon-btn"
          title="New Agent"
          aria-label="Create new agent"
          onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-agent'))}
        >
          <Plus size={14} />
        </button>
      </div>
      <div className="aw-agent-panel__list">
        {agents.map((a) => (
          <div
            key={a.id}
            className={`aw-agent-item${a.id === selectedAgentId ? ' active' : ''}`}
            onClick={() => setSelectedAgentId(a.id)}
            onContextMenu={(e) => showMenu(e, a)}
          >
            <AgentAvatar seed={a.color_seed || a.id + a.name} size={22} />
            <span className="aw-agent-item__name">{a.name}</span>
            <button
              className="icon-btn aw-agent-item__menu"
              title="Options"
              aria-label={`Options for ${a.name}`}
              onClick={(e) => showMenu(e, a)}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <circle cx="12" cy="5" r="1.6" />
                <circle cx="12" cy="12" r="1.6" />
                <circle cx="12" cy="19" r="1.6" />
              </svg>
            </button>
          </div>
        ))}
        {agents.length === 0 && <div className="aw-agent-panel__empty">No agents yet.</div>}
      </div>
      {menu && (
        <ContextMenu x={menu.x} y={menu.y} items={menu.items} onClose={() => setMenu(null)} />
      )}
    </aside>
  );
}
