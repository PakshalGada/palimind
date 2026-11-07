import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { useCommandHandler } from '../../commands/useCommand';
import type { AgentListItem } from '../../types';
import type { InspectorSection } from './types';
import AgentOnboarding from './AgentOnboarding';
import Inspector from './Inspector';
import './agents.css';
import './AgentManager.css';

/**
 * Hosts the agent create wizard and the settings inspector. The main Agents
 * area is the shared ChatArea; this component only exists so the sidebar's
 * "New Agent" / settings actions still have somewhere to go.
 */
export default function AgentManager() {
  const { setSelectedAgentId, selectedAgentId, addToast, setActiveView, setAgentsView } = useApp();
  const [creating, setCreating] = useState(false);
  const [configId, setConfigId] = useState<string | null>(null);
  const [configSection, setConfigSection] = useState<InspectorSection>('identity');
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
      const detail = (e as CustomEvent).detail as { agentId?: string; tab?: InspectorSection } | undefined;
      const agentId = detail?.agentId;
      if (agentId) {
        setConfigId(agentId);
        setConfigSection(detail?.tab ?? 'identity');
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

  useCommandHandler('agents.manage-memory', () => {
    if (!selectedAgentId) {
      addToast('Select an agent to manage its memory.');
      return;
    }
    setConfigId(selectedAgentId);
    setConfigSection('runs');
    void refresh();
  });

  const configAgent = configId ? agents.find((a) => a.id === configId) || null : null;

  return (
    <>
      <AgentOnboarding
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(id) => {
          setCreating(false);
          setActiveView('agents');
          setAgentsView('chat');
          if (id) setSelectedAgentId(id);
          addToast('Agent created');
          window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
        }}
      />

      {configAgent && (
        <Inspector
          agent={configAgent}
          initialSection={configSection}
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
      )}
    </>
  );
}
