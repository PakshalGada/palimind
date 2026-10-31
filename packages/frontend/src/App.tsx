import { useEffect } from 'react';
import { useApp } from './AppContext';
import { api } from './api';
import Sidebar from './components/Sidebar';
import WelcomeScreen from './components/WelcomeScreen';
import ChatArea from './components/ChatArea';
import SettingsModal from './components/SettingsModal';
import DirectoryPicker from './components/DirectoryPicker';
import KnowledgeGraph from './components/KnowledgeGraph';
import ToastContainer from './components/ToastContainer';
import SetupProgress from './components/SetupProgress';
import ShortcutsModal from './components/ShortcutsModal';
import CommandPalette from './components/CommandPalette';
import ResearchPlanModal from './components/ResearchPlanModal';
import ResearchManager from './components/ResearchManager';
import SaveToResearchModal from './components/SaveToResearchModal';
import ComparisonView from './components/ComparisonView';
import SocialSignals from './components/SocialSignals';
import AgentGraph from './components/AgentGraph';
import SkillManager from './components/SkillManager';
import PlanReview from './components/PlanReview';
import TaskMonitor from './components/TaskMonitor';
import ArtifactAutoOpen from './components/ArtifactAutoOpen';
import AgentManager from './features/agents/AgentManager';
import AgentsWorkspace from './features/agents/AgentsWorkspace';
import AppLayout from './components/layout/AppLayout';
import ResponsiveSidebar from './components/layout/ResponsiveSidebar';
import SidePanel from './components/layout/SidePanel';
import { useCommandHandlers } from './commands/useCommand';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import { ChatStreamProvider } from './stream/ChatStream';

export default function App() {
  const {
    activeView,
    selectedAgentId,
    activeField, setActiveField, setSessions, setActiveSessionId,
    setCurrentModel, setLlmSubMode, setOrchestratorModel, setWorkerModel,
    setIsIndexing, setIndexingStatus, addToast,
    isRecording, isTranscribing, isSpeaking,
    setActiveView, setAgentsView, setChatMode, theme, setTheme,
    chatMode,
    setCommandPaletteOpen, setShortcutsModalOpen,
    toggleSidebar, setArtifactPanelOpen, openArtifactLibrary,
    artifactPanelOpen,
    shortcutOverrides, commandPaletteOpen,
  } = useApp();

  useKeyboardShortcuts({ overrides: shortcutOverrides, disabled: commandPaletteOpen });

  // App-level commands: navigation, view toggles and global modals.
  useCommandHandlers({
    'general.palette': () => setCommandPaletteOpen(true),
    'general.shortcuts': () => setShortcutsModalOpen(true),
    'general.settings': () => {
      const modal = document.getElementById('settings-modal');
      if (modal) modal.style.display = 'flex';
    },
    'view.toggle-sidebar': toggleSidebar,
    'view.toggle-theme': () => setTheme(theme === 'dark' ? 'light' : 'dark'),
    'view.toggle-artifacts': () => {
      setArtifactPanelOpen(!artifactPanelOpen);
    },
    'view.browse-artifacts': openArtifactLibrary,
    'nav.chat': () => {
      setActiveView('chat');
      setChatMode('llm');
    },
    'nav.knowledge': () => {
      setActiveView('fields');
      setChatMode('document');
    },
    'nav.agents': () => setActiveView('agents'),
    'nav.graph': () => {
      const modal = document.getElementById('graph-modal');
      if (modal) modal.style.display = 'flex';
      window.dispatchEvent(new CustomEvent('palimind:open-graph'));
    },
    'nav.search': () => setCommandPaletteOpen(true),
    'research.projects': () => {
      window.dispatchEvent(new CustomEvent('palimind:open-research'));
    },
    'research.compare': () => {
      window.dispatchEvent(new CustomEvent('palimind:open-compare'));
    },
    'research.social': () => {
      window.dispatchEvent(new CustomEvent('palimind:open-social'));
    },
    'chat.toggle-mode': () => setChatMode(chatMode === 'llm' ? 'document' : 'llm'),
    'agents.new': () => {
      window.dispatchEvent(new CustomEvent('palimind:new-agent'));
    },
    'agents.orchestrate': () => {
      window.dispatchEvent(new CustomEvent('palimind:open-agent-graph'));
    },
    'agents.skills': () => {
      window.dispatchEvent(new CustomEvent('palimind:open-skill-manager'));
    },
    'agents.plans': () => {
      window.dispatchEvent(new CustomEvent('palimind:open-plan-review'));
    },
    'agents.tasks': () => {
      window.dispatchEvent(new CustomEvent('palimind:open-task-monitor'));
    },
    'agents.kanban': () => {
      setActiveView('agents');
      setAgentsView('kanban');
    },
  });

  // The Agents area reuses the global chat surface but is backed by the
  // selected agent's own scope (separate sessions, model and settings). With
  // no agent selected the scope is intentionally empty — it must never fall
  // back to global or knowledge-base chat.
  const scope =
    activeView === 'agents'
      ? selectedAgentId
        ? `agent:${selectedAgentId}`
        : ''
      : activeView === 'chat'
        ? 'chat'
        : 'field';

  useEffect(() => {
    async function init() {
      try {
        const fieldsData = await api.fields.list();
        setActiveField(fieldsData.active_field);
        setIsIndexing(fieldsData.is_indexing);
        if (fieldsData.is_indexing) {
          setIndexingStatus(fieldsData.indexing_status || 'Indexing knowledge base...');
        }
        if (!scope) return;
        const configData = await api.config.get(scope);
        if (configData.chat_model) {
          setCurrentModel(configData.chat_model);
        }
        if (configData.moe_sub_mode) {
          setLlmSubMode(configData.moe_sub_mode as 'default' | 'moe');
        }
        if (configData.moe_orchestrator_model) {
          setOrchestratorModel(configData.moe_orchestrator_model);
        }
        if (configData.moe_worker_model) {
          setWorkerModel(configData.moe_worker_model);
        }
      } catch (e) {
        console.error('Init error:', e);
        addToast('Failed to connect to backend');
      }
    }
    init();
  }, [scope]);

  useEffect(() => {
    if (!scope || (scope === 'field' && !activeField)) {
      setSessions([]);
      setActiveSessionId(null);
      return;
    }
    // Clear the previous scope first, and ignore a late response from a scope
    // we have already left, so histories never cross between scopes.
    let cancelled = false;
    setSessions([]);
    setActiveSessionId(null);
    api.sessions.list(scope).then(data => {
      if (cancelled || data.error) return;
      setSessions(data.sessions);
      setActiveSessionId(data.active_session_id);
    }).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [scope, activeField]);

  const containerClass = [
    isRecording ? 'recording' : '',
    isTranscribing ? 'transcribing' : '',
    isSpeaking ? 'speaking' : '',
  ].filter(Boolean).join(' ');

  return (
    <ChatStreamProvider>
      <ArtifactAutoOpen />
      <AppLayout
        className={containerClass}
        sidebar={
          <ResponsiveSidebar>
            <Sidebar />
          </ResponsiveSidebar>
        }
        sidePanel={<SidePanel />}
      >
        <SetupProgress />
        {activeView === "agents" ? (
          <AgentsWorkspace />
        ) : activeView === "chat" || activeField ? (
          <ChatArea />
        ) : (
          <WelcomeScreen />
        )}
        <AgentManager />
        <SettingsModal />
        <DirectoryPicker />
        <KnowledgeGraph />
        <ShortcutsModal />
        <CommandPalette />
        <ResearchPlanModal />
        <ResearchManager />
        <SaveToResearchModal />
        <ComparisonView />
        <SocialSignals />
        <AgentGraph />
        <SkillManager />
        <PlanReview />
        <TaskMonitor />
        <ToastContainer />
      </AppLayout>
    </ChatStreamProvider>
  );
}
