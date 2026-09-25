import { useCallback, useEffect, useState } from 'react';
import { MoreVertical } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import ContextMenu from '../../components/ContextMenu';
import { useConfirm } from '../../components/ConfirmDialog';
import type { AgentListItem } from '../../types';
import './AgentHeader.css';

/**
 * Top bar for the Agents area: shows the current agent's name / model and a
 * three-dot menu (Info → settings popup, Delete agent).
 */
export default function AgentHeader() {
  const { selectedAgentId, setSelectedAgentId } = useApp();
  const confirm = useConfirm();
  const [agent, setAgent] = useState<AgentListItem | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.agents.list();
      setAgent((data.agents || []).find((a) => a.id === selectedAgentId) || null);
    } catch {
      // best effort
    }
  }, [selectedAgentId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onChanged = () => void refresh();
    window.addEventListener('palimind:agents-changed', onChanged);
    return () => window.removeEventListener('palimind:agents-changed', onChanged);
  }, [refresh]);

  if (!agent) return null;

  const openSettings = () =>
    window.dispatchEvent(
      new CustomEvent('palimind:open-agent-config', { detail: { agentId: agent.id } }),
    );

  const deleteAgent = async () => {
    const ok = await confirm(`Delete agent "${agent.name}"? This cannot be undone.`, {
      title: 'Delete Agent',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.agents.remove(agent.id);
      setSelectedAgentId(null);
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } catch {
      // ignore
    }
  };

  const openMenu = (e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenu({ x: Math.max(8, rect.right - 168), y: rect.bottom + 4 });
  };

  return (
    <header className="agents-topbar">
      <AgentAvatar seed={agent.color_seed || agent.id + agent.name} size={24} thinking={agent.running} />
      <div className="agents-topbar__id">
        <span className="agents-topbar__name">{agent.name}</span>
        <span className="agents-topbar__meta">
          {agent.model || 'default model'} · {agent.tools.length} tools
          {!agent.enabled ? ' · disabled' : ''}
        </span>
      </div>
      <button
        type="button"
        className="icon-btn"
        title="Agent options"
        aria-label="Agent options"
        onClick={openMenu}
      >
        <MoreVertical size={16} />
      </button>
      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          onClose={() => setMenu(null)}
          items={[
            { label: 'Info', action: openSettings },
            { label: 'Delete Agent', action: deleteAgent, isDanger: true },
          ]}
        />
      )}
    </header>
  );
}
