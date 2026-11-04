import { BookOpen, FolderPlus, Network, RefreshCw } from 'lucide-react';
import ChatArea from '../../components/ChatArea';
import PageTitle from '../../components/layout/PageTitle';
import { useApp } from '../../AppContext';
import { runCommand } from '../../commands/registry';
import { PixelSweep } from '../../components/pixel/PixelSweep';
import '../view.css';

function leaf(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export default function KnowledgeView() {
  const { activeField, isIndexing, indexingStatus } = useApp();

  return (
    <div className="view-frame">
      <PageTitle
        eyebrow="Knowledge"
        title={activeField ? leaf(activeField) : 'Knowledge'}
        subtitle={
          activeField
            ? isIndexing
              ? indexingStatus || 'Indexing documents…'
              : 'Indexed locally · semantic search ready'
            : 'Add a folder to index documents on this device.'
        }
        actions={
          <>
            <button
              type="button"
              className="ui-btn ui-btn--sm"
              onClick={() => {
                const modal = document.getElementById('dir-picker-modal');
                if (modal) {
                  modal.style.display = 'flex';
                  window.dispatchEvent(new CustomEvent('palimind:open-dir-picker'));
                }
              }}
            >
              <FolderPlus size={13} /> Add folder
            </button>
            <button
              type="button"
              className="ui-btn ui-btn--sm"
              onClick={() => runCommand('nav.graph')}
              disabled={!activeField}
            >
              <Network size={13} /> Graph
            </button>
            <button
              type="button"
              className="ui-btn ui-btn--primary ui-btn--sm"
              onClick={() => runCommand('nav.sync')}
              disabled={!activeField || isIndexing}
            >
              <RefreshCw size={13} /> {isIndexing ? 'Indexing…' : 'Sync'}
            </button>
          </>
        }
      />
      {activeField && (
        <div className="view-meta">
          {isIndexing ? (
            <PixelSweep label={indexingStatus || 'Indexing'}>
              <BookOpen size={13} />
            </PixelSweep>
          ) : (
            <BookOpen size={13} />
          )}
          <span className="view-meta__path" title={activeField}>
            {activeField}
          </span>
        </div>
      )}
      <div className="view-frame__chat">
        <ChatArea />
      </div>
    </div>
  );
}
