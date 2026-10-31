import { useState } from 'react';
import { api } from '../../api';
import type { ToastOptions } from '../../AppContext';
import {
  EXPORT_FORMAT_LABEL,
  downloadArtifact,
  triggerDownload,
  type ExportFormat,
} from '../../utils/artifacts';
import { exportArtifactAs } from '../../utils/artifactExport';
import type { ActiveArtifact } from './types';

interface Options {
  active: ActiveArtifact | null;
  content: string;
  activeProjectId: string | null;
  addToast: (message: string, options?: ToastOptions) => void;
}

/** Clipboard, download, share and export actions for the selected artifact. */
export function useArtifactExport({
  active,
  content,
  activeProjectId,
  addToast,
}: Options) {
  const [exporting, setExporting] = useState<ExportFormat | null>(null);

  const copy = () => {
    if (!active) return;
    navigator.clipboard
      .writeText(content)
      .then(() => addToast('Artifact copied to clipboard'))
      .catch(() => addToast('Could not access the clipboard'));
  };

  const download = () => {
    if (!active) return;
    downloadArtifact({ type: active.type, title: active.title, content });
  };

  const share = async () => {
    if (!active) return;
    if (navigator.share) {
      try {
        await navigator.share({ title: active.title, text: content });
        return;
      } catch {
        // fall through to clipboard
      }
    }
    copy();
  };

  const openInNewTab = async () => {
    if (!active) return;
    try {
      if (active.type === 'html' || active.type === 'svg') {
        const body =
          active.type === 'svg'
            ? `<!doctype html><html><body style="margin:0;padding:24px;background:#fff">${content}</body></html>`
            : content;
        const mime = active.type === 'svg' ? 'image/svg+xml' : 'text/html';
        const url = URL.createObjectURL(new Blob([body], { type: `${mime};charset=utf-8` }));
        window.open(url, '_blank');
        window.setTimeout(() => URL.revokeObjectURL(url), 15_000);
        return;
      }
      const tab = window.open('', '_blank');
      try {
        const { blob } = await exportArtifactAs(
          { type: active.type, language: active.language, title: active.title, content },
          'html',
        );
        const url = URL.createObjectURL(blob);
        if (tab) tab.location.href = url;
        else window.open(url, '_blank');
        window.setTimeout(() => URL.revokeObjectURL(url), 15_000);
      } catch (error) {
        tab?.close();
        throw error;
      }
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Could not open preview.', {
        tone: 'error',
      });
    }
  };

  const exportAs = async (format: ExportFormat) => {
    if (!active) return;
    setExporting(format);
    try {
      const { blob, filename } = await exportArtifactAs(
        { type: active.type, language: active.language, title: active.title, content },
        format,
      );
      triggerDownload(blob, filename);
      addToast(`Exported ${EXPORT_FORMAT_LABEL[format]}`, { tone: 'success' });
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Export failed', {
        tone: 'error',
      });
    } finally {
      setExporting(null);
    }
  };

  const saveToKnowledge = async () => {
    if (!active) return;
    try {
      const result = await api.artifacts.saveToKnowledge({
        title: active.title,
        content,
        project_id: activeProjectId || undefined,
      });
      if (result.error) {
        addToast(`Saved file, but indexing failed: ${result.error}`, {
          tone: 'warning',
        });
        return;
      }
      addToast(result.message || 'Saved to knowledge base', { tone: 'success' });
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Could not save to knowledge.', {
        tone: 'error',
      });
    }
  };

  return { exporting, copy, download, share, openInNewTab, exportAs, saveToKnowledge };
}
