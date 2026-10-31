import type { ArtifactFile, ArtifactType } from '../../utils/artifacts';

/** Artifact shape used by the panel, whether it came from the session or the library. */
export interface ActiveArtifact {
  id: string;
  type: ArtifactType;
  language: string;
  title: string;
  content: string;
  messageIndex?: number;
  projectId?: string;
  /** Library/project provenance; unrelated to detection. */
  source?: string;
  filePaths?: string[];
  files?: ArtifactFile[];
  streaming?: boolean;
  closed?: boolean;
}

export type ViewMode = 'preview' | 'code';

export interface ProjectSummary {
  id: string;
  name: string;
  description?: string;
}
