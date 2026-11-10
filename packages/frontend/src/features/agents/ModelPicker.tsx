import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Cloud, HardDrive, KeyRound, Search } from 'lucide-react';
import { api } from '../../api';
import type { ModelItem } from '../../types';
import { Spinner } from '../../ui/primitives';

interface ProviderStatus {
  id: string;
  available?: boolean;
  key_present?: boolean;
  error?: string;
}

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
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  const fetchModels = useCallback(async () => {
    setLoading(true);
    try {
      const [catalog, status] = await Promise.all([
        api.models.list(),
        api.providers.list().catch(() => ({ providers: [] })),
      ]);
      if (catalog.models) setModels(catalog.models);
      setProviders((status.providers || []) as unknown as ProviderStatus[]);
    } catch {
      // ignore — the default option still works
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

  const selected = models.find((model) => model.model_id === value);
  const opencode = providers.find((provider) => provider.id === 'opencode');
  const opencodeReady = Boolean(opencode?.key_present ?? opencode?.available);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = models.filter(
      (model) =>
        !q ||
        model.model_id?.toLowerCase().includes(q) ||
        model.display_name?.toLowerCase().includes(q) ||
        model.family?.toLowerCase().includes(q) ||
        model.provider?.toLowerCase().includes(q),
    );
    return {
      local: filtered.filter((model) => (model.provider || 'ollama') !== 'opencode'),
      hosted: filtered.filter((model) => model.provider === 'opencode'),
    };
  }, [models, query]);

  const label = selected
    ? `${selected.display_name || selected.model_id} · ${selected.provider === 'opencode' ? 'OpenCode' : 'Local'}`
    : value || placeholder;

  return (
    <div className="ax-model-picker" ref={ref}>
      <div
        role="button"
        tabIndex={0}
        className="ax-model-picker__btn"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ' || event.key === 'ArrowDown') {
            event.preventDefault();
            setOpen((value) => !value);
          }
        }}
      >
        <span className="ax-model-picker__label">{label}</span>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>
      {open && (
        <div className="ax-model-picker__menu">
          <label className="ax-model-picker__search-wrap">
            <Search size={13} />
            <input
              className="ui-input ax-model-picker__search"
              placeholder="Search models..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              autoFocus
            />
          </label>
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

            {!loading && groups.local.length > 0 && (
              <div className="ax-model-picker__group">
                <span className="ax-model-picker__group-title">
                  <HardDrive size={12} /> On this computer
                </span>
                {groups.local.map((model) => (
                  <ModelRow
                    key={`local:${model.model_id}`}
                    model={model}
                    selected={value === model.model_id}
                    onPick={() => {
                      onChange(model.model_id);
                      setOpen(false);
                    }}
                  />
                ))}
              </div>
            )}

            {!loading && (
              <div className="ax-model-picker__group">
                <span className="ax-model-picker__group-title">
                  <Cloud size={12} /> OpenCode
                  {!opencodeReady && <em className="ax-model-picker__key">API key needed</em>}
                </span>
                {groups.hosted.length === 0 && (
                  <div className="ax-model-picker__empty">
                    {opencodeReady
                      ? 'No hosted models listed.'
                      : 'Add an OpenCode API key in Settings to use hosted models.'}
                  </div>
                )}
                {groups.hosted.map((model) => (
                  <ModelRow
                    key={`hosted:${model.model_id}`}
                    model={model}
                    selected={value === model.model_id}
                    onPick={() => {
                      onChange(model.model_id);
                      setOpen(false);
                    }}
                  />
                ))}
              </div>
            )}

            {!loading && groups.local.length === 0 && groups.hosted.length === 0 && models.length > 0 && (
              <div className="ax-model-picker__loading">No models found</div>
            )}

            {!loading && models.length === 0 && (
              <div className="ax-model-picker__empty">
                No models available. Start Ollama or add an OpenCode key.
              </div>
            )}
          </div>
          {!opencodeReady && (
            <div className="ax-model-picker__hint">
              <KeyRound size={12} />
              OpenCode models need a key: Settings → OpenCode.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ModelRow({
  model,
  selected,
  onPick,
}: {
  model: ModelItem;
  selected: boolean;
  onPick: () => void;
}) {
  const hosted = model.provider === 'opencode';
  return (
    <button
      type="button"
      className={`ax-model-picker__item${selected ? ' is-selected' : ''}`}
      onClick={onPick}
    >
      <span className="ax-model-picker__name">{model.display_name || model.model_id}</span>
      <span className="ax-model-picker__meta">
        {hosted ? 'hosted' : model.parameter_size || (model.size_gb ? `${model.size_gb}GB` : 'local')}
      </span>
    </button>
  );
}
