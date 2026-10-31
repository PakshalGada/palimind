import { useEffect, useState } from 'react';
import ArtifactPanel from '../ArtifactPanel';
import { useApp } from '../../AppContext';

/** How long the exit animation runs. Keep in sync with layout.css (240ms). */
const CLOSE_MS = 240;

/**
 * Right rail for artifacts. The panel renders nothing when closed, but instead
 * of unmounting immediately, a short "closing" phase keeps it mounted so the
 * exit animation in layout.css can play — closing no longer feels abrupt.
 */
export default function SidePanel() {
  const { artifactPanelOpen, artifactLibraryOpen } = useApp();
  const open = artifactPanelOpen || artifactLibraryOpen;

  const [phase, setPhase] = useState<'open' | 'closing' | 'closed'>(
    open ? 'open' : 'closed',
  );

  useEffect(() => {
    if (open) {
      setPhase('open');
      return;
    }
    setPhase(previous => (previous === 'closed' ? previous : 'closing'));
  }, [open]);

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
      <ArtifactPanel forceVisible />
    </div>
  );
}
