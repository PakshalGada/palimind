import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BookOpen,
  Copy,
  Download,
  FileText,
  FlaskConical,
  Plus,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { api } from '../api';
import { useApp } from '../AppContext';
import { useConfirm } from './ConfirmDialog';
import { Modal, EmptyState, Tabs } from '../ui/primitives';
import { exportMarkdown } from '../utils/canvasExport';
import type { ResearchProject, ResearchProjectSummary } from '../types';
import './ResearchManager.css';

type Tab = 'notes' | 'findings' | 'sources' | 'timeline' | 'reports';

function projectToMarkdown(project: ResearchProject): string {
  const lines: string[] = [`# ${project.title}`, ''];
  if (project.query) lines.push(`**Research question:** ${project.query}`, '');
  if (project.notes.trim()) lines.push('## Notes', '', project.notes.trim(), '');
  if (project.findings.length) {
    lines.push('## Findings', '');
    for (const f of project.findings) lines.push(`### ${f.title}`, '', f.content, '');
  }
  if (project.reports.length) {
    lines.push('## Reports', '');
    for (const r of project.reports) {
      lines.push(`### ${r.query || 'Report'}`, '', r.report, '');
    }
  }
  if (project.sources.length) {
    lines.push('## Sources', '');
    for (const s of project.sources) {
      const link = s.url ? `[${s.title}](${s.url})` : s.title;
      lines.push(`${s.marker}. ${link}${s.score ? ` _(quality ${Math.round(s.score * 100)}%)_` : ''}`);
    }
  }
  return lines.join('\n');
}

export default function ResearchManager() {
  const { addToast } = useApp();
  const confirm = useConfirm();
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ResearchProjectSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [tab, setTab] = useState<Tab>('notes');
  const [newTitle, setNewTitle] = useState('');
  const [notes, setNotes] = useState('');
  const [findingTitle, setFindingTitle] = useState('');
  const [findingBody, setFindingBody] = useState('');

  const loadProjects = useCallback(async () => {
    try {
      const data = await api.research.projects.list();
      setProjects(data.projects || []);
      return data.projects || [];
    } catch {
      addToast('Could not load research projects.');
      return [];
    }
  }, [addToast]);

  const loadProject = useCallback(
    async (id: string) => {
      try {
        const data = await api.research.projects.get(id);
        if (data.error) {
          addToast(data.error);
          return;
        }
        setProject(data);
        setNotes(data.notes || '');
        setSelectedId(id);
      } catch {
        addToast('Could not open project.');
      }
    },
    [addToast],
  );

  useEffect(() => {
    const handler = () => {
      setOpen(true);
      void loadProjects();
    };
    window.addEventListener('palimind:open-research', handler);
    return () => window.removeEventListener('palimind:open-research', handler);
  }, [loadProjects]);

  const createProject = async () => {
    const title = newTitle.trim() || 'Untitled Research';
    try {
      const created = await api.research.projects.create(title);
      setNewTitle('');
      await loadProjects();
      if (created.id) await loadProject(created.id);
    } catch {
      addToast('Could not create project.');
    }
  };

  const deleteProject = async (id: string) => {
    const ok = await confirm('Delete this research project? This cannot be undone.', {
      title: 'Delete Project',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.research.projects.remove(id);
      if (selectedId === id) {
        setSelectedId(null);
        setProject(null);
      }
      await loadProjects();
    } catch {
      addToast('Could not delete project.');
    }
  };

  const saveNotes = async () => {
    if (!project) return;
    try {
      const updated = await api.research.projects.update(project.id, { notes });
      setProject(updated);
      addToast('Notes saved');
    } catch {
      addToast('Could not save notes.');
    }
  };

  const addFinding = async () => {
    if (!project) return;
    if (!findingTitle.trim() && !findingBody.trim()) return;
    try {
      await api.research.projects.addFinding(project.id, findingTitle.trim() || 'Finding', findingBody.trim());
      setFindingTitle('');
      setFindingBody('');
      await loadProject(project.id);
    } catch {
      addToast('Could not add finding.');
    }
  };

  const copySummary = () => {
    if (!project) return;
    const summary = projectToMarkdown(project).slice(0, 6000);
    navigator.clipboard
      .writeText(summary)
      .then(() => addToast('Research summary copied'))
      .catch(() => addToast('Could not access the clipboard'));
  };

  const continueResearch = () => {
    if (!project) return;
    const context = project.findings
      .slice(0, 5)
      .map((f) => `- ${f.title}: ${f.content.slice(0, 400)}`)
      .join('\n');
    const text =
      `${project.query || project.title}\n\n` +
      (context ? `Build on these existing findings:\n${context}\n\n` : '') +
      'Deepen the research and update the findings.';
    window.dispatchEvent(new CustomEvent('palimind:prefill-composer', { detail: { text } }));
    setOpen(false);
  };

  const sourcesSorted = useMemo(
    () => (project ? [...project.sources].sort((a, b) => (b.score || 0) - (a.score || 0)) : []),
    [project],
  );

  return (
    <Modal
      open={open}
      onClose={() => setOpen(false)}
      title="Research Projects"
      subtitle="Persistent workspaces that build on previous findings."
      width={900}
    >
      <div className="research-manager">
        <aside className="research-manager-list">
          <div className="research-new">
            <input
              value={newTitle}
              placeholder="New project title…"
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void createProject();
              }}
            />
            <button type="button" className="ui-icon-btn" title="Create project" onClick={createProject}>
              <Plus size={15} />
            </button>
          </div>
          {projects.length === 0 && <div className="research-manager-empty">No projects yet.</div>}
          {projects.map((p) => (
            <div
              key={p.id}
              className={`research-project-row${p.id === selectedId ? ' is-active' : ''}`}
              onClick={() => loadProject(p.id)}
            >
              <FlaskConical size={14} />
              <span className="research-project-text">
                <span className="research-project-title">{p.title}</span>
                <span className="research-project-meta">
                  {p.finding_count} findings · {p.source_count} sources
                </span>
              </span>
              <button
                type="button"
                className="ui-icon-btn research-project-delete"
                title="Delete project"
                aria-label={`Delete ${p.title}`}
                onClick={(e) => {
                  e.stopPropagation();
                  void deleteProject(p.id);
                }}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </aside>

        <section className="research-manager-detail">
          {!project ? (
            <EmptyState
              icon={<FlaskConical size={26} />}
              title="Select a project"
              description="Create or open a research project to see its notes, findings, sources and timeline."
            />
          ) : (
            <>
              <div className="research-detail-head">
                <input
                  className="research-detail-title"
                  value={project.title}
                  onChange={(e) => setProject({ ...project, title: e.target.value })}
                  onBlur={() => void api.research.projects.update(project.id, { title: project.title })}
                />
                <div className="research-detail-actions">
                  <button type="button" className="ui-btn ui-btn--ghost ui-btn--sm" onClick={continueResearch}>
                    <Sparkles size={13} /> Continue research
                  </button>
                  <button type="button" className="ui-icon-btn" title="Copy summary" onClick={copySummary}>
                    <Copy size={15} />
                  </button>
                  <button
                    type="button"
                    className="ui-icon-btn"
                    title="Export project"
                    onClick={() => exportMarkdown(project.title, projectToMarkdown(project))}
                  >
                    <Download size={15} />
                  </button>
                </div>
              </div>

              <Tabs<Tab>
                value={tab}
                onChange={setTab}
                tabs={[
                  { id: 'notes', label: 'Notes' },
                  { id: 'findings', label: 'Findings', count: project.findings.length },
                  { id: 'sources', label: 'Sources', count: project.sources.length },
                  { id: 'timeline', label: 'Timeline' },
                  { id: 'reports', label: 'Reports', count: project.reports.length },
                ]}
              />

              <div className="research-tab-body">
                {tab === 'notes' && (
                  <div className="research-notes">
                    <textarea
                      value={notes}
                      placeholder="Working notes, hypotheses, open questions…"
                      onChange={(e) => setNotes(e.target.value)}
                    />
                    <button type="button" className="ui-btn ui-btn--primary ui-btn--sm" onClick={saveNotes}>
                      Save notes
                    </button>
                  </div>
                )}

                {tab === 'findings' && (
                  <div className="research-findings">
                    <div className="research-finding-form">
                      <input
                        value={findingTitle}
                        placeholder="Finding title"
                        onChange={(e) => setFindingTitle(e.target.value)}
                      />
                      <textarea
                        value={findingBody}
                        placeholder="What did you learn?"
                        rows={3}
                        onChange={(e) => setFindingBody(e.target.value)}
                      />
                      <button type="button" className="ui-btn ui-btn--primary ui-btn--sm" onClick={addFinding}>
                        <Plus size={13} /> Add finding
                      </button>
                    </div>
                    {project.findings.map((f) => (
                      <div key={f.id} className="research-finding">
                        <div className="research-finding-title">{f.title}</div>
                        <div className="research-finding-body">{f.content}</div>
                      </div>
                    ))}
                  </div>
                )}

                {tab === 'sources' && (
                  <div className="research-sources">
                    {sourcesSorted.length === 0 && <div className="research-manager-empty">No sources saved.</div>}
                    {sourcesSorted.map((s) => (
                      <div key={s.marker} className="research-source">
                        <span className="research-source-score" title="Quality score">
                          {Math.round((s.score || 0) * 100)}
                        </span>
                        <span className="research-source-body">
                          {s.url ? (
                            <a href={s.url} target="_blank" rel="noopener noreferrer">
                              {s.title}
                            </a>
                          ) : (
                            <span>{s.title}</span>
                          )}
                          {s.snippet && <span className="research-source-snippet">{s.snippet}</span>}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {tab === 'timeline' && (
                  <div className="research-timeline">
                    {project.timeline.length === 0 && <div className="research-manager-empty">No activity yet.</div>}
                    {[...project.timeline].reverse().map((entry, i) => (
                      <div key={i} className="research-timeline-row">
                        <span className="research-timeline-dot" />
                        <span className="research-timeline-text">{entry.text}</span>
                        <span className="research-timeline-time">
                          {new Date(entry.at * 1000).toLocaleString()}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {tab === 'reports' && (
                  <div className="research-reports">
                    {project.reports.length === 0 && (
                      <div className="research-manager-empty">
                        No reports yet. Use “Save to Research” on a research answer.
                      </div>
                    )}
                    {project.reports.map((r) => (
                      <details key={r.id} className="research-report">
                        <summary>
                          <FileText size={13} /> {r.query || 'Report'}
                          <span className="research-report-time">
                            {new Date(r.created_at * 1000).toLocaleDateString()}
                          </span>
                        </summary>
                        <div className="research-report-body">{r.report}</div>
                      </details>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </section>
      </div>
      <div className="research-manager-footer">
        <BookOpen size={13} /> Projects are stored locally on this device.
      </div>
    </Modal>
  );
}
