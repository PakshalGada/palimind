import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import type { AgentListItem } from '../../types';
import AgentWizard from './AgentWizard';
import Inspector from './Inspector';
import './agents.css';
import './AgentManager.css';

/**
 * Hosts the agent create wizard and the settings inspector as modals. The
 * main Agents area is the shared ChatArea; this component only exists so the
 * sidebar's "New Agent" / "Info" actions still have somewhere to go.
 */
export default function AgentManager() {
  const { setSelectedAgentId } = useApp();
  const [creating, setCreating] = useState(false);
  const [configId, setConfigId] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentListItem[]>([]);

  const refresh = useCallback(async () => {
    try {
      const data = await api.agents.list();
      setAgents(data.agents || []);
    } catch {
      // best effort
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onChanged = () => void refresh();
    const onNew = () => setCreating(true);
    const onConfig = (e: Event) => {
      const agentId = (e as CustomEvent).detail?.agentId as string | undefined;
      if (agentId) {
        setConfigId(agentId);
        void refresh();
      }
    };
    window.addEventListener('palimind:agents-changed', onChanged);
    window.addEventListener('palimind:new-agent', onNew);
    window.addEventListener('palimind:open-agent-config', onConfig);
    return () => {
      window.removeEventListener('palimind:agents-changed', onChanged);
      window.removeEventListener('palimind:new-agent', onNew);
      window.removeEventListener('palimind:open-agent-config', onConfig);
    };
  }, [refresh]);

  const configAgent = configId ? agents.find((a) => a.id === configId) || null : null;

  return (
    <>
      <AgentWizard
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(id) => {
          setCreating(false);
          if (id) setSelectedAgentId(id);
          window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
        }}
      />

      {configAgent && (
        <div className="am-overlay" onMouseDown={() => setConfigId(null)}>
          <div className="am-panel" onMouseDown={(e) => e.stopPropagation()}>
            <Inspector
              agent={configAgent}
              onSaved={() => {
                void refresh();
                window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
              }}
              onDeleted={() => {
                setConfigId(null);
                setSelectedAgentId(null);
                window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
              }}
              onClose={() => setConfigId(null)}
            />
          </div>
        </div>
      )}
    </>
  );
}
