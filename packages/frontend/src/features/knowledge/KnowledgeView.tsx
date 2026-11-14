import { useEffect, useState } from 'react';
import ChatArea from '../../components/ChatArea';
import SurfaceHeader from '../../components/layout/SurfaceHeader';
import { useApp } from '../../AppContext';
import { runCommand } from '../../commands/registry';
import { EmptyState } from '../../ui/primitives';
import { PixelGlyph } from '../../components/pixel/PixelGlyph';
import { PixelIcon } from '../../components/pixel/PixelIcon';
import '../view.css';

function leaf(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export default function KnowledgeView() {
  const { activeField, isIndexing, indexingStatus } = useApp();
  const [offline, setOffline] = useState(
    () => document.documentElement.dataset.connection === 'offline',
  );

  useEffect(() => {
    const onConnection = (event: Event) => {
      const detail = (event as CustomEvent<{ ok?: boolean }>).detail;
      if (typeof detail?.ok === 'boolean') setOffline(!detail.ok);
    };
    window.addEventListener('palimind:connection', onConnection);
    return () => window.removeEventListener('palimind:connection', onConnection);
  }, []);

  return (
    <div className="view-frame">
      <SurfaceHeader
        title={activeField ? leaf(activeField) : 'Knowledge'}
        meta={
          activeField
            ? isIndexing
              ? indexingStatus || 'Indexing documents…'
              : 'Indexed locally · semantic search ready'
            : 'Add a folder to index documents on this device'
        }
        actions={
          activeField ? (
            <>
              <button
                type="button"
                className="ui-btn ui-btn--sm"
                onClick={() => {
                  window.dispatchEvent(new CustomEvent('palimind:open-dir-picker'));
                }}
              >
                <PixelIcon name="folder" size={16} /> Add folder
              </button>
              <button
                type="button"
                className="ui-btn ui-btn--sm"
                onClick={() => runCommand('nav.graph')}
              >
                <PixelIcon name="graph" size={16} /> Graph
              </button>
              <button
                type="button"
                className="ui-btn ui-btn--primary ui-btn--sm"
                onClick={() => runCommand('nav.sync')}
                disabled={isIndexing}
              >
                <PixelIcon name="refresh" size={16} /> {isIndexing ? 'Indexing…' : 'Sync'}
              </button>
            </>
          ) : undefined
        }
      />
      {activeField ? (
        <div className="view-frame__chat">
          <ChatArea />
        </div>
      ) : (
        <div className="view-frame__body">
          {offline ? (
            <EmptyState
              glyph={<PixelGlyph sprite="cross" cell={4} />}
              title="Local engine not connected"
              description="Start PaliMind, then retry. Your knowledge folders stay on this device and are safe."
              action={
                <button
                  type="button"
                  className="ui-btn ui-btn--primary"
                  onClick={() => window.location.reload()}
                >
                  <PixelIcon name="refresh" size={16} /> Retry
                </button>
              }
            />
          ) : (
            <EmptyState
              glyph={<PixelGlyph sprite="book" cell={4} />}
              title="Add your first knowledge folder"
              description="Point PaliMind at a folder of notes, PDFs or code. Everything is indexed on this device and answers cite the source files."
              action={
                <button
                  type="button"
                  className="ui-btn ui-btn--primary"
                  onClick={() => window.dispatchEvent(new CustomEvent('palimind:open-dir-picker'))}
                >
                  <PixelIcon name="folder" size={16} /> Add folder
                </button>
              }
            />
          )}
        </div>
      )}
    </div>
  );
}
