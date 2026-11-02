import { useRef, useEffect, useMemo, useState, useCallback, memo } from 'react';
import { useApp } from '../AppContext';
import { useUserName } from '../hooks/useUserName';
import { getGreeting } from '../utils/greeting';
import { api } from '../api';
import { useBookmarks } from '../hooks/useBookmarks';
import IndexingProgress from './IndexingProgress';
import InputArea from './InputArea';
import MessageActions from './MessageActions';
import MessageContent from './MessageContent';
import { useChatStreamContext } from '../stream/context';
import StreamingTurn from '../stream/StreamingTurn';
import { HistoryActivity } from '@/components/activity/shell/HistoryActivity';
import { SourcesList } from '@/components/activity/citations/SourcesList';
import { resultsFromSources } from '@/components/activity/recorder';
import { isTerminal } from '@/components/activity/model';
import { persistActivity } from '@/components/activity/store';
import type { ActivityMode } from '../AppContext';
import type { CitationPayload } from '../types';

interface ChatMessage {
  role: string;
  content: string;
  sources?: string[];
  citations?: CitationPayload;
}

export default function ChatArea() {
  const {
    sessions,
    activeSessionId,
    activeView,
    selectedAgentId,
    chatMode,
    llmSubMode,
    setSessions,
    setActiveSessionId,
    refreshSessions,
    addToast,
    openArtifact,
  } = useApp();
  const messagesRef = useRef<HTMLDivElement>(null);
  const [scrollbarVisible, setScrollbarVisible] = useState(false);
  const { state: streamState, activityStore } = useChatStreamContext();
  const persistedKey = useRef('');
  const finalRunRef = useRef('');

  const currentSess = sessions.find(s => s.id === activeSessionId);
  // A live turn belongs to the session it was started from. New sessions have
  // no id yet, so `null` means "show wherever the composer is".
  const isStreaming =
    streamState.status !== 'idle' &&
    (streamState.sessionId === null || streamState.sessionId === activeSessionId);
  const isEmpty =
    !isStreaming && (!currentSess || !currentSess.messages || currentSess.messages.length === 0);

  // Remember the run that just settled, before the stream state resets.
  useEffect(() => {
    if (streamState.status === 'idle') return;
    const act = activityStore.getState();
    if (act && isTerminal(act.status)) finalRunRef.current = act.runId;
  }, [streamState.status, activityStore, streamState.revision]);

  // Persist the settled run once the refreshed session exists. This also
  // covers first messages, whose session id is only assigned by the backend.
  useEffect(() => {
    if (!activeSessionId || !finalRunRef.current) return;
    if (streamState.sessionId !== null && streamState.sessionId !== activeSessionId) return;
    const act = activityStore.getState();
    if (!act || act.runId !== finalRunRef.current) return;
    const messages = currentSess?.messages ?? [];
    const last = messages[messages.length - 1];
    if (!last || last.role === 'user') return;
    const index = messages.length - 1;
    const key = `${activeSessionId}:${index}:${act.runId}`;
    if (persistedKey.current === key) return;
    persistedKey.current = key;
    const reasoningText = activityStore.buffers.get('reasoning').getSnapshot().text;
    const persisted =
      act.reasoning && reasoningText
        ? { ...act, reasoning: { ...act.reasoning, text: reasoningText } }
        : act;
    persistActivity(activeSessionId, index, persisted);
    finalRunRef.current = '';
  }, [
    activeSessionId,
    currentSess?.messages,
    activityStore,
    streamState.sessionId,
    streamState.status,
  ]);

  const { isBookmarked, toggle: toggleBookmark } = useBookmarks(activeSessionId);

  const scope =
    activeView === 'agents'
      ? selectedAgentId
        ? `agent:${selectedAgentId}`
        : ''
      : activeView === 'chat'
        ? 'chat'
        : 'field';

  const activityMode: ActivityMode =
    activeView === 'agents'
      ? 'agent'
      : chatMode === 'document'
        ? 'document'
        : llmSubMode === 'moe'
          ? 'moe'
          : llmSubMode === 'deep_research'
            ? 'deep_research'
            : 'llm';

  const applySessions = useCallback(
    (data: { sessions?: unknown[]; active_session_id?: string; error?: string }) => {
      if (data.error) {
        addToast(data.error);
        return;
      }
      if (data.sessions) setSessions(data.sessions as typeof sessions);
      if (data.active_session_id) setActiveSessionId(data.active_session_id);
    },
    [addToast, setSessions, setActiveSessionId],
  );

  const triggerRegenerate = useCallback(
    async (userContent: string) => {
      window.dispatchEvent(
        new CustomEvent('palimind:regenerate-message', { detail: { content: userContent } }),
      );
    },
    [],
  );

  const handleRegenerate = useCallback(
    async (index: number) => {
      if (!currentSess || !activeSessionId) return;
      const messages = currentSess.messages;
      let userIndex = -1;
      for (let i = index - 1; i >= 0; i--) {
        if (messages[i].role === 'user') {
          userIndex = i;
          break;
        }
      }
      if (userIndex === -1) {
        addToast('No prompt found to regenerate from.');
        return;
      }
      try {
        const data = await api.sessions.truncate(activeSessionId, userIndex, scope);
        applySessions(data);
        await refreshSessions();
        await triggerRegenerate(messages[userIndex].content);
      } catch {
        addToast('Could not regenerate response.');
      }
    },
    [currentSess, activeSessionId, scope, addToast, applySessions, refreshSessions, triggerRegenerate],
  );

  const handleSaveEdit = useCallback(
    async (index: number, content: string) => {
      if (!activeSessionId) return;
      const trimmed = content.trim();
      if (!trimmed) {
        addToast('Message cannot be empty.');
        return;
      }
      try {
        const data = await api.sessions.truncate(activeSessionId, index, scope);
        applySessions(data);
        await refreshSessions();
        await triggerRegenerate(trimmed);
      } catch {
        addToast('Could not edit message.');
      }
    },
    [activeSessionId, scope, addToast, applySessions, refreshSessions, triggerRegenerate],
  );

  const handleDelete = useCallback(
    async (index: number) => {
      if (!activeSessionId) return;
      try {
        const data = await api.sessions.deleteMessage(activeSessionId, index, scope);
        applySessions(data);
        await refreshSessions();
        addToast('Message deleted');
      } catch {
        addToast('Could not delete message.');
      }
    },
    [activeSessionId, scope, addToast, applySessions, refreshSessions],
  );

  const handleShare = useCallback(() => {
    if (!currentSess?.messages?.length) {
      addToast('Nothing to share yet.');
      return;
    }
    const transcript = currentSess.messages
      .map((m) => `${m.role === 'user' ? 'You' : 'Assistant'}:\n${m.content}`)
      .join('\n\n---\n\n');
    navigator.clipboard
      .writeText(transcript)
      .then(() => addToast('Conversation transcript copied to clipboard'))
      .catch(() => addToast('Could not access the clipboard'));
  }, [currentSess, addToast]);

  const handleSaveResearch = useCallback((content: string, sources: unknown[]) => {
    window.dispatchEvent(
      new CustomEvent('palimind:save-research', { detail: { content, sources } }),
    );
  }, []);

  // Track whether the user is pinned to the bottom of the conversation.
  // We only auto-scroll when they're already near the bottom so that
  // scrolling up to read earlier messages isn't interrupted by background
  // session refreshes.
  const pinnedToBottom = useRef(true);

  const handleScroll = () => {
    const el = messagesRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    pinnedToBottom.current = distanceFromBottom < 80;
  };

  // Use message count + last message content as dependency instead of array reference
  // This prevents unnecessary scroll resets when the array reference changes but content hasn't
  const messagesKey = useMemo(() => {
    if (!currentSess?.messages || currentSess.messages.length === 0) return 'empty';
    const lastMsg = currentSess.messages[currentSess.messages.length - 1];
    return `${currentSess.messages.length}-${lastMsg?.content?.length || 0}`;
  }, [currentSess?.messages]);

  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    if (pinnedToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messagesKey, streamState.revision]);

  const showScrollbarNearEdge = (event: React.MouseEvent<HTMLElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setScrollbarVisible(event.clientX >= rect.right - 28);
  };

  return (
    <main
      className="chat-area"
      id="main-area"
      onMouseMove={showScrollbarNearEdge}
      onMouseLeave={() => setScrollbarVisible(false)}
    >
      <div id="chat-interface" className={`chat-interface${isEmpty ? ' empty-chat' : ''}`} aria-busy={isStreaming}>
        {activeView !== 'chat' && activeView !== 'agents' && <IndexingProgress />}

        <div
          id="messages-scroll-area"
          className={`messages${scrollbarVisible ? ' is-scrollbar-visible' : ''}`}
          ref={messagesRef}
          onScroll={handleScroll}
        >
          {!isEmpty && currentSess?.messages.map((msg, i) => (
            <MessageComponent
              key={`${i}-${msg.role}`}
              msg={msg}
              index={i}
              bookmarked={isBookmarked(msg)}
              onRegenerate={handleRegenerate}
              onSaveEdit={handleSaveEdit}
              onDelete={handleDelete}
              onShare={handleShare}
              onOpenArtifact={openArtifact}
              onSaveResearch={handleSaveResearch}
              onToggleBookmark={toggleBookmark}
              activityMode={activityMode}
              sessionId={activeSessionId}
            />
          ))}
          <StreamingTurn activeSessionId={activeSessionId} />
        </div>

        {isEmpty && <ChatHero />}
        <InputArea />
      </div>
    </main>
  );
}

function ChatHero() {
  const name = useUserName();
  const greeting = useMemo(() => getGreeting(name), [name]);

  return (
    <div className="chat-hero">
      <h1 className="chat-hero-title">{greeting}</h1>
    </div>
  );
}

interface MessageComponentProps {
  msg: ChatMessage;
  index: number;
  bookmarked: boolean;
  onRegenerate: (index: number) => void;
  onSaveEdit: (index: number, content: string) => void;
  onDelete: (index: number) => void;
  onShare: () => void;
  onOpenArtifact: (artifactId: string) => void;
  onSaveResearch: (content: string, sources: unknown[]) => void;
  onToggleBookmark: (msg: ChatMessage) => void;
  activityMode: ActivityMode;
  sessionId: string | null;
}

const MessageComponent = memo(function MessageComponent({
  msg,
  index,
  bookmarked,
  onRegenerate,
  onSaveEdit,
  onDelete,
  onShare,
  onOpenArtifact,
  onSaveResearch,
  onToggleBookmark,
  activityMode,
  sessionId,
}: MessageComponentProps) {
  const isUser = msg.role === 'user';
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(msg.content);

  useEffect(() => {
    setDraft(msg.content);
  }, [msg.content]);

  if (editing) {
    const save = () => {
      setEditing(false);
      onSaveEdit(index, draft);
    };
    return (
      <div className="message user-message">
        <div className="message-wrapper">
          <div className="message-edit">
            <textarea
              value={draft}
              autoFocus
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.preventDefault();
                  setDraft(msg.content);
                  setEditing(false);
                } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  save();
                }
              }}
            />
            <div className="message-edit-actions">
              <button type="button" className="action-btn primary" onClick={save}>
                Save &amp; resend
              </button>
              <button
                type="button"
                className="action-btn"
                onClick={() => {
                  setDraft(msg.content);
                  setEditing(false);
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const historySources = !isUser
    ? resultsFromSources(msg.citations ?? null, [], [])
    : { sources: [], passages: [] };

  return (
    <div className={`message ${isUser ? 'user-message' : 'system-message'} history-message`}>
      <div className="message-wrapper">
        {!isUser && (
          <HistoryActivity
            sessionId={sessionId}
            messageIndex={index}
            mode={activityMode}
            citations={msg.citations}
          />
        )}
        <MessageContent
          content={msg.content}
          citations={msg.citations}
          messageIndex={isUser ? undefined : index}
          onOpenArtifact={onOpenArtifact}
        />
        {!isUser && (
          <SourcesList sources={historySources.sources} passages={historySources.passages} />
        )}
        <MessageActions
          content={msg.content}
          isUser={isUser}
          bookmarked={bookmarked}
          onRegenerate={!isUser ? () => onRegenerate(index) : undefined}
          onEdit={isUser ? () => setEditing(true) : undefined}
          onSaveResearch={!isUser ? () => onSaveResearch(msg.content, msg.citations?.sources ?? []) : undefined}
          onDelete={() => onDelete(index)}
          onShare={onShare}
          onToggleBookmark={() => onToggleBookmark(msg)}
        />
      </div>
    </div>
  );
});