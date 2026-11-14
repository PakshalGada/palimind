import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRight,
  FolderKanban,
  FolderOpen,
  MessageSquare,
  Package,
  Plus,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { useConfirm } from '../../components/ConfirmDialog';
import SurfaceHeader from '../../components/layout/SurfaceHeader';
import { PixelGlyph } from '../../components/pixel/PixelGlyph';
import { PixelMeter } from '../../components/pixel/PixelMeter';
import { Dialog, EmptyState, InlineError, SkeletonList } from '../../ui/primitives';
import type { Project, ProjectArtifact } from '../../types';
import { relativeTime } from '../../utils/time';
import './projects.css';

type Tab = 'overview' | 'sessions' | 'artifacts';

export default function ProjectsView() {
  const {
    addToast,
    activeProjectId,
    setActiveProjectId,
    setActiveView,
    setSessions: setGlobalSessions,
    setActiveSessionId,
    setActiveProjectName,
  } = useApp();
  const confirm = useConfirm();

  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(activeProjectId);
  const [project, setProject] = useState<Project | null>(null);
  const [sessions, setSessions] = useState<{ id: string; name: string; messages: unknown[] }[]>([]);
  const [artifacts, setArtifacts] = useState<ProjectArtifact[]>([]);
  const [tab, setTab] = useState<Tab>('overview');
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newPath, setNewPath] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<'recent' | 'name'>('recent');
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.projects.list();
      setProjects(data.projects ?? []);
    } catch {
      setError('Could not load projects. Check that the local engine is running.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // The CommandBar's primary action opens this dialog.
  useEffect(() => {
    const open = () => setCreateOpen(true);
    window.addEventListener('palimind:new-project', open);
    return () => window.removeEventListener('palimind:new-project', open);
  }, []);

  // Latest project requested; responses for an earlier click are dropped so a
  // slow reply never shows project A's details while B is selected.
  const selectSeq = useRef(0);

  const select = useCallback(async (id: string) => {
    const seq = ++selectSeq.current;
    setSelectedId(id);
    setProject(null);
    setSessions([]);
    setArtifacts([]);
    try {
      const data = await api.projects.get(id);
      if (seq !== selectSeq.current) return;
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      setProject(data);
      const [sessionData, artifactData] = await Promise.allSettled([
        api.projects.sessions.list(id),
        api.projects.artifacts.library(id),
      ]);
      if (seq !== selectSeq.current) return;
      setSessions(
        sessionData.status === 'fulfilled' ? sessionData.value.sessions ?? [] : [],
      );
      setArtifacts(
        artifactData.status === 'fulfilled' ? artifactData.value.artifacts ?? [] : [],
      );
    } catch {
      if (seq !== selectSeq.current) return;
      addToast('Could not open project.', { tone: 'error' });
    }
  }, [addToast]);

  useEffect(() => {
    if (selectedId) void select(selectedId);
    // Only on first mount / when the global selection changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const create = async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      const created = await api.projects.create({
        name,
        description: newDescription.trim() || undefined,
        workspace_path: newPath.trim() || undefined,
      });
      setNewName('');
      setNewDescription('');
      setNewPath('');
      setCreateOpen(false);
      await load();
      if (created.id) void select(created.id);
    } catch {
      addToast('Could not create project.', { tone: 'error' });
    }
  };

  const updateMeta = async () => {
    if (!project) return;
    const name = editName.trim();
    if (!name) return;
    try {
      const updated = await api.projects.update(project.id, {
        name,
        description: editDescription.trim(),
      });
      if (updated.error) {
        addToast(updated.error, { tone: 'error' });
        return;
      }
      setProject(updated);
      setEditOpen(false);
      addToast('Project updated', { tone: 'success' });
      await load();
    } catch {
      addToast('Could not update project.', { tone: 'error' });
    }
  };

  const openEdit = () => {
    if (!project) return;
    setEditName(project.name);
    setEditDescription(project.description || '');
    setEditOpen(true);
  };

  const remove = async (target: Project) => {
    const ok = await confirm(`Delete “${target.name}”? Sessions stay on disk.`, {
      title: 'Delete project',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.projects.remove(target.id);
      if (selectedId === target.id) {
        selectSeq.current += 1;
        setSelectedId(null);
        setProject(null);
      }
      // Don't leave chat pointed at a project that no longer exists.
      if (activeProjectId === target.id) {
        setActiveProjectId(null);
        setActiveProjectName(null);
      }
      await load();
    } catch {
      addToast('Could not delete project.', { tone: 'error' });
    }
  };

  const sync = async () => {
    if (!project) return;
    setSyncing(true);
    try {
      const result = await api.projects.kb.sync(project.id);
      if (result.error) addToast(result.error, { tone: 'error' });
      else addToast(`Indexed ${result.indexed_files ?? 0} files`);
      await select(project.id);
    } catch {
      addToast('Knowledge sync failed.', { tone: 'error' });
    } finally {
      setSyncing(false);
    }
  };

  const openInChat = async () => {
    if (!project) return;
    try {
      const opened = await api.projects.open(project.id);
      setActiveProjectId(project.id);
      setActiveProjectName(project.name);
      const sessionData = opened.sessions;
      if (sessionData?.sessions) setGlobalSessions(sessionData.sessions as never);
      if (sessionData?.active_session_id !== undefined) {
        setActiveSessionId(sessionData.active_session_id);
      }
      setActiveView('chat');
    } catch {
      addToast('Could not open project chat.', { tone: 'error' });
    }
  };

  const openProjectSession = (sessionId: string) => {
    if (!project) return;
    setActiveProjectId(project.id);
    setActiveProjectName(project.name);
    setGlobalSessions(sessions as never);
    setActiveSessionId(sessionId);
    setActiveView('chat');
  };

  const kb = project?.kb_status;
  const indexed = kb?.has_index || (kb?.indexed_files ?? 0) > 0;

  const visibleProjects = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? projects.filter(
          (item) =>
            item.name.toLowerCase().includes(q) ||
            (item.description || '').toLowerCase().includes(q) ||
            (item.workspace_path || '').toLowerCase().includes(q),
        )
      : projects;
    return [...list].sort((a, b) =>
      sort === 'name'
        ? a.name.localeCompare(b.name)
        : (b.last_opened_at ?? b.updated_at) - (a.last_opened_at ?? a.updated_at),
    );
  }, [projects, query, sort]);

  const headerActions = useMemo(
    () => (
      <>
        <button
          type="button"
          className="ui-btn ui-btn--primary ui-btn--sm"
          onClick={() => setCreateOpen(true)}
        >
          <Plus size={13} /> New project
        </button>
        <button type="button" className="ui-btn ui-btn--sm" onClick={() => void load()}>
          <RefreshCw size={13} /> Refresh
        </button>
      </>
    ),
    [load],
  );

  return (
    <div className="projects-view">
      <SurfaceHeader
        title="Projects"
        meta={
          loading
            ? 'Loading…'
            : error
              ? 'Unavailable'
              : `${projects.length} ${projects.length === 1 ? 'workspace' : 'workspaces'}`
        }
        actions={headerActions}
      />

      <div className="projects-body">
        <aside className="projects-list" aria-label="Projects">
          {loading ? (
            <SkeletonList rows={5} avatar={false} />
          ) : error ? (
            <InlineError title="Couldn't load projects" message={error} onRetry={() => void load()} />
          ) : projects.length === 0 ? (
            <EmptyState
              compact
              glyph={<PixelGlyph sprite="folder" cell={3} />}
              title="No projects yet"
              description="Use the templates on the right to create your first workspace."
            />
          ) : (
            <>
              <div className="projects-list__tools">
                <input
                  className="ui-input"
                  value={query}
                  placeholder="Filter projects…"
                  aria-label="Filter projects"
                  onChange={(e) => setQuery(e.target.value)}
                />
                <button
                  type="button"
                  className="ui-icon-btn"
                  title={sort === 'recent' ? 'Sort by name' : 'Sort by recent'}
                  aria-label={sort === 'recent' ? 'Sort by name' : 'Sort by recent'}
                  onClick={() => setSort(sort === 'recent' ? 'name' : 'recent')}
                >
                  <RefreshCw size={13} style={{ transform: sort === 'name' ? 'rotate(90deg)' : undefined }} />
                </button>
              </div>
              <ul className="projects-list__items">
                {visibleProjects.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={`project-row${item.id === selectedId ? ' is-active' : ''}`}
                      onClick={() => void select(item.id)}
                    >
                      <FolderKanban size={15} className="project-row__icon" />
                      <span className="project-row__body">
                        <span className="project-row__name">{item.name}</span>
                        {item.description && (
                          <span className="project-row__desc">{item.description}</span>
                        )}
                        <span className="project-row__meta">
                          {item.kb?.indexed_files ? `${item.kb.indexed_files} files · ` : ''}
                          {relativeTime(item.last_opened_at ?? item.updated_at)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
                {visibleProjects.length === 0 && (
                  <li className="projects-list__empty">No projects match “{query}”.</li>
                )}
              </ul>
            </>
          )}
        </aside>

        <section className="projects-detail">
          {!project ? (
            projects.length === 0 && !loading && !error ? (
              <div className="projects-zero">
                <div className="projects-zero__head">
                  <span className="projects-zero__glyph">
                    <PixelGlyph sprite="projects" cell={4} />
                  </span>
                  <div>
                    <h2>Create your first project</h2>
                    <p>
                      A project keeps chats, knowledge and artifacts together so a
                      piece of work never gets lost between surfaces.
                    </p>
                  </div>
                </div>
                <div className="projects-zero__templates">
                  {[
                    { name: 'Blank workspace', desc: 'Start with a clean project.' },
                    { name: 'Product notes', desc: 'Decisions, specs and research.' },
                    { name: 'Codebase', desc: 'A repository and its docs.' },
                    { name: 'Client work', desc: 'Deliverables and source files.' },
                  ].map((template) => (
                    <button
                      key={template.name}
                      type="button"
                      className="projects-zero__template"
                      onClick={() => {
                        setNewName(template.name);
                        setCreateOpen(true);
                      }}
                    >
                      <FolderKanban size={16} />
                      <span className="projects-zero__template-name">{template.name}</span>
                      <span className="projects-zero__template-desc">{template.desc}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState
                glyph={<PixelGlyph sprite="folder" cell={4} />}
                title="Select a project"
                description="Choose a workspace on the left, or create one to collect work in one place."
              />
            )
          ) : (
            <>
              <header className="projects-detail__head">
                <div className="projects-detail__title-block">
                  <h2 className="projects-detail__name">{project.name}</h2>
                  <div className="projects-detail__path">{project.workspace_path || 'No folder linked'}</div>
                </div>
                <div className="projects-detail__actions">
                  <button type="button" className="ui-btn ui-btn--sm" onClick={openEdit}>
                    <FolderOpen size={13} /> Edit
                  </button>
                  <button type="button" className="ui-btn ui-btn--sm" onClick={() => void sync()} disabled={syncing}>
                    <RefreshCw size={13} /> {syncing ? 'Syncing…' : 'Sync knowledge'}
                  </button>
                  <button type="button" className="ui-btn ui-btn--primary ui-btn--sm" onClick={() => void openInChat()}>
                    <MessageSquare size={13} /> Open in chat
                  </button>
                  <button
                    type="button"
                    className="ui-icon-btn"
                    title="Delete project"
                    aria-label={`Delete ${project.name}`}
                    onClick={() => void remove(project)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </header>

              <div className="projects-stats">
                <div>
                  <span className="projects-stats__value">{sessions.length}</span>
                  <span className="projects-stats__label">Sessions</span>
                </div>
                <div>
                  <span className="projects-stats__value">{artifacts.length}</span>
                  <span className="projects-stats__label">Artifacts</span>
                </div>
                <div>
                  <span className="projects-stats__value">{kb?.indexed_files ?? 0}</span>
                  <span className="projects-stats__label">Files indexed</span>
                </div>
                <div>
                  <span className="projects-stats__value">{kb?.chunks ?? 0}</span>
                  <span className="projects-stats__label">Chunks</span>
                </div>
              </div>

              <div className="projects-detail__tabs">
                {(['overview', 'sessions', 'artifacts'] as Tab[]).map((id) => (
                  <button
                    key={id}
                    type="button"
                    className={`projects-tab${tab === id ? ' is-active' : ''}`}
                    onClick={() => setTab(id)}
                  >
                    {id === 'overview' ? 'Overview' : id === 'sessions' ? 'Sessions' : 'Artifacts'}
                    {id === 'sessions' && sessions.length > 0 && (
                      <span className="projects-tab__count">{sessions.length}</span>
                    )}
                    {id === 'artifacts' && artifacts.length > 0 && (
                      <span className="projects-tab__count">{artifacts.length}</span>
                    )}
                  </button>
                ))}
              </div>

              {tab === 'overview' && (
                <div className="projects-overview">
                  {project.description && (
                    <p className="projects-overview__desc">{project.description}</p>
                  )}
                  <dl className="projects-facts">
                    <div>
                      <dt>Folder</dt>
                      <dd className="projects-facts__mono">{project.workspace_path || '—'}</dd>
                    </div>
                    <div>
                      <dt>Index health</dt>
                      <dd>
                        {syncing ? (
                          <PixelMeter value={null} label="Syncing…" />
                        ) : indexed ? (
                          <span className="projects-health is-ready">
                            <PixelGlyph sprite="check" cell={1.5} />
                            {kb?.indexed_files ?? 0} files · {kb?.chunks ?? 0} chunks
                          </span>
                        ) : (
                          <span className="projects-health">Not indexed yet</span>
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>Last opened</dt>
                      <dd>{relativeTime(project.last_opened_at)}</dd>
                    </div>
                    <div>
                      <dt>Created</dt>
                      <dd>{relativeTime(project.created_at)}</dd>
                    </div>
                  </dl>
                  <div className="projects-overview__links">
                    <button type="button" className="projects-link" onClick={() => setActiveView('knowledge')}>
                      <FolderOpen size={14} /> Knowledge
                      <ArrowRight size={13} />
                    </button>
                    <button type="button" className="projects-link" onClick={() => setActiveView('artifacts')}>
                      <Package size={14} /> Artifacts
                      <ArrowRight size={13} />
                    </button>
                  </div>
                </div>
              )}

              {tab === 'sessions' && (
                <ul className="projects-rows">
                  {sessions.length === 0 && (
                    <li className="projects-rows__empty">No sessions in this project yet.</li>
                  )}
                  {sessions.map((session) => (
                    <li key={session.id} className="projects-row">
                      <button
                        type="button"
                        className="projects-row__open"
                        onClick={() => openProjectSession(session.id)}
                      >
                        <MessageSquare size={14} />
                        <span className="projects-row__title">{session.name}</span>
                        <span className="projects-row__meta">{session.messages.length} messages</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {tab === 'artifacts' && (
                <ul className="projects-rows">
                  {artifacts.length === 0 && (
                    <li className="projects-rows__empty">No artifacts saved to this project.</li>
                  )}
                  {artifacts.map((artifact) => (
                    <li key={artifact.id} className="projects-row">
                      <Package size={14} />
                      <span className="projects-row__title">{artifact.title}</span>
                      <span className="projects-row__mono">{artifact.type}</span>
                      <span className="projects-row__meta">v{artifact.current_version}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      </div>

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="New project"
        subtitle="Sessions, knowledge and artifacts stay scoped to this workspace."
        width={520}
        footer={
          <>
            <button type="button" className="ui-btn" onClick={() => setCreateOpen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="ui-btn ui-btn--primary"
              onClick={() => void create()}
              disabled={!newName.trim()}
            >
              Create project
            </button>
          </>
        }
      >
        <div className="projects-form">
          <label className="ui-field">
            <span className="ui-field__label">Name</span>
            <input
              className="ui-input"
              value={newName}
              autoFocus
              placeholder="Product notes"
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void create();
              }}
            />
          </label>
          <label className="ui-field">
            <span className="ui-field__label">Description (optional)</span>
            <textarea
              className="ui-textarea"
              value={newDescription}
              placeholder="What kind of work lives here?"
              rows={3}
              onChange={(e) => setNewDescription(e.target.value)}
            />
          </label>
          <label className="ui-field">
            <span className="ui-field__label">Folder (optional)</span>
            <input
              className="ui-input"
              value={newPath}
              placeholder="/home/you/notes"
              onChange={(e) => setNewPath(e.target.value)}
            />
            <span className="ui-field__hint">Leave empty to start without a knowledge folder.</span>
          </label>
        </div>
      </Dialog>

      <Dialog
        open={editOpen}
        onClose={() => setEditOpen(false)}
        title="Edit project"
        subtitle="Rename the workspace or update its description."
        width={520}
        footer={
          <>
            <button type="button" className="ui-btn" onClick={() => setEditOpen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="ui-btn ui-btn--primary"
              onClick={() => void updateMeta()}
              disabled={!editName.trim()}
            >
              Save changes
            </button>
          </>
        }
      >
        <div className="projects-form">
          <label className="ui-field">
            <span className="ui-field__label">Name</span>
            <input
              className="ui-input"
              value={editName}
              autoFocus
              onChange={(e) => setEditName(e.target.value)}
            />
          </label>
          <label className="ui-field">
            <span className="ui-field__label">Description</span>
            <textarea
              className="ui-textarea"
              value={editDescription}
              rows={3}
              onChange={(e) => setEditDescription(e.target.value)}
            />
          </label>
        </div>
      </Dialog>
    </div>
  );
}
