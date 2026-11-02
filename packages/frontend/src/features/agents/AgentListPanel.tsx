import { useCallback, useEffect, useMemo, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import { botStateFor } from '../../bots/config';
import ContextMenu from '../../components/ContextMenu';
import { useConfirm } from '../../components/ConfirmDialog';
import { TextInput } from '../../ui/primitives';
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
  const [query, setQuery] = useState('');

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
    const timer = window.setInterval(() => void fetchAgents(), 15000);
    window.addEventListener('palimind:agents-changed', onChanged);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('palimind:agents-changed', onChanged);
    };
  }, [fetchAgents]);

  const openConfig = (agent: AgentListItem) => {
    setSelectedAgentId(agent.id);
    window.dispatchEvent(new CustomEvent('palimind:open-agent-config', { detail: { agentId: agent.id } }));
  };

  const visibleAgents = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter((a) => {
      const label = `${a.display_name || ''} ${a.name} ${a.title || ''}`.toLowerCase();
      return label.includes(q);
    });
  }, [agents, query]);

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

  const deleteAll = async () => {
    const ok = await confirm(
      `Delete all ${agents.length} agents? This removes every bot along with its memory, chats, sessions and run history. This cannot be undone.`,
      { title: 'Delete all agents', confirmLabel: 'Delete all', danger: true },
    );
    if (!ok) return;
    try {
      await api.agents.removeAll();
      setAgents([]);
      setSelectedAgentId(null);
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } catch {
      // ignore
    }
  };

  const runNow = async (agent: AgentListItem) => {
    try {
      await api.agents.runNow(agent.id);
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } catch {
      // ignore
    }
  };

  const duplicate = async (agent: AgentListItem) => {
    try {
      const res = await api.agents.duplicate(agent);
      if (res.error) return;
      if (res.id) setSelectedAgentId(res.id);
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } catch {
      // ignore
    }
  };

  const toggleEnabled = async (agent: AgentListItem) => {
    try {
      await api.agents.update(agent.id, { enabled: !agent.enabled });
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
        { label: 'Settings', action: () => openConfig(agent) },
        { label: 'Run now', action: () => void runNow(agent) },
        { label: 'Duplicate', action: () => void duplicate(agent) },
        {
          label: agent.enabled ? 'Disable' : 'Enable',
          action: () => void toggleEnabled(agent),
        },
        { label: 'Delete agent', action: () => void deleteAgent(agent), isDanger: true },
      ],
    });
  };

  return (
    <aside className="aw-agent-panel" aria-label="Agents">
      <div className="aw-agent-panel__head">
        <span>Agents</span>
        <div className="aw-agent-panel__actions">
          {agents.length > 0 && (
            <button
              className="icon-btn"
              title="Delete all agents"
              aria-label="Delete all agents"
              onClick={() => void deleteAll()}
            >
              <Trash2 size={14} />
            </button>
          )}
          <button
            className="icon-btn"
            title="New Agent"
            aria-label="Create new agent"
            onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-agent'))}
          >
            <Plus size={14} />
          </button>
        </div>
      </div>
      {agents.length > 0 && (
        <div className="aw-agent-panel__search">
          <TextInput
            placeholder="Search agents…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      )}
      <div className="aw-agent-panel__list">
        {visibleAgents.map((a) => (
          <div
            key={a.id}
            className={`aw-agent-item${a.id === selectedAgentId ? ' active' : ''}`}
            onClick={() => setSelectedAgentId(a.id)}
            onContextMenu={(e) => showMenu(e, a)}
          >
            <AgentAvatar
              config={a.avatar_config}
              type={a.avatar_type === 'upload' ? 'upload' : 'bot'}
              upload={a.avatar_upload}
              state={botStateFor(a)}
              size={26}
            />
            <span className="aw-agent-item__text">
              <span className="aw-agent-item__name">
                {a.display_name || a.name}
                {!a.enabled && <span className="aw-agent-item__off">off</span>}
                {(a.active_runs || 0) > 0 && (
                  <span className="aw-agent-item__runs">{a.active_runs}</span>
                )}
              </span>
              <span className="aw-agent-item__title">
                {a.title ? `${a.title} · @${a.name}` : `@${a.name}`}
              </span>
            </span>
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
        {agents.length === 0 && (
          <div className="aw-agent-panel__empty">
            <p>No agents yet.</p>
            <button
              type="button"
              className="aw-agent-panel__empty-cta"
              onClick={() => window.dispatchEvent(new CustomEvent('palimind:new-agent'))}
            >
              Create your first agent
            </button>
          </div>
        )}
        {agents.length > 0 && visibleAgents.length === 0 && (
          <div className="aw-agent-panel__empty">No agents match “{query}”.</div>
        )}
      </div>
      {menu && (
        <ContextMenu x={menu.x} y={menu.y} items={menu.items} onClose={() => setMenu(null)} />
      )}
    </aside>
  );
}
