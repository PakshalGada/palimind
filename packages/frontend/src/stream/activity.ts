import type { ActivityMode, ActivityState } from '../AppContext';

/**
 * Metadata a send needs to pick its run renderer. The old tracker that lived
 * here has been replaced by the normalized activity store.
 */
export interface ActivityInfo {
  mode: ActivityMode;
  title: string;
  subtitle?: string;
  seed?: string;
  agentAvatar?: ActivityState['agentAvatar'];
}
