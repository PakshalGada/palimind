import { useEffect } from 'react';
import { useApp } from './AppContext';
import { api } from './api';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import SettingsModal from './components/SettingsModal';
import DirectoryPicker from './components/DirectoryPicker';
import KnowledgeGraph from './components/KnowledgeGraph';
import ToastContainer from './components/ToastContainer';
import SetupProgress from './components/SetupProgress';
import ShortcutsModal from './components/ShortcutsModal';
import CommandPalette from './components/CommandPalette';
import AgentGraph from './components/AgentGraph';
import SkillManager from './components/SkillManager';
import PlanReview from './components/PlanReview';
import ResearchPlanModal from './components/ResearchPlanModal';
import TaskMonitor from './components/TaskMonitor';
import ArtifactAutoOpen from './components/ArtifactAutoOpen';
import AgentManager from './features/agents/AgentManager';
import AgentsWorkspace from './features/agents/AgentsWorkspace';
import AppLayout from './components/layout/AppLayout';
import ConnectionBanner from './components/layout/ConnectionBanner';
import ResponsiveSidebar from './components/layout/ResponsiveSidebar';
import SidePanel from './components/layout/SidePanel';
import { useCommandHandlers } from './commands/useCommand';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import { usePixelMotion } from './design/usePixelMotion';
import { resolveScope } from './lib/scope';
import { ChatStreamProvider } from './stream/ChatStream';
import HomeView from './features/home/HomeView';
import ProjectsView from './features/projects/ProjectsView';
import ArtifactsView from './features/artifacts/ArtifactsView';
import KnowledgeView from './features/knowledge/KnowledgeView';

export default function App() {
  const {
    activeView,
    selectedAgentId,
    activeProjectId,
    activeField, setActiveField, setSessions, setActiveSessionId,
    setCurrentModel, setLlmSubMode, setOrchestratorModel, setWorkerModel,
    setIsIndexing, setIndexingStatus,
    isRecording, isTranscribing, isSpeaking,
    setActiveView, setAgentsView, setAgentsWorkTab, setChatMode, theme, setTheme,
    chatMode,
    setCommandPaletteOpen, setShortcutsModalOpen,
    toggleSidebar, setArtifactPanelOpen,
    artifactPanelOpen,
    shortcutOverrides, commandPaletteOpen,
  } = useApp();

  useKeyboardShortcuts({ overrides: shortcutOverrides, disabled: commandPaletteOpen });
  usePixelMotion();

  // Deep links: #home, #chat, #agents, #knowledge, #projects, #artifacts.
  // The view is reflected in the hash so a reload keeps context. Older
  // #research links are migrated to Projects instead of dead-ending.
  useEffect(() => {
    const fromHash = () => {
      let value = window.location.hash.replace(/^#\/?/, '');
      if (value === 'research') {
        value = 'projects';
        window.history.replaceState(null, '', '#projects');
      }
      const views = ['home', 'chat', 'agents', 'knowledge', 'projects', 'artifacts'];
      if (views.includes(value)) setActiveView(value as typeof activeView);
    };
    fromHash();
    window.addEventListener('hashchange', fromHash);
    return () => window.removeEventListener('hashchange', fromHash);
  }, [setActiveView]);

  useEffect(() => {
    if (window.location.hash.replace(/^#\/?/, '') !== activeView) {
      window.history.replaceState(null, '', `#${activeView}`);
    }
  }, [activeView]);

  // App-level commands: navigation, view toggles and global modals.
  useCommandHandlers({
    'general.palette': () => setCommandPaletteOpen(true),
    'general.shortcuts': () => setShortcutsModalOpen(true),
    'general.settings': () => {
      window.dispatchEvent(new CustomEvent('palimind:open-settings'));
    },
    'view.toggle-sidebar': toggleSidebar,
    'view.toggle-theme': () => setTheme(theme === 'dark' ? 'light' : 'dark'),
    'view.toggle-artifacts': () => {
      setArtifactPanelOpen(!artifactPanelOpen);
    },
    'view.browse-artifacts': () => setActiveView('artifacts'),
    'nav.chat': () => {
      setActiveView('chat');
      setChatMode('llm');
    },
    'nav.knowledge': () => {
      setActiveView('knowledge');
      setChatMode('document');
    },
    'nav.agents': () => setActiveView('agents'),
    'nav.home': () => setActiveView('home'),
    'nav.projects': () => setActiveView('projects'),
    'nav.artifacts': () => setActiveView('artifacts'),
    'nav.graph': () => {
      window.dispatchEvent(new CustomEvent('palimind:open-graph'));
    },
    'nav.search': () => setCommandPaletteOpen(true),
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
      setAgentsView('work');
      setAgentsWorkTab('board');
    },
  });

  // The Agents area reuses the global chat surface but is backed by the
  // selected agent's own scope (separate sessions, model and settings). A
  // project context wins for chat/knowledge so project sessions, config and
  // knowledge stay isolated. One resolver keeps every surface consistent.
  const scope = resolveScope(activeView, {
    agentId: selectedAgentId,
    projectId: activeProjectId,
  });

  useEffect(() => {
    // A late config response from a scope we already left must not overwrite
    // the model/MoE settings of the scope now on screen.
    let cancelled = false;
    async function init() {
      try {
        const fieldsData = await api.fields.list();
        if (cancelled) return;
        setActiveField(fieldsData.active_field);
        setIsIndexing(fieldsData.is_indexing);
        if (fieldsData.is_indexing) {
          setIndexingStatus(fieldsData.indexing_status || 'Indexing knowledge base...');
        }
        if (!scope) return;
        const configData = await api.config.get(scope);
        if (cancelled) return;
        if (configData.chat_model) {
          setCurrentModel(configData.chat_model);
        }
        if (configData.moe_sub_mode) {
          setLlmSubMode(configData.moe_sub_mode as 'default' | 'moe' | 'deep_research');
        }
        if (configData.moe_orchestrator_model) {
          setOrchestratorModel(configData.moe_orchestrator_model);
        }
        if (configData.moe_worker_model) {
          setWorkerModel(configData.moe_worker_model);
        }
      } catch (e) {
        if (cancelled) return;
        console.error('Init error:', e);
        window.dispatchEvent(
          new CustomEvent('palimind:connection', {
            detail: {
              ok: false,
              message:
                'The local engine is not responding. Start PaliMind, then retry.',
            },
          }),
        );
      }
    }
    init();
    return () => {
      cancelled = true;
    };
  }, [
    scope, setActiveField, setIsIndexing, setIndexingStatus, setCurrentModel,
    setLlmSubMode, setOrchestratorModel, setWorkerModel,
  ]);

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
  }, [scope, activeField, setSessions, setActiveSessionId]);

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
        <ConnectionBanner />
        <div className="view-enter" key={activeView}>
          {activeView === 'home' && <HomeView />}
          {activeView === 'chat' && <ChatArea />}
          {activeView === 'agents' && <AgentsWorkspace />}
          {activeView === 'knowledge' && <KnowledgeView />}
          {activeView === 'projects' && <ProjectsView />}
          {activeView === 'artifacts' && <ArtifactsView />}
        </div>
        <AgentManager />
        <SettingsModal />
        <DirectoryPicker />
        <KnowledgeGraph />
        <ShortcutsModal />
        <CommandPalette />
        <AgentGraph />
        <SkillManager />
        <PlanReview />
        <ResearchPlanModal />
        <TaskMonitor />
        <ToastContainer />
      </AppLayout>
    </ChatStreamProvider>
  );
}
