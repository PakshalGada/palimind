import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { Code2, Package } from 'lucide-react';
import { useApp } from '../AppContext';
import { useChatStreamContext } from '../stream/context';
import type { StreamState } from '../stream/types';
import { EmptyState } from '../ui/primitives';
import type { Artifact, ArtifactSource } from '../utils/artifacts';
import ArtifactLibrary, { type OpenedArtifact } from './ArtifactLibrary';
import ArtifactPanelHeader from './artifact/ArtifactPanelHeader';
import ArtifactProjectDialog from './artifact/ArtifactProjectDialog';
import ArtifactPreview from './artifact/ArtifactPreview';
import ArtifactTabs from './artifact/ArtifactTabs';
import ArtifactToolbar from './artifact/ArtifactToolbar';
import ArtifactVersionDialog from './artifact/ArtifactVersionDialog';
import ArtifactEditor from './artifact/ArtifactEditor';
import { sourceLanguage } from './artifact/languages';
import type { ActiveArtifact, ViewMode } from './artifact/types';
import { useArtifactExport } from './artifact/useArtifactExport';
import { useArtifactProjects } from './artifact/useArtifactProjects';
import { useArtifactVault } from './artifact/useArtifactVault';
import { useLiveArtifacts } from './artifact/useLiveArtifacts';
import './ArtifactPanel.css';

function toActive(artifact: Artifact | OpenedArtifact): ActiveArtifact {
  return {
    id: artifact.id,
    type: artifact.type,
    language: artifact.language,
    title: artifact.title,
    content: artifact.content,
    messageIndex: 'messageIndex' in artifact ? artifact.messageIndex : undefined,
    projectId: 'projectId' in artifact ? artifact.projectId : undefined,
    source: 'source' in artifact ? artifact.source : undefined,
    filePaths: 'filePaths' in artifact ? artifact.filePaths : undefined,
    files: 'files' in artifact ? artifact.files : undefined,
    streaming: 'streaming' in artifact ? artifact.streaming : undefined,
    closed: 'closed' in artifact ? artifact.closed : undefined,
  };
}

const SPLIT_KEY = 'palimind:artifact-editor-split';
const PANEL_WIDTH_KEY = 'palimind:artifact-panel-width';
const PANEL_MIN_WIDTH = 380;
const PANEL_MAX_WIDTH = 980;
const PANEL_DEFAULT_WIDTH = 600;

function clampPanelWidth(width: number): number {
  const viewportMax = Math.max(
    PANEL_MIN_WIDTH,
    Math.min(PANEL_MAX_WIDTH, window.innerWidth - 420),
  );
  return Math.min(Math.max(width, PANEL_MIN_WIDTH), viewportMax);
}

function initialPanelWidth(): number {
  try {
    const stored = Number(window.localStorage.getItem(PANEL_WIDTH_KEY));
    if (Number.isFinite(stored) && stored > 0) return clampPanelWidth(stored);
  } catch {
    // localStorage may be unavailable
  }
  return PANEL_DEFAULT_WIDTH;
}

function initialSplit(): number {
  try {
    const stored = Number(window.localStorage.getItem(SPLIT_KEY));
    if (Number.isFinite(stored) && stored >= 25 && stored <= 75) return stored;
  } catch {
    // localStorage may be unavailable
  }
  return 48;
}

interface ArtifactFeed {
  artifacts: Artifact[];
  status: StreamState['status'];
}

/**
 * Subscribes to the live stream and publishes artifacts on the throttled
 * cadence used by `useLiveArtifacts`.
 *
 * The panel itself must not consume `ChatStreamContext`: that value changes on
 * every token and every reasoning chunk, which would re-render the entire
 * panel (tabs, toolbar, preview, editor) many times per second. This tiny
 * component can re-render freely because it returns nothing.
 */
function LiveArtifactFeed({
  messages,
  onChange,
}: {
  messages: ArtifactSource[] | undefined;
  onChange: (feed: ArtifactFeed) => void;
}) {
  const { liveText, state } = useChatStreamContext();
  const artifacts = useLiveArtifacts({
    messages,
    liveText,
    streaming: state.status !== 'idle',
  });
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    onChangeRef.current({ artifacts, status: state.status });
  }, [artifacts, state.status]);

  return null;
}

function isEditableElement(element: Element | null): boolean {
  if (!(element instanceof HTMLElement)) return false;
  const tag = element.tagName;
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    element.isContentEditable
  );
}

/**
 * `forceVisible` keeps the panel mounted while its exit animation plays
 * (SidePanel sets it during the closing phase) even though the app context
 * already reports the panel as closed.
 */
export default function ArtifactPanel({
  forceVisible = false,
}: {
  forceVisible?: boolean;
}) {
  const {
    artifactPanelOpen,
    setArtifactPanelOpen,
    artifactLibraryOpen,
    setArtifactLibraryOpen,
    openArtifactLibrary,
    artifactTarget,
    clearArtifactTarget,
    sessions,
    activeSessionId,
    activeProjectId,
    setActiveProjectId,
    addToast,
  } = useApp();

  const messages = useMemo(
    () => sessions.find(session => session.id === activeSessionId)?.messages,
    [sessions, activeSessionId],
  );

  const [artifactFeed, setArtifactFeed] = useState<ArtifactFeed>({
    artifacts: [],
    status: 'idle',
  });
  const { artifacts: sessionArtifacts, status: streamStatus } = artifactFeed;

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [external, setExternal] = useState<ActiveArtifact | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('preview');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [newIds, setNewIds] = useState<Set<string>>(() => new Set());
  const [splitPercent, setSplitPercent] = useState(initialSplit);
  const [panelWidth, setPanelWidth] = useState(initialPanelWidth);

  const panelRef = useRef<HTMLElement>(null);
  const previewScrollRef = useRef<HTMLDivElement>(null);
  const pendingScrollRef = useRef<number | null>(null);
  const splitContainerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  const panelDraggingRef = useRef(false);
  const panelDragStartXRef = useRef(0);
  const panelDragStartWidthRef = useRef(panelWidth);
  const previousIdsRef = useRef<Set<string>>(new Set());
  const previousSessionRef = useRef(activeSessionId);
  const newIdsReadyRef = useRef(false);

  const selectedSessionArtifact = useMemo(() => {
    if (sessionArtifacts.length === 0) return null;
    return (
      sessionArtifacts.find(artifact => artifact.id === selectedId) ??
      sessionArtifacts[0]
    );
  }, [sessionArtifacts, selectedId]);

  const active = useMemo<ActiveArtifact | null>(() => {
    if (external) return external;
    return selectedSessionArtifact ? toActive(selectedSessionArtifact) : null;
  }, [external, selectedSessionArtifact]);

  const activeId = active?.id ?? '';
  const content = active ? (edits[activeId] ?? active.content) : '';
  const streaming = sessionArtifacts.some(artifact => artifact.streaming);

  const {
    saved,
    save: saveToVaultNow,
    saveDraft,
    saveDraftFor,
    restore,
    refresh: refreshVault,
    projectArtifact,
    projectLoading,
    refreshProject,
    restoreProjectVersion,
    getLocalVersionContent,
    getProjectVersionContent,
  } = useArtifactVault({
    active,
    content,
    panelOpen: artifactPanelOpen,
    activeProjectId,
    activeSessionId,
    addToast,
    applyContent: (artifactId, next) => {
      setEdits(prev => ({ ...prev, [artifactId]: next }));
    },
  });

  const {
    exporting,
    copy,
    download,
    share,
    openInNewTab,
    exportAs,
    saveToKnowledge,
  } = useArtifactExport({ active, content, activeProjectId, addToast });

  const {
    projects,
    pickerOpen,
    setPickerOpen,
    newProjectName,
    setNewProjectName,
    creatingProject,
    pinBusy,
    openPicker,
    createProject,
    pinToProject,
  } = useArtifactProjects({
    active,
    content,
    activeProjectId,
    activeSessionId,
    setActiveProjectId,
    addToast,
  });

  const baselineContent = saved?.content ?? active?.content ?? '';
  const dirty = Boolean(active) && content !== baselineContent;

  // Keep the latest values available to unmount/switch-time autosave without
  // re-registering handlers on every render.
  const activeRef = useRef(active);
  const dirtyRef = useRef(dirty);
  const saveDraftRef = useRef(saveDraft);
  const saveDraftForRef = useRef(saveDraftFor);
  activeRef.current = active;
  dirtyRef.current = dirty;
  saveDraftRef.current = saveDraft;
  saveDraftForRef.current = saveDraftFor;

  const autosave = useCallback(() => {
    if (dirtyRef.current && activeRef.current) {
      void saveDraftRef.current('Autosaved before closing');
    }
  }, []);

  const previousSnapshotRef = useRef<{
    id: string;
    artifact: ActiveArtifact;
    content: string;
    dirty: boolean;
  } | null>(null);

  // Flush the artifact we are leaving before switching tabs.
  useLayoutEffect(() => {
    const previous = previousSnapshotRef.current;
    if (previous && previous.id !== activeId && previous.dirty) {
      void saveDraftForRef.current(
        previous.artifact,
        previous.content,
        'Autosaved before switching artifacts',
      );
    }
  }, [activeId]);

  // Snapshot for the switch handler above. Runs after the layout effect so the
  // previous snapshot is still readable when the active id changes.
  useEffect(() => {
    previousSnapshotRef.current = activeRef.current
      ? {
          id: activeId,
          artifact: activeRef.current,
          content,
          dirty,
        }
      : null;
  });

  useEffect(() => () => autosave(), [autosave]);

  const wasOpenRef = useRef(artifactPanelOpen);
  useEffect(() => {
    const wasOpen = wasOpenRef.current;
    wasOpenRef.current = artifactPanelOpen;
    if (wasOpen && !artifactPanelOpen) autosave();
  }, [artifactPanelOpen, autosave]);

  // Reset transient state when switching artifacts.
  useEffect(() => {
    setEditing(false);
    setViewMode('preview');
  }, [activeId]);

  // Entering edit mode freezes the current content in the editor draft, so a
  // still-streaming artifact cannot overwrite what the user is typing.
  useEffect(() => {
    if (!editing || !activeId || !activeRef.current?.streaming) return;
    setEdits(prev => {
      if (prev[activeId] !== undefined) return prev;
      const current = activeRef.current?.content ?? '';
      return { ...prev, [activeId]: current };
    });
  }, [editing, activeId]);

  // Keep the selected tab valid as artifacts stream in.
  useEffect(() => {
    if (external) return;
    if (sessionArtifacts.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !sessionArtifacts.some(artifact => artifact.id === selectedId)) {
      setSelectedId(sessionArtifacts[sessionArtifacts.length - 1].id);
    }
  }, [external, sessionArtifacts, selectedId]);

  // Restore a saved draft when reopening, unless the editor already has newer
  // content for this artifact.
  useEffect(() => {
    if (!activeId || !saved) return;
    setEdits(prev => {
      if (prev[activeId] !== undefined) return prev;
      if (saved.content === activeRef.current?.content) return prev;
      return { ...prev, [activeId]: saved.content };
    });
  }, [activeId, saved]);

  // Sidebar / command palette can request the library.
  useEffect(() => {
    const handler = () => openArtifactLibrary();
    window.addEventListener('palimind:open-artifact-library', handler);
    window.addEventListener('palimind:open-artifact-vault', handler);
    return () => {
      window.removeEventListener('palimind:open-artifact-library', handler);
      window.removeEventListener('palimind:open-artifact-vault', handler);
    };
  }, [openArtifactLibrary]);

  // A chat block asked to open a specific artifact.
  useEffect(() => {
    if (!artifactTarget) return;
    setExternal(null);
    setSelectedId(artifactTarget.id);
    clearArtifactTarget();
  }, [artifactTarget, clearArtifactTarget]);

  // Mark artifacts that appear while streaming.
  useEffect(() => {
    const ids = new Set(sessionArtifacts.map(artifact => artifact.id));
    const sessionChanged = previousSessionRef.current !== activeSessionId;

    if (!newIdsReadyRef.current || sessionChanged) {
      newIdsReadyRef.current = true;
      previousSessionRef.current = activeSessionId;
      previousIdsRef.current = ids;
      const latest = sessionArtifacts[sessionArtifacts.length - 1];
      setNewIds(
        !external && streamStatus === 'streaming' && latest
          ? new Set([latest.id])
          : new Set(),
      );
      return;
    }

    if (streamStatus === 'streaming' && !external) {
      const added = [...ids].filter(id => !previousIdsRef.current.has(id));
      if (added.length > 0) {
        setNewIds(prev => {
          const next = new Set(prev);
          for (const id of added) next.add(id);
          return next;
        });
      }
    }
    previousIdsRef.current = ids;
  }, [activeSessionId, external, sessionArtifacts, streamStatus]);

  // Fade the "new" dots once the stream settles.
  useEffect(() => {
    if (streamStatus === 'streaming' || newIds.size === 0) return;
    const timer = window.setTimeout(() => setNewIds(new Set()), 2500);
    return () => window.clearTimeout(timer);
  }, [newIds, streamStatus]);

  // Focus the panel on open, but never steal focus from the composer.
  useEffect(() => {
    if (!artifactPanelOpen) return;
    if (isEditableElement(document.activeElement)) return;
    panelRef.current?.focus({ preventScroll: true });
  }, [artifactPanelOpen]);

  // Restore preview scroll across edit-mode toggles.
  useLayoutEffect(() => {
    if (pendingScrollRef.current === null) return;
    const scrollTop = pendingScrollRef.current;
    pendingScrollRef.current = null;
    if (previewScrollRef.current) previewScrollRef.current.scrollTop = scrollTop;
  }, [editing]);

  const updateContent = useCallback(
    (next: string) => {
      if (!activeId) return;
      setEdits(prev => ({ ...prev, [activeId]: next }));
    },
    [activeId],
  );

  const selectSessionArtifact = useCallback((id: string) => {
    setExternal(null);
    setSelectedId(id);
    setNewIds(prev => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const toggleEditing = useCallback(() => {
    pendingScrollRef.current = previewScrollRef.current?.scrollTop ?? null;
    setEditing(value => !value);
  }, []);

  // Keyboard shortcuts. Registered once per open (not on every render).
  const shortcutsRef = useRef({ editing, toggleEditing, saveToVaultNow, copy });
  shortcutsRef.current = { editing, toggleEditing, saveToVaultNow, copy };
  const hasActive = Boolean(active);

  useEffect(() => {
    if (!artifactPanelOpen || !hasActive) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const target = document.activeElement;
      const focusInPanel = Boolean(panelRef.current?.contains(target));
      const focusIsNeutral =
        !target || target === document.body || target === document.documentElement;
      if (!focusInPanel && !focusIsNeutral) return;

      const current = shortcutsRef.current;
      if (event.key === 'Escape' && current.editing) {
        event.preventDefault();
        event.stopImmediatePropagation();
        current.toggleEditing();
        return;
      }

      if (!(event.metaKey || event.ctrlKey)) return;
      const key = event.key.toLowerCase();
      if (key === 's') {
        event.preventDefault();
        event.stopImmediatePropagation();
        void current.saveToVaultNow();
        return;
      }
      if (key === 'e') {
        event.preventDefault();
        event.stopImmediatePropagation();
        current.toggleEditing();
        return;
      }
      if (event.shiftKey && key === 'c') {
        if (window.getSelection()?.toString()) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        current.copy();
      }
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [artifactPanelOpen, hasActive]);

  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    draggingRef.current = true;
    document.body.classList.add('is-resizing-artifact');
  };

  const startPanelResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    panelDraggingRef.current = true;
    panelDragStartXRef.current = event.clientX;
    panelDragStartWidthRef.current = panelWidth;
    document.body.classList.add('is-resizing-artifact-panel');
  };

  const movePanelResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!panelDraggingRef.current) return;
    const next =
      panelDragStartWidthRef.current + (panelDragStartXRef.current - event.clientX);
    setPanelWidth(clampPanelWidth(next));
  };

  const endPanelResize = () => {
    if (!panelDraggingRef.current) return;
    panelDraggingRef.current = false;
    document.body.classList.remove('is-resizing-artifact-panel');
    try {
      window.localStorage.setItem(PANEL_WIDTH_KEY, String(panelWidth));
    } catch {
      // ignore unavailable storage
    }
  };

  const nudgePanelWidth = (delta: number) => {
    setPanelWidth(value => {
      const next = clampPanelWidth(value + delta);
      try {
        window.localStorage.setItem(PANEL_WIDTH_KEY, String(next));
      } catch {
        // ignore unavailable storage
      }
      return next;
    });
  };

  const resetPanelWidth = () => {
    const next = clampPanelWidth(PANEL_DEFAULT_WIDTH);
    setPanelWidth(next);
    try {
      window.localStorage.setItem(PANEL_WIDTH_KEY, String(next));
    } catch {
      // ignore unavailable storage
    }
  };

  const moveResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return;
    const container = splitContainerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    if (rect.width === 0) return;
    const percent = ((event.clientX - rect.left) / rect.width) * 100;
    setSplitPercent(Math.max(25, Math.min(75, percent)));
  };

  const endResize = () => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    document.body.classList.remove('is-resizing-artifact');
    try {
      window.localStorage.setItem(SPLIT_KEY, String(splitPercent));
    } catch {
      // ignore unavailable storage
    }
  };

  const nudgeSplit = (delta: number) => {
    setSplitPercent(value => {
      const next = Math.max(25, Math.min(75, value + delta));
      try {
        window.localStorage.setItem(SPLIT_KEY, String(next));
      } catch {
        // ignore unavailable storage
      }
      return next;
    });
  };

  const resetSplit = () => {
    setSplitPercent(48);
    try {
      window.localStorage.setItem(SPLIT_KEY, '48');
    } catch {
      // ignore unavailable storage
    }
  };

  if (!artifactPanelOpen && !artifactLibraryOpen && !forceVisible) return null;

  return (
    <aside
      className="artifact-panel artp"
      aria-label="Artifacts panel"
      aria-busy={streaming}
      tabIndex={-1}
      ref={panelRef}
      style={{ width: panelWidth }}
    >
      <LiveArtifactFeed messages={messages} onChange={setArtifactFeed} />
      <div
        className="artp-resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize artifacts panel"
        aria-valuemin={PANEL_MIN_WIDTH}
        aria-valuemax={PANEL_MAX_WIDTH}
        aria-valuenow={Math.round(panelWidth)}
        tabIndex={0}
        onPointerDown={startPanelResize}
        onPointerMove={movePanelResize}
        onPointerUp={endPanelResize}
        onPointerCancel={endPanelResize}
        onDoubleClick={resetPanelWidth}
        title="Drag to resize · double-click to reset"
        onKeyDown={event => {
          if (event.key === 'ArrowLeft') {
            event.preventDefault();
            nudgePanelWidth(30);
          } else if (event.key === 'ArrowRight') {
            event.preventDefault();
            nudgePanelWidth(-30);
          }
        }}
      >
        <span className="artp-resizer-grip" aria-hidden="true" />
      </div>

      <ArtifactPanelHeader
        count={external ? 0 : sessionArtifacts.length}
        external={Boolean(external)}
        streaming={streaming}
        onBack={() => setExternal(null)}
        onOpenLibrary={() => setArtifactLibraryOpen(true)}
        onClose={() => {
          setArtifactLibraryOpen(false);
          setArtifactPanelOpen(false);
        }}
      />

      {!active ? (
        <div className="artp-empty">
          <EmptyState
            icon={<Code2 size={22} />}
            title="No artifacts yet"
            description="Ask for HTML, code, a diagram, or a document. It will appear here, ready to preview, edit and save."
            action={
              <button
                type="button"
                className="artp-empty-action"
                onClick={() => setArtifactLibraryOpen(true)}
              >
                <Package size={14} />
                Browse saved artifacts
              </button>
            }
          >
            <div className="artp-empty-chips">
              <span>HTML</span>
              <span>Diagrams</span>
              <span>Documents</span>
              <span>Slides</span>
            </div>
          </EmptyState>
        </div>
      ) : (
        <div className="artp-doc">
          {!external && (sessionArtifacts.length > 1 || streaming || newIds.size > 0) && (
            <ArtifactTabs
              artifacts={sessionArtifacts}
              activeId={active.id}
              newIds={newIds}
              onSelect={selectSessionArtifact}
            />
          )}

          <ArtifactToolbar
            active={active}
            content={content}
            saved={Boolean(saved)}
            versionCount={saved?.versions.length ?? 0}
            editing={editing}
            viewMode={viewMode}
            exporting={exporting}
            pinBusy={pinBusy}
            onToggleView={setViewMode}
            onToggleEdit={toggleEditing}
            onSave={() => void saveToVaultNow()}
            onExport={format => void exportAs(format)}
            onCopy={copy}
            onDownload={download}
            onShare={() => void share()}
            onOpenHistory={() => {
              void refreshVault();
              void refreshProject();
              setHistoryOpen(true);
            }}
            onOpenProject={openPicker}
            onSaveKnowledge={() => void saveToKnowledge()}
            onOpenInNewTab={() => void openInNewTab()}
          />

          <div
            ref={splitContainerRef}
            className={`artp-content${editing ? ' is-editing' : ''}`}
          >
            {editing && (
              <div
                key="editor"
                className="artp-edit"
                style={{ width: `${splitPercent}%` }}
              >
                <ArtifactEditor
                  value={content}
                  language={sourceLanguage(active.type, active.language)}
                  onChange={updateContent}
                />
              </div>
            )}
            {editing && (
              <div
                key="resizer"
                className="artp-split"
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize editor and preview"
                aria-valuemin={25}
                aria-valuemax={75}
                aria-valuenow={Math.round(splitPercent)}
                tabIndex={0}
                onPointerDown={startResize}
                onPointerMove={moveResize}
                onPointerUp={endResize}
                onPointerCancel={endResize}
                onDoubleClick={resetSplit}
                title="Drag to resize · double-click to reset"
                onKeyDown={event => {
                  if (event.key === 'ArrowLeft') {
                    event.preventDefault();
                    nudgeSplit(-5);
                  } else if (event.key === 'ArrowRight') {
                    event.preventDefault();
                    nudgeSplit(5);
                  }
                }}
              >
                <span className="artp-split-grip" aria-hidden="true" />
              </div>
            )}
            <div key="preview" className="artp-preview-pane">
              <ArtifactPreview
                key={active.id}
                artifact={active}
                content={content}
                viewMode={viewMode}
                scrollRef={previewScrollRef}
              />
            </div>
          </div>
        </div>
      )}

      <ArtifactLibrary
        open={artifactLibraryOpen}
        onClose={() => {
          setArtifactLibraryOpen(false);
          void refreshVault();
        }}
        onOpen={opened => {
          setExternal(toActive(opened));
          setEdits(prev => ({ ...prev, [opened.id]: opened.content }));
          setEditing(false);
          if (opened.projectId) setActiveProjectId(opened.projectId);
        }}
      />

      <ArtifactVersionDialog
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        title={active?.title}
        currentContent={content}
        dirty={dirty}
        saved={saved}
        projectArtifact={projectArtifact}
        projectLoading={projectLoading}
        onRestoreLocal={restore}
        onRestoreProject={restoreProjectVersion}
        onLoadLocalVersion={getLocalVersionContent}
        onLoadProjectVersion={getProjectVersionContent}
      />

      <ArtifactProjectDialog
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        projects={projects}
        activeProjectId={activeProjectId}
        pinBusy={pinBusy}
        newProjectName={newProjectName}
        creatingProject={creatingProject}
        onNameChange={setNewProjectName}
        onCreate={() => void createProject()}
        onPin={projectId => void pinToProject(projectId)}
      />
    </aside>
  );
}
