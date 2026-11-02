import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { ActivityStore } from '@/components/activity/store';
import {
  ChatStreamActionsContext,
  ChatStreamContext,
  type ChatStreamActions,
  type ChatStreamStateValue,
} from './context';
import { useChatStream } from './useChatStream';
import type { VideoTarget } from './types';
import VideoOverlay from './VideoOverlay';
import './stream.css';

/**
 * Single owner of live chat state for the whole app, so the composer, the
 * message list and the artifact panel all read the same stream buffer.
 * Actions and state live in separate contexts: the composer never re-renders
 * just because a token arrived.
 */
export function ChatStreamProvider({ children }: { children: ReactNode }) {
  const activityStore = useMemo(() => new ActivityStore(), []);
  const stream = useChatStream(activityStore);
  const [videoTarget, setVideoTarget] = useState<VideoTarget | null>(null);
  const openVideo = useCallback((target: VideoTarget) => setVideoTarget(target), []);
  const closeVideo = useCallback(() => setVideoTarget(null), []);

  const { state, send, stop, retry, isStreaming, liveText } = stream;
  const stateValue = useMemo<ChatStreamStateValue>(
    () => ({ state, isStreaming, liveText, openVideo, activityStore }),
    [state, isStreaming, liveText, openVideo, activityStore],
  );
  const actionsValue = useMemo<ChatStreamActions>(() => ({ send, stop, retry }), [send, stop, retry]);

  return (
    <ChatStreamActionsContext.Provider value={actionsValue}>
      <ChatStreamContext.Provider value={stateValue}>
        {children}
        <VideoOverlay target={videoTarget} onClose={closeVideo} />
      </ChatStreamContext.Provider>
    </ChatStreamActionsContext.Provider>
  );
}
