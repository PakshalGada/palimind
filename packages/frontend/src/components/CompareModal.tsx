import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Loader2, Square, Swords, X } from 'lucide-react';
import { api } from '../api';
import { useApp } from '../AppContext';
import { resolveScope } from '../lib/scope';
import { Button, Select } from '../ui/primitives';
import type { ModelItem } from '../types';
import './CompareModal.css';

/**
 * Side-by-side model comparison: one prompt, two local models, two columns.
 * Both runs stream from `/api/compare/stream` (no history, nothing stored);
 * the winner can be promoted to the chat model with one click.
 */
export default function CompareModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { addToast, currentModel, activeView, activeProjectId, selectedAgentId } = useApp();
  const [models, setModels] = useState<ModelItem[]>([]);
  const [prompt, setPrompt] = useState('');
  const [leftModel, setLeftModel] = useState('');
  const [rightModel, setRightModel] = useState('');
  const [leftText, setLeftText] = useState('');
  const [rightText, setRightText] = useState('');
  const [leftError, setLeftError] = useState('');
  const [rightError, setRightError] = useState('');
  const [running, setRunning] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  const close = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api.models
      .list()
      .then((data) => {
        if (cancelled) return;
        const list = (data.models || []).filter((m) => m.model_id);
        setModels(list);
        const current = currentModel && currentModel !== 'Loading...' ? currentModel : '';
        const candidates = list.map((m) => m.model_id);
        setLeftModel(current || candidates[0] || '');
        setRightModel(
          candidates[1] && candidates[1] !== (current || candidates[0])
            ? candidates[1]
            : candidates[0] || '',
        );
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [open, currentModel]);

  useEffect(() => () => sourceRef.current?.close(), []);

  const modelLabel = useMemo(() => {
    const byId = new Map(models.map((m) => [m.model_id, m]));
    return (id: string) => {
      const model = byId.get(id);
      if (!model) return id;
      return model.display_name && model.display_name !== id
        ? `${id} (${model.display_name})`
        : id;
    };
  }, [models]);

  const stop = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
    setRunning(false);
  }, []);

  const run = useCallback(() => {
    const text = prompt.trim();
    if (!text || !leftModel || !rightModel) return;
    sourceRef.current?.close();
    setLeftText('');
    setRightText('');
    setLeftError('');
    setRightError('');
    setRunning(true);
    const params = new URLSearchParams({
      q: text,
      model: leftModel,
      model2: rightModel,
    });
    const source = new EventSource(`/api/compare/stream?${params.toString()}`, {
      withCredentials: true,
    });
    sourceRef.current = source;
    source.onmessage = (message) => {
      let event: { type?: string; text?: string; error?: string };
      try {
        event = JSON.parse(message.data);
      } catch {
        return;
      }
      if (event.type === 'left') {
        if (event.error) setLeftError(event.error);
        else if (event.text) setLeftText((prev) => prev + event.text);
      } else if (event.type === 'right') {
        if (event.error) setRightError(event.error);
        else if (event.text) setRightText((prev) => prev + event.text);
      } else if (event.type === 'done') {
        source.close();
        sourceRef.current = null;
        setRunning(false);
      }
    };
    source.onerror = () => {
      source.close();
      sourceRef.current = null;
      setRunning(false);
    };
  }, [prompt, leftModel, rightModel]);

  /** Promote a column's model: switch chat to it and prefill the composer. */
  const promote = useCallback(
    (modelId: string, text: string) => {
      stop();
      const scope = resolveScope(activeView, {
        agentId: selectedAgentId,
        projectId: activeProjectId,
      });
      api.config
        .setModel(modelId, scope)
        .then(() => {
          addToast(`Chat model set to ${modelLabel(modelId)}`, { tone: 'success' });
          window.dispatchEvent(
            new CustomEvent('palimind:prefill-composer', {
              detail: { text: text.trim() || prompt.trim() },
            }),
          );
          close();
        })
        .catch(() => addToast('Could not switch the chat model', { tone: 'error' }));
    },
    [addToast, close, modelLabel, prompt, stop, activeView, activeProjectId, selectedAgentId],
  );

  if (!open) return null;

  const busy = running;

  return (
    <div className="compare-overlay" onMouseDown={close} role="presentation">
      <div
        className="compare-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Compare models"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="compare-header">
          <h2 className="compare-title">
            <Swords size={16} /> Compare models
          </h2>
          <button type="button" className="compare-close" aria-label="Close" onClick={close}>
            <X size={16} />
          </button>
        </header>

        <div className="compare-setup">
          <textarea
            className="compare-prompt"
            placeholder="Ask both models the same question…"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                if (!busy) run();
              }
            }}
          />
          <div className="compare-pickers">
            <Select
              aria-label="Left model"
              value={leftModel}
              onChange={(e) => setLeftModel(e.target.value)}
              disabled={busy}
            >
              {models.length === 0 && <option value="">No models found</option>}
              {models.map((model) => (
                <option key={model.model_id} value={model.model_id}>
                  {model.display_name || model.model_id}
                </option>
              ))}
            </Select>
            <span className="compare-vs">vs</span>
            <Select
              aria-label="Right model"
              value={rightModel}
              onChange={(e) => setRightModel(e.target.value)}
              disabled={busy}
            >
              {models.length === 0 && <option value="">No models found</option>}
              {models.map((model) => (
                <option key={model.model_id} value={model.model_id}>
                  {model.display_name || model.model_id}
                </option>
              ))}
            </Select>
            {busy ? (
              <Button variant="secondary" onClick={stop} aria-label="Stop comparison">
                <Square size={13} /> Stop
              </Button>
            ) : (
              <Button variant="primary" onClick={run} disabled={!prompt.trim()}>
                Run
              </Button>
            )}
          </div>
        </div>

        <div className="compare-columns">
          {[
            { side: 'left', model: leftModel, text: leftText, error: leftError },
            { side: 'right', model: rightModel, text: rightText, error: rightError },
          ].map((column) => (
            <section key={column.side} className={`compare-column is-${column.side}`}>
              <header className="compare-column__head">
                <span className="compare-column__model" title={column.model}>
                  {column.model || '—'}
                </span>
                {column.text && !busy && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => promote(column.model, column.text)}
                    title="Switch chat to this model and keep the prompt"
                  >
                    Use in chat
                  </Button>
                )}
              </header>
              <div className="compare-column__body">
                {column.error ? (
                  <p className="compare-column__error">{column.error}</p>
                ) : column.text ? (
                  <p className="compare-column__text">{column.text}</p>
                ) : busy ? (
                  <p className="compare-column__pending">
                    <Loader2 size={14} className="compare-spin" /> waiting for {column.model || 'model'}…
                  </p>
                ) : (
                  <p className="compare-column__pending">Run a prompt to see the answer.</p>
                )}
              </div>
            </section>
          ))}
        </div>

        <footer className="compare-footer">
          <span>Runs are not saved to any conversation.</span>
          <span>⌘/Ctrl + Enter to run</span>
        </footer>
      </div>
    </div>
  );
}
