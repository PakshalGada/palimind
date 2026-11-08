import { useEffect, useRef } from 'react';
import { api } from '../api';
import { useApp } from '../AppContext';
import { useChatStreamContext } from '../stream/context';
import { triggerDownload } from '../utils/artifacts';
import { buildOfficePayload } from '../utils/officePipeline';

export interface OfficeJob {
  format: 'docx' | 'pptx';
  title: string;
  /** Set when the user started the job from the composer. */
  id: number;
}

/**
 * Watches the turn started by the composer's "Word document" / "PowerPoint
 * file" actions. When the answer settles it turns the fenced artifact into a
 * real Office file on the backend and downloads it.
 *
 * This lives in a tiny component so the heavy stream context re-renders do
 * not touch the whole composer. The job is one-shot; `onDone` clears it.
 */
export default function OfficeExportWatcher({
  job,
  onDone,
}: {
  job: OfficeJob | null;
  onDone: () => void;
}) {
  const { state } = useChatStreamContext();
  const { addToast } = useApp();
  const handled = useRef<number | null>(null);
  // A previous turn may still be `done` when the job is armed. Require this
  // job's turn to actually start before accepting its terminal state.
  const started = useRef<number | null>(null);

  useEffect(() => {
    if (!job || handled.current === job.id) return;
    if (state.status === 'streaming') {
      started.current = job.id;
      return;
    }
    if (started.current !== job.id) return;
    if (state.status !== 'done' && state.status !== 'error') return;
    handled.current = job.id;
    started.current = null;

    if (state.status === 'error') {
      addToast(
        state.error || `The ${job.format.toUpperCase()} job could not finish.`,
        { tone: 'error' },
      );
      onDone();
      return;
    }

    const answer = state.answer || '';
    if (!answer.trim()) {
      addToast(`The model returned no content for the ${job.format.toUpperCase()} file.`, {
        tone: 'warning',
      });
      onDone();
      return;
    }

    const payload = buildOfficePayload(job.format, answer, job.title || 'Document');
    if (!payload) {
      addToast(`No ${job.format === 'pptx' ? 'slides' : 'document'} were found in the answer.`, {
        tone: 'warning',
      });
      onDone();
      return;
    }

    void (async () => {
      try {
        const result = await api.office.generate(payload);
        triggerDownload(result.blob, result.filename);
        addToast(`${job.format === 'pptx' ? 'PowerPoint' : 'Word'} file downloaded`, {
          tone: 'success',
        });
      } catch (error) {
        addToast(error instanceof Error ? error.message : 'Could not build the file', {
          tone: 'error',
        });
      } finally {
        onDone();
      }
    })();
  }, [job, state.status, state.answer, state.error, addToast, onDone]);

  return null;
}
