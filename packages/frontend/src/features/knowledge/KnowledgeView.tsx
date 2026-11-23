import { useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpen, FolderPlus, Globe, Network, Plus, RefreshCw } from 'lucide-react';
import ChatArea from '../../components/ChatArea';
import SurfaceHeader from '../../components/layout/SurfaceHeader';
import { useApp } from '../../AppContext';
import { api } from '../../api';
import { runCommand } from '../../commands/registry';
import { EmptyState } from '../../ui/primitives';
import { PixelGlyph } from '../../components/pixel/PixelGlyph';
import type { KnowledgeSpace } from '../../types';
import CreateSpaceDialog from './CreateSpaceDialog';
import SourcesPanel from './SourcesPanel';
import '../view.css';
import './KnowledgeView.css';

type Tab = 'chat' | 'sources' | 'graph';

function leaf(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export default function KnowledgeView() {
  const { activeField, isIndexing, indexingStatus, addToast } = useApp();
  const [spaces, setSpaces] = useState<KnowledgeSpace[]>([]);
  const [activeSpaceId, setActiveSpaceId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('chat');
  const [createOpen, setCreateOpen] = useState(false);
  const [createMode, setCreateMode] = useState<'create' | 'link'>('create');
  const [sourceCount, setSourceCount] = useState(0);
  const [graphStats, setGraphStats] = useState<{ nodes: number; edges: number } | null>(null);

  const fetchSpaces = useCallback(async () => {
    try {
      const data = await api.spaces.list();
      setSpaces(data.spaces || []);
      setActiveSpaceId(data.active_space_id || null);
    } catch {
      // The legacy /fields endpoint still drives the rest of the app.
    }
  }, []);

  useEffect(() => {
    void fetchSpaces();
    const handler = () => void fetchSpaces();
    window.addEventListener('palimind:spaces-changed', handler);
    window.addEventListener('palimind:field-added', handler);
    return () => {
      window.removeEventListener('palimind:spaces-changed', handler);
      window.removeEventListener('palimind:field-added', handler);
    };
  }, [fetchSpaces]);

  const activeSpace = useMemo(() => {
    return (
      spaces.find((space) => space.id === activeSpaceId) ||
      spaces.find((space) => space.root === activeField) ||
      null
    );
  }, [spaces, activeSpaceId, activeField]);

  useEffect(() => {
    if (tab !== 'graph' || !activeSpace) return;
    let cancelled = false;
    void (async () => {
      try {
        const data = await api.graph.get();
        if (!cancelled) {
          setGraphStats({ nodes: data.nodes?.length ?? 0, edges: data.edges?.length ?? 0 });
        }
      } catch {
        if (!cancelled) setGraphStats(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tab, activeSpace]);

  const activate = async (space: KnowledgeSpace) => {
    try {
      const data = await api.spaces.activate(space.id);
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      setActiveSpaceId(space.id);
      window.dispatchEvent(new CustomEvent('palimind:spaces-changed'));
      window.dispatchEvent(new CustomEvent('palimind:field-added'));
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not open the space.', { tone: 'error' });
    }
  };

  const openCreate = (mode: 'create' | 'link') => {
    setCreateMode(mode);
    setCreateOpen(true);
  };

  const sync = async () => {
    try {
      const data = await api.sync();
      if (data.status === 'success') {
        addToast(`Synced: ${data.indexed_files} added, ${data.deleted_files} removed`, {
          tone: 'success',
        });
        window.dispatchEvent(new CustomEvent('palimind:sources-changed'));
      } else {
        addToast(`Sync error: ${data.error}`, { tone: 'error' });
      }
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Sync failed.', { tone: 'error' });
    }
  };

  return (
    <div className="view-frame">
      <SurfaceHeader
        title={activeSpace?.name || (activeField ? leaf(activeField) : 'Knowledge')}
        meta={
          activeSpace
            ? isIndexing
              ? indexingStatus || 'Indexing documents…'
              : `${activeSpace.kind === 'managed' ? 'New folder' : 'Linked folder'} · ${activeSpace.root}`
            : 'Create a space or connect a folder — no existing folder required'
        }
        actions={
          activeSpace ? (
            <>
              <button
                type="button"
                className="ui-btn ui-btn--sm"
                onClick={() => {
                  setTab('sources');
                  window.dispatchEvent(new CustomEvent('palimind:add-source'));
                }}
              >
                <Globe size={13} /> Save link
              </button>
              <button
                type="button"
                className="ui-btn ui-btn--sm"
                onClick={() => openCreate('create')}
              >
                <Plus size={13} /> New space
              </button>
              <button
                type="button"
                className="ui-btn ui-btn--sm"
                onClick={() => runCommand('nav.graph')}
              >
                <Network size={13} /> Graph
              </button>
              <a
                className="ui-btn ui-btn--sm"
                href={`/api/spaces/${encodeURIComponent(activeSpace.id)}/export`}
                download
              >
                Export
              </a>
              <button
                type="button"
                className="ui-btn ui-btn--primary ui-btn--sm"
                onClick={() => void sync()}
                disabled={isIndexing}
              >
                <RefreshCw size={13} /> {isIndexing ? 'Indexing…' : 'Sync'}
              </button>
            </>
          ) : undefined
        }
      />

      {activeSpace ? (
        <>
          <div className="knowledge-tabs" role="tablist" aria-label="Knowledge workspace">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'chat'}
              className={`knowledge-tab${tab === 'chat' ? ' is-active' : ''}`}
              onClick={() => setTab('chat')}
            >
              <BookOpen size={14} /> Chat
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'sources'}
              className={`knowledge-tab${tab === 'sources' ? ' is-active' : ''}`}
              onClick={() => setTab('sources')}
            >
              <Globe size={14} /> Sources
              <span className="knowledge-tab__count">{sourceCount}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'graph'}
              className={`knowledge-tab${tab === 'graph' ? ' is-active' : ''}`}
              onClick={() => setTab('graph')}
            >
              <Network size={14} /> Graph
            </button>

            {spaces.length > 1 ? (
              <select
                className="ui-select knowledge-space-select"
                value={activeSpace.id}
                onChange={(e) => {
                  const next = spaces.find((space) => space.id === e.target.value);
                  if (next) void activate(next);
                }}
                aria-label="Switch knowledge space"
              >
                {spaces.map((space) => (
                  <option key={space.id} value={space.id}>
                    {space.name}
                  </option>
                ))}
              </select>
            ) : null}
          </div>

          {tab === 'chat' ? (
            <div className="view-frame__chat">
              <ChatArea />
            </div>
          ) : tab === 'sources' ? (
            <SourcesPanel spaceId={activeSpace.id} onCountChange={setSourceCount} />
          ) : (
            <div className="knowledge-graph-tab">
              <div className="knowledge-graph-tab__card">
                <Network size={20} />
                <h3>Knowledge graph</h3>
                <p>
                  {graphStats
                    ? `${graphStats.nodes} nodes and ${graphStats.edges} relationships across this space.`
                    : 'Build the graph from your indexed sources to explore entities and relationships.'}
                </p>
                <div className="knowledge-graph-tab__actions">
                  <button
                    type="button"
                    className="ui-btn ui-btn--primary"
                    onClick={() => runCommand('nav.graph')}
                  >
                    Open graph
                  </button>
                  <button
                    type="button"
                    className="ui-btn"
                    onClick={() => {
                      void api.graph.rebuild().then(() => {
                        addToast('Rebuilding the knowledge graph…', { tone: 'success' });
                      });
                    }}
                  >
                    Rebuild
                  </button>
                  <a
                    className="ui-btn"
                    href={`/api/spaces/${encodeURIComponent(activeSpace.id)}/graph/export?format=json`}
                    download
                  >
                    Export JSON
                  </a>
                  <a
                    className="ui-btn"
                    href={`/api/spaces/${encodeURIComponent(activeSpace.id)}/graph/export?format=graphml`}
                    download
                  >
                    GraphML
                  </a>
                </div>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="view-frame__body">
          <EmptyState
            glyph={<PixelGlyph sprite="book" cell={4} />}
            title="Create your first knowledge space"
            description="You don't need a folder on this computer. PaliMind can create one anywhere you choose, then you can paste links and notes and ask questions with citations."
            action={
              <div className="knowledge-empty-actions">
                <button
                  type="button"
                  className="ui-btn ui-btn--primary"
                  onClick={() => openCreate('create')}
                >
                  <FolderPlus size={14} /> Create a space
                </button>
                <button type="button" className="ui-btn" onClick={() => openCreate('link')}>
                  Connect a folder
                </button>
              </div>
            }
          />
          {spaces.length ? (
            <div className="knowledge-space-list">
              {spaces.map((space) => (
                <button
                  key={space.id}
                  type="button"
                  className="knowledge-space-card"
                  onClick={() => void activate(space)}
                >
                  <strong>{space.name}</strong>
                  <span>{space.root}</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      )}

      <CreateSpaceDialog
        open={createOpen}
        initialMode={createMode}
        onClose={() => setCreateOpen(false)}
        onCreated={(space) => {
          setActiveSpaceId(space.id);
          setTab('sources');
          void fetchSpaces();
        }}
      />
    </div>
  );
}
