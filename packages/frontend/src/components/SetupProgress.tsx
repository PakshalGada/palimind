import { useApp } from '../AppContext';

/**
 * Global banner for first-run model downloads / loads. The packaged backend
 * redirects stdout/stderr to /dev/null, so this is the only place the user
 * can see that a model is downloading and how far along it is.
 */
export default function SetupProgress() {
  const { setupTasks } = useApp();

  if (setupTasks.length === 0) return null;

  return (
    <div className="indexing-progress-container" role="status" aria-live="polite">
      {setupTasks.map((task) => (
        <div key={task.key} className="setup-task">
          <div className="progress-bar-label">
            <span className="pulse-dot" />
            {task.label}
            {task.message ? ` — ${task.message}` : ''}
          </div>
          <div className="progress-bar-track">
            <div
              className="progress-bar-fill"
              style={
                task.progress != null
                  ? { width: `${Math.round(task.progress * 100)}%`, animation: 'none' }
                  : undefined
              }
            />
          </div>
        </div>
      ))}
    </div>
  );
}
