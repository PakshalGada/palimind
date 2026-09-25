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
import AgentManager from './features/agents/AgentManager';
import AgentHeader from './features/agents/AgentHeader';

export default function App() {
  const {
    activeView,
    selectedAgentId,
    activeField, setActiveField, setSessions, setActiveSessionId,
    setCurrentModel, setLlmSubMode, setOrchestratorModel, setWorkerModel,
    setIsIndexing, setIndexingStatus, addToast,
    isRecording, isTranscribing, isSpeaking,
  } = useApp();

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
    'app-container',
    isRecording ? 'recording' : '',
    isTranscribing ? 'transcribing' : '',
    isSpeaking ? 'speaking' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={containerClass}>
      <Sidebar />
      {activeView === "agents" ? (
        <div className="agents-main">
          <AgentHeader />
          {selectedAgentId ? (
            <ChatArea />
          ) : (
            <div className="agents-nosel">Select an agent to start chatting.</div>
          )}
        </div>
      ) : activeView === "chat" || activeField ? (
        <ChatArea />
      ) : (
        <WelcomeScreen />
      )}
      <AgentManager />
      <SettingsModal />
      <DirectoryPicker />
      <KnowledgeGraph />
      <ToastContainer />
    </div>
  );
}
