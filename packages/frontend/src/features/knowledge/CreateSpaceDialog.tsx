import { useCallback, useEffect, useState } from 'react';
import { Folder, FolderPlus, Link2 } from 'lucide-react';
import { api } from '../../api';
import type { DirItem, KnowledgeSpace } from '../../types';
import { useApp } from '../../AppContext';
import { Dialog, EmptyState, SkeletonList } from '../../ui/primitives';

type Mode = 'create' | 'link';

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated?: (space: KnowledgeSpace) => void;
  initialMode?: Mode;
}

/**
 * Create a knowledge space anywhere the user wants:
 *  - "create" makes a new folder under a chosen parent;
 *  - "link" adopts an existing folder without moving it.
 */
export default function CreateSpaceDialog({ open, onClose, onCreated, initialMode = 'create' }: Props) {
  const { addToast } = useApp();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [name, setName] = useState('');
  const [folderName, setFolderName] = useState('');
  const [path, setPath] = useState('');
  const [current, setCurrent] = useState('');
  const [parent, setParent] = useState<string | null>(null);
  const [items, setItems] = useState<DirItem[]>([]);
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (target?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.fs.list(target);
      if (data.error) {
        setError('Could not read that folder.');
        return;
      }
      setCurrent(data.current_path);
      setParent(data.parent_path || null);
      setItems((data.items || []).filter((item) => item.type === 'directory'));
      setPath(data.current_path);
      setSelected('');
    } catch {
      setError('Could not read that folder.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setMode(initialMode);
    setName('');
    setFolderName('');
    setSelected('');
    setError(null);
    void (async () => {
      try {
        const data = await api.spaces.list();
        const start = data.default_parent || '';
        setPath(start);
        await load(start || undefined);
      } catch {
        await load();
      }
    })();
  }, [open, initialMode, load]);

  useEffect(() => {
    if (!open) return;
    if (!folderName && name) setFolderName(name);
  }, [name, folderName, open]);

  const submit = async () => {
    if (!name.trim()) {
      setError('Give the knowledge space a name.');
      return;
    }
    const location = selected || path || current;
    if (!location) {
      setError('Choose a folder.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload =
        mode === 'create'
          ? {
              name: name.trim(),
              mode: 'create' as const,
              parent_dir: location,
              folder_name: (folderName || name).trim(),
              index: true,
            }
          : {
              name: name.trim(),
              mode: 'link' as const,
              root: location,
              index: true,
            };
      const data = await api.spaces.create(payload);
      if (data.error || !data.space) {
        setError(data.error || 'Could not create the space.');
        return;
      }
      window.dispatchEvent(new CustomEvent('palimind:spaces-changed'));
      window.dispatchEvent(new CustomEvent('palimind:field-added'));
      addToast(`Space "${data.space.name}" is ready`, { tone: 'success' });
      onCreated?.(data.space);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the space.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={mode === 'create' ? 'Create a knowledge space' : 'Connect a folder'}
      subtitle="Everything stays on this device. You can put the folder anywhere."
      width={680}
      footer={
        <>
          <button type="button" className="ui-btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="ui-btn ui-btn--primary"
            disabled={busy || !name.trim() || !(selected || path || current)}
            onClick={() => void submit()}
          >
            {busy ? 'Working…' : mode === 'create' ? 'Create space' : 'Link folder'}
          </button>
        </>
      }
    >
      <div className="space-create">
        <div className="space-create__modes" role="tablist" aria-label="Space source">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'create'}
            className={`space-create__mode${mode === 'create' ? ' is-active' : ''}`}
            onClick={() => setMode('create')}
          >
            <FolderPlus size={15} />
            <span>
              <strong>New folder</strong>
              <small>PaliMind creates it for you</small>
            </span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'link'}
            className={`space-create__mode${mode === 'link' ? ' is-active' : ''}`}
            onClick={() => setMode('link')}
          >
            <Link2 size={15} />
            <span>
              <strong>Existing folder</strong>
              <small>Index a folder you already have</small>
            </span>
          </button>
        </div>

        <label className="space-create__field">
          <span>Space name</span>
          <input
            className="ui-input"
            value={name}
            autoFocus
            placeholder="Research, Reading list, Client work…"
            onChange={(e) => setName(e.target.value)}
          />
        </label>

        {mode === 'create' ? (
          <label className="space-create__field">
            <span>Folder name</span>
            <input
              className="ui-input"
              value={folderName}
              placeholder={name || 'Folder name'}
              onChange={(e) => setFolderName(e.target.value)}
            />
          </label>
        ) : null}

        <div className="space-create__field">
          <span>{mode === 'create' ? 'Parent folder' : 'Folder to link'}</span>
          <div className="space-create__path">
            <input
              className="ui-input"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              onBlur={() => path && void load(path)}
              placeholder="Type any path, e.g. ~/Documents/PaliMind"
            />
            <button type="button" className="ui-btn ui-btn--sm" onClick={() => void load(path || undefined)}>
              Go
            </button>
          </div>
        </div>

        <div className="space-create__browser">
          <div className="space-create__browser-head">
            <button
              type="button"
              className="ui-btn ui-btn--sm"
              disabled={!parent}
              onClick={() => parent && void load(parent)}
            >
              Up
            </button>
            <span title={current}>{current}</span>
            <button
              type="button"
              className="ui-btn ui-btn--sm"
              onClick={() => {
                setSelected(current);
                setPath(current);
              }}
            >
              Use this folder
            </button>
          </div>
          <div className="space-create__list">
            {loading ? (
              <SkeletonList rows={4} avatar={false} />
            ) : error ? (
              <EmptyState compact title="Couldn't read this folder" description={error} />
            ) : items.length === 0 ? (
              <EmptyState compact title="No subfolders" description="You can still use this folder." />
            ) : (
              items.map((item) => (
                <button
                  key={item.path}
                  type="button"
                  className={`space-create__dir${selected === item.path ? ' is-selected' : ''}`}
                  title={item.path}
                  onClick={() => {
                    setSelected(item.path);
                    setPath(item.path);
                  }}
                  onDoubleClick={() => void load(item.path)}
                >
                  <Folder size={14} />
                  <span>{item.name}</span>
                </button>
              ))
            )}
          </div>
        </div>

        <p className="space-create__picked">
          {selected || path ? (
            <>
              {mode === 'create' ? 'Creating inside' : 'Linking'}: <code>{selected || path}</code>
            </>
          ) : (
            'Pick a folder above.'
          )}
        </p>
        {error ? <p className="space-create__error">{error}</p> : null}
      </div>
    </Dialog>
  );
}
