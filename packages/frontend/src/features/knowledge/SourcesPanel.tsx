import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Bell,
  Check,
  Clock,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  Globe,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Star,
  Trash2,
} from 'lucide-react';
import { api } from '../../api';
import type { KnowledgeSource, SourceCollection } from '../../types';
import { useApp } from '../../AppContext';
import { Dialog, EmptyState, SkeletonList } from '../../ui/primitives';
import SpaceSettingsDialog from './SpaceSettingsDialog';
import SavedSearchesDialog from './SavedSearchesDialog';

const PENDING = new Set(['queued', 'fetching', 'extracting', 'writing']);
const STATUS_LABEL: Record<string, string> = {
  queued: 'Queued',
  fetching: 'Fetching',
  extracting: 'Extracting',
  writing: 'Saving',
  ready: 'Ready',
  failed: 'Failed',
  blocked: 'Blocked',
  not_modified: 'Up to date',
};

function stripFrontMatter(text: string): string {
  if (!text.startsWith('---')) return text;
  return text.replace(/^---\s*\n[\s\S]*?\n---\s*\n?/, '');
}

function dateLabel(value?: number | null): string {
  if (!value) return '';
  try {
    return new Date(value * 1000).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return '';
  }
}

interface AddResult {
  status?: string;
  error?: string;
  sources?: KnowledgeSource[];
  items?: KnowledgeSource[];
  errors?: { url: string; error: string }[];
}

function statusTone(status: string): string {
  if (status === 'ready') return 'ok';
  if (status === 'failed' || status === 'blocked') return 'error';
  if (STATUS_LABEL[status] && status !== 'ready') return 'warn';
  return 'idle';
}

interface Props {
  spaceId: string | null;
  onCountChange?: (count: number) => void;
}

export default function SourcesPanel({ spaceId, onCountChange }: Props) {
  const { addToast } = useApp();
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [total, setTotal] = useState(0);
  const [collections, setCollections] = useState<SourceCollection[]>([]);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [readingState, setReadingState] = useState('');
  const [collection, setCollection] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [searchesOpen, setSearchesOpen] = useState(false);
  const [addMode, setAddMode] = useState<'link' | 'text' | 'feed' | 'site'>('link');
  const [urls, setUrls] = useState('');
  const [feedUrl, setFeedUrl] = useState('');
  const [crawlUrl, setCrawlUrl] = useState('');
  const [noteText, setNoteText] = useState('');
  const [noteTitle, setNoteTitle] = useState('');
  const [adding, setAdding] = useState(false);
  const [reader, setReader] = useState<{
    source: KnowledgeSource;
    content: string;
    related?: KnowledgeSource[];
  } | null>(null);
  const [readerLoading, setReaderLoading] = useState(false);
  const [readerNote, setReaderNote] = useState('');

  const fetchSources = useCallback(async () => {
    if (!spaceId) {
      setSources([]);
      setTotal(0);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await api.spaces.sources.list(spaceId, {
        q: query.trim(),
        status,
        reading_state: readingState,
        collection,
        limit: 200,
      });
      if (data.error) {
        setError(data.error);
        return;
      }
      setSources(data.sources || []);
      setTotal(data.total || 0);
      onCountChange?.(data.total || 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load sources.');
    } finally {
      setLoading(false);
    }
  }, [spaceId, query, status, readingState, collection, onCountChange]);

  const fetchCollections = useCallback(async () => {
    if (!spaceId) return;
    try {
      const data = await api.spaces.collections.list(spaceId);
      setCollections(data.collections || []);
    } catch {
      setCollections([]);
    }
  }, [spaceId]);

  useEffect(() => {
    void fetchSources();
  }, [fetchSources]);

  useEffect(() => {
    void fetchCollections();
  }, [fetchCollections]);

  // Sources finish in the background; poll while anything is still pending.
  useEffect(() => {
    if (!sources.some((source) => PENDING.has(source.status))) return;
    const timer = window.setTimeout(() => void fetchSources(), 2500);
    return () => window.clearTimeout(timer);
  }, [sources, fetchSources]);

  useEffect(() => {
    const handler = () => void fetchSources();
    window.addEventListener('palimind:sources-changed', handler);
    return () => window.removeEventListener('palimind:sources-changed', handler);
  }, [fetchSources]);

  useEffect(() => {
    const handler = () => setAddOpen(true);
    window.addEventListener('palimind:add-source', handler);
    return () => window.removeEventListener('palimind:add-source', handler);
  }, []);

  const pendingCount = useMemo(
    () => sources.filter((source) => PENDING.has(source.status)).length,
    [sources],
  );

  const addSources = async () => {
    if (!spaceId) return;
    setAdding(true);
    try {
      const data = (await (addMode === 'feed'
        ? api.spaces.feeds.add(spaceId, feedUrl.trim())
        : addMode === 'site'
          ? api.spaces.crawl(spaceId, crawlUrl.trim(), 10)
          : addMode === 'link'
            ? api.spaces.sources.add(spaceId, {
                urls: urls
                  .split(/\n+/)
                  .map((line) => line.trim())
                  .filter(Boolean),
              })
            : api.spaces.sources.add(spaceId, { text: noteText, title: noteTitle }))) as AddResult;
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      const count =
        data.sources?.length ??
        (data as { items?: KnowledgeSource[] }).items?.length ??
        0;
      const failures = data.errors?.length ?? 0;
      addToast(
        failures
          ? `Saved ${count} item(s); ${failures} link(s) failed`
          : `Saved ${count} item(s) to this space`,
        { tone: failures ? 'warning' : 'success' },
      );
      setAddOpen(false);
      setUrls('');
      setFeedUrl('');
      setCrawlUrl('');
      setNoteText('');
      setNoteTitle('');
      await fetchSources();
      window.dispatchEvent(new CustomEvent('palimind:sources-changed'));
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not save.', { tone: 'error' });
    } finally {
      setAdding(false);
    }
  };

  const openReader = async (source: KnowledgeSource) => {
    if (!spaceId) return;
    setReaderLoading(true);
    try {
      const data = await api.spaces.sources.content(spaceId, source.id);
      if (data.error || !data.source) {
        addToast(data.error || 'Could not open the source.', { tone: 'error' });
        return;
      }
      setReader({
        source: data.source,
        content: data.content || '',
        related: data.related || [],
      });
      setReaderNote(data.source.note || '');
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not open the source.', { tone: 'error' });
    } finally {
      setReaderLoading(false);
    }
  };

  const act = async (source: KnowledgeSource, action: 'refresh' | 'reindex' | 'delete' | 'state' | 'favorite') => {
    if (!spaceId) return;
    try {
      if (action === 'refresh') {
        const data = await api.spaces.sources.refresh(spaceId, source.id);
        if (data.error) addToast(data.error, { tone: 'error' });
        else addToast('Refreshing source…', { tone: 'success' });
      } else if (action === 'reindex') {
        const data = await api.spaces.sources.reindex(spaceId, source.id);
        if (data.error) addToast(data.error, { tone: 'error' });
        else addToast('Source reindexed', { tone: 'success' });
      } else if (action === 'delete') {
        if (!window.confirm(`Remove "${source.title || source.url}" from this space?`)) return;
        const data = await api.spaces.sources.remove(spaceId, source.id);
        if (data.error) addToast(data.error, { tone: 'error' });
        else addToast('Source removed', { tone: 'success' });
      } else if (action === 'state') {
        const next =
          source.reading_state === 'unread'
            ? 'read'
            : source.reading_state === 'read'
              ? 'archived'
              : 'unread';
        await api.spaces.sources.update(spaceId, source.id, { reading_state: next });
      } else if (action === 'favorite') {
        await api.spaces.sources.update(spaceId, source.id, { favorite: !source.favorite });
      }
      await fetchSources();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Action failed.', { tone: 'error' });
    }
  };

  const saveNote = async () => {
    if (!spaceId || !reader) return;
    try {
      const data = await api.spaces.sources.update(spaceId, reader.source.id, { note: readerNote });
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      setReader({ ...reader, source: data.source || reader.source });
      addToast('Note saved', { tone: 'success' });
      await fetchSources();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not save the note.', { tone: 'error' });
    }
  };

  const createCollection = async () => {
    if (!spaceId) return;
    const name = window.prompt('Collection name');
    if (!name) return;
    try {
      const data = await api.spaces.collections.create(spaceId, name);
      if (data.error) addToast(data.error, { tone: 'error' });
      else await fetchCollections();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not create the collection.', { tone: 'error' });
    }
  };

  if (!spaceId) {
    return (
      <div className="view-frame__body">
        <EmptyState
          title="No space selected"
          description="Create or open a knowledge space to start saving links and notes."
        />
      </div>
    );
  }

  return (
    <div className="sources-panel">
      <div className="sources-toolbar">
        <div className="knowledge-search sources-search">
          <Search size={14} />
          <input
            value={query}
            placeholder="Search saved sources…"
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select className="ui-select" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="ready">Ready</option>
          <option value="queued">Queued</option>
          <option value="failed">Failed</option>
          <option value="blocked">Blocked</option>
        </select>
        <select
          className="ui-select"
          value={readingState}
          onChange={(e) => setReadingState(e.target.value)}
        >
          <option value="">All reading states</option>
          <option value="unread">Unread</option>
          <option value="reading">Reading</option>
          <option value="read">Read</option>
          <option value="archived">Archived</option>
        </select>
        <select className="ui-select" value={collection} onChange={(e) => setCollection(e.target.value)}>
          <option value="">All collections</option>
          {collections.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} ({item.source_count})
            </option>
          ))}
        </select>
        <button type="button" className="ui-btn ui-btn--sm" onClick={() => void createCollection()}>
          <Plus size={13} /> Collection
        </button>
        <button type="button" className="ui-btn ui-btn--sm" onClick={() => setSearchesOpen(true)}>
          <Bell size={13} /> Searches
        </button>
        <button type="button" className="ui-btn ui-btn--sm" onClick={() => setSettingsOpen(true)}>
          <Settings size={13} /> Settings
        </button>
        <button
          type="button"
          className="ui-btn ui-btn--primary ui-btn--sm"
          onClick={() => setAddOpen(true)}
        >
          <Plus size={13} /> Save link
        </button>
      </div>

      <div className="sources-meta">
        <span>
          {total} source{total === 1 ? '' : 's'}
          {pendingCount ? ` · ${pendingCount} in progress` : ''}
        </span>
        <button type="button" className="knowledge-link" onClick={() => void fetchSources()}>
          <RefreshCw size={11} /> Refresh
        </button>
      </div>

      {loading && sources.length === 0 ? (
        <SkeletonList rows={5} avatar={false} />
      ) : error ? (
        <EmptyState
          compact
          title="Couldn't load sources"
          description={error}
          action={
            <button type="button" className="ui-btn ui-btn--sm" onClick={() => void fetchSources()}>
              Retry
            </button>
          }
        />
      ) : sources.length === 0 ? (
        <div className="sources-empty">
          <EmptyState
            glyph={<Globe size={20} />}
            title="Nothing saved here yet"
            description="Paste a link and PaliMind crawls it, saves a readable copy, indexes it and links it into the knowledge graph."
            action={
              <button type="button" className="ui-btn ui-btn--primary" onClick={() => setAddOpen(true)}>
                <Plus size={14} /> Save your first link
              </button>
            }
          />
        </div>
      ) : (
        <div className="sources-list">
          {sources.map((source) => (
            <article key={source.id} className="source-card">
              <button type="button" className="source-card__main" onClick={() => void openReader(source)}>
                <span className="source-card__icon">
                  {source.kind === 'web' ? <Globe size={15} /> : <FileText size={15} />}
                </span>
                <span className="source-card__body">
                  <span className="source-card__title">
                    {source.title || source.url || source.file_path || 'Untitled source'}
                  </span>
                  <span className="source-card__sub">
                    {source.site || source.kind}
                    {source.published_at ? ` · ${source.published_at.slice(0, 10)}` : ''}
                    {source.fetched_at ? ` · saved ${dateLabel(source.fetched_at)}` : ''}
                  </span>
                  {source.note ? <span className="source-card__note">{source.note}</span> : null}
                  {source.change_summary ? (
                    <span className="source-card__sub">Changed: {source.change_summary}</span>
                  ) : null}
                  {source.error ? <span className="source-card__error">{source.error}</span> : null}
                </span>
              </button>
              <div className="source-card__side">
                <span className={`knowledge-pill knowledge-pill--${statusTone(source.status)}`}>
                  {source.status === 'failed' || source.status === 'blocked' ? (
                    <AlertTriangle size={10} />
                  ) : source.status === 'ready' ? (
                    <Check size={10} />
                  ) : (
                    <Clock size={10} />
                  )}
                  {STATUS_LABEL[source.status] || source.status}
                </span>
                {source.tags.length ? (
                  <span className="source-card__tags">
                    {source.tags.slice(0, 3).map((tag) => (
                      <span key={tag} className="knowledge-tag">
                        {tag}
                      </span>
                    ))}
                  </span>
                ) : null}
                <span className="source-card__badges">
                  {source.local_only !== false ? (
                    <span className="knowledge-pill knowledge-pill--ok">Local only</span>
                  ) : null}
                  {source.redacted ? (
                    <span className="knowledge-pill knowledge-pill--error">Redacted</span>
                  ) : null}
                </span>
                <div className="source-card__actions">
                  <button
                    type="button"
                    className="ui-icon-btn"
                    title={source.favorite ? 'Unfavorite' : 'Favorite'}
                    aria-label={source.favorite ? 'Unfavorite' : 'Favorite'}
                    onClick={() => void act(source, 'favorite')}
                  >
                    <Star size={13} fill={source.favorite ? 'currentColor' : 'none'} />
                  </button>
                  <button
                    type="button"
                    className="ui-icon-btn"
                    title="Mark read"
                    aria-label="Mark read"
                    onClick={() => void act(source, 'state')}
                  >
                    <Check size={13} />
                  </button>
                  <button
                    type="button"
                    className="ui-icon-btn"
                    title={source.redacted ? 'Unredact' : 'Redact content'}
                    aria-label={source.redacted ? 'Unredact' : 'Redact content'}
                    onClick={() =>
                      void api.spaces.sources
                        .update(spaceId, source.id, { redacted: !source.redacted })
                        .then(() => void fetchSources())
                    }
                  >
                    {source.redacted ? <Eye size={13} /> : <EyeOff size={13} />}
                  </button>
                  {source.kind === 'web' ? (
                    <button
                      type="button"
                      className="ui-icon-btn"
                      title="Refresh source"
                      aria-label="Refresh source"
                      onClick={() => void act(source, 'refresh')}
                    >
                      <RefreshCw size={13} />
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="ui-icon-btn"
                    title="Remove"
                    aria-label="Remove"
                    onClick={() => void act(source, 'delete')}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      <Dialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="Save to this space"
        subtitle="Paste links or write a note. Links are fetched, cleaned and indexed locally."
        width={640}
        footer={
          <>
            <button type="button" className="ui-btn" onClick={() => setAddOpen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="ui-btn ui-btn--primary"
              disabled={
                adding ||
                (addMode === 'link'
                  ? !urls.trim()
                  : addMode === 'feed'
                    ? !feedUrl.trim()
                    : addMode === 'site'
                      ? !crawlUrl.trim()
                      : !noteText.trim())
              }
              onClick={() => void addSources()}
            >
              {adding
                ? 'Saving…'
                : addMode === 'link'
                  ? 'Save links'
                  : addMode === 'feed'
                    ? 'Subscribe'
                    : addMode === 'site'
                      ? 'Crawl site'
                      : 'Save note'}
            </button>
          </>
        }
      >
        <div className="source-add">
          <div className="space-create__modes space-create__modes--four" role="tablist" aria-label="Source type">
            <button
              type="button"
              className={`space-create__mode${addMode === 'link' ? ' is-active' : ''}`}
              role="tab"
              aria-selected={addMode === 'link'}
              onClick={() => setAddMode('link')}
            >
              <Globe size={15} />
              <span>
                <strong>Web links</strong>
                <small>One URL per line</small>
              </span>
            </button>
            <button
              type="button"
              className={`space-create__mode${addMode === 'text' ? ' is-active' : ''}`}
              role="tab"
              aria-selected={addMode === 'text'}
              onClick={() => setAddMode('text')}
            >
              <FileText size={15} />
              <span>
                <strong>Note</strong>
                <small>Paste text to keep</small>
              </span>
            </button>
            <button
              type="button"
              className={`space-create__mode${addMode === 'feed' ? ' is-active' : ''}`}
              role="tab"
              aria-selected={addMode === 'feed'}
              onClick={() => setAddMode('feed')}
            >
              <RefreshCw size={15} />
              <span>
                <strong>Feed</strong>
                <small>RSS or Atom</small>
              </span>
            </button>
            <button
              type="button"
              className={`space-create__mode${addMode === 'site' ? ' is-active' : ''}`}
              role="tab"
              aria-selected={addMode === 'site'}
              onClick={() => setAddMode('site')}
            >
              <ExternalLink size={15} />
              <span>
                <strong>Site</strong>
                <small>Crawl same-site pages</small>
              </span>
            </button>
          </div>

          {addMode === 'link' ? (
            <label className="space-create__field">
              <span>Links</span>
              <textarea
                className="ui-input"
                rows={7}
                value={urls}
                placeholder={'https://example.com/article\nhttps://another.site/post\nhttps://example.com/paper.pdf'}
                onChange={(e) => setUrls(e.target.value)}
              />
            </label>
          ) : addMode === 'feed' ? (
            <label className="space-create__field">
              <span>Feed URL</span>
              <input
                className="ui-input"
                value={feedUrl}
                placeholder="https://example.com/feed.xml"
                onChange={(e) => setFeedUrl(e.target.value)}
              />
              <small className="knowledge-muted">
                The latest items are saved as individual web sources and indexed.
              </small>
            </label>
          ) : addMode === 'site' ? (
            <label className="space-create__field">
              <span>Starting page</span>
              <input
                className="ui-input"
                value={crawlUrl}
                placeholder="https://example.com/docs"
                onChange={(e) => setCrawlUrl(e.target.value)}
              />
              <small className="knowledge-muted">
                Saves the page and up to 10 same-site links it points to.
              </small>
            </label>
          ) : (
            <>
              <label className="space-create__field">
                <span>Title</span>
                <input
                  className="ui-input"
                  value={noteTitle}
                  placeholder="Optional title"
                  onChange={(e) => setNoteTitle(e.target.value)}
                />
              </label>
              <label className="space-create__field">
                <span>Note</span>
                <textarea
                  className="ui-input"
                  rows={8}
                  value={noteText}
                  placeholder="Paste or write anything you want searchable…"
                  onChange={(e) => setNoteText(e.target.value)}
                />
              </label>
            </>
          )}
        </div>
      </Dialog>

      <Dialog
        open={Boolean(reader)}
        onClose={() => setReader(null)}        title={reader?.source.title || reader?.source.url || 'Source'}
        subtitle={
          reader?.source.site
            ? `${reader.source.site}${reader.source.published_at ? ` · ${reader.source.published_at.slice(0, 10)}` : ''}`
            : reader?.source.kind
        }
        width={820}
        footer={
          reader ? (
            <>
              {reader.source.url ? (
                <a className="ui-btn" href={reader.source.url} target="_blank" rel="noreferrer">
                  <ExternalLink size={13} /> Open original
                </a>
              ) : null}
              <button
                type="button"
                className="ui-btn"
                onClick={() => void act(reader.source, 'reindex')}
              >
                <RefreshCw size={13} /> Reindex
              </button>
              <button type="button" className="ui-btn ui-btn--primary" onClick={() => void saveNote()}>
                Save note
              </button>
            </>
          ) : null
        }
      >
        {readerLoading ? (
          <SkeletonList rows={6} avatar={false} />
        ) : reader ? (
          <div className="source-reader">
            <div className="source-reader__meta">
              <span className={`knowledge-pill knowledge-pill--${statusTone(reader.source.status)}`}>
                {STATUS_LABEL[reader.source.status] || reader.source.status}
              </span>
              {reader.source.redacted ? (
                <span className="knowledge-pill knowledge-pill--error">Redacted</span>
              ) : (
                <span className="knowledge-pill knowledge-pill--ok">Local only</span>
              )}
              {reader.source.author ? <span>By {reader.source.author}</span> : null}
              {reader.source.fetched_at ? <span>Saved {dateLabel(reader.source.fetched_at)}</span> : null}
              {reader.source.file_path ? (
                <code title={reader.source.file_path}>{reader.source.file_path}</code>
              ) : null}
            </div>
            <label className="space-create__field">
              <span>Your note</span>
              <textarea
                className="ui-input"
                rows={2}
                value={readerNote}
                placeholder="Why did you save this?"
                onChange={(e) => setReaderNote(e.target.value)}
              />
            </label>
            <pre className="source-reader__content">{stripFrontMatter(reader.content)}</pre>
            {reader.related?.length ? (
              <div className="source-reader__related">
                <span>Related sources</span>
                <div>
                  {reader.related.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className="knowledge-tag"
                      onClick={() => void openReader(item)}
                      title={item.url || item.file_path}
                    >
                      {item.title || item.url}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </Dialog>

      <SpaceSettingsDialog
        open={settingsOpen}
        spaceId={spaceId}
        onClose={() => setSettingsOpen(false)}
        onChanged={() => {
          void fetchSources();
        }}
      />
      <SavedSearchesDialog
        open={searchesOpen}
        spaceId={spaceId}
        onClose={() => setSearchesOpen(false)}
      />
    </div>
  );
}
