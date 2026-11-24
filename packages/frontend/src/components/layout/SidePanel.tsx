import { useEffect, useState } from 'react';
import WorkbenchPanel from '../workbench/WorkbenchPanel';
import { useApp } from '../../AppContext';

/** How long the exit animation runs. Keep in sync with layout.css (240ms). */
const CLOSE_MS = 240;

/**
 * Right rail for the Workbench (artifacts, browser, files and sources). The
 * panel renders nothing when closed, but a short "closing" phase keeps it
 * mounted so the exit animation can play.
 */
export default function SidePanel() {
  const { workbenchOpen } = useApp();

  const [phase, setPhase] = useState<'open' | 'closing' | 'closed'>(
    workbenchOpen ? 'open' : 'closed',
  );

  useEffect(() => {
    if (workbenchOpen) {
      setPhase('open');
      return;
    }
    setPhase(previous => (previous === 'closed' ? previous : 'closing'));
  }, [workbenchOpen]);

  useEffect(() => {
    if (phase !== 'closing') return;
    const timer = window.setTimeout(() => setPhase('closed'), CLOSE_MS);
    return () => window.clearTimeout(timer);
  }, [phase]);

  if (phase === 'closed') return null;

  const closing = phase === 'closing';

  return (
    <div
      className={`app-side-panel${closing ? ' is-closing' : ''}`}
      aria-label="Side panel"
      aria-hidden={closing || undefined}
    >
      <WorkbenchPanel />
    </div>
  );
}
