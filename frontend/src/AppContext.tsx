import { createContext, useContext, useState, useCallback, useRef, useEffect, type ReactNode } from 'react';
import { api } from './api';
import type { AppView, ChatMode, LlmSubMode, Theme } from './types';

interface Toast {
  id: number;
  message: string;
}

export interface AgentState {
  agent_id: number;
  label: string;
  task?: string;
  status: 'working' | 'complete';
  steps: string[];
}

interface AppState {
  activeView: AppView;
  activeField: string | null;
  activeSessionId: string | null;
  sessions: { id: string; name: string; messages: { role: string; content: string; sources?: string[] }[] }[];
  selectedFiles: Set<string>;
  chatMode: ChatMode;
  isGenerating: boolean;
  theme: Theme;
  currentModel: string;
  llmSubMode: LlmSubMode;
  orchestratorModel: string;
  workerModel: string;
  isIndexing: boolean;
  indexingStatus: string;
  toasts: Toast[];
  attachedFiles: File[];
  isRecording: boolean;
  isTranscribing: boolean;
  isSpeaking: boolean;
  thinkingText: string;
  agentStates: AgentState[];
  selectedAgentId: string | null;
}

interface AppContextType extends AppState {
  setActiveView: (view: AppView) => void;
  setActiveField: (field: string | null) => void;
  setActiveSessionId: (id: string | null) => void;
  setSessions: (sessions: AppState['sessions']) => void;
  toggleSelectedFile: (path: string) => void;
  clearSelectedFiles: () => void;
  setChatMode: (mode: ChatMode) => void;
  setIsGenerating: (v: boolean) => void;
  setTheme: (theme: Theme) => void;
  setCurrentModel: (model: string) => void;
  setLlmSubMode: (mode: LlmSubMode) => void;
  setOrchestratorModel: (model: string) => void;
  setWorkerModel: (model: string) => void;
  setIsIndexing: (v: boolean) => void;
  setIndexingStatus: (s: string) => void;
  addToast: (message: string) => void;
  setAttachedFiles: (files: File[]) => void;
  setIsRecording: (v: boolean) => void;
  setIsTranscribing: (v: boolean) => void;
  setIsSpeaking: (v: boolean) => void;
  setThinkingText: React.Dispatch<React.SetStateAction<string>>;
  setAgentStates: React.Dispatch<React.SetStateAction<AgentState[]>>;
  setSelectedAgentId: (id: string | null) => void;
  refreshFields: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  refreshFileTree: () => Promise<void>;
  abortController: AbortController | null;
  setAbortController: (c: AbortController | null) => void;
}

export const AppContext = createContext<AppContextType | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [activeView, setActiveView] = useState<AppView>('fields');
  const [activeField, setActiveField] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<AppState['sessions']>([]);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [chatMode, setChatMode] = useState<ChatMode>('document');
  const [isGenerating, setIsGenerating] = useState(false);
  const [theme, setThemeState] = useState<Theme>(() => (localStorage.getItem('theme') as Theme) || 'dark');
  const [currentModel, setCurrentModel] = useState('Loading...');
  const [llmSubMode, setLlmSubMode] = useState<LlmSubMode>('default');
  const [orchestratorModel, setOrchestratorModel] = useState('');
  const [workerModel, setWorkerModel] = useState('');
  const [isIndexing, setIsIndexing] = useState(false);
  const [indexingStatus, setIndexingStatus] = useState('');
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [thinkingText, setThinkingText] = useState('');
  const [agentStates, setAgentStates] = useState<AgentState[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [abortController, setAbortController] = useState<AbortController | null>(null);

  const toastId = useRef(0);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    localStorage.setItem('theme', t);
    if (t === 'light') {
      document.documentElement.classList.add('light-mode');
    } else {
      document.documentElement.classList.remove('light-mode');
    }
  }, []);

  const toggleSelectedFile = useCallback((path: string) => {
    setSelectedFiles(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const clearSelectedFiles = useCallback(() => {
    setSelectedFiles(new Set());
  }, []);

  const addToast = useCallback((message: string) => {
    const id = ++toastId.current;
    setToasts(prev => [...prev, { id, message }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 5000);
  }, []);

  const refreshFields = useCallback(async () => {
    try {
      const data = await api.fields.list();
      setIsIndexing(data.is_indexing);
      if (data.is_indexing) {
        setIndexingStatus(data.indexing_status || 'Indexing field...');
      }
      setActiveField(data.active_field);
    } catch (e) {
      console.error('Error fetching fields:', e);
    }
  }, []);

  const refreshSessions = useCallback(async () => {
    if (!activeField) return;
    try {
      const data = await api.sessions.list();
      if (data.error) return;
      setSessions(data.sessions);
      setActiveSessionId(data.active_session_id);
    } catch (e) {
      console.error('Error fetching sessions:', e);
    }
  }, [activeField]);

  const refreshFileTree = useCallback(async () => {
    // handled in FileTreeView component
  }, []);

  useEffect(() => {
    if (theme === 'light') {
      document.documentElement.classList.add('light-mode');
    }
  }, [theme]);

  useEffect(() => {
    const es = new EventSource('/api/events');
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === 'indexing_start') {
          setIsIndexing(true);
          setIndexingStatus(data.message || 'Indexing field...');
        } else if (data.type === 'indexing_complete' || data.type === 'indexing_error') {
          setIsIndexing(false);
          setIndexingStatus('');
        }
      } catch {}
    };
    return () => es.close();
  }, [setIsIndexing, setIndexingStatus]);

  return (
    <AppContext.Provider
      value={{
        activeView, setActiveView,
        activeField, setActiveField,
        activeSessionId, setActiveSessionId,
        sessions, setSessions,
        selectedFiles, toggleSelectedFile, clearSelectedFiles,
        chatMode, setChatMode,
        isGenerating, setIsGenerating,
        theme, setTheme,
        currentModel, setCurrentModel,
        llmSubMode, setLlmSubMode,
        orchestratorModel, setOrchestratorModel,
        workerModel, setWorkerModel,
        isIndexing, setIsIndexing,
        indexingStatus, setIndexingStatus,
        toasts, addToast,
        attachedFiles, setAttachedFiles,
        isRecording, setIsRecording,
        isTranscribing, setIsTranscribing,
        isSpeaking, setIsSpeaking,
        thinkingText, setThinkingText,
        agentStates, setAgentStates,
        selectedAgentId, setSelectedAgentId,
        refreshFields, refreshSessions, refreshFileTree,
        abortController, setAbortController,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppContextType {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}
