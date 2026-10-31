import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import type { ToastOptions } from '../../AppContext';
import type { ProjectArtifact } from '../../types';
import {
  getVaultVersionContent,
  loadVault,
  restoreVaultVersion,
  saveDraft as persistDraft,
  saveToVault,
  type SavedArtifact,
} from '../../utils/artifactVault';
import type { ActiveArtifact } from './types';

interface Options {
  active: ActiveArtifact | null;
  content: string;
  panelOpen: boolean;
  activeProjectId: string | null;
  activeSessionId: string | null;
  addToast: (message: string, options?: ToastOptions) => void;
  /** Apply restored content back into the panel's editor state. */
  applyContent: (artifactId: string, content: string) => void;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

/**
 * Vault + project version state for the selected artifact.
 *
 * Explicit saves create local versions (and a server version for project
 * artifacts). Restores autosave the current content first and offer an
 * "Undo restore" action in the toast.
 */
export function useArtifactVault({
  active,
  content,
  panelOpen,
  activeProjectId,
  activeSessionId,
  addToast,
  applyContent,
}: Options) {
  const [vaultItems, setVaultItems] = useState<SavedArtifact[]>([]);
  const [projectArtifact, setProjectArtifact] = useState<ProjectArtifact | null>(
    null,
  );
  const [projectLoading, setProjectLoading] = useState(false);
  const savingRef = useRef(false);
  const projectRequestRef = useRef(0);
  const refreshTokenRef = useRef(0);

  const applyVaultItems = (items: SavedArtifact[]) => {
    // Invalidate any in-flight refresh whose snapshot predates this write.
    refreshTokenRef.current += 1;
    setVaultItems(items);
  };

  const refresh = useCallback(async () => {
    const token = refreshTokenRef.current + 1;
    refreshTokenRef.current = token;
    try {
      const items = await loadVault();
      if (refreshTokenRef.current === token) setVaultItems(items);
    } catch {
      if (refreshTokenRef.current === token) setVaultItems([]);
    }
  }, []);

  useEffect(() => {
    if (panelOpen) void refresh();
  }, [panelOpen, refresh]);

  // Keep the panel in sync with async autosaves (e.g. a draft written while
  // the panel was closing and immediately reopened).
  useEffect(() => {
    const handler = () => {
      void refresh();
    };
    window.addEventListener('palimind:artifact-vault-updated', handler);
    return () => {
      window.removeEventListener('palimind:artifact-vault-updated', handler);
    };
  }, [refresh]);

  const projectId = active?.projectId ?? null;
  const artifactId = active?.id ?? '';

  const loadProjectArtifact = useCallback(async () => {
    const request = projectRequestRef.current + 1;
    projectRequestRef.current = request;

    if (!projectId || !artifactId) {
      setProjectArtifact(null);
      setProjectLoading(false);
      return;
    }
    setProjectLoading(true);
    try {
      const result = await api.projects.artifacts.get(projectId, artifactId);
      if (projectRequestRef.current !== request) return;
      setProjectArtifact(result.error ? null : result);
    } catch {
      if (projectRequestRef.current === request) setProjectArtifact(null);
    } finally {
      if (projectRequestRef.current === request) setProjectLoading(false);
    }
  }, [artifactId, projectId]);

  useEffect(() => {
    if (panelOpen) void loadProjectArtifact();
  }, [panelOpen, loadProjectArtifact]);

  const saved = active
    ? vaultItems.find(item => item.id === active.id) || null
    : null;

  const saveDraftFor = async (
    artifact: Pick<ActiveArtifact, 'id' | 'type' | 'language' | 'title'>,
    value: string,
    note: string,
  ) => {
    const result = await persistDraft(
      {
        id: artifact.id,
        type: artifact.type,
        language: artifact.language,
        title: artifact.title,
        content: value,
      },
      note,
    );
    applyVaultItems(result.items);
    return result;
  };

  const saveDraftSnapshot = async (note: string) => {
    if (!active) return null;
    return saveDraftFor(active, content, note);
  };

  const save = async () => {
    if (!active || savingRef.current) return;
    savingRef.current = true;
    try {
      const isProject = Boolean(active.projectId && active.source === 'project');
      const needLocal = !saved || saved.content !== content;
      const needServer = isProject && projectArtifact?.content !== content;

      if (!needLocal && !needServer) {
        addToast('No changes to save');
        return;
      }

      let localSaved = false;
      if (needLocal) {
        const result = await saveToVault(
          {
            id: active.id,
            type: active.type,
            language: active.language,
            title: active.title,
            content,
          },
          'Saved from artifact panel',
        );
        applyVaultItems(result.items);
        localSaved = result.created;
      }

      let serverSaved = false;
      if (isProject && active.projectId) {
        // Project artifacts use the server's immutable version history.
        try {
          const updated = await api.projects.artifacts.addVersion(
            active.projectId,
            active.id,
            {
              title: active.title,
              content,
              description: 'Saved from artifact panel',
            },
          );
          if (!updated.error) {
            serverSaved = true;
            await loadProjectArtifact();
          }
        } catch {
          // The local vault copy is still saved.
        }
      } else {
        // Mirror the save into the optional server-side global library.
        void api.artifacts
          .save({
            id: active.id,
            title: active.title,
            type: active.type,
            language: active.language,
            content,
            project_id: activeProjectId || undefined,
            source: 'artifact-vault',
            session_id: activeSessionId || undefined,
          })
          .catch(() => undefined);
      }

      if (!localSaved && !serverSaved) {
        addToast('No changes to save');
        return;
      }
      addToast(
        serverSaved && !localSaved
          ? 'Server version saved'
          : 'Saved to artifact vault',
        { tone: 'success' },
      );
    } finally {
      savingRef.current = false;
    }
  };

  const undoLocalRestore = async (
    restoredArtifactId: string,
    versionId: string,
  ) => {
    try {
      const next = await restoreVaultVersion(restoredArtifactId, versionId);
      applyVaultItems(next);
      const restored = next.find(item => item.id === restoredArtifactId);
      if (restored) {
        applyContent(restoredArtifactId, restored.content);
        addToast('Restore undone', { tone: 'success' });
      }
    } catch (error) {
      addToast(errorMessage(error, 'Could not undo the restore.'), {
        tone: 'error',
      });
    }
  };

  const restore = async (versionId: string) => {
    if (!active) return;
    const restoredArtifactId = active.id;
    try {
      // Keep the pre-restore content as a visible autosaved draft.
      const draft = await saveDraftSnapshot('Autosaved before restore');
      const next = await restoreVaultVersion(restoredArtifactId, versionId);
      applyVaultItems(next);
      const restored = next.find(item => item.id === restoredArtifactId);
      if (!restored) return;
      applyContent(restoredArtifactId, restored.content);
      addToast('Version restored', {
        tone: 'success',
        duration: 9000,
        action: draft
          ? {
              label: 'Undo restore',
              onClick: () => {
                void undoLocalRestore(restoredArtifactId, draft.versionId);
              },
            }
          : undefined,
      });
    } catch (error) {
      addToast(errorMessage(error, 'Could not restore the version.'), {
        tone: 'error',
      });
    }
  };

  const undoProjectRestore = async (
    restoredArtifactId: string,
    restoredProjectId: string,
    contentToRestore: string,
  ) => {
    try {
      const updated = await api.projects.artifacts.addVersion(
        restoredProjectId,
        restoredArtifactId,
        { content: contentToRestore, description: 'Undo restore' },
      );
      if (updated.error) throw new Error(updated.error);
      applyContent(restoredArtifactId, contentToRestore);
      await loadProjectArtifact();
      addToast('Restore undone', { tone: 'success' });
    } catch (error) {
      addToast(errorMessage(error, 'Could not undo the restore.'), {
        tone: 'error',
      });
    }
  };

  const restoreProjectVersion = async (version: number) => {
    if (!active || !projectId) return;
    const restoredArtifactId = active.id;
    const restoredProjectId = projectId;
    const previousContent = content;

    try {
      const target = await api.projects.artifacts.get(
        restoredProjectId,
        restoredArtifactId,
        version,
      );
      if (target.error) throw new Error(target.error);

      if (projectArtifact && target.content === projectArtifact.content) {
        addToast('No changes to restore');
        return;
      }

      await saveDraftSnapshot(`Autosaved before restoring server version ${version}`);
      const updated = await api.projects.artifacts.addVersion(
        restoredProjectId,
        restoredArtifactId,
        {
          title: active.title,
          content: target.content ?? '',
          description: `Restored server version ${version}`,
        },
      );
      if (updated.error) throw new Error(updated.error);

      applyContent(restoredArtifactId, target.content ?? '');
      await loadProjectArtifact();
      addToast(`Server version ${version} restored`, {
        tone: 'success',
        duration: 9000,
        action: {
          label: 'Undo restore',
          onClick: () => {
            void undoProjectRestore(
              restoredArtifactId,
              restoredProjectId,
              previousContent,
            );
          },
        },
      });
    } catch (error) {
      addToast(errorMessage(error, 'Could not restore the server version.'), {
        tone: 'error',
      });
    }
  };

  const getLocalVersionContent = async (versionId: string) => {
    if (!active) return '';
    return (await getVaultVersionContent(active.id, versionId)) ?? '';
  };

  const getProjectVersionContent = async (version: number) => {
    if (!projectId || !artifactId) return '';
    try {
      const result = await api.projects.artifacts.get(projectId, artifactId, version);
      return result.content ?? '';
    } catch {
      return '';
    }
  };

  return {
    saved,
    save,
    saveDraft: saveDraftSnapshot,
    saveDraftFor,
    restore,
    refresh,
    projectArtifact,
    projectLoading,
    refreshProject: loadProjectArtifact,
    restoreProjectVersion,
    getLocalVersionContent,
    getProjectVersionContent,
  };
}
