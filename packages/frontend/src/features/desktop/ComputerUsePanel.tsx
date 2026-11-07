import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import {
  AppWindow,
  Check,
  ChevronDown,
  Copy,
  Cpu,
  Crosshair,
  Eye,
  Loader2,
  Maximize2,
  MousePointerClick,
  RefreshCw,
  ShieldQuestion,
  Sparkles,
  Square,
  X,
} from 'lucide-react';
import { api } from '../../api';
import type { ModelItem } from '../../types';
import './desktop.css';

export interface DesktopRegion {
  x: number;
  y: number;
  width: number;
  height: number;
  dpr?: number;
  mode?: 'ask' | 'act';
}

interface WindowItem {
  id: string;
  app_name: string;
  title: string;
  pid: number;
  is_focused?: boolean;
  minimized?: boolean;
  visible?: boolean;
  bounds?: { x: number; y: number; width: number; height: number };
}

interface DesktopStatus {
  platform?: string;
  session_type?: string;
  permissions?: { accessibility?: { state?: string } };
  kernel_input?: { accessible?: boolean; detail?: string };
  policy?: { enabled?: boolean; stopped?: boolean; allowed_apps?: string[] };
}

interface ScreenshotResult {
  image?: string;
  path?: string;
  width?: number;
  height?: number;
}

interface PendingApproval {
  agentId: string;
  runId: string;
  tool: string;
  args?: unknown;
}

const STOP_EVENT = 'palimind:desktop-stop';
const REGION_EVENT = 'palimind:region-selected';

const SUGGESTIONS = [
  'What is on my screen right now?',
  'Summarize the active window',
  'Find and click Save',
  'Explain the error in this dialog',
];

async function tauriInvoke(command: string, args?: Record<string, unknown>) {
  try {
    return await invoke(command, args);
  } catch {
    return null;
  }
}

function prettyApp(name: string): string {
  const leaf = name.split('/').filter(Boolean).pop() || name;
  let candidate = leaf.endsWith('.desktop') ? leaf.slice(0, -'.desktop'.length) : leaf;
  const dotted = candidate.split('.').filter(Boolean);
  // Desktop ids look like org.gnome.Calculator; dotted process names like
  // python3.10 are not ids, so keep the whole leaf when the tail is numeric.
  if (dotted.length > 1 && !/^\d+$/.test(dotted[dotted.length - 1])) {
    candidate = dotted[dotted.length - 1];
  }
  const cleaned = candidate.replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  return cleaned || 'Application';
}

function initials(name: string): string {
  return prettyApp(name)
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] || '')
    .join('')
    .toUpperCase();
}

function friendlyError(error: unknown): string {
  const text = String(error);
  if (/not found|404/i.test(text)) {
    return (
      'This window is newer than the running backend. Restart Palimind ' +
      '(or the backend) once so the desktop API is reloaded, then press Refresh.'
    );
  }
  return text;
}

function compactArgs(args: unknown): string {
  if (!args || typeof args !== 'object') return '';
  return Object.entries(args as Record<string, unknown>)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join(' · ');
}

export function ApprovalCard({
  tool,
  args,
  onDecide,
}: {
  tool: string;
  args?: unknown;
  onDecide: (approved: boolean) => void;
}) {
  return (
    <section className="cu-approval" role="alert">
      <div className="cu-approval__head">
        <ShieldQuestion size={15} />
        <span>Approval needed</span>
      </div>
      <div className="cu-approval__body">
        <code>{tool}</code>
        {compactArgs(args) && <span className="cu-approval__args">{compactArgs(args)}</span>}
      </div>
      <div className="cu-approval__actions">
        <button type="button" className="cu-btn cu-btn--ghost" onClick={() => onDecide(false)}>
          Deny
        </button>
        <button type="button" className="cu-btn cu-btn--primary" onClick={() => onDecide(true)}>
          Approve
        </button>
      </div>
    </section>
  );
}

/**
 * Compact model picker for the popup. It reuses the app's ModelSwitcher chrome
 * (pill + dropdown) but keeps its own state so the secondary window does not
 * depend on the main window's config lifecycle.
 */
function ModelPicker({
  value,
  onChange,
  onError,
}: {
  value: string;
  onChange: (modelId: string) => void;
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const selectionRef = useRef(0);

  const loadModels = useCallback(async () => {
    const version = selectionRef.current;
    setLoading(true);
    setError('');
    try {
      const data = await api.models.list();
      if (data.models) setModels(data.models);
      // A slow list response must not overwrite a model the user just picked.
      if (data.current_model && selectionRef.current === version) {
        onChange(data.current_model);
      }
      if (data.status === 'offline') {
        setError('Ollama is offline');
      } else if (!data.models?.length) {
        setError('No models installed');
      }
    } catch {
      setError('Could not reach the backend');
    } finally {
      setLoading(false);
    }
  }, [onChange]);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!target.isConnected) return;
      if (rootRef.current && !rootRef.current.contains(target)) setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  const openPicker = () => {
    setOpen(true);
    setQuery('');
    void loadModels();
    window.setTimeout(() => searchRef.current?.focus(), 40);
  };

  const selectModel = async (modelId: string) => {
    setOpen(false);
    if (modelId === value) return;
    selectionRef.current += 1;
    const previous = value;
    onChange(modelId);
    try {
      const result = await api.config.setModel(modelId, 'field');
      if (result.error) throw new Error(result.error);
    } catch (err) {
      onChange(previous);
      onError(`Could not switch model: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const filtered = query.trim()
    ? models.filter((item) => {
        const needle = query.toLowerCase();
        return (
          item.model_id.toLowerCase().includes(needle) ||
          item.display_name?.toLowerCase().includes(needle) ||
          item.family?.toLowerCase().includes(needle)
        );
      })
    : models;

  return (
    <div
      className="model-switcher-area cu-model"
      ref={rootRef}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          setOpen(false);
        }
      }}
    >
      <button
        type="button"
        className={`model-switcher-pill${open ? ' open' : ''}`}
        title="Switch model"
        aria-label="Switch model"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={(event) => {
          event.stopPropagation();
          if (open) setOpen(false);
          else openPicker();
        }}
      >
        <Cpu size={12} aria-hidden="true" />
        <span id="cu-model-name">{value || 'Select model'}</span>
        <ChevronDown size={10} aria-hidden="true" />
      </button>

      {open && (
        <div
          className="model-switcher-dropdown cu-model__dropdown"
          role="dialog"
          aria-label="Model selection"
        >
          <div className="cu-model__head">
            <span className="cu-label">Model</span>
            <span className="cu-model__hint">Used for desktop requests</span>
          </div>
          <div className="model-search-container">
            <input
              ref={searchRef}
              type="text"
              className="model-search-input"
              placeholder="Search models…"
              aria-label="Search models"
              autoComplete="off"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <div className="model-list" role="listbox">
            {loading && (
              <div className="model-list-loading">
                <Loader2 size={13} className="cu-spin" />
                Loading models…
              </div>
            )}
            {!loading && error && (
              <div className="model-empty-state">
                <span className="model-empty-msg">{error}</span>
                <button type="button" className="model-retry-btn" onClick={() => void loadModels()}>
                  Retry
                </button>
              </div>
            )}
            {!loading && !error && filtered.length === 0 && (
              <div className="model-list-loading">No models found</div>
            )}
            {!loading &&
              !error &&
              filtered.map((item) => (
                <div
                  key={item.model_id}
                  className={`model-list-item${item.model_id === value ? ' active-model' : ''}`}
                  role="option"
                  aria-selected={item.model_id === value}
                  tabIndex={0}
                  onClick={() => void selectModel(item.model_id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      void selectModel(item.model_id);
                    }
                  }}
                >
                  {item.model_id === value && <span className="model-active-dot" />}
                  <span className="model-list-item-name">
                    {item.display_name || item.model_id}
                  </span>
                  {item.provider && (
                    <span className={`model-provider-badge model-provider-${item.provider}`}>
                      {item.provider === 'opencode' ? 'OpenCode' : 'Ollama'}
                    </span>
                  )}
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ComputerUsePanel() {
  const [status, setStatus] = useState<DesktopStatus | null>(null);
  const [windows, setWindows] = useState<WindowItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selection, setSelection] = useState<DesktopRegion | null>(null);
  const [thumbnail, setThumbnail] = useState<ScreenshotResult | null>(null);
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<'ask' | 'act'>('ask');
  const [answer, setAnswer] = useState('');
  const [approval, setApproval] = useState<PendingApproval | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingApps, setLoadingApps] = useState(false);
  const [copied, setCopied] = useState(false);
  const [message, setMessage] = useState('');
  const [model, setModel] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  const selected = useMemo(
    () => windows.find((item) => item.id === selectedId) ?? null,
    [windows, selectedId],
  );

  const refresh = useCallback(async () => {
    try {
      const view = await api.desktop.status();
      setStatus((view.status as DesktopStatus) ?? null);
      if (!view.ok) setMessage('The native desktop service is unavailable.');
    } catch (error) {
      setMessage(friendlyError(error));
    }
  }, []);

  const loadWindows = useCallback(async () => {
    setLoadingApps(true);
    try {
      const view = await api.desktop.apps('windows');
      if (!view.ok) {
        setMessage('Could not list windows.');
        return;
      }
      const seen = new Set<string>();
      const items = ((view.items ?? []) as unknown as WindowItem[])
        .filter((item) => item.visible !== false && !item.minimized)
        .filter((item) => !/palimind/i.test(item.app_name))
        .filter((item) => {
          const key = `${item.app_name}::${item.title}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      setWindows(items);
      setSelectedId((current) => {
        if (current && items.some((item) => item.id === current)) return current;
        return items.find((item) => item.is_focused)?.id ?? items[0]?.id ?? null;
      });
    } catch (error) {
      setMessage(friendlyError(error));
    } finally {
      setLoadingApps(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    void loadWindows();
    let cleanup: (() => void) | undefined;
    void listen<DesktopRegion>(REGION_EVENT, (event) => {
      setSelection(event.payload);
      if (event.payload.mode === 'act') setMode('act');
      setThumbnail(null);
      setMessage('');
      void (async () => {
        await tauriInvoke('hide_region_overlay');
        await new Promise((resolve) => setTimeout(resolve, 180));
        const result = await api.desktop.screenshot({
          screen: 0,
          region: event.payload,
          annotate: false,
        });
        if (result.ok && result.data?.image) {
          setThumbnail(result.data);
        } else {
          setMessage(
            result.error?.message ||
              'Could not capture the selected region. The desktop may have denied the screenshot.',
          );
        }
      })();
    }).then((unlisten) => {
      cleanup = unlisten;
    });
    void listen(STOP_EVENT, () => {
      setMessage('Stopped. Held keys and buttons were released.');
      setBusy(false);
      setApproval(null);
      abortRef.current?.abort();
    }).then((unlisten) => {
      const previous = cleanup;
      cleanup = () => {
        previous?.();
        unlisten();
      };
    });
    return () => cleanup?.();
  }, [refresh, loadWindows]);

  const selectArea = async () => {
    setMessage('');
    const opened = await tauriInvoke('show_region_overlay');
    if (!opened) setMessage('Region selection needs the desktop app.');
  };

  const useActiveWindow = () => {
    setSelection(null);
    setThumbnail(null);
    void loadWindows();
  };

  const stop = async () => {
    abortRef.current?.abort();
    setApproval(null);
    await tauriInvoke('hide_ghost_cursor');
    await api.desktop.stop().catch(() => null);
    setBusy(false);
    setMessage('Stopped. Held keys and buttons were released.');
    await refresh();
  };

  const openMain = async () => {
    await tauriInvoke('hide_ghost_cursor');
    await tauriInvoke('focus_main_window');
    await tauriInvoke('hide_computer_use');
  };

  const showTargetHint = async () => {
    const target = selection ?? null;
    if (!target && !selected?.bounds) {
      setMessage('Pick an app or select a region first.');
      return;
    }
    const bounds = target ?? selected?.bounds;
    if (!bounds) return;
    const shown = await tauriInvoke('show_ghost_cursor', {
      cursor: {
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
        label: target ? 'Selected region' : prettyApp(selected?.app_name || ''),
      },
    });
    if (!shown) setMessage('The ghost cursor needs the desktop app.');
  };

  const copyAnswer = async () => {
    if (!answer) return;
    try {
      await navigator.clipboard.writeText(answer);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      setMessage('Clipboard is unavailable.');
    }
  };

  const send = async () => {
    const text = prompt.trim();
    if (!text) {
      setMessage('Describe what you want to do first.');
      return;
    }
    if (busy && !approval) return;
    setBusy(true);
    setAnswer('');
    setApproval(null);
    setMessage('');
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await api.desktop.ask({
        input: text,
        mode,
        model: model || undefined,
        region: selection,
        app: selection ? undefined : selected?.app_name,
        window_id: selection ? undefined : selected?.id,
      });
      if (!response.ok || !response.body) {
        const detail = await response.text().catch(() => '');
        throw new Error(detail || `Request failed (${response.status})`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finished = false;
      while (!finished) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split('\n\n');
        buffer = chunks.pop() ?? '';
        for (const chunk of chunks) {
          const line = chunk.split('\n').find((entry) => entry.startsWith('data: '));
          if (!line) continue;
          let event: Record<string, unknown>;
          try {
            event = JSON.parse(line.slice(6));
          } catch {
            continue;
          }
          const type = String(event.type || '');
          if (type === 'agent:token' && typeof event.text === 'string') {
            setAnswer((previous) => previous + event.text);
          } else if (type === 'agent:completed' && typeof event.output === 'string') {
            setAnswer(event.output);
          } else if (type === 'agent:waiting_for_human') {
            setApproval({
              agentId: String(event.agent_id || ''),
              runId: String(event.run_id || ''),
              tool: String(event.tool || 'action'),
              args: event.args,
            });
          } else if (type === 'error') {
            setMessage(String(event.text || 'The agent failed.'));
          } else if (type === 'done') {
            finished = true;
          }
        }
      }
    } catch (error) {
      if ((error as Error).name !== 'AbortError') setMessage(String(error));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const decide = async (approved: boolean) => {
    if (!approval) return;
    setApproval(null);
    try {
      await api.agents.approve(approval.agentId, approved, '', approval.runId);
    } catch (error) {
      setMessage(String(error));
    }
  };

  const stopped = Boolean(status?.policy?.stopped);
  const enabled = status ? Boolean(status.policy?.enabled) : true;
  const state = stopped ? 'paused' : enabled ? 'ready' : 'off';
  const stateLabel = stopped ? 'Paused' : enabled ? 'Ready' : 'Off';

  return (
    <div className="cu-shell">
      <header className="cu-top" data-tauri-drag-region>
        <div className="cu-brand">
          <img className="cu-brand__mark" src="/ui/palimind-icon.png" alt="" />
          <div className="cu-brand__text">
            <span className="cu-brand__name">Computer Use</span>
            <span className="cu-brand__sub">Any app · protected processes excluded</span>
          </div>
        </div>
        <div className="cu-top__actions">
          <span className={`cu-state cu-state--${state}`}>
            <span className="cu-state__dot" />
            {stateLabel}
          </span>
          <button
            type="button"
            className="cu-iconbtn"
            title="Open in main window"
            aria-label="Open in main window"
            onClick={() => void openMain()}
          >
            <Maximize2 size={14} />
          </button>
          <button
            type="button"
            className="cu-iconbtn"
            title="Close"
            aria-label="Close"
            onClick={() => void tauriInvoke('hide_computer_use')}
          >
            <X size={15} />
          </button>
        </div>
      </header>

      <div className="cu-scroll">
        <section className="cu-block">
          <div className="cu-block__head">
            <span className="cu-label">Target</span>
            <div className="cu-block__tools">
              <button
                type="button"
                className="cu-textbtn"
                onClick={() => void loadWindows()}
                disabled={loadingApps}
              >
                <RefreshCw size={12} className={loadingApps ? 'cu-spin' : undefined} />
                Refresh
              </button>
              <button type="button" className="cu-textbtn" onClick={() => void selectArea()}>
                <Crosshair size={12} />
                Select area
              </button>
            </div>
          </div>

          {windows.length === 0 ? (
            <div className="cu-empty">
              <AppWindow size={17} />
              <span>{loadingApps ? 'Looking for windows…' : 'No windows found yet.'}</span>
            </div>
          ) : (
            <div className="cu-apps" role="listbox" aria-label="Target application">
              {windows.slice(0, 8).map((item) => {
                const active = !selection && item.id === selectedId;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="option"
                    aria-selected={active}
                    className={`cu-app${active ? ' is-on' : ''}`}
                    onClick={() => {
                      setSelectedId(item.id);
                      setSelection(null);
                      setThumbnail(null);
                    }}
                  >
                    <span className="cu-app__badge">{initials(item.app_name)}</span>
                    <span className="cu-app__text">
                      <span className="cu-app__name">{prettyApp(item.app_name)}</span>
                      <span className="cu-app__title">{item.title || 'Window'}</span>
                    </span>
                    {item.is_focused && <span className="cu-app__focus">active</span>}
                    {active && <Check size={13} className="cu-app__check" />}
                  </button>
                );
              })}
            </div>
          )}
        </section>

        {selection && (
          <section className="cu-block cu-block--preview">
            <div className="cu-block__head">
              <span className="cu-label">Selection</span>
              <button type="button" className="cu-textbtn" onClick={useActiveWindow}>
                Clear
              </button>
            </div>
            <div className="cu-preview">
              {thumbnail?.image ? (
                <img src={thumbnail.image} alt="Selected screen region" />
              ) : (
                <div className="cu-preview__placeholder">
                  <Loader2 size={15} className="cu-spin" />
                  Capturing region…
                </div>
              )}
              <span className="cu-preview__meta">
                {Math.round(selection.width)} × {Math.round(selection.height)} at{' '}
                {Math.round(selection.x)}, {Math.round(selection.y)}
              </span>
            </div>
          </section>
        )}

        <section className="cu-block">
          <div className="cu-block__head">
            <span className="cu-label">Request</span>
            <button type="button" className="cu-textbtn" onClick={() => void showTargetHint()}>
              <Crosshair size={12} />
              Show target
            </button>
          </div>
          <div className="cu-modes" role="tablist" aria-label="Mode">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'ask'}
              className={`cu-mode${mode === 'ask' ? ' is-on' : ''}`}
              onClick={() => setMode('ask')}
            >
              <Eye size={13} />
              <span>
                <strong>Ask</strong>
                <small>read-only</small>
              </span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'act'}
              className={`cu-mode${mode === 'act' ? ' is-on' : ''}`}
              onClick={() => setMode('act')}
            >
              <MousePointerClick size={13} />
              <span>
                <strong>Act</strong>
                <small>approve each step</small>
              </span>
            </button>
          </div>
          <div className="cu-composer">
            <textarea
              id="cu-prompt"
              className="cu-composer__input"
              rows={3}
              placeholder={
                selected
                  ? `Ask about ${prettyApp(selected.app_name)}, or tell it what to do…`
                  : 'Ask about your screen, or tell it what to do…'
              }
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) void send();
              }}
            />
            <div className="cu-composer__bar">
              <span className="cu-kbd">
                <kbd>Ctrl</kbd>
                <kbd>↵</kbd>
              </span>
              <div className="cu-suggest">
                {SUGGESTIONS.slice(0, 2).map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    className="cu-chip"
                    onClick={() => setPrompt(suggestion)}
                  >
                    <Sparkles size={10} />
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          </div>

        </section>

        {approval && (
          <ApprovalCard
            tool={approval.tool}
            args={approval.args}
            onDecide={(approved) => void decide(approved)}
          />
        )}

        {(answer || busy) && (
          <section className="cu-result">
            <div className="cu-result__head">
              <span className="cu-label">Response</span>
              <button
                type="button"
                className="cu-textbtn"
                onClick={() => void copyAnswer()}
                disabled={!answer}
              >
                {copied ? <Check size={12} /> : <Copy size={12} />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <div className="cu-result__body">
              {answer || (
                <span className="cu-thinking">
                  <Loader2 size={13} className="cu-spin" /> Working on it…
                </span>
              )}
              {busy && answer && <span className="cu-caret">▍</span>}
            </div>
          </section>
        )}

        {message && <div className="cu-notice">{message}</div>}
      </div>

      <footer className="cu-bottom">
        <div className="cu-bottom__status">
          <span className={`cu-mini${enabled && !stopped ? ' is-on' : ''}`} />
          <span>
            {status?.session_type || 'linux'} ·{' '}
            {status?.permissions?.accessibility?.state || 'accessibility'} ·{' '}
            {status?.kernel_input?.accessible ? 'kernel input' : 'semantic input'}
          </span>
        </div>
        <div className="cu-bottom__actions">
          <ModelPicker
            value={model}
            onChange={setModel}
            onError={(text) => setMessage(text)}
          />
          <button type="button" className="cu-btn cu-btn--stop" onClick={() => void stop()}>
            <Square size={11} />
            Stop
          </button>
          <button
            type="button"
            className="cu-btn cu-btn--primary"
            onClick={() => void send()}
            disabled={busy && !approval}
          >
            {busy && !approval ? (
              <>
                <Loader2 size={13} className="cu-spin" />
                Working…
              </>
            ) : mode === 'act' ? (
              'Run with approval'
            ) : (
              'Send'
            )}
          </button>
        </div>
      </footer>
    </div>
  );
}
