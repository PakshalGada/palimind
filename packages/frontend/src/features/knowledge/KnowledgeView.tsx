import { FolderPlus, Network, RefreshCw } from 'lucide-react';
import ChatArea from '../../components/ChatArea';
import SurfaceHeader from '../../components/layout/SurfaceHeader';
import { useApp } from '../../AppContext';
import { runCommand } from '../../commands/registry';
import { EmptyState } from '../../ui/primitives';
import { PixelGlyph } from '../../components/pixel/PixelGlyph';
import '../view.css';

function leaf(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export default function KnowledgeView() {
  const { activeField, isIndexing, indexingStatus } = useApp();

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
                <FolderPlus size={13} /> Add folder
              </button>
              <button
                type="button"
                className="ui-btn ui-btn--sm"
                onClick={() => runCommand('nav.graph')}
              >
                <Network size={13} /> Graph
              </button>
              <button
                type="button"
                className="ui-btn ui-btn--primary ui-btn--sm"
                onClick={() => runCommand('nav.sync')}
                disabled={isIndexing}
              >
                <RefreshCw size={13} /> {isIndexing ? 'Indexing…' : 'Sync'}
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
                <FolderPlus size={14} /> Add folder
              </button>
            }
          />
        </div>
      )}
    </div>
  );
}
