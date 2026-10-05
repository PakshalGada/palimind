import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDown,
  Download,
  Eye,
  FileText,
  FolderOpen,
  History,
  Plus,
  RotateCcw,
  Save,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { useApp } from '../AppContext';
import { api } from '../api';
import { formatMarkdown } from '../utils/markdown';
import { exportDoc, exportMarkdown, exportPdf } from '../utils/canvasExport';
import './CanvasPanel.css';

interface Revision {
  title: string;
  content: string;
  at: number;
}

interface CanvasMeta {
  id: string;
  title: string;
  updated_at: number;
  created_at: number;
}

type StreamMode = 'idle' | 'document' | 'replace';

function newId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `canvas-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function CanvasPanel() {
  const {
    canvasOpen,
    setCanvasOpen,
    canvasEnabled,
    addToast,
    activeView,
    selectedAgentId,
    activeSessionId,
  } = useApp();

  const [canvasId, setCanvasId] = useState<string | null>(null);
  const [title, setTitle] = useState('Untitled');
  const [content, setContent] = useState('');
  const [instruction, setInstruction] = useState('');
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [canvases, setCanvases] = useState<CanvasMeta[]>([]);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [streamBuffer, setStreamBuffer] = useState('');
  const [streamMode, setStreamMode] = useState<StreamMode>('idle');
  const [selection, setSelection] = useState({ start: 0, end: 0 });

  const esRef = useRef<EventSource | null>(null);
  const bufferRef = useRef('');
  const modeRef = useRef<StreamMode>('idle');
  const replaceRangeRef = useRef({ start: 0, end: 0 });
  const initializedRef = useRef(false);

  const loadList = useCallback(async () => {
    try {
      const data = await api.canvas.list();
      setCanvases(data.canvases || []);
    } catch {
      // backend unavailable — canvases remain local for this session
    }
  }, []);

  const pushRevision = useCallback(() => {
    setRevisions((prev) => [{ title, content, at: Date.now() }, ...prev].slice(0, 25));
  }, [title, content]);

  const openCanvas = useCallback(
    async (id: string) => {
      try {
        const data = await api.canvas.get(id);
        if (data.error) {
          addToast(data.error);
          return;
        }
        setCanvasId(data.id);
        setTitle(data.title || 'Untitled');
        setContent(data.content || '');
        setSavedAt(data.updated_at ?? null);
        setPickerOpen(false);
      } catch {
        addToast('Could not open canvas.');
      }
    },
    [addToast],
  );

  const createNew = useCallback(() => {
    setCanvasId(null);
    setTitle('Untitled');
    setContent('');
    setSavedAt(null);
    setStreamBuffer('');
    setPickerOpen(false);
  }, []);

  const saveNow = useCallback(async () => {
    const id = canvasId ?? newId();
    if (!canvasId) setCanvasId(id);
    setSaving(true);
    try {
      const record = await api.canvas.save(id, title, content);
      setSavedAt(record.updated_at);
    } catch {
      addToast('Could not save canvas.');
    } finally {
      setSaving(false);
    }
  }, [canvasId, title, content, addToast]);

  const removeCanvas = useCallback(
    async (id: string) => {
      try {
        await api.canvas.remove(id);
        if (id === canvasId) createNew();
        void loadList();
      } catch {
        addToast('Could not delete canvas.');
      }
    },
    [canvasId, createNew, loadList, addToast],
  );

  // Load the most recent canvas the first time the panel opens.
  useEffect(() => {
    if (!canvasOpen) {
      esRef.current?.close();
      esRef.current = null;
      return;
    }
    void loadList();
    if (!initializedRef.current) {
      initializedRef.current = true;
      api.canvas
        .list()
        .then((data) => {
          if (data.canvases?.length) void openCanvas(data.canvases[0].id);
        })
        .catch(() => {});
    }
  }, [canvasOpen, loadList, openCanvas]);

  // Accept content pushed from the chat ("Open in Canvas").
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { title?: string; content?: string } | undefined;
      setCanvasId(null);
      setTitle(detail?.title || 'Untitled');
      setContent(detail?.content || '');
      setSavedAt(null);
      setCanvasOpen(true);
    };
    window.addEventListener('palimind:canvas-open', handler);
    return () => window.removeEventListener('palimind:canvas-open', handler);
  }, [setCanvasOpen]);

  // The canvas belongs to the chat it was opened from: switching sessions or
  // scopes closes it instead of leaving it hanging over unrelated chats.
  const scope =
    activeView === 'agents'
      ? selectedAgentId
        ? `agent:${selectedAgentId}`
        : ''
      : activeView === 'chat'
        ? 'chat'
        : 'field';
  const sessionKey = `${scope}|${activeSessionId ?? ''}`;
  const openedKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (!canvasOpen) {
      openedKeyRef.current = null;
      return;
    }
    if (openedKeyRef.current === null) {
      openedKeyRef.current = sessionKey;
      return;
    }
    if (openedKeyRef.current !== sessionKey) {
      openedKeyRef.current = null;
      setCanvasOpen(false);
    }
  }, [canvasOpen, sessionKey, setCanvasOpen]);

  // Debounced autosave.
  useEffect(() => {
    if (!canvasOpen) return;
    if (!content.trim() && title === 'Untitled') return;
    const timer = window.setTimeout(async () => {
      const id = canvasId ?? newId();
      if (!canvasId) setCanvasId(id);
      try {
        const record = await api.canvas.save(id, title, content);
        setSavedAt(record.updated_at);
      } catch {
        // offline / backend down — keep editing locally
      }
    }, 800);
    return () => window.clearTimeout(timer);
  }, [content, title, canvasOpen, canvasId]);

  const displayContent = useMemo(() => {
    if (!busy) return content;
    if (streamMode === 'replace') {
      const { start, end } = replaceRangeRef.current;
      return content.slice(0, start) + streamBuffer + content.slice(end);
    }
    return streamBuffer;
  }, [busy, streamMode, content, streamBuffer]);

  // If the document is a full HTML page, the preview renders it live in a
  // sandboxed frame instead of as Markdown.
  const looksLikeHtml = useMemo(
    () => /^\s*(<!doctype html|<html[\s>])/i.test(displayContent.trim()),
    [displayContent],
  );

  const finishStream = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    const buffer = bufferRef.current;
    const mode = modeRef.current;
    if (buffer.trim()) {
      pushRevision();
      if (mode === 'replace') {
        const { start, end } = replaceRangeRef.current;
        setContent(content.slice(0, start) + buffer + content.slice(end));
      } else {
        setContent(buffer);
      }
    } else {
      addToast('The model returned no content.');
    }
    bufferRef.current = '';
    modeRef.current = 'idle';
    setStreamBuffer('');
    setStreamMode('idle');
    setBusy(false);
  }, [content, pushRevision, addToast]);

  const generate = useCallback(() => {
    if (busy) return;
    const trimmed = instruction.trim();
    if (!trimmed) {
      addToast('Enter an instruction first.');
      return;
    }
    const selectedText =
      selection.end > selection.start ? content.slice(selection.start, selection.end) : '';
    let prompt: string;
    let mode: StreamMode;
    if (selectedText.trim()) {
      mode = 'replace';
      replaceRangeRef.current = { start: selection.start, end: selection.end };
      prompt =
        'Rewrite the following selected passage according to the instruction. ' +
        'Return only the rewritten passage with no preamble or commentary.\n\n' +
        `Instruction: ${trimmed}\n\nPassage:\n${selectedText}`;
    } else {
      mode = 'document';
      prompt =
        `You are editing a Markdown document titled "${title}". ` +
        'Apply the instruction and return the complete updated document in Markdown only, ' +
        'with no commentary.\n\n' +
        `Instruction: ${trimmed}\n\nCurrent document:\n${content}`;
    }

    modeRef.current = mode;
    setStreamMode(mode);
    bufferRef.current = '';
    setStreamBuffer('');
    setBusy(true);

    const es = new EventSource(`/api/canvas/generate?q=${encodeURIComponent(prompt)}`);
    esRef.current = es;

    es.onmessage = (event) => {
      let data: { type?: string; text?: string; reset?: boolean; output?: string };
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      if (data.type === 'token' || data.type === 'agent:token') {
        if (data.reset) bufferRef.current = '';
        else if (data.text) bufferRef.current += data.text;
        setStreamBuffer(bufferRef.current);
      } else if (data.type === 'agent:completed' && data.output) {
        bufferRef.current = data.output;
        setStreamBuffer(bufferRef.current);
        finishStream();
      } else if (data.type === 'error') {
        addToast(`Generation failed: ${data.text ?? 'unknown error'}`);
        finishStream();
      } else if (data.type === 'done') {
        finishStream();
      }
    };
    es.onerror = () => {
      if (modeRef.current !== 'idle') finishStream();
    };
  }, [busy, instruction, selection, content, title, addToast, finishStream]);

  const stop = useCallback(() => {
    finishStream();
  }, [finishStream]);

  if (!canvasOpen || !canvasEnabled) return null;

  const savedLabel = saving
    ? 'Saving…'
    : savedAt
      ? `Saved ${new Date(savedAt * 1000).toLocaleTimeString()}`
      : 'Not saved yet';

  return (
    <aside className="canvas-panel" aria-label="Canvas">
      <header className="canvas-head">
        <div className="canvas-heading">
          <FileText size={15} />
          <input
            className="canvas-title-input"
            value={title}
            aria-label="Canvas title"
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className="canvas-head-actions">
          <button type="button" className="ui-icon-btn" title="New canvas" aria-label="New canvas" onClick={createNew}>
            <Plus size={15} />
          </button>
          <div className="canvas-menu-wrap">
            <button
              type="button"
              className="ui-icon-btn"
              title="Open canvas"
              aria-label="Open canvas"
              onClick={() => {
                setPickerOpen((v) => !v);
                void loadList();
              }}
            >
              <FolderOpen size={15} />
            </button>
            {pickerOpen && (
              <div className="canvas-menu canvas-picker" role="menu">
                {canvases.length === 0 && <div className="canvas-menu-empty">No saved canvases</div>}
                {canvases.map((c) => (
                  <div key={c.id} className="canvas-picker-row">
                    <button type="button" role="menuitem" onClick={() => openCanvas(c.id)}>
                      {c.title || 'Untitled'}
                    </button>
                    <button
                      type="button"
                      className="canvas-picker-delete"
                      title="Delete"
                      aria-label={`Delete ${c.title}`}
                      onClick={() => removeCanvas(c.id)}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <button
            type="button"
            className={`ui-icon-btn${historyOpen ? ' is-active' : ''}`}
            title="Revision history"
            aria-label="Toggle revision history"
            onClick={() => setHistoryOpen((v) => !v)}
          >
            <History size={15} />
          </button>
          <button
            type="button"
            className={`ui-icon-btn${previewOpen ? ' is-active' : ''}`}
            title="Toggle preview"
            aria-label="Toggle preview"
            onClick={() => setPreviewOpen((v) => !v)}
          >
            <Eye size={15} />
          </button>
          <div className="canvas-menu-wrap">
            <button
              type="button"
              className="ui-icon-btn"
              title="Export"
              aria-label="Export canvas"
              onClick={() => setExportOpen((v) => !v)}
            >
              <Download size={15} />
              <ChevronDown size={10} />
            </button>
            {exportOpen && (
              <div className="canvas-menu canvas-export-menu" role="menu">
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    exportMarkdown(title, content);
                    setExportOpen(false);
                  }}
                >
                  Markdown (.md)
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    if (!exportPdf(title, content)) addToast('Allow pop-ups to export PDF.');
                    setExportOpen(false);
                  }}
                >
                  PDF (print)
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    exportDoc(title, content);
                    setExportOpen(false);
                  }}
                >
                  Word (.doc)
                </button>
              </div>
            )}
          </div>
          <button
            type="button"
            className="ui-icon-btn"
            title="Save now"
            aria-label="Save canvas"
            onClick={saveNow}
            disabled={saving}
          >
            <Save size={15} />
          </button>
          <button
            type="button"
            className="canvas-close-btn"
            title="Close canvas"
            aria-label="Close canvas"
            onClick={() => setCanvasOpen(false)}
          >
            <X size={14} />
            <span>Close</span>
          </button>
        </div>
      </header>

      <div className="canvas-status">{savedLabel}</div>

      <div className="canvas-body">
        <div className="canvas-editor-wrap">
          <textarea
            className="canvas-editor"
            value={displayContent}
            readOnly={busy}
            spellCheck={false}
            aria-label="Canvas document"
            onChange={(e) => setContent(e.target.value)}
            onSelect={(e) =>
              setSelection({
                start: e.currentTarget.selectionStart,
                end: e.currentTarget.selectionEnd,
              })
            }
          />
          {busy && (
            <div className="canvas-streaming-badge">
              <Sparkles size={13} /> Generating…
              <button type="button" onClick={stop}>
                Stop
              </button>
            </div>
          )}
        </div>

        {previewOpen && (
          looksLikeHtml ? (
            <iframe
              className="canvas-preview-frame"
              title="Canvas HTML preview"
              sandbox="allow-scripts allow-forms allow-modals allow-popups"
              srcDoc={displayContent}
            />
          ) : (
            <div
              className="canvas-preview"
              dangerouslySetInnerHTML={{ __html: formatMarkdown(displayContent) }}
            />
          )
        )}

        {historyOpen && (
          <div className="canvas-history">
            <div className="canvas-history-title">Revision history</div>
            {revisions.length === 0 && <div className="canvas-menu-empty">No revisions yet</div>}
            {revisions.map((rev, i) => (
              <div key={`${rev.at}-${i}`} className="canvas-history-row">
                <span>{new Date(rev.at).toLocaleTimeString()}</span>
                <button
                  type="button"
                  className="canvas-history-restore"
                  onClick={() => {
                    pushRevision();
                    setTitle(rev.title);
                    setContent(rev.content);
                  }}
                >
                  <RotateCcw size={13} /> Restore
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="canvas-generate">
        <Sparkles size={15} className="canvas-generate-icon" />
        <input
          className="canvas-generate-input"
          placeholder={
            selection.end > selection.start
              ? 'Revise the selected text…'
              : 'Ask the AI to write or edit this document…'
          }
          value={instruction}
          disabled={busy}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              generate();
            }
          }}
        />
        <button
          type="button"
          className="ui-btn ui-btn--primary ui-btn--sm"
          onClick={generate}
          disabled={busy || !instruction.trim()}
        >
          {busy ? 'Generating…' : 'Generate'}
        </button>
      </div>
    </aside>
  );
}
