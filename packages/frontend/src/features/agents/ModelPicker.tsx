import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../../api';
import type { ModelItem } from '../../types';
import { Spinner } from '../../ui/primitives';

export default function ModelPicker({
  value,
  onChange,
  placeholder = 'Default (global model)',
}: {
  value: string;
  onChange: (model: string) => void;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  const fetchModels = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.models.list();
      if (data.models) setModels(data.models);
    } catch {
      // ignore — dropdown still offers the default option
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (open && models.length === 0) void fetchModels();
  }, [open, models.length, fetchModels]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return models;
    return models.filter(
      (m) =>
        m.model_id?.toLowerCase().includes(q) ||
        m.display_name?.toLowerCase().includes(q) ||
        m.family?.toLowerCase().includes(q),
    );
  }, [models, query]);

  return (
    <div className="ax-model-picker" ref={ref}>
      <button type="button" className="ax-model-picker__btn" onClick={() => setOpen((o) => !o)}>
        <span className="ax-model-picker__label">{value || placeholder}</span>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div className="ax-model-picker__menu">
          <input
            className="ui-input ax-model-picker__search"
            placeholder="Search models..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
          <div className="ax-model-picker__list">
            <button
              type="button"
              className={`ax-model-picker__item${!value ? ' is-selected' : ''}`}
              onClick={() => {
                onChange('');
                setOpen(false);
              }}
            >
              <span className="ax-model-picker__name">Default (use global model)</span>
            </button>
            {loading && (
              <div className="ax-model-picker__loading">
                <Spinner size={14} /> Loading models…
              </div>
            )}
            {!loading &&
              filtered.map((m) => (
                <button
                  type="button"
                  key={m.model_id}
                  className={`ax-model-picker__item${value === m.model_id ? ' is-selected' : ''}`}
                  onClick={() => {
                    onChange(m.model_id);
                    setOpen(false);
                  }}
                >
                  <span className="ax-model-picker__name">{m.display_name || m.model_id}</span>
                  <span className="ax-model-picker__meta">
                    {m.parameter_size || ''}
                    {m.size_gb ? ` · ${m.size_gb}GB` : ''}
                  </span>
                </button>
              ))}
            {!loading && filtered.length === 0 && models.length > 0 && (
              <div className="ax-model-picker__loading">No models found</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
