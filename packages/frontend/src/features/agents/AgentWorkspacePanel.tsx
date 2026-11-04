import { useCallback, useEffect, useState } from 'react';
import { FileText, Folder, Trash2, X } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { Button, EmptyState, Spinner } from '../../ui/primitives';
import type { WorkspaceFile } from '../../types';
import './AgentWorkspacePanel.css';

export default function AgentWorkspacePanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { selectedAgentId, addToast } = useApp();
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [path, setPath] = useState('');
  const [root, setRoot] = useState('');
  const [preview, setPreview] = useState<{ path: string; content: string; binary: boolean } | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(
    async (target = '') => {
      if (!selectedAgentId) return;
      setLoading(true);
      try {
        const res = await api.agents.workspace.list(selectedAgentId, target);
        setFiles(res.files || []);
        setPath(res.path || target);
        setRoot(res.root || '');
      } catch {
        // best effort
      }
      setLoading(false);
    },
    [selectedAgentId],
  );

  useEffect(() => {
    if (!open || !selectedAgentId) return;
    setPreview(null);
    void refresh('');
  }, [open, selectedAgentId, refresh]);

  const openFile = async (file: WorkspaceFile) => {
    if (!selectedAgentId) return;
    if (file.type === 'directory') {
      void refresh(file.path);
      return;
    }
    const res = await api.agents.workspace.read(selectedAgentId, file.path);
    if (res.error) addToast(res.error, { tone: 'error' });
    else setPreview({ path: file.path, content: res.content || '', binary: !!res.binary });
  };

  const remove = async (file: WorkspaceFile) => {
    if (!selectedAgentId) return;
    const res = await api.agents.workspace.remove(selectedAgentId, file.path);
    if (res.error) addToast(res.error, { tone: 'error' });
    else {
      setPreview(null);
      void refresh(path);
    }
  };

  if (!open) return null;

  return (
    <div className="awp" role="dialog" aria-modal="true" aria-label="Agent workspace">
      <button type="button" className="awp__scrim" onClick={onClose} aria-label="Close workspace" />
      <aside className="awp__panel">
        <header className="awp__head">
          <div>
            <h2>
              <Folder size={15} /> Workspace
            </h2>
            <p>{root || 'Files this agent writes and reads.'}</p>
          </div>
          <button type="button" className="awp__close" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </header>

        <div className="awp__body">
          {!selectedAgentId ? (
            <EmptyState icon={<Folder size={22} />} title="No agent selected" description="Pick an agent first." />
          ) : preview ? (
            <div className="awp__preview">
              <div className="awp__preview-head">
                <Button size="sm" variant="ghost" onClick={() => setPreview(null)}>
                  Back
                </Button>
                <span className="awp__preview-path">{preview.path}</span>
              </div>
              {preview.binary ? (
                <p className="ah-panel__empty">Binary file — download to view.</p>
              ) : (
                <pre className="awp__preview-body">{preview.content}</pre>
              )}
            </div>
          ) : (
            <>
              <div className="awp__path">
                <button type="button" onClick={() => void refresh('')}>
                  workspace
                </button>
                {path && <span>/ {path}</span>}
              </div>
              {loading ? (
                <div className="awp__loading">
                  <Spinner size={14} /> Loading files…
                </div>
              ) : files.length === 0 ? (
                <EmptyState
                  icon={<Folder size={22} />}
                  title="No files yet"
                  description="When this agent writes a deliverable it appears here. Every agent has its own persistent workspace."
                />
              ) : (
                <div className="awp__list">
                  {files.map((file) => (
                    <div key={file.path} className="awp__row">
                      <button type="button" className="awp__row-main" onClick={() => void openFile(file)}>
                        {file.type === 'directory' ? <Folder size={14} /> : <FileText size={14} />}
                        <span className="awp__row-name">{file.name}</span>
                        {file.type === 'file' && <span className="awp__row-size">{formatSize(file.size)}</span>}
                      </button>
                      <button type="button" className="awp__row-del" onClick={() => void remove(file)} aria-label="Delete">
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
