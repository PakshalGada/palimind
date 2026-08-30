import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import type { DirItem } from '../types';
import LoadingSpinner from './LoadingSpinner';

export default function DirectoryPicker() {
  const [currentPath, setCurrentPath] = useState('');
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [items, setItems] = useState<DirItem[]>([]);
  const [selectedPath, setSelectedPath] = useState('');
  const [loading, setLoading] = useState(false);

  const loadPath = useCallback(async (path?: string) => {
    setLoading(true);
    try {
      const data = await api.fs.list(path);
      if (data.error) { alert(data.error); return; }
      setCurrentPath(data.current_path);
      setParentPath(data.parent_path || null);
      setItems(data.items);
    } catch (e) {
      console.error('dir picker error:', e);
    }
    setLoading(false);
  }, []);

  const close = () => {
    const modal = document.getElementById('dir-picker-modal');
    if (modal) modal.style.display = 'none';
  };

  useEffect(() => {
    const handler = () => loadPath();
    window.addEventListener('palimind:open-dir-picker', handler);
    return () => window.removeEventListener('palimind:open-dir-picker', handler);
  }, [loadPath]);

  useEffect(() => {
    const modal = document.getElementById('dir-picker-modal');
    if (!modal) return;
    const clickHandler = (e: MouseEvent) => {
      if (e.target === modal) close();
    };
    modal.addEventListener('click', clickHandler);
    return () => modal.removeEventListener('click', clickHandler);
  }, []);

  const handleSelect = async () => {
    if (!selectedPath) return;
    close();
    const addData = await api.fields.add(selectedPath);
    if (!addData.error) {
      window.dispatchEvent(new CustomEvent('palimind:field-added'));
    } else {
      alert(addData.error);
    }
  };

  return (
    <div id="dir-picker-modal" className="modal" role="dialog" aria-modal="true" aria-labelledby="dir-picker-title" style={{ display: 'none' }}>
      <div className="modal-content dir-picker-content">
        <div className="modal-header">
          <h2 id="dir-picker-title">Choose Workspace Directory</h2>
          <button className="icon-btn" title="Cancel" aria-label="Close directory picker" onClick={close}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="modal-body dir-picker-body">
          <div className="dir-picker-path-row">
            <button
              className="icon-btn"
              title="Go Up"
              aria-label="Go up one directory"
              disabled={!parentPath}
              style={{ opacity: parentPath ? 1 : 0.4 }}
              onClick={() => parentPath && loadPath(parentPath)}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
              </svg>
            </button>
            <input
              type="text"
              aria-label="Current directory path"
              readOnly
              value={currentPath}
              style={{
                flex: 1,
                background: 'var(--input-bg)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-main)',
                padding: '8px 12px',
                borderRadius: 8,
                fontFamily: "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
                fontSize: '0.85rem',
                outline: 'none',
              }}
            />
          </div>
          <div className="dir-picker-list" id="dir-picker-list">
            {loading && <LoadingSpinner size="sm" text="Loading directory contents..." className="model-list-loading" />}
            {items.map((item, idx) => (
              <div
                key={idx}
                className={`dir-item ${item.type === 'file' ? 'file-item-disabled' : ''} ${item.path === selectedPath ? 'selected' : ''}`}
                onClick={() => {
                  if (item.type === 'directory') {
                    setSelectedPath(item.path);
                  }
                }}
                onDoubleClick={() => {
                  if (item.type === 'directory') loadPath(item.path);
                }}
              >
                <span className="dir-item-icon">
                  {item.type === 'directory' ? (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                    </svg>
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><polyline points="13 2 13 9 20 9" />
                    </svg>
                  )}
                </span>
                <span>{item.name}</span>
              </div>
            ))}
          </div>
          <div className="dir-picker-footer">
            <button className="primary-btn" onClick={handleSelect}>
              Select Current Folder
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
