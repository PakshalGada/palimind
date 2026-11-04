import type { OpenedArtifact } from '../ArtifactLibrary';

/**
 * Hand-off for artifacts opened outside the panel (the Artifacts page).
 *
 * The panel may not be mounted yet when the request is made, so the artifact
 * is parked here and taken by the panel on mount or on the event below.
 */
export const PENDING_OPEN_EVENT = 'palimind:artifact-pending-open';

let pending: OpenedArtifact | null = null;

export function queueArtifactOpen(artifact: OpenedArtifact): void {
  pending = artifact;
  window.dispatchEvent(new Event(PENDING_OPEN_EVENT));
}

export function takePendingArtifactOpen(): OpenedArtifact | null {
  const artifact = pending;
  pending = null;
  return artifact;
}
