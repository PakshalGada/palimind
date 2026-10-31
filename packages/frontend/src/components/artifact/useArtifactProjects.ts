import { useState } from 'react';
import { api } from '../../api';
import type { ToastOptions } from '../../AppContext';
import type { ActiveArtifact, ProjectSummary } from './types';

interface Options {
  active: ActiveArtifact | null;
  content: string;
  activeProjectId: string | null;
  activeSessionId: string | null;
  setActiveProjectId: (projectId: string | null) => void;
  addToast: (message: string, options?: ToastOptions) => void;
}

/** Project list, create-project and pin-to-project actions. */
export function useArtifactProjects({
  active,
  content,
  activeProjectId,
  activeSessionId,
  setActiveProjectId,
  addToast,
}: Options) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [creatingProject, setCreatingProject] = useState(false);
  const [pinBusy, setPinBusy] = useState(false);

  const loadProjects = async () => {
    try {
      const result = await api.projects.list();
      setProjects(
        (result.projects || []).map(project => ({
          id: project.id,
          name: project.name,
          description: project.description,
        })),
      );
    } catch {
      setProjects([]);
    }
  };

  const createProject = async () => {
    const name = newProjectName.trim();
    if (!name) return;
    setCreatingProject(true);
    try {
      const project = await api.projects.create({ name });
      setNewProjectName('');
      await loadProjects();
      addToast(`Project “${project.name}” created`, { tone: 'success' });
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Could not create project.', {
        tone: 'error',
      });
    } finally {
      setCreatingProject(false);
    }
  };

  const pinToProject = async (projectId: string) => {
    if (!active) return;
    setPinBusy(true);
    try {
      if (active.projectId && active.source === 'project') {
        await api.projects.artifacts.addVersion(active.projectId, active.id, {
          content,
          title: active.title,
          description: 'Updated from the artifact panel',
        });
      } else {
        await api.projects.artifacts.save(projectId, {
          title: active.title,
          type: active.type,
          language: active.language,
          description: 'Pinned from the artifact panel',
          content,
          source: 'artifact-panel',
          session_id: activeSessionId || undefined,
        });
      }
      setActiveProjectId(projectId);
      const project = projects.find(item => item.id === projectId);
      addToast(
        active.source === 'project'
          ? 'Project artifact updated'
          : `Pinned to ${project?.name || 'project'}`,
        { tone: 'success' },
      );
      setPickerOpen(false);
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Could not pin artifact.', {
        tone: 'error',
      });
      await loadProjects();
      setPickerOpen(true);
    } finally {
      setPinBusy(false);
    }
  };

  const openPicker = () => {
    if (!active) return;
    if (active.projectId) {
      void pinToProject(active.projectId);
      return;
    }
    if (activeProjectId) {
      void pinToProject(activeProjectId);
      return;
    }
    void loadProjects().then(() => setPickerOpen(true));
  };

  return {
    projects,
    pickerOpen,
    setPickerOpen,
    newProjectName,
    setNewProjectName,
    creatingProject,
    pinBusy,
    openPicker,
    createProject,
    pinToProject,
  };
}
