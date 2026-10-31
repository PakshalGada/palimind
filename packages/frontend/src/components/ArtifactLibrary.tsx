import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from 'react';
import {
  Download,
  FolderOpen,
  Package,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react';
import { api } from '../api';
import { useConfirm } from './ConfirmDialog';
import {
  EmptyState,
  InlineError,
  Modal,
  Picker,
  SkeletonList,
} from '../ui/primitives';
import { fuzzyRank } from '../utils/fuzzy';
import {
  ARTIFACT_TYPE_LABEL,
  downloadArtifact,
  type ArtifactType,
} from '../utils/artifacts';
import { loadVault, removeFromVault } from '../utils/artifactVault';
import ArtifactIcon from './artifact/ArtifactIcon';
import ArtifactPreview from './artifact/ArtifactPreview';
import type { ActiveArtifact } from './artifact/types';
import './ArtifactLibrary.css';

const VALID_TYPES = new Set<ArtifactType>([
  'html',
  'svg',
  'mermaid',
  'react',
  'markdown',
  'code',
  'document',
  'slide-outline',
  'table',
  'code-file',
  'multi-file',
]);

type TypeFilter = 'all' | 'visual' | 'document' | 'slides' | 'code' | 'data';

const TYPE_FILTERS: { value: TypeFilter; label: string }[] = [
  { value: 'all', label: 'All types' },
  { value: 'visual', label: 'Visual' },
  { value: 'document', label: 'Documents' },
  { value: 'slides', label: 'Slides' },
  { value: 'code', label: 'Code' },
  { value: 'data', label: 'Tables' },
];

const TYPE_CATEGORY: Record<ArtifactType, TypeFilter> = {
  html: 'visual',
  svg: 'visual',
  mermaid: 'visual',
  react: 'code',
  markdown: 'document',
  code: 'code',
  document: 'document',
  'slide-outline': 'slides',
  table: 'data',
  'code-file': 'code',
  'multi-file': 'code',
};

export interface OpenedArtifact {
  id: string;
  type: ArtifactType;
  language: string;
  title: string;
  content: string;
  projectId?: string;
  source?: 'vault' | 'project' | 'global' | 'session';
}

interface LibraryEntry {
  key: string;
  source: 'vault' | 'project' | 'global';
  id: string;
  projectId?: string;
  projectName?: string;
  title: string;
  type: ArtifactType;
  language: string;
  content: string;
  size: number;
  updatedAt: number;
  versions: number;
}

function asType(value: string): ArtifactType {
  return VALID_TYPES.has(value as ArtifactType) ? (value as ArtifactType) : 'code';
}

function formatBytes(size: number): string {
  if (!size) return '0 B';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function toMillis(value: number): number {
  return value && value < 10_000_000_000 ? value * 1000 : value;
}

function formatRelative(value: number): string {
  if (!value) return '';
  const timestamp = toMillis(value);
  const diff = Date.now() - timestamp;
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h ago`;
  if (diff < 7 * 86_400_000) return `${Math.round(diff / 86_400_000)}d ago`;
  return new Date(timestamp).toLocaleDateString();
}

function formatExact(value: number): string {
  if (!value) return '';
  return new Date(toMillis(value)).toLocaleString();
}

function sourceLabel(entry: LibraryEntry): string {
  if (entry.source === 'vault') return 'Local vault';
  if (entry.source === 'project') return entry.projectName || 'Project';
  return 'Global library';
}

export default function ArtifactLibrary({
  open,
  onClose,
  onOpen,
}: {
  open: boolean;
  onClose: () => void;
  onOpen: (artifact: OpenedArtifact) => void;
}) {
  const confirm = useConfirm();
  const [entries, setEntries] = useState<LibraryEntry[]>([]);
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');
  const [opening, setOpening] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const deferredQuery = useDeferredValue(query);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const collected: LibraryEntry[] = [];
      const seenIds = new Set<string>();

      const vault = await loadVault();
      for (const saved of vault) {
        seenIds.add(saved.id);
        collected.push({
          key: `vault:${saved.id}`,
          source: 'vault',
          id: saved.id,
          title: saved.title,
          type: asType(saved.type),
          language: saved.language,
          content: saved.content,
          size: saved.content.length,
          updatedAt: saved.savedAt,
          versions: saved.versions.length,
        });
      }

      const projectResult = await api.projects.list().catch(() => ({ projects: [] }));
      const projectList = (projectResult.projects || []).map(project => ({
        id: project.id,
        name: project.name,
      }));
      setProjects(projectList);
      const projectArtifacts = await Promise.allSettled(
        projectList.map(async project => ({
          project,
          result: await api.projects.artifacts.library(project.id, true),
        })),
      );
      for (const settled of projectArtifacts) {
        if (settled.status !== 'fulfilled') continue;
        const { project, result } = settled.value;
        for (const artifact of result.artifacts || []) {
          collected.push({
            key: `project:${project.id}:${artifact.id}`,
            source: 'project',
            id: artifact.id,
            projectId: project.id,
            projectName: project.name,
            title: artifact.title,
            type: asType(artifact.type),
            language: artifact.language,
            content: artifact.content || '',
            size: artifact.size,
            updatedAt: artifact.updated_at,
            versions: artifact.versions?.length || 0,
          });
        }
      }

      try {
        const globalResult = await api.artifacts.list('', '', true);
        for (const artifact of globalResult.artifacts || []) {
          if (seenIds.has(artifact.id)) continue;
          collected.push({
            key: `global:${artifact.id}`,
            source: 'global',
            id: artifact.id,
            projectId: artifact.project_id || undefined,
            title: artifact.title,
            type: asType(artifact.type),
            language: artifact.language,
            content: artifact.content || '',
            size: artifact.size,
            updatedAt: artifact.updated_at,
            versions: 0,
          });
        }
      } catch {
        // The global registry is optional; local/project entries still work.
      }

      collected.sort((a, b) => b.updatedAt - a.updatedAt);
      setEntries(collected);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the artifact library.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const filterOptions = useMemo(
    () => [
      { value: 'all', label: 'All sources' },
      { value: 'vault', label: 'Local vault' },
      { value: 'global', label: 'Global library' },
      ...projects.map(project => ({
        value: `project:${project.id}`,
        label: project.name,
      })),
    ],
    [projects],
  );

  const counts = useMemo(
    () => ({
      total: entries.length,
      vault: entries.filter(entry => entry.source === 'vault').length,
      project: entries.filter(entry => entry.source === 'project').length,
      global: entries.filter(entry => entry.source === 'global').length,
    }),
    [entries],
  );

  const visible = useMemo(() => {
    const scoped = entries.filter(entry => {
      if (filter !== 'all') {
        if (filter === 'vault' && entry.source !== 'vault') return false;
        if (filter === 'global' && entry.source !== 'global') return false;
        if (filter.startsWith('project:')) {
          if (entry.source !== 'project' || entry.projectId !== filter.slice(8)) {
            return false;
          }
        }
      }
      if (typeFilter !== 'all' && TYPE_CATEGORY[entry.type] !== typeFilter) {
        return false;
      }
      return true;
    });

    const needle = deferredQuery.trim();
    if (!needle) return [...scoped].sort((a, b) => b.updatedAt - a.updatedAt);
    return fuzzyRank(scoped, needle, entry => [
      entry.title,
      entry.type,
      entry.language,
      (entry.content || '').slice(0, 4000),
    ]).map(result => result.item);
  }, [deferredQuery, entries, filter, typeFilter]);

  const selectedEntry = useMemo(
    () => visible.find(entry => entry.key === selectedKey) ?? visible[0] ?? null,
    [selectedKey, visible],
  );

  useEffect(() => {
    if (!open) return;
    if (!visible.some(entry => entry.key === selectedKey)) {
      setSelectedKey(visible[0]?.key ?? null);
    }
  }, [open, selectedKey, visible]);

  const previewArtifact: ActiveArtifact | null = selectedEntry
    ? {
        id: selectedEntry.id,
        type: selectedEntry.type,
        language: selectedEntry.language,
        title: selectedEntry.title,
        content: selectedEntry.content,
        projectId: selectedEntry.projectId,
        source: selectedEntry.source,
      }
    : null;

  const openEntry = async (entry: LibraryEntry) => {
    setOpening(entry.key);
    try {
      let content = entry.content;
      if (!content) {
        if (entry.source === 'project' && entry.projectId) {
          const full = await api.projects.artifacts.get(entry.projectId, entry.id);
          content = full.content || '';
        } else if (entry.source === 'global') {
          const full = await api.artifacts.get(entry.id);
          content = full.content || '';
        }
      }
      onOpen({
        id: entry.id,
        type: entry.type,
        language: entry.language,
        title: entry.title,
        content,
        projectId: entry.projectId,
        source: entry.source,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not open artifact.');
    } finally {
      setOpening(null);
    }
  };

  const removeEntry = async (entry: LibraryEntry) => {
    const ok = await confirm(`Delete “${entry.title}”? This cannot be undone.`, {
      title: 'Delete Artifact',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      if (entry.source === 'vault') await removeFromVault(entry.id);
      if (entry.source === 'project' && entry.projectId) {
        await api.projects.artifacts.remove(entry.projectId, entry.id);
      }
      if (entry.source === 'global') await api.artifacts.remove(entry.id);
      setEntries(prev => prev.filter(item => item.key !== entry.key));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete artifact.');
    }
  };

  const download = (entry: LibraryEntry) => {
    if (!entry.content) return;
    downloadArtifact({ type: entry.type, title: entry.title, content: entry.content });
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Artifacts"
      subtitle="Browse, preview and open everything you have saved."
      width={1120}
    >
      <div className="artifact-library">
        <div className="artifact-library-summary">
          <div className="artifact-library-summary-main">
            <span className="artifact-library-summary-total">{counts.total}</span>
            <span className="artifact-library-summary-label">saved artifacts</span>
          </div>
          <div className="artifact-library-summary-breakdown">
            <span><strong>{counts.vault}</strong> local</span>
            <span><strong>{counts.project}</strong> projects</span>
            <span><strong>{counts.global}</strong> global</span>
          </div>
        </div>

        <div className="artifact-library-layout">
          <section className="artifact-library-browser" aria-label="Artifact list">
            <div className="artifact-library-toolbar">
              <label className="artifact-library-search">
                <Search size={14} />
                <input
                  type="text"
                  value={query}
                  placeholder="Search artifacts…"
                  onChange={event => setQuery(event.target.value)}
                  autoFocus
                />
              </label>
              <Picker
                value={filter}
                options={filterOptions}
                onChange={setFilter}
                ariaLabel="Filter artifacts by source"
                className="artifact-library-filter"
              />
              <button
                type="button"
                className="artifact-library-refresh"
                title="Refresh artifacts"
                aria-label="Refresh artifacts"
                disabled={loading}
                onClick={() => void load()}
              >
                <RefreshCw size={14} className={loading ? 'is-spinning' : undefined} />
              </button>
            </div>

            <div className="artifact-library-type-filters" role="tablist" aria-label="Artifact type">
              {TYPE_FILTERS.map(item => (
                <button
                  key={item.value}
                  type="button"
                  role="tab"
                  aria-selected={typeFilter === item.value}
                  className={`artifact-library-type-filter${
                    typeFilter === item.value ? ' is-active' : ''
                  }`}
                  onClick={() => setTypeFilter(item.value)}
                >
                  {item.label}
                </button>
              ))}
            </div>

            {error && (
              <InlineError
                title="Artifact library"
                message={error}
                onDismiss={() => setError('')}
              />
            )}

            {loading ? (
              <SkeletonList rows={6} />
            ) : visible.length === 0 ? (
              <EmptyState
                icon={<Package size={24} />}
                title={query ? 'No matching artifacts' : 'No saved artifacts yet'}
                description={
                  query
                    ? 'Try a different title, type or content phrase.'
                    : 'Save an artifact to the vault or pin it to a project and it will appear here.'
                }
              />
            ) : (
              <div className="artifact-library-list" role="listbox" aria-label="Artifacts">
                {visible.map(entry => {
                  const isSelected = selectedEntry?.key === entry.key;
                  return (
                    <div
                      key={entry.key}
                      role="option"
                      aria-selected={isSelected}
                      tabIndex={0}
                      className={`artifact-library-card${isSelected ? ' is-selected' : ''}`}
                      onClick={() => setSelectedKey(entry.key)}
                      onDoubleClick={() => void openEntry(entry)}
                      onKeyDown={event => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          setSelectedKey(entry.key);
                        }
                      }}
                    >
                      <span className={`artifact-library-card-icon type-${entry.type}`}>
                        <ArtifactIcon type={entry.type} size={16} />
                      </span>
                      <span className="artifact-library-card-text">
                        <span className="artifact-library-title" title={entry.title}>
                          {entry.title}
                        </span>
                        <span className="artifact-library-meta">
                          {sourceLabel(entry)} · {ARTIFACT_TYPE_LABEL[entry.type]}
                          {entry.versions
                            ? ` · ${entry.versions} version${entry.versions === 1 ? '' : 's'}`
                            : ''}
                          {entry.updatedAt ? ` · ${formatRelative(entry.updatedAt)}` : ''}
                          {entry.size ? ` · ${formatBytes(entry.size)}` : ''}
                        </span>
                      </span>
                      <span className="artifact-library-card-actions">
                        <button
                          type="button"
                          className="ui-icon-btn"
                          title="Open in artifact panel"
                          aria-label={`Open ${entry.title}`}
                          disabled={opening === entry.key}
                          onClick={event => {
                            event.stopPropagation();
                            void openEntry(entry);
                          }}
                        >
                          <FolderOpen size={15} />
                        </button>
                        <button
                          type="button"
                          className="ui-icon-btn"
                          title="Download source"
                          aria-label={`Download ${entry.title}`}
                          onClick={event => {
                            event.stopPropagation();
                            download(entry);
                          }}
                        >
                          <Download size={15} />
                        </button>
                        <button
                          type="button"
                          className="ui-icon-btn"
                          title="Delete artifact"
                          aria-label={`Delete ${entry.title}`}
                          onClick={event => {
                            event.stopPropagation();
                            void removeEntry(entry);
                          }}
                        >
                          <Trash2 size={15} />
                        </button>
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          <aside className="artifact-library-preview" aria-label="Artifact preview">
            {selectedEntry && previewArtifact ? (
              <>
                <header className="artifact-library-preview-head">
                  <span className={`artifact-library-card-icon type-${selectedEntry.type}`}>
                    <ArtifactIcon type={selectedEntry.type} size={16} />
                  </span>
                  <div className="artifact-library-preview-title">
                    <strong title={selectedEntry.title}>{selectedEntry.title}</strong>
                    <span title={formatExact(selectedEntry.updatedAt)}>
                      {sourceLabel(selectedEntry)} · {formatRelative(selectedEntry.updatedAt)}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="artifact-library-open-btn"
                    disabled={opening === selectedEntry.key}
                    onClick={() => void openEntry(selectedEntry)}
                  >
                    <FolderOpen size={14} />
                    <span>Open</span>
                  </button>
                </header>
                <div className="artifact-library-preview-body">
                  {selectedEntry.content ? (
                    <ArtifactPreview
                      key={selectedEntry.key}
                      artifact={previewArtifact}
                      content={selectedEntry.content}
                      viewMode="preview"
                    />
                  ) : (
                    <div className="artifact-library-preview-empty">
                      <Package size={22} />
                      <span>No preview content</span>
                    </div>
                  )}
                </div>
                <footer className="artifact-library-preview-foot">
                  <span>{ARTIFACT_TYPE_LABEL[selectedEntry.type]}</span>
                  <span>{formatBytes(selectedEntry.size)}</span>
                  <span>
                    {selectedEntry.versions} version
                    {selectedEntry.versions === 1 ? '' : 's'}
                  </span>
                </footer>
              </>
            ) : (
              <div className="artifact-library-preview-empty">
                <Package size={26} />
                <span>Select an artifact to preview it</span>
              </div>
            )}
          </aside>
        </div>

        <div className="artifact-library-storage">
          Local versions are stored in IndexedDB on this device; metadata lives in
          localStorage. Project and global versions live in the local Palimind backend.
        </div>
      </div>
    </Modal>
  );
}
