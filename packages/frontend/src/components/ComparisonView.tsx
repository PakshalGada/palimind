import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { GitCompare, Play } from 'lucide-react';
import { api } from '../api';
import { useApp } from '../AppContext';
import { Modal } from '../ui/primitives';
import { formatMarkdown } from '../utils/markdown';
import type { ComparisonResult, ModelItem } from '../types';
import './ComparisonView.css';

interface AnswerState {
  model: string;
  answer: string;
  done: boolean;
}

export default function ComparisonView() {
  const { addToast } = useApp();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [models, setModels] = useState<ModelItem[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [answers, setAnswers] = useState<AnswerState[]>([]);
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const handler = () => {
      setOpen(true);
      if (models.length === 0) {
        api.models
          .list()
          .then((d) => setModels(d.models || []))
          .catch(() => setModels([]));
      }
    };
    window.addEventListener('palimind:open-compare', handler);
    return () => window.removeEventListener('palimind:open-compare', handler);
  }, [models.length]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const toggleModel = (id: string) => {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((m) => m !== id);
      if (prev.length >= 3) {
        addToast('Compare at most 3 models.');
        return prev;
      }
      return [...prev, id];
    });
  };

  const run = useCallback(async () => {
    if (running) return;
    if (!query.trim()) {
      addToast('Enter a question to compare.');
      return;
    }
    if (selected.length < 2) {
      addToast('Select at least two models.');
      return;
    }
    setRunning(true);
    setResult(null);
    setAnswers(selected.map((model) => ({ model, answer: '', done: false })));

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const res = await fetch(
        `/api/research/compare?q=${encodeURIComponent(query)}&models=${encodeURIComponent(selected.join(','))}`,
        { signal: ctrl.signal },
      );
      if (!res.ok || !res.body) throw new Error(`compare failed: ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          for (const line of frame.split('\n')) {
            if (!line.startsWith('data:')) continue;
            let ev: Record<string, unknown>;
            try {
              ev = JSON.parse(line.slice(5).trim());
            } catch {
              continue;
            }
            if (ev.type === 'compare_model') {
              const model = String(ev.model);
              setAnswers((prev) =>
                prev.map((a) => (a.model === model ? { ...a, answer: String(ev.answer ?? ''), done: true } : a)),
              );
            } else if (ev.type === 'compare_result') {
              setResult(ev as unknown as ComparisonResult);
            }
          }
        }
      }
    } catch {
      if (!ctrl.signal.aborted) addToast('Comparison failed.');
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }, [running, query, selected, addToast]);

  const close = () => {
    abortRef.current?.abort();
    setOpen(false);
  };

  const consensusModels = useMemo(() => result?.models ?? selected, [result, selected]);

  return (
    <Modal
      open={open}
      onClose={close}
      title="Compare Models"
      subtitle="Ask the same question across up to three models and compare their answers."
      width={1000}
      footer={
        <div className="compare-footer">
          <button type="button" className="ui-btn ui-btn--ghost ui-btn--sm" onClick={close}>
            Close
          </button>
          <button type="button" className="ui-btn ui-btn--primary ui-btn--sm" onClick={run} disabled={running}>
            <Play size={13} /> {running ? 'Comparing…' : 'Run comparison'}
          </button>
        </div>
      }
    >
      <div className="compare-controls">
        <input
          className="compare-query"
          value={query}
          placeholder="Research question to compare…"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void run();
          }}
        />
        <div className="compare-model-picker">
          {models.length === 0 && <span className="compare-empty">No models available.</span>}
          {models.slice(0, 30).map((m) => (
            <button
              key={m.model_id}
              type="button"
              className={`compare-model-chip${selected.includes(m.model_id) ? ' is-active' : ''}`}
              onClick={() => toggleModel(m.model_id)}
            >
              {m.display_name || m.model_id}
            </button>
          ))}
        </div>
      </div>

      {(answers.length > 0 || result) && (
        <div className="compare-results">
          {result && (
            <div className="compare-insights">
              <section className="compare-insight">
                <h4>
                  <GitCompare size={14} /> Consensus ({result.consensus.length})
                </h4>
                {result.consensus.length === 0 && <p className="compare-none">No strong consensus found.</p>}
                {result.consensus.map((c, i) => (
                  <div key={i} className="compare-consensus">
                    <p>{c.text}</p>
                    <div className="compare-tags">
                      {c.models.map((m) => (
                        <span key={m} className="compare-tag">
                          {m}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </section>

              <section className="compare-insight">
                <h4>Contradictions ({result.contradictions?.length ?? 0})</h4>
                {(!result.contradictions || result.contradictions.length === 0) && (
                  <p className="compare-none">No direct contradictions detected.</p>
                )}
                {result.contradictions?.map((c, i) => (
                  <div key={i} className="compare-contradiction">
                    <div className="compare-contradiction-side">
                      <span className="compare-tag">{c.model_a}</span>
                      <p>{c.claim_a}</p>
                    </div>
                    <div className="compare-contradiction-side">
                      <span className="compare-tag">{c.model_b}</span>
                      <p>{c.claim_b}</p>
                    </div>
                    {c.explanation && <p className="compare-explanation">{c.explanation}</p>}
                  </div>
                ))}
              </section>

              <section className="compare-insight">
                <h4>Unique insights</h4>
                {consensusModels.map((model) => (
                  <div key={model} className="compare-unique">
                    <span className="compare-tag">{model}</span>
                    <ul>
                      {(result.unique[model] ?? []).slice(0, 6).map((u, i) => (
                        <li key={i}>{u}</li>
                      ))}
                      {(result.unique[model] ?? []).length === 0 && <li className="compare-none">None</li>}
                    </ul>
                  </div>
                ))}
              </section>
            </div>
          )}

          <div className="compare-columns">
            {answers.map((a) => (
              <div key={a.model} className="compare-column">
                <div className="compare-column-head">
                  <span>{a.model}</span>
                  {!a.done && running && <span className="compare-loading">…</span>}
                </div>
                <div
                  className="compare-column-body"
                  dangerouslySetInnerHTML={{ __html: formatMarkdown(a.answer || '_Waiting…_') }}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}
