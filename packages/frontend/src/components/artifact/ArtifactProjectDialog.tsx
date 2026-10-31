import { FolderPlus } from 'lucide-react';
import { Dialog, EmptyState } from '../../ui/primitives';
import type { ProjectSummary } from './types';

export default function ArtifactProjectDialog({
  open,
  onClose,
  projects,
  activeProjectId,
  pinBusy,
  newProjectName,
  creatingProject,
  onNameChange,
  onCreate,
  onPin,
}: {
  open: boolean;
  onClose: () => void;
  projects: ProjectSummary[];
  activeProjectId?: string | null;
  pinBusy: boolean;
  newProjectName: string;
  creatingProject: boolean;
  onNameChange: (value: string) => void;
  onCreate: () => void;
  onPin: (projectId: string) => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Pin to Project"
      subtitle="Save this artifact to a project's artifact collection."
      width={520}
    >
      {projects.length === 0 ? (
        <EmptyState
          icon={<FolderPlus size={22} />}
          title="No projects yet"
          description="Create a project first, then pin artifacts into it."
        />
      ) : (
        <div className="artifact-project-list">
          {projects.map(project => (
            <button
              key={project.id}
              type="button"
              className="artifact-project-item"
              disabled={pinBusy}
              onClick={() => onPin(project.id)}
            >
              <span className="artifact-project-name">{project.name}</span>
              {project.description && (
                <span className="artifact-project-desc">{project.description}</span>
              )}
              {activeProjectId === project.id && (
                <span className="artifact-project-active">Active</span>
              )}
            </button>
          ))}
        </div>
      )}
      <div className="artifact-project-create">
        <input
          type="text"
          value={newProjectName}
          placeholder="New project name"
          onChange={event => onNameChange(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') onCreate();
          }}
        />
        <button
          type="button"
          className="artifact-project-create-btn"
          disabled={!newProjectName.trim() || creatingProject}
          onClick={onCreate}
        >
          {creatingProject ? 'Creating…' : 'Create'}
        </button>
      </div>
    </Dialog>
  );
}
