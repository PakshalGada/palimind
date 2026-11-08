import { useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Globe2,
  Loader2,
  Maximize2,
  Minimize2,
  Plus,
  RotateCw,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { api } from '../../../api';
import { useApp } from '../../../AppContext';
import type { BrowserTab } from '../../../types';
import { useBrowserSession } from './useBrowserSession';
import { normalizeAddress, toPagePoint } from './coordinates';
import './BrowserDock.css';

export default function BrowserDock({ agentId }: { agentId?: string | null }) {
  const {
    browserOpen,
    setBrowserOpen,
    browserFullscreen,
    setBrowserFullscreen,
  } = useApp();
  const { state, busy, frameFailed, setFrameFailed, refresh, act, claim, release, frameUrl } =
    useBrowserSession(browserOpen, agentId || '');
  const [address, setAddress] = useState('');
  const [editing, setEditing] = useState(false);
  const [frameLoading, setFrameLoading] = useState(true);
  const [zoom, setZoom] = useState(() => {
    try {
      const stored = Number(localStorage.getItem('palimind:browser-zoom'));
      if (Number.isFinite(stored) && stored >= 75 && stored <= 250) return stored;
    } catch {
      // localStorage may be unavailable
    }
    return 125;
  });
  const stageRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const addressRef = useRef<HTMLInputElement>(null);
  const actionQueue = useRef<Promise<unknown>>(Promise.resolve());

  const enqueue = (action: string, payload: Record<string, unknown> = {}) => {
    actionQueue.current = actionQueue.current
      .then(() => act(action, payload))
      .catch(() => undefined);
    return actionQueue.current;
  };

  useEffect(() => {
    if (!editing) setAddress(state.url || '');
  }, [state.url, editing]);

  useEffect(() => {
    try {
      localStorage.setItem('palimind:browser-zoom', String(zoom));
    } catch {
      // localStorage may be unavailable
    }
  }, [zoom]);

  const changeZoom = (delta: number) =>
    setZoom((current) => Math.max(75, Math.min(250, current + delta)));

  useEffect(() => {
    if (!state.open) {
      setFrameLoading(false);
      return;
    }
    setFrameLoading(true);
    // A frame older than a couple of seconds means the screenshot route is
    // stuck; leave the previous image visible instead of a blank stage.
    const timer = window.setTimeout(() => setFrameLoading(false), 2500);
    return () => window.clearTimeout(timer);
  }, [state.open, state.url, state.title]);

  useEffect(() => {
    if (!browserFullscreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setBrowserFullscreen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [browserFullscreen, setBrowserFullscreen]);

  // Ctrl/⌘+L focuses the address bar like a normal browser. Escape returns
  // focus to the page so page keyboard input resumes immediately.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!browserOpen) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'l') {
        event.preventDefault();
        addressRef.current?.focus();
        addressRef.current?.select();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [browserOpen]);

  /** The user taking any action is the natural handoff; no extra modal. */
  const ensureHuman = async () => {
    if (state.owner === 'human') return;
    if (takeover && takeover.status === 'pending') {
      await api.browser.acceptTakeover(takeover.id);
    } else {
      await claim(agentId || '', takeover?.id || '');
    }
  };

  const userAct = async (action: string, payload: Record<string, unknown> = {}) => {
    await ensureHuman();
    return enqueue(action, payload);
  };

  if (!browserOpen) return null;

  const human = state.owner === 'human';
  const pending = state.owner === 'pending';
  const takeover = state.takeover;
  const viewport = state.viewport || { width: 1280, height: 800 };

  const takeOver = async () => {
    if (takeover && takeover.status === 'pending') {
      await api.browser.acceptTakeover(takeover.id);
      await refresh();
    } else {
      await claim(agentId || '', takeover?.id || '');
    }
  };

  const handBack = async () => {
    const hadTakeover = Boolean(takeover);
    if (takeover && takeover.status === 'active') {
      await api.browser.resolveTakeover(takeover.id, 'completed');
      await refresh();
    } else {
      await release();
    }
    if (hadTakeover) {
      window.dispatchEvent(new CustomEvent('palimind:browser-handed-back', { detail: { agentId } }));
    }
  };

  const closeBrowser = () => {
    if (human) {
      void (takeover && takeover.status === 'active'
        ? api.browser.resolveTakeover(takeover.id, 'completed')
        : api.browser.releaseControl()).catch(() => undefined);
    }
    setBrowserFullscreen(false);
    setBrowserOpen(false);
  };

  const navigate = async () => {
    const target = normalizeAddress(address);
    if (!target) return;
    setEditing(false);
    await userAct('goto', { url: target });
  };

  const pagePoint = (event: React.MouseEvent) => {
    const img = imgRef.current;
    if (!img) return { x: 0, y: 0 };
    return toPagePoint(event.clientX, event.clientY, img.getBoundingClientRect(), viewport);
  };

  const onStageClick = async (event: React.MouseEvent) => {
    stageRef.current?.focus();
    if (!state.open) return;
    const { x, y } = pagePoint(event);
    await userAct('click', { x, y });
  };

  const onStageDoubleClick = async (event: React.MouseEvent) => {
    stageRef.current?.focus();
    if (!state.open) return;
    const { x, y } = pagePoint(event);
    await userAct('dblclick', { x, y });
  };

  const onStageContextMenu = async (event: React.MouseEvent) => {
    event.preventDefault();
    if (!state.open) return;
    const { x, y } = pagePoint(event);
    await userAct('right_click', { x, y });
  };

  const onKeyDown = async (event: React.KeyboardEvent) => {
    if (!state.open || event.metaKey || event.ctrlKey) return;
    event.preventDefault();
    const named = new Set([
      'Enter',
      'Escape',
      'Tab',
      'Backspace',
      'Delete',
      'ArrowUp',
      'ArrowDown',
      'ArrowLeft',
      'ArrowRight',
      'Home',
      'End',
      'PageUp',
      'PageDown',
      ' ',
    ]);
    if (named.has(event.key)) {
      await userAct('key', { key: event.key });
      return;
    }
    if (event.key.length === 1 && !event.altKey) {
      await userAct('key', { key: event.key, text: event.key });
    }
  };

  const onPaste = async (event: React.ClipboardEvent) => {
    const text = event.clipboardData.getData('text');
    if (!text) return;
    event.preventDefault();
    await userAct('type', { text });
  };

  const onWheel = async (event: React.WheelEvent) => {
    if (!state.open) return;
    event.preventDefault();
    if (event.ctrlKey || event.metaKey) {
      changeZoom(event.deltaY < 0 ? 15 : -15);
      return;
    }
    await userAct('wheel', { dx: 0, dy: event.deltaY });
  };

  const tabLabel = (tab: BrowserTab) => tab.title || tab.url || 'New tab';

  return (
    <aside
      className={`ag-browser${browserFullscreen ? ' is-full' : ''}`}
      aria-label="Browser"
    >
      <div className="ag-browser__tabs">
        {state.tabs.map((tab) => (
          <button
            key={`${tab.index}-${tab.url}`}
            type="button"
            className={`ag-browser__tab${tab.active ? ' is-active' : ''}`}
            onClick={() => void userAct('select_tab', { index: tab.index })}
          >
            <span>{tabLabel(tab)}</span>
            <span
              role="button"
              tabIndex={-1}
              className="ag-browser__tab-close"
              aria-label="Close tab"
              onClick={(event) => {
                event.stopPropagation();
                void userAct('close_tab', { index: tab.index });
              }}
            >
              <X size={10} />
            </span>
          </button>
        ))}
        <button
          type="button"
          className="ag-browser__tab-new"
          title="New tab"
          aria-label="New tab"
          onClick={() => void userAct('new_tab', {})}
        >
          <Plus size={12} />
        </button>
        <span className="ag-browser__spacer" />
        <button
          type="button"
          className="ag-icon-btn"
          title={browserFullscreen ? 'Exit full screen' : 'Full screen'}
          aria-label={browserFullscreen ? 'Exit full screen' : 'Full screen'}
          onClick={() => setBrowserFullscreen(!browserFullscreen)}
        >
          {browserFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
        <button
          type="button"
          className="ag-icon-btn"
          title="Close browser"
          aria-label="Close browser"
          onClick={closeBrowser}
        >
          <X size={14} />
        </button>
      </div>

      <div className="ag-browser__nav">
        <button
          type="button"
          className="ag-icon-btn"
          title="Back"
          aria-label="Back"
          disabled={!state.open || state.can_go_back === false}
          onClick={() => void userAct('back')}
        >
          <ArrowLeft size={14} />
        </button>
        <button
          type="button"
          className="ag-icon-btn"
          title="Forward"
          aria-label="Forward"
          disabled={!state.open || state.can_go_forward === false}
          onClick={() => void userAct('forward')}
        >
          <ArrowRight size={14} />
        </button>
        <button
          type="button"
          className="ag-icon-btn"
          title="Reload"
          aria-label="Reload"
          disabled={!state.open}
          onClick={() => void userAct('reload')}
        >
          <RotateCw size={14} />
        </button>
        <button
          type="button"
          className="ag-icon-btn"
          title="Zoom out"
          aria-label="Zoom out"
          disabled={zoom <= 75}
          onClick={() => changeZoom(-15)}
        >
          <ZoomOut size={14} />
        </button>
        <button
          type="button"
          className="ag-icon-btn ag-browser__zoom"
          title={`Reset zoom to 100% (${zoom}%)`}
          aria-label={`Browser zoom ${zoom}%`}
          onClick={() => setZoom(100)}
        >
          {zoom}%
        </button>
        <button
          type="button"
          className="ag-icon-btn"
          title="Zoom in"
          aria-label="Zoom in"
          disabled={zoom >= 250}
          onClick={() => changeZoom(15)}
        >
          <ZoomIn size={14} />
        </button>
        <input
          ref={addressRef}
          className="ag-browser__address"
          value={address}
          placeholder="Enter a URL"
          spellCheck={false}
          autoCapitalize="off"
          autoComplete="off"
          onFocus={(event) => {
            setEditing(true);
            event.currentTarget.select();
          }}
          onBlur={() => setEditing(false)}
          onChange={(event) => setAddress(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void navigate();
            if (event.key === 'Escape') {
              event.currentTarget.blur();
              stageRef.current?.focus();
            }
          }}
          aria-label="Address"
        />
        <span className={`ag-browser__owner${human ? ' is-human' : ''}`}>
          <span className="ag-browser__owner-dot" />
          {human ? 'You' : pending ? 'Waiting' : state.open ? 'Agent' : 'Closed'}
        </span>
      </div>

      {state.error && (
        <div className="ag-browser__alert" role="alert">
          <span>{state.error}</span>
          <button type="button" onClick={() => void refresh()}>
            Retry
          </button>
        </div>
      )}

      <div className="ag-browser__stage-wrap">
        {!state.open ? (
          <div className="ag-browser__empty">
            <Globe2 size={30} />
            <h3>No browser session</h3>
            <p>Open a URL to start browsing. Agents can use the same session.</p>
            <div className="ag-browser__empty-form">
              <input
                value={address}
                placeholder="example.com"
                onChange={(event) => setAddress(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void navigate();
                }}
              />
              <button type="button" onClick={() => void navigate()} disabled={busy}>
                Open
              </button>
            </div>
            {state.error && <p className="ag-browser__error">{state.error}</p>}
          </div>
        ) : (
          <div
            ref={stageRef}
            className={`ag-browser__stage${human ? ' is-human' : ''}`}
            style={{
              aspectRatio: `${viewport.width} / ${viewport.height}`,
              width: `${zoom}%`,
            }}
            role="application"
            tabIndex={0}
            onClick={(event) => void onStageClick(event)}
            onDoubleClick={(event) => void onStageDoubleClick(event)}
            onContextMenu={(event) => void onStageContextMenu(event)}
            onKeyDown={(event) => void onKeyDown(event)}
            onPaste={(event) => void onPaste(event)}
            onWheel={(event) => void onWheel(event)}
            aria-label={state.title || 'Browser page'}
          >
            {!frameFailed ? (
              <img
                ref={imgRef}
                src={frameUrl}
                alt={state.title || 'Browser page'}
                draggable={false}
                onError={() => {
                  setFrameFailed(true);
                  setFrameLoading(false);
                }}
                onLoad={() => {
                  setFrameFailed(false);
                  setFrameLoading(false);
                }}
              />
            ) : (
              <div className="ag-browser__frame-error">
                <Globe2 size={22} />
                <span>{state.title || 'Waiting for the page'}</span>
                <button type="button" onClick={() => void refresh()}>
                  Retry
                </button>
              </div>
            )}
            {(frameLoading || busy) && frameFailed === false && (
              <div className="ag-browser__loading" role="status" aria-label="Loading page">
                <Loader2 size={14} className="spin" />
              </div>
            )}
            {!human && (
              <div className="ag-browser__lock">
                <span>
                  {pending
                    ? 'Waiting for you to take over'
                    : agentId
                      ? 'Agent is using this browser'
                      : 'Agent control'}
                </span>
                <button type="button" onClick={() => void takeOver()}>
                  Take over
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="ag-browser__foot">
        <span className="ag-browser__url" title={state.url}>
          {state.url || 'about:blank'}
        </span>
        {human ? (
          <button type="button" className="ag-browser__handback" onClick={() => void handBack()}>
            Hand back
          </button>
        ) : (
          <button type="button" className="ag-browser__handback" onClick={() => void takeOver()} disabled={!state.open}>
            Take over
          </button>
        )}
      </div>

      {takeover && takeover.status === 'pending' && (
        <div className="ag-browser__takeover">
          <div>
            <strong>Agent needs you</strong>
            <span>{takeover.reason || 'Complete the step in the browser.'}</span>
          </div>
          <button
            type="button"
            className="ag-browser__dismiss"
            onClick={() =>
              void api.browser.resolveTakeover(takeover.id, 'cancelled').then(() => refresh())
            }
          >
            Dismiss
          </button>
          <button type="button" onClick={() => void takeOver()}>
            Take over
          </button>
        </div>
      )}
    </aside>
  );
}
