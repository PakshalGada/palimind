import { useEffect, useState } from 'react';
import { FlaskConical } from 'lucide-react';
import { api } from '../api';
import { useApp } from '../AppContext';
import { Modal } from '../ui/primitives';
import type { ResearchProjectSummary } from '../types';
import './SaveToResearchModal.css';

export default function SaveToResearchModal() {
  const { addToast } = useApp();
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ResearchProjectSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [sources, setSources] = useState<unknown[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { content?: string; sources?: unknown[] } | undefined;
      if (!detail?.content) return;
      setContent(detail.content);
      setSources(Array.isArray(detail.sources) ? detail.sources : []);
      const heading = detail.content.match(/^\s*#{1,6}\s+(.+)$/m)?.[1]?.trim();
      setTitle(heading?.slice(0, 80) || 'Research finding');
      setSelected(null);
      setNewTitle('');
      setOpen(true);
      api.research.projects
        .list()
        .then((d) => setProjects(d.projects || []))
        .catch(() => setProjects([]));
    };
    window.addEventListener('palimind:save-research', handler);
    return () => window.removeEventListener('palimind:save-research', handler);
  }, []);

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      let projectId = selected;
      if (!projectId) {
        const created = await api.research.projects.create(newTitle.trim() || title.trim() || 'Untitled Research');
        if (!created.id) {
          addToast('Could not create project.');
          return;
        }
        projectId = created.id;
      }
      await api.research.projects.addFinding(projectId, title.trim() || 'Research finding', content);
      if (sources.length) await api.research.projects.addSources(projectId, sources);
      addToast('Saved to research project');
      setOpen(false);
    } catch {
      addToast('Could not save to research project.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => setOpen(false)}
      title="Save to Research"
      subtitle="Store this answer as a finding in a research project."
      width={560}
      footer={
        <div className="save-research-footer">
          <button type="button" className="ui-btn ui-btn--ghost ui-btn--sm" onClick={() => setOpen(false)}>
            Cancel
          </button>
          <button type="button" className="ui-btn ui-btn--primary ui-btn--sm" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : 'Save finding'}
          </button>
        </div>
      }
    >
      <label className="save-research-field">
        <span>Finding title</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>

      <div className="save-research-field">
        <span>Add to project</span>
        <div className="save-research-projects">
          {projects.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`save-research-project${selected === p.id ? ' is-active' : ''}`}
              onClick={() => setSelected(selected === p.id ? null : p.id)}
            >
              <FlaskConical size={13} /> {p.title}
            </button>
          ))}
        </div>
      </div>

      {!selected && (
        <label className="save-research-field">
          <span>…or create a new project</span>
          <input
            value={newTitle}
            placeholder="New project title"
            onChange={(e) => setNewTitle(e.target.value)}
          />
        </label>
      )}

      <div className="save-research-preview">
        {sources.length > 0 && <div className="save-research-note">{sources.length} source(s) will be saved to the library.</div>}
        <div className="save-research-excerpt">{content.slice(0, 400)}{content.length > 400 ? '…' : ''}</div>
      </div>
    </Modal>
  );
}
