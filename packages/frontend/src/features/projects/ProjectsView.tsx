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
import PageTitle from '../../components/layout/PageTitle';
import { PixelGlyph } from '../../components/pixel/PixelGlyph';
import { PixelMeter } from '../../components/pixel/PixelMeter';
import { Dialog, EmptyState, InlineError, SkeletonList } from '../../ui/primitives';
import type { Project, ProjectArtifact } from '../../types';
import { relativeTime } from '../../utils/time';
import './projects.css';

type Tab = 'overview' | 'sessions' | 'artifacts';

export default function ProjectsView() {
  const { addToast, activeProjectId, setActiveProjectId, setActiveView } = useApp();
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
  const [newPath, setNewPath] = useState('');
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.projects.list();
      setProjects(data.projects ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load projects.');
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
        workspace_path: newPath.trim() || undefined,
      });
      setNewName('');
      setNewPath('');
      setCreateOpen(false);
      await load();
      if (created.id) void select(created.id);
    } catch {
      addToast('Could not create project.', { tone: 'error' });
    }
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
      if (activeProjectId === target.id) setActiveProjectId(null);
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

  const openInChat = () => {
    if (!project) return;
    setActiveProjectId(project.id);
    setActiveView('chat');
  };

  const kb = project?.kb_status;
  const kbRatio = kb && kb.chunks > 0 ? Math.min(1, kb.indexed_files / Math.max(1, kb.chunks)) : 0;

  const headerActions = useMemo(
    () => (
      <button type="button" className="ui-btn ui-btn--sm" onClick={() => void load()}>
        <RefreshCw size={13} /> Refresh
      </button>
    ),
    [load],
  );

  return (
    <div className="projects-view">
      <PageTitle
        eyebrow="Workspace"
        title="Projects"
        subtitle="Persistent workspaces with their own sessions, knowledge and artifacts."
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
              description="A project keeps sessions, knowledge and artifacts together."
              action={
                <button
                  type="button"
                  className="ui-btn ui-btn--primary ui-btn--sm"
                  onClick={() => setCreateOpen(true)}
                >
                  <Plus size={13} /> New project
                </button>
              }
            />
          ) : (
            <ul className="projects-list__items">
              {projects.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={`project-row${item.id === selectedId ? ' is-active' : ''}`}
                    onClick={() => void select(item.id)}
                  >
                    <FolderKanban size={15} className="project-row__icon" />
                    <span className="project-row__body">
                      <span className="project-row__name">{item.name}</span>
                      <span className="project-row__meta">
                        {item.kb?.indexed_files ? `${item.kb.indexed_files} files · ` : ''}
                        {relativeTime(item.last_opened_at ?? item.updated_at)}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="projects-detail">
          {!project ? (
            <EmptyState
              glyph={<PixelGlyph sprite="folder" cell={4} />}
              title="Select a project"
              description="Or create one to start collecting work in a single workspace."
            />
          ) : (
            <>
              <header className="projects-detail__head">
                <div className="projects-detail__title-block">
                  <h2 className="projects-detail__name">{project.name}</h2>
                  <div className="projects-detail__path">{project.workspace_path || 'No folder linked'}</div>
                </div>
                <div className="projects-detail__actions">
                  <button type="button" className="ui-btn ui-btn--sm" onClick={() => void sync()} disabled={syncing}>
                    <RefreshCw size={13} /> {syncing ? 'Syncing…' : 'Sync knowledge'}
                  </button>
                  <button type="button" className="ui-btn ui-btn--primary ui-btn--sm" onClick={openInChat}>
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
                        <PixelMeter
                          value={kbRatio}
                          label={
                            kb
                              ? `${kb.indexed_files} files · ${kb.chunks} chunks`
                              : 'Not indexed'
                          }
                          showPercent={false}
                        />
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
                      <MessageSquare size={14} />
                      <span className="projects-row__title">{session.name}</span>
                      <span className="projects-row__meta">{session.messages.length} messages</span>
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
              placeholder="Research notes"
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void create();
              }}
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
    </div>
  );
}
