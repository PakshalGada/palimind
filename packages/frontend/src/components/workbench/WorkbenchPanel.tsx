import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { Globe2, Link2, Package, X } from 'lucide-react';
import { useApp, type WorkbenchTab } from '../../AppContext';
import ArtifactPanel from '../ArtifactPanel';
import BrowserDock from '../../features/agents/browser/BrowserDock';
import { SourcesPanel } from '../sources/SourcesPanel';
import { EmptyState } from '../../ui/primitives';
import { collectArtifacts } from '../../utils/artifacts';
import './Workbench.css';

const WIDTH_KEY = 'palimind:workbench-width';
const MIN_WIDTH = 360;
const MAX_WIDTH = 980;
const DEFAULT_WIDTH = 620;

function clampWidth(width: number): number {
  if (typeof window === 'undefined') return width;
  const viewportMax = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, window.innerWidth - 420));
  return Math.min(Math.max(width, MIN_WIDTH), viewportMax);
}

function initialWidth(): number {
  try {
    const stored = Number(window.localStorage.getItem(WIDTH_KEY));
    if (Number.isFinite(stored) && stored > 0) return clampWidth(stored);
  } catch {
    // localStorage may be unavailable
  }
  return DEFAULT_WIDTH;
}

const TABS: { id: WorkbenchTab; label: string; icon: typeof Package }[] = [
  { id: 'artifacts', label: 'Artifacts', icon: Package },
  { id: 'browser', label: 'Browser', icon: Globe2 },
  { id: 'sources', label: 'Sources', icon: Link2 },
];

function SourcesWorkbench() {
  const { sessions, activeSessionId } = useApp();
  const session = sessions.find((item) => item.id === activeSessionId);
  const messages = useMemo(() => session?.messages ?? [], [session?.messages]);
  const lastAssistant = useMemo(
    () => [...messages].reverse().find((message) => message.role !== 'user'),
    [messages],
  );
  const citations = lastAssistant?.citations;
  const legacySources = lastAssistant?.sources ?? [];
  const hasSources = Boolean(citations) || legacySources.length > 0;

  if (!hasSources) {
    return (
      <div className="wb-empty">
        <EmptyState
          icon={<Link2 size={22} />}
          title="No sources yet"
          description="Sources from the current answer will appear here with links to the original documents and pages."
        />
      </div>
    );
  }

  return (
    <div className="wb-sources">
      <SourcesPanel citations={citations} legacySources={legacySources} />
    </div>
  );
}

export default function WorkbenchPanel() {
  const {
    workbenchTab,
    setWorkbenchTab,
    closeWorkbench,
    sessions,
    activeSessionId,
  } = useApp();
  const [width, setWidth] = useState(initialWidth);
  const draggingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(width);

  const sessionArtifacts = useMemo(() => {
    const session = sessions.find((item) => item.id === activeSessionId);
    return collectArtifacts(session?.messages);
  }, [sessions, activeSessionId]);
  const artifactCount = sessionArtifacts.length;

  const persist = useCallback((next: number) => {
    try {
      window.localStorage.setItem(WIDTH_KEY, String(next));
    } catch {
      // storage is optional
    }
  }, []);

  useEffect(() => {
    persist(width);
  }, [width, persist]);

  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    draggingRef.current = true;
    startXRef.current = event.clientX;
    startWidthRef.current = width;
    document.body.classList.add('is-resizing-workbench');
  };

  const moveResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return;
    const next = startWidthRef.current + (startXRef.current - event.clientX);
    setWidth(clampWidth(next));
  };

  const endResize = () => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    document.body.classList.remove('is-resizing-workbench');
  };

  const nudge = (delta: number) => setWidth((value) => clampWidth(value + delta));

  return (
    <aside className="app-workbench" aria-label="Workbench" style={{ width }}>
      <div
        className="app-workbench__resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize workbench"
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={MAX_WIDTH}
        aria-valuenow={Math.round(width)}
        tabIndex={0}
        onPointerDown={startResize}
        onPointerMove={moveResize}
        onPointerUp={endResize}
        onPointerCancel={endResize}
        onDoubleClick={() => setWidth(DEFAULT_WIDTH)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft') {
            event.preventDefault();
            nudge(30);
          } else if (event.key === 'ArrowRight') {
            event.preventDefault();
            nudge(-30);
          }
        }}
        title="Drag to resize · double-click to reset"
      >
        <span className="app-workbench__grip" aria-hidden="true" />
      </div>

      <header className="app-workbench__head">
        <div className="app-workbench__tabs" role="tablist" aria-label="Workbench sections">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const active = workbenchTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={active}
                className={`app-workbench__tab${active ? ' is-active' : ''}`}
                onClick={() => setWorkbenchTab(tab.id)}
                title={tab.label}
              >
                <Icon size={14} />
                <span>{tab.label}</span>
                {tab.id === 'artifacts' && artifactCount > 0 && (
                  <span className="app-workbench__badge">{artifactCount}</span>
                )}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          className="app-workbench__close"
          onClick={closeWorkbench}
          title="Close workbench"
          aria-label="Close workbench"
        >
          <X size={15} />
        </button>
      </header>

      <div className="app-workbench__body">
        {workbenchTab === 'artifacts' && (
          <div className="wb-artifacts">
            <ArtifactPanel forceVisible embedded panelVisible />
          </div>
        )}
        {workbenchTab === 'browser' && (
          <BrowserDock embedded onClose={closeWorkbench} />
        )}
        {workbenchTab === 'sources' && <SourcesWorkbench />}
      </div>
    </aside>
  );
}
