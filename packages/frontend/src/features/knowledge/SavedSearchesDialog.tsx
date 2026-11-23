import { useCallback, useEffect, useState } from 'react';
import { Bell, Play, Trash2 } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { Dialog, EmptyState, SkeletonList } from '../../ui/primitives';

interface SavedSearch {
  id: string;
  name: string;
  query: string;
  collection: string;
  alert: boolean;
  last_checked: number | null;
  last_count: number;
}

interface Props {
  open: boolean;
  spaceId: string | null;
  onClose: () => void;
}

export default function SavedSearchesDialog({ open, spaceId, onClose }: Props) {
  const { addToast } = useApp();
  const [searches, setSearches] = useState<SavedSearch[]>([]);
  const [name, setName] = useState('');
  const [query, setQuery] = useState('');
  const [alert, setAlert] = useState(true);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<{
    title: string;
    hits: { title?: string; file_path: string; content: string; url?: string }[];
  } | null>(null);

  const load = useCallback(async () => {
    if (!spaceId) return;
    setLoading(true);
    try {
      const data = await api.spaces.searches.list(spaceId);
      setSearches(data.searches || []);
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not load saved searches.', { tone: 'error' });
    } finally {
      setLoading(false);
    }
  }, [spaceId, addToast]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const save = async () => {
    if (!spaceId || !query.trim()) return;
    try {
      const data = await api.spaces.searches.save(spaceId, {
        name: name.trim() || query.trim(),
        query: query.trim(),
        alert,
      });
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      setName('');
      setQuery('');
      addToast('Saved search created', { tone: 'success' });
      await load();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not save the search.', { tone: 'error' });
    }
  };

  const run = async (search: SavedSearch) => {
    if (!spaceId) return;
    try {
      const data = await api.spaces.searches.run(spaceId, search.id);
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      setResults({ title: search.name, hits: data.results || [] });
      await load();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Search failed.', { tone: 'error' });
    }
  };

  const remove = async (search: SavedSearch) => {
    if (!spaceId) return;
    try {
      await api.spaces.searches.remove(spaceId, search.id);
      await load();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not remove the search.', { tone: 'error' });
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Saved searches"
      subtitle="Save a query, run it later, and record an alert source when new matches appear."
      width={720}
      footer={
        <button type="button" className="ui-btn" onClick={onClose}>
          Close
        </button>
      }
    >
      <div className="saved-searches">
        <div className="saved-searches__form">
          <input
            className="ui-input"
            placeholder="Name (optional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className="ui-input"
            placeholder="Query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void save();
              }
            }}
          />
          <label className="space-settings__check">
            <input type="checkbox" checked={alert} onChange={(e) => setAlert(e.target.checked)} />
            Alert
          </label>
          <button type="button" className="ui-btn ui-btn--primary ui-btn--sm" onClick={() => void save()}>
            Save search
          </button>
        </div>

        {loading ? (
          <SkeletonList rows={4} avatar={false} />
        ) : searches.length === 0 ? (
          <EmptyState compact title="No saved searches" description="Save a query to run it later." />
        ) : (
          <ul className="saved-searches__list">
            {searches.map((search) => (
              <li key={search.id}>
                <span>
                  <strong>{search.name}</strong>
                  <small>
                    {search.query}
                    {search.alert ? ' · alert' : ''}
                    {search.last_count ? ` · ${search.last_count} last results` : ''}
                  </small>
                </span>
                <div>
                  <button
                    type="button"
                    className="ui-icon-btn"
                    title="Run search"
                    aria-label="Run search"
                    onClick={() => void run(search)}
                  >
                    <Play size={13} />
                  </button>
                  <button
                    type="button"
                    className="ui-icon-btn"
                    title="Remove search"
                    aria-label="Remove search"
                    onClick={() => void remove(search)}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {results ? (
          <div className="saved-searches__results">
            <h4>
              <Bell size={13} /> {results.title} · {results.hits.length} result(s)
            </h4>
            {results.hits.length === 0 ? (
              <p className="knowledge-muted">No matches.</p>
            ) : (
              results.hits.map((hit, index) => (
                <article key={`${hit.file_path}-${index}`}>
                  <strong>{hit.title || hit.file_path}</strong>
                  <p>{hit.content}</p>
                  {hit.url ? (
                    <a href={hit.url} target="_blank" rel="noreferrer">
                      {hit.url}
                    </a>
                  ) : null}
                </article>
              ))
            )}
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
