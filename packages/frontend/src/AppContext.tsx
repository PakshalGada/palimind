import { createContext, useContext, useState, useCallback, useRef, useEffect, useMemo, type ReactNode } from 'react';
import { api } from './api';
import type { AppView, AgentsView, ChatMode, CitationPayload, LlmSubMode, Overview, Approval, Theme } from './types';
import type { BotAvatarConfig } from './bots/config';
import type { ShortcutOverrides } from './utils/shortcuts';
import { loadShortcutOverrides, saveShortcutOverrides } from './utils/shortcuts';
import { useTheme } from './design/ThemeProvider';
import { resolveScope } from './lib/scope';

export type ToastTone = 'default' | 'success' | 'warning' | 'error' | 'info';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  title?: string;
  tone?: ToastTone;
  /** Auto-dismiss delay in ms. Pass 0 to keep the toast until dismissed. */
  duration?: number;
  action?: ToastAction;
}

export interface Toast {
  id: number;
  message: string;
  title?: string;
  tone?: ToastTone;
  action?: ToastAction;
  duration?: number;
}

export interface AgentState {
  agent_id: number;
  label: string;
  task?: string;
  status: 'working' | 'complete';
  steps: string[];
}

export type ActivityMode = 'llm' | 'document' | 'moe' | 'agent';
export type ActivityStatus = 'pending' | 'active' | 'done' | 'error';

export interface ActivityStep {
  id: string;
  kind: string;
  title: string;
  detail?: string;
  /** Raw tool name for tool steps, when the backend supplied one. */
  tool?: string;
  /** Compact human summary of a tool's output, set by agent:tool_result. */
  result?: string;
  startedAt?: number;
  completedAt?: number;
  status: ActivityStatus;
  children?: ActivityStep[];
}

export interface ActivityAgentAvatar {
  config?: BotAvatarConfig;
  type?: string;
  upload?: string;
}

export interface ActivityState {
  mode: ActivityMode;
  title: string;
  subtitle?: string;
  /** Avatar seed when the activity belongs to a named agent. */
  seed?: string;
  /** The named agent's exact avatar, when the activity is an agent run. */
  agentAvatar?: ActivityAgentAvatar;
  steps: ActivityStep[];
}

interface AppState {
  activeView: AppView;
  agentsView: AgentsView;
  activeField: string | null;
  activeProjectId: string | null;
  activeProjectName: string | null;
  activeSessionId: string | null;
  sessions: { id: string; name: string; created_at?: number; messages: { role: string; content: string; timestamp?: number; sources?: string[]; citations?: CitationPayload }[] }[];
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
  selectedAgentId: string | null;
  selectedTeamId: string | null;
  overview: Overview | null;
  inbox: Approval[];
  sidebarCollapsed: boolean;
  commandPaletteOpen: boolean;
  shortcutsModalOpen: boolean;
  artifactPanelOpen: boolean;
  artifactLibraryOpen: boolean;
  artifactTarget: { id: string; nonce: number } | null;
  shortcutOverrides: ShortcutOverrides;
}

interface AppContextType extends AppState {
  setActiveView: (view: AppView) => void;
  setAgentsView: (view: AgentsView) => void;
  setActiveField: (field: string | null) => void;
  setActiveProjectId: (id: string | null) => void;
  setActiveProjectName: (name: string | null) => void;
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
  addToast: (message: string, options?: ToastOptions) => void;
  dismissToast: (id: number) => void;
  setAttachedFiles: (files: File[]) => void;
  setIsRecording: (v: boolean) => void;
  setIsTranscribing: (v: boolean) => void;
  setIsSpeaking: (v: boolean) => void;
  setSelectedAgentId: (id: string | null) => void;
  setSelectedTeamId: (id: string | null) => void;
  refreshOverview: () => Promise<void>;
  refreshInbox: () => Promise<void>;
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
  setArtifactLibraryOpen: (v: boolean) => void;
  openArtifactLibrary: () => void;
  openArtifact: (id: string) => void;
  clearArtifactTarget: () => void;
  setShortcutOverride: (commandId: string, combo: string | null) => void;
  resetShortcut: (commandId: string) => void;
  resetAllShortcuts: () => void;
}

/**
 * Live run state (thinking text, activity chain, agent roster).
 *
 * These values change several times per second while a response streams. They
 * live in their own context so a token/timer tick only re-renders the activity
 * UI instead of every consumer of the app-wide context.
 */
export interface ActivityContextType {
  thinkingText: string;
  setThinkingText: React.Dispatch<React.SetStateAction<string>>;
  agentStates: AgentState[];
  setAgentStates: React.Dispatch<React.SetStateAction<AgentState[]>>;
  agentLoading: { seed: string; name: string } | null;
  setAgentLoading: (v: { seed: string; name: string } | null) => void;
  activity: ActivityState | null;
  setActivity: React.Dispatch<React.SetStateAction<ActivityState | null>>;
}

export const AppContext = createContext<AppContextType | null>(null);
export const ActivityContext = createContext<ActivityContextType | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [activeView, setActiveView] = useState<AppView>(() => {
    // Deep link wins over the default so a reload keeps the current view and
    // there is no flash of Home before the hash effect runs.
    if (typeof window === 'undefined') return 'home';
    const value = window.location.hash.replace(/^#\/?/, '');
    const views = ['home', 'chat', 'agents', 'knowledge', 'projects', 'artifacts'];
    return views.includes(value) ? (value as AppView) : 'home';
  });
  const [agentsView, setAgentsView] = useState<AgentsView>('home');
  const [activeField, setActiveField] = useState<string | null>(null);
  const [activeProjectId, setActiveProjectIdState] = useState<string | null>(
    () => localStorage.getItem('palimind:active-project'),
  );
  const [activeProjectName, setActiveProjectNameState] = useState<string | null>(
    () => localStorage.getItem('palimind:active-project-name'),
  );
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<AppState['sessions']>([]);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [chatMode, setChatMode] = useState<ChatMode>('llm');
  const [isGenerating, setIsGenerating] = useState(false);
  const { theme, setTheme } = useTheme();
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
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [inbox, setInbox] = useState<Approval[]>([]);
  const [agentLoading, setAgentLoading] = useState<{ seed: string; name: string } | null>(null);
  const [activity, setActivity] = useState<ActivityState | null>(null);
  const [abortController, setAbortController] = useState<AbortController | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches,
  );
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [shortcutsModalOpen, setShortcutsModalOpen] = useState(false);
  const [artifactPanelOpen, setArtifactPanelOpen] = useState(false);
  const [artifactLibraryOpen, setArtifactLibraryOpen] = useState(false);
  const [artifactTarget, setArtifactTarget] = useState<{ id: string; nonce: number } | null>(null);
  const artifactNonce = useRef(0);
  const [shortcutOverrides, setShortcutOverridesState] = useState<ShortcutOverrides>(() => loadShortcutOverrides());

  const toastId = useRef(0);
  const lastToastRef = useRef<{ message: string; at: number } | null>(null);

  const toggleSidebar = useCallback(() => setSidebarCollapsed((v) => !v), []);

  const setActiveProjectId = useCallback((id: string | null) => {
    setActiveProjectIdState(id);
    try {
      if (id) localStorage.setItem('palimind:active-project', id);
      else localStorage.removeItem('palimind:active-project');
    } catch {
      // ignore unavailable storage
    }
  }, []);

  const setActiveProjectName = useCallback((name: string | null) => {
    setActiveProjectNameState(name);
    try {
      if (name) localStorage.setItem('palimind:active-project-name', name);
      else localStorage.removeItem('palimind:active-project-name');
    } catch {
      // ignore unavailable storage
    }
  }, []);

  const openArtifactLibrary = useCallback(() => {
    setArtifactPanelOpen(true);
    setArtifactLibraryOpen(true);
  }, []);

  const openArtifact = useCallback((id: string) => {
    artifactNonce.current += 1;
    setArtifactTarget({ id, nonce: artifactNonce.current });
    setArtifactLibraryOpen(false);
    setArtifactPanelOpen(true);
  }, []);

  const clearArtifactTarget = useCallback(() => setArtifactTarget(null), []);

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

  const addToast = useCallback((message: string, options: ToastOptions = {}) => {
    const now = Date.now();
    // Repeated failures (one per request) should not stack five identical
    // notifications. The connection banner owns persistent errors.
    if (
      lastToastRef.current &&
      lastToastRef.current.message === message &&
      now - lastToastRef.current.at < 3000
    ) {
      return;
    }
    lastToastRef.current = { message, at: now };
    const id = ++toastId.current;
    const duration = options.duration ?? (options.action ? 8000 : 5000);
    const toast: Toast = {
      id,
      message,
      title: options.title,
      tone: options.tone,
      action: options.action,
      duration,
    };
    // Keep the stack short so notifications never cover the workspace.
    setToasts(prev => [...prev.slice(-4), toast]);
    if (duration > 0) {
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id));
      }, duration);
    }
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
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

  // One canonical scope per view, matching the scope App loads sessions for.
  // The Agents view is deliberately empty when no agent is selected — it must
  // never fall back to global/field chat.
  const sessionScope = resolveScope(activeView, {
    agentId: selectedAgentId,
    projectId: activeProjectId,
  });

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

  const refreshOverview = useCallback(async () => {
    try {
      const data = await api.agents.overview();
      setOverview(data);
      setInbox(data.inbox || []);
    } catch {
      // best effort
    }
  }, []);

  const refreshInbox = useCallback(async () => {
    try {
      const data = await api.agents.inbox();
      setInbox(data.approvals || []);
    } catch {
      // best effort
    }
  }, []);

  useEffect(() => {
    const es = new EventSource('/api/events', { withCredentials: true });
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

  // Memoize the context value to prevent unnecessary re-renders of all consumers
  const contextValue = useMemo(() => ({
    activeView, setActiveView,
    agentsView, setAgentsView,
    activeField, setActiveField,
    activeProjectId, setActiveProjectId,
    activeProjectName, setActiveProjectName,
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
    toasts, addToast, dismissToast,
    attachedFiles, setAttachedFiles,
    isRecording, setIsRecording,
    isTranscribing, setIsTranscribing,
    isSpeaking, setIsSpeaking,
    selectedAgentId, setSelectedAgentId,
    selectedTeamId, setSelectedTeamId,
    overview, inbox, refreshOverview, refreshInbox,
    refreshFields, refreshSessions, refreshFileTree,
    abortController, setAbortController,
    sidebarCollapsed, setSidebarCollapsed, toggleSidebar,
    commandPaletteOpen, setCommandPaletteOpen,
    shortcutsModalOpen, setShortcutsModalOpen,
    artifactPanelOpen, setArtifactPanelOpen,
    artifactLibraryOpen, setArtifactLibraryOpen, artifactTarget,
    openArtifactLibrary, openArtifact, clearArtifactTarget,
    shortcutOverrides, setShortcutOverride, resetShortcut, resetAllShortcuts,
  }), [
    activeView, agentsView, activeField, activeProjectId, activeProjectName, activeSessionId, sessions, selectedFiles,
    chatMode, isGenerating, theme, currentModel, llmSubMode,
    orchestratorModel, workerModel, isIndexing, indexingStatus,
    toasts, dismissToast, attachedFiles, isRecording, isTranscribing, isSpeaking,
    selectedAgentId, abortController,
    selectedTeamId, overview, inbox, refreshOverview, refreshInbox,
    sidebarCollapsed, commandPaletteOpen, shortcutsModalOpen,
    artifactPanelOpen, artifactLibraryOpen, artifactTarget, shortcutOverrides,
    toggleSidebar, setShortcutOverride, resetShortcut, resetAllShortcuts,
    openArtifactLibrary, openArtifact, clearArtifactTarget,
    setActiveProjectId, setActiveProjectName, setTheme, refreshFields, addToast, clearSelectedFiles,
    refreshFileTree, refreshSessions, toggleSelectedFile,
  ]);

  const activityValue = useMemo<ActivityContextType>(() => ({
    thinkingText, setThinkingText,
    agentStates, setAgentStates,
    agentLoading, setAgentLoading,
    activity, setActivity,
  }), [thinkingText, agentStates, agentLoading, activity]);

  return (
    <AppContext.Provider value={contextValue}>
      <ActivityContext.Provider value={activityValue}>
        {children}
      </ActivityContext.Provider>
    </AppContext.Provider>
  );
}

export function useApp(): AppContextType {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
}

export function useActivity(): ActivityContextType {
  const ctx = useContext(ActivityContext);
  if (!ctx) throw new Error('useActivity must be used within AppProvider');
  return ctx;
}
