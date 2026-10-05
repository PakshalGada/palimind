import { createContext, useContext, useState, useCallback, useRef, useEffect, useMemo, type ReactNode } from 'react';
import { api } from './api';
import type { AppView, ChatMode, LlmSubMode, SetupTask, Theme } from './types';
import type { ShortcutOverrides } from './utils/shortcuts';
import { loadShortcutOverrides, saveShortcutOverrides } from './utils/shortcuts';

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

export type ActivityMode = 'llm' | 'document' | 'moe' | 'deep_research' | 'agent';
export type ActivityStatus = 'pending' | 'active' | 'done' | 'error';

export interface ActivityStep {
  id: string;
  kind: string;
  title: string;
  detail?: string;
  status: ActivityStatus;
  children?: ActivityStep[];
}

export interface ActivityState {
  mode: ActivityMode;
  title: string;
  subtitle?: string;
  /** Avatar seed when the activity belongs to a named agent. */
  seed?: string;
  steps: ActivityStep[];
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
  agentLoading: { seed: string; name: string } | null;
  activity: ActivityState | null;
  setupTasks: SetupTask[];
  sidebarCollapsed: boolean;
  commandPaletteOpen: boolean;
  shortcutsModalOpen: boolean;
  artifactPanelOpen: boolean;
  canvasOpen: boolean;
  canvasEnabled: boolean;
  shortcutOverrides: ShortcutOverrides;
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
  setAgentLoading: (v: { seed: string; name: string } | null) => void;
  setActivity: React.Dispatch<React.SetStateAction<ActivityState | null>>;
  refreshFields: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  refreshFileTree: () => Promise<void>;
  abortController: AbortController | null;
  setAbortController: (c: AbortController | null) => void;
  setSidebarCollapsed: (v: boolean) => void;
  toggleSidebar: () => void;
  setCommandPaletteOpen: (v: boolean) => void;
  setShortcutsModalOpen: (v: boolean) => void;
  setArtifactPanelOpen: (v: boolean) => void;
  setCanvasOpen: (v: boolean) => void;
  setCanvasEnabled: (v: boolean) => void;
  setShortcutOverride: (commandId: string, combo: string | null) => void;
  resetShortcut: (commandId: string) => void;
  resetAllShortcuts: () => void;
}

export const AppContext = createContext<AppContextType | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [activeView, setActiveView] = useState<AppView>('chat');
  const [activeField, setActiveField] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<AppState['sessions']>([]);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [chatMode, setChatMode] = useState<ChatMode>('llm');
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
  const [agentLoading, setAgentLoading] = useState<{ seed: string; name: string } | null>(null);
  const [activity, setActivity] = useState<ActivityState | null>(null);
  const [setupTasks, setSetupTasks] = useState<SetupTask[]>([]);
  const [abortController, setAbortController] = useState<AbortController | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [shortcutsModalOpen, setShortcutsModalOpen] = useState(false);
  const [artifactPanelOpen, setArtifactPanelOpen] = useState(false);
  const [canvasOpen, setCanvasOpen] = useState(false);
  const [canvasEnabled, setCanvasEnabledState] = useState<boolean>(
    () => localStorage.getItem('palimind:canvas-enabled') !== 'false',
  );
  const [shortcutOverrides, setShortcutOverridesState] = useState<ShortcutOverrides>(() => loadShortcutOverrides());

  const toastId = useRef(0);

  const toggleSidebar = useCallback(() => setSidebarCollapsed((v) => !v), []);

  const setCanvasEnabled = useCallback((value: boolean) => {
    setCanvasEnabledState(value);
    try {
      localStorage.setItem('palimind:canvas-enabled', value ? 'true' : 'false');
    } catch {
      // ignore
    }
    if (!value) setCanvasOpen(false);
  }, []);

  const setShortcutOverride = useCallback((commandId: string, combo: string | null) => {
    setShortcutOverridesState((prev) => {
      const next = { ...prev };
      if (combo) next[commandId] = combo;
      else delete next[commandId];
      saveShortcutOverrides(next);
      return next;
    });
  }, []);

  const resetShortcut = useCallback((commandId: string) => {
    setShortcutOverridesState((prev) => {
      if (!(commandId in prev)) return prev;
      const next = { ...prev };
      delete next[commandId];
      saveShortcutOverrides(next);
      return next;
    });
  }, []);

  const resetAllShortcuts = useCallback(() => {
    saveShortcutOverrides({});
    setShortcutOverridesState({});
  }, []);

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
        setIndexingStatus(data.indexing_status || 'Indexing knowledge base...');
      }
      setActiveField(data.active_field);
    } catch (e) {
      console.error('Error fetching fields:', e);
    }
  }, []);

  // One canonical scope per view. The Agents view is deliberately empty when
  // no agent is selected — it must never fall back to global/field chat.
  const sessionScope =
    activeView === 'agents'
      ? selectedAgentId
        ? `agent:${selectedAgentId}`
        : ''
      : activeView === 'chat'
        ? 'chat'
        : 'field';

  const sessionScopeRef = useRef(sessionScope);
  useEffect(() => {
    sessionScopeRef.current = sessionScope;
  }, [sessionScope]);

  const refreshSessions = useCallback(async () => {
    const requested = sessionScope;
    if (!requested) {
      setSessions([]);
      setActiveSessionId(null);
      return;
    }
    if (requested === 'field' && !activeField) {
      setSessions([]);
      setActiveSessionId(null);
      return;
    }
    try {
      const data = await api.sessions.list(requested);
      // Ignore a late response from a scope we have since left.
      if (data.error || sessionScopeRef.current !== requested) return;
      setSessions(data.sessions);
      setActiveSessionId(data.active_session_id);
    } catch (e) {
      console.error('Error fetching sessions:', e);
    }
  }, [activeField, sessionScope]);

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
          setIndexingStatus(data.message || 'Indexing knowledge base...');
        } else if (data.type === 'indexing_complete' || data.type === 'indexing_error') {
          setIsIndexing(false);
          setIndexingStatus('');
        }
      } catch {}
    };
    return () => es.close();
  }, [setIsIndexing, setIndexingStatus]);

  // Poll first-run model download/load status so the user sees progress even
  // though the backend's stdout/stderr are detached in the packaged app.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await api.setup.status();
        if (!cancelled) setSetupTasks(data.tasks || []);
      } catch {
        // backend not ready yet — ignore
      }
    };
    void tick();
    const timer = window.setInterval(tick, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  // Memoize the context value to prevent unnecessary re-renders of all consumers
  const contextValue = useMemo(() => ({
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
    agentLoading, setAgentLoading,
    activity, setActivity,
    setupTasks,
    refreshFields, refreshSessions, refreshFileTree,
    abortController, setAbortController,
    sidebarCollapsed, setSidebarCollapsed, toggleSidebar,
    commandPaletteOpen, setCommandPaletteOpen,
    shortcutsModalOpen, setShortcutsModalOpen,
    artifactPanelOpen, setArtifactPanelOpen,
    canvasOpen, setCanvasOpen, canvasEnabled, setCanvasEnabled,
    shortcutOverrides, setShortcutOverride, resetShortcut, resetAllShortcuts,
  }), [
    activeView, activeField, activeSessionId, sessions, selectedFiles,
    chatMode, isGenerating, theme, currentModel, llmSubMode,
    orchestratorModel, workerModel, isIndexing, indexingStatus,
    toasts, attachedFiles, isRecording, isTranscribing, isSpeaking,
    thinkingText, agentStates, selectedAgentId, agentLoading,
    activity, setupTasks, abortController,
    sidebarCollapsed, commandPaletteOpen, shortcutsModalOpen,
    artifactPanelOpen, canvasOpen, canvasEnabled, shortcutOverrides,
    toggleSidebar, setShortcutOverride, resetShortcut, resetAllShortcuts,
  ]);

  return (
    <AppContext.Provider value={contextValue}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppContextType {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}
