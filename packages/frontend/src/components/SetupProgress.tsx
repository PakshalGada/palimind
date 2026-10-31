import { useEffect, useState } from 'react';
import { api } from '../api';
import type { SetupTask } from '../types';
import { ProgressBar } from '../ui/primitives';
import Thinking from './Thinking';

/** Fast cadence while a model is downloading/loading. */
const POLL_ACTIVE_MS = 2000;
/** Idle cadence: cheap enough to catch a first-run load that starts later. */
const POLL_IDLE_MS = 15_000;

function sameTasks(a: SetupTask[], b: SetupTask[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (
      a[i].key !== b[i].key ||
      a[i].progress !== b[i].progress ||
      a[i].message !== b[i].message ||
      a[i].label !== b[i].label
    ) {
      return false;
    }
  }
  return true;
}

/**
 * Global banner for first-run model downloads / loads. The packaged backend
 * redirects stdout/stderr to /dev/null, so this is the only place the user
 * can see that a model is downloading and how far along it is.
 *
 * Polling lives here (rather than in AppContext) so the 2s tick only re-renders
 * this banner, and only when the reported tasks actually change.
 */
export default function SetupProgress() {
  const [tasks, setTasks] = useState<SetupTask[]>([]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      let next: SetupTask[] | null = null;
      try {
        const data = await api.setup.status();
        next = data.tasks || [];
      } catch {
        // backend not ready yet — keep polling quietly
      }
      if (cancelled) return;
      if (next) setTasks((prev) => (sameTasks(prev, next) ? prev : next));
      const delay = next && next.length > 0 ? POLL_ACTIVE_MS : POLL_IDLE_MS;
      timer = window.setTimeout(tick, delay);
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  if (tasks.length === 0) return null;

  return (
    <div className="indexing-progress-container" role="status" aria-live="polite">
      {tasks.map((task) => (
        <div key={task.key} className="setup-task">
          <ProgressBar
            value={task.progress}
            label={
              <>
                <Thinking variant="beacon" size={12} />
                {task.label}
                {task.message ? ` — ${task.message}` : ''}
              </>
            }
          />
        </div>
      ))}
    </div>
  );
}
