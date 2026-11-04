import { useCallback, useEffect, useState } from 'react';
import { MoreVertical } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import { botStateFor } from '../../bots/config';
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
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(timer);
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
    const ok = await confirm(
      `Delete agent "${agent.display_name || agent.name}"? This removes its memory, chats and runs.`,
      { title: 'Delete agent', confirmLabel: 'Delete', danger: true },
    );
    if (!ok) return;
    try {
      await api.agents.remove(agent.id);
      setSelectedAgentId(null);
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } catch {
      // ignore
    }
  };

  const runNow = async () => {
    try {
      await api.agents.runNow(agent.id);
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
    } catch {
      // ignore
    }
  };

  const duplicate = async () => {
    try {
      const res = await api.agents.duplicate(agent);
      if (res.error) return;
      window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
      if (res.id) setSelectedAgentId(res.id);
    } catch {
      // ignore
    }
  };

  const toggleEnabled = async () => {
    try {
      await api.agents.update(agent.id, { enabled: !agent.enabled });
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
      <AgentAvatar
        config={agent.avatar_config}
        type={agent.avatar_type === 'upload' ? 'upload' : 'bot'}
        upload={agent.avatar_upload}
        state={botStateFor(agent)}
        size={30}
      />
      <div className="agents-topbar__id">
        <span className="agents-topbar__name">{agent.display_name || agent.name}</span>
        <span className="agents-topbar__meta">
          @{agent.name}
          {agent.title ? ` · ${agent.title}` : ''}
          {` · ${agent.model || 'default model'} · ${agent.tools.length} tools`}
          {!agent.enabled ? ' · disabled' : ''}
          {(agent.active_runs || 0) > 0 ? ` · ${agent.active_runs} running` : ''}
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
            { label: 'Settings', action: openSettings },
            {
              label: 'Files',
              action: () =>
                window.dispatchEvent(new CustomEvent('palimind:open-agent-files')),
            },
            { label: 'Run now', action: () => void runNow() },
            { label: 'Duplicate', action: () => void duplicate() },
            { label: agent.enabled ? 'Disable' : 'Enable', action: () => void toggleEnabled() },
            { label: 'Delete agent', action: () => void deleteAgent(), isDanger: true },
          ]}
        />
      )}
    </header>
  );
}
