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
import Agents from './views/Agents';

export default function App() {
  const {
    activeView,
    activeField, setActiveField, setSessions, setActiveSessionId,
    setCurrentModel, setLlmSubMode, setOrchestratorModel, setWorkerModel,
    setIsIndexing, setIndexingStatus, addToast,
    isRecording, isTranscribing, isSpeaking,
  } = useApp();

  useEffect(() => {
    async function init() {
      const scope = activeView === 'chat' ? 'chat' : 'field';
      try {
        const [fieldsData, configData] = await Promise.all([
          api.fields.list(),
          api.config.get(scope),
        ]);
        setActiveField(fieldsData.active_field);
        setIsIndexing(fieldsData.is_indexing);
        if (fieldsData.is_indexing) {
          setIndexingStatus(fieldsData.indexing_status || 'Indexing knowledge base...');
        }
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
  }, [activeView]);

  useEffect(() => {
    if (activeView === 'chat') {
      api.sessions.list('chat').then(data => {
        if (!data.error) {
          setSessions(data.sessions);
          setActiveSessionId(data.active_session_id);
        }
      }).catch(() => {});
      return;
    }
    if (!activeField) {
      setSessions([]);
      setActiveSessionId(null);
      return;
    }
    api.sessions.list('field').then(data => {
      if (!data.error) {
        setSessions(data.sessions);
        setActiveSessionId(data.active_session_id);
      }
    }).catch(() => {});
  }, [activeField, activeView]);

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
        <Agents />
      ) : activeView === "chat" || activeField ? (
        <ChatArea />
      ) : (
        <WelcomeScreen />
      )}
      <SettingsModal />
      <DirectoryPicker />
      <KnowledgeGraph />
      <ToastContainer />
    </div>
  );
}
