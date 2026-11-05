import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import type { DirItem } from '../types';
import { useApp } from '../AppContext';
import { Dialog, EmptyState, IconButton, SkeletonList } from '../ui/primitives';
import { PixelGlyph } from './pixel/PixelGlyph';

/**
 * Folder picker built on the shared Dialog primitive: portal, focus trap,
 * Escape handling, aria and a single scroll lock now come for free.
 */
export default function DirectoryPicker() {
  const { addToast } = useApp();
  const [open, setOpen] = useState(false);
  const [currentPath, setCurrentPath] = useState('');
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [items, setItems] = useState<DirItem[]>([]);
  const [selectedPath, setSelectedPath] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPath = useCallback(async (path?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.fs.list(path);
      if (data.error) {
        setError('Could not read that folder.');
        return;
      }
      setCurrentPath(data.current_path);
      setParentPath(data.parent_path || null);
      setItems(data.items ?? []);
    } catch {
      setError('Could not read that folder.');
    } finally {
      setLoading(false);
    }
  }, []);

  const close = () => setOpen(false);

  useEffect(() => {
    const handler = () => {
      setSelectedPath('');
      setOpen(true);
    };
    window.addEventListener('palimind:open-dir-picker', handler);
    return () => window.removeEventListener('palimind:open-dir-picker', handler);
  }, []);

  useEffect(() => {
    if (!open) return;
    void loadPath();
  }, [open, loadPath]);

  const handleSelect = async () => {
    if (!selectedPath) return;
    setOpen(false);
    try {
      const addData = await api.fields.add(selectedPath);
      if (!addData.error) {
        window.dispatchEvent(new CustomEvent('palimind:field-added'));
        addToast('Folder added to your workspace', { tone: 'success' });
      } else {
        addToast(addData.error, { tone: 'error' });
      }
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not add the folder.', {
        tone: 'error',
      });
    }
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Choose workspace folder"
      subtitle="Index a folder locally. Nothing leaves this machine."
      width={720}
      footer={
        <>
          <button type="button" className="ui-btn" onClick={close}>
            Cancel
          </button>
          <button
            type="button"
            className="ui-btn ui-btn--primary"
            disabled={!selectedPath}
            onClick={() => void handleSelect()}
          >
            Add folder
          </button>
        </>
      }
    >
      <div className="dir-picker">
        <div className="dir-picker-path-row">
          <button
            type="button"
            className="ui-icon-btn"
            title="Go up one directory"
            aria-label="Go up one directory"
            disabled={!parentPath}
            onClick={() => parentPath && void loadPath(parentPath)}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
          </button>
          <input
            type="text"
            className="ui-input dir-picker-path"
            aria-label="Current directory path"
            readOnly
            value={currentPath}
          />
        </div>

        <div className="dir-picker-list" role="listbox" aria-label="Folders">
          {loading ? (
            <SkeletonList rows={5} avatar={false} />
          ) : error ? (
            <EmptyState
              compact
              glyph={<PixelGlyph sprite="cross" cell={2} />}
              title="Couldn't read this folder"
              description={error}
              action={
                <button type="button" className="ui-btn ui-btn--sm" onClick={() => void loadPath(currentPath)}>
                  Retry
                </button>
              }
            />
          ) : items.length === 0 ? (
            <EmptyState
              compact
              glyph={<PixelGlyph sprite="folder" cell={2} />}
              title="This folder is empty"
              description="Pick this folder, or go up and choose another one."
            />
          ) : (
            items.map((item) => (
              <button
                key={item.path}
                type="button"
                role="option"
                aria-selected={item.path === selectedPath}
                className={`dir-item${item.type === 'file' ? ' is-file' : ''}${
                  item.path === selectedPath ? ' is-selected' : ''
                }`}
                disabled={item.type === 'file'}
                onClick={() => item.type === 'directory' && setSelectedPath(item.path)}
                onDoubleClick={() => item.type === 'directory' && void loadPath(item.path)}
              >
                <span className="dir-item-icon">
                  <PixelGlyph sprite={item.type === 'directory' ? 'folder' : 'terminal'} cell={1.6} />
                </span>
                <span className="dir-item-name">{item.name}</span>
                {item.path === selectedPath && (
                  <span className="dir-item-check" aria-label="Selected">
                    <PixelGlyph sprite="check" cell={1.4} />
                  </span>
                )}
              </button>
            ))
          )}
        </div>

        <div className="dir-picker-selection" title={selectedPath || undefined}>
          {selectedPath ? (
            <>
              <PixelGlyph sprite="check" cell={1.3} />
              <span>{selectedPath}</span>
            </>
          ) : (
            <span>Select a folder to add. Double-click to open it.</span>
          )}
          <IconButton
            label="Refresh folder"
            className="dir-picker-refresh"
            onClick={() => void loadPath(currentPath)}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
          </IconButton>
        </div>
      </div>
    </Dialog>
  );
}
