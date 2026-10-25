import ArtifactPanel from '../ArtifactPanel';
import CanvasPanel from '../CanvasPanel';
import { useApp } from '../../AppContext';

/**
 * Right rail shared by artifacts and the canvas editor. Both panels already
 * render nothing when closed; this wrapper adds the 200ms slide/fade motion
 * and keeps the two mutually exclusive rails in one flex slot.
 */
export default function SidePanel() {
  const { artifactPanelOpen, canvasOpen } = useApp();
  const open = artifactPanelOpen || canvasOpen;

  if (!open) return null;

  return (
    <div className="app-side-panel" aria-label="Side panel">
      <ArtifactPanel />
      <CanvasPanel />
    </div>
  );
}
