import { useState } from 'react';
import { Globe, Search } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { Dialog, EmptyState, SkeletonList } from '../../ui/primitives';

interface Hit {
  space_id: string;
  space_name: string;
  space_root: string;
  file_path: string;
  section: string;
  page?: number | null;
  score?: number | null;
  url?: string;
  title?: string;
  site?: string;
  content: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function CrossSpaceSearchDialog({ open, onClose }: Props) {
  const { addToast } = useApp();
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<Hit[]>([]);
  const [meta, setMeta] = useState<{ total: number; spaces: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.spaces.searchAll(query.trim(), { maxResults: 40 });
      if (data.error) {
        setError(data.error);
        return;
      }
      setHits(data.results || []);
      setMeta({ total: data.total, spaces: data.spaces_searched });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Search failed.');
    } finally {
      setLoading(false);
    }
  };

  const openSpace = async (hit: Hit) => {
    try {
      const data = await api.spaces.activate(hit.space_id);
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      window.dispatchEvent(new CustomEvent('palimind:spaces-changed'));
      window.dispatchEvent(new CustomEvent('palimind:field-added'));
      onClose();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not open the space.', { tone: 'error' });
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Search all spaces"
      subtitle="Query every knowledge space at once, then jump to the one that has the answer."
      width={760}
      footer={
        <>
          <button type="button" className="ui-btn" onClick={onClose}>
            Close
          </button>
          <button
            type="button"
            className="ui-btn ui-btn--primary"
            disabled={loading || !query.trim()}
            onClick={() => void run()}
          >
            {loading ? 'Searching…' : 'Search'}
          </button>
        </>
      }
    >
      <div className="cross-search">
        <div className="knowledge-search">
          <Search size={14} />
          <input
            value={query}
            autoFocus
            placeholder="Ask across every space…"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                void run();
              }
            }}
          />
        </div>
        {meta ? (
          <p className="knowledge-muted">
            {meta.total} result{meta.total === 1 ? '' : 's'} from {meta.spaces} space
            {meta.spaces === 1 ? '' : 's'}
          </p>
        ) : null}
        {loading ? (
          <SkeletonList rows={5} avatar={false} />
        ) : error ? (
          <EmptyState compact title="Search failed" description={error} />
        ) : hits.length === 0 ? (
          <EmptyState
            compact
            title={meta ? 'Nothing matched' : 'Search across spaces'}
            description={
              meta
                ? 'Try a broader phrase or a different space.'
                : 'Results keep their space name, source title and citation snippet.'
            }
          />
        ) : (
          <div className="cross-search__list">
            {hits.map((hit, index) => (
              <article key={`${hit.space_id}-${hit.file_path}-${index}`} className="cross-search__hit">
                <div className="cross-search__head">
                  <span className="knowledge-pill">{hit.space_name}</span>
                  {hit.title ? <strong>{hit.title}</strong> : null}
                  {hit.site ? <span className="knowledge-muted">{hit.site}</span> : null}
                  {hit.score != null ? (
                    <span className="cross-search__score">{Number(hit.score).toFixed(3)}</span>
                  ) : null}
                </div>
                <p>{hit.content}</p>
                <div className="cross-search__actions">
                  <button type="button" className="knowledge-link" onClick={() => void openSpace(hit)}>
                    Open in {hit.space_name}
                  </button>
                  {hit.url ? (
                    <a className="knowledge-link" href={hit.url} target="_blank" rel="noreferrer">
                      <Globe size={11} /> Original
                    </a>
                  ) : null}
                  <span className="knowledge-muted">
                    {hit.file_path}
                    {hit.section ? ` → ${hit.section}` : ''}
                    {hit.page ? ` (p. ${hit.page})` : ''}
                  </span>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </Dialog>
  );
}
