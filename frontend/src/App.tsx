import { useEffect } from 'react';
import { useApp } from './AppContext';
import { api } from './api';
import Sidebar from './components/Sidebar';
import WelcomeScreen from './components/WelcomeScreen';
import ChatArea from './components/ChatArea';
import PaliVisionWorkspace from './components/PaliVisionWorkspace';
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
      try {
        const [fieldsData, configData] = await Promise.all([
          api.fields.list(),
          api.config.get(),
        ]);
        setActiveField(fieldsData.active_field);
        setIsIndexing(fieldsData.is_indexing);
        if (fieldsData.is_indexing) {
          setIndexingStatus(fieldsData.indexing_status || 'Indexing field...');
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
  }, []);

  useEffect(() => {
    if (!activeField) {
      setSessions([]);
      setActiveSessionId(null);
      return;
    }
    api.sessions.list().then(data => {
      if (!data.error) {
        setSessions(data.sessions);
        setActiveSessionId(data.active_session_id);
      }
    }).catch(() => {});
  }, [activeField]);

  const containerClass = [
    'app-container',
    isRecording ? 'recording' : '',
    isTranscribing ? 'transcribing' : '',
    isSpeaking ? 'speaking' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={containerClass}>
      <Sidebar />
      {activeView === "palivision" ? (
        <PaliVisionWorkspace />
      ) : activeView === "agents" ? (
        <Agents />
      ) : activeField ? (
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
