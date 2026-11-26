import { useRef, useEffect, useMemo, useState, useCallback, memo } from 'react';
import { useApp } from '../AppContext';
import { useUserName } from '../hooks/useUserName';
import { getGreeting } from '../utils/greeting';
import { api } from '../api';
import { useBookmarks } from '../hooks/useBookmarks';
import IndexingProgress from './IndexingProgress';
import { PixelGlyph } from './pixel/PixelGlyph';
import { PixelAssemble } from './pixel/PixelAssemble';
import InputArea from './InputArea';
import ArtifactAnswerBlock from './ArtifactAnswerBlock';
import MessageAttachments from './chat/MessageAttachments';
import FollowUpChips from './chat/FollowUpChips';
import MessageActions from './MessageActions';
import MessageContent from './MessageContent';
import { speech, useSpeech } from '../utils/speech';
import { getVoice } from '../utils/voicePrefs';
import type { BranchChild } from '../types';
import { parseArtifacts, shouldAutoOpenArtifact, type Artifact } from '../utils/artifacts';
import { saveToVault } from '../utils/artifactVault';
import { exportConversation, type ConversationExportFormat } from '../utils/conversationExport';
import { useChatStreamContext } from '../stream/context';
import StreamingTurn from '../stream/StreamingTurn';
import { streamBelongsTo } from '../stream/reducer';
import { HistoryActivity } from '@/components/activity/shell/HistoryActivity';
import { SourcesPanel } from '@/components/sources/SourcesPanel';
import { isTerminal } from '@/components/activity/model';
import { persistActivity } from '@/components/activity/store';
import type { ActivityMode } from '../AppContext';
import type { CitationPayload, ChatAttachment } from '../types';
import { resolveScope } from '../lib/scope';

interface ChatMessage {
  id?: number;
  role: string;
  content: string;
  sources?: string[];
  citations?: CitationPayload;
  suggestions?: string[];
  attachments?: ChatAttachment[];
}

export default function ChatArea() {
  const {
    sessions,
    activeSessionId,
    activeView,
    activeProjectId,
    isGenerating,
    selectedAgentId,
    chatMode,
    llmSubMode,
    setSessions,
    setActiveSessionId,
    refreshSessions,
    addToast,
    openArtifact,
    addChatMemory,
    pinContext,
  } = useApp();
  const messagesRef = useRef<HTMLDivElement>(null);
  const [scrollbarVisible, setScrollbarVisible] = useState(false);
  const { state: streamState, activityStore } = useChatStreamContext();
  const persistedKey = useRef('');
  const finalRunRef = useRef('');

  const currentSess = sessions.find(s => s.id === activeSessionId);
  // A live turn belongs to the session it was started from (or, for a new
  // chat, the one the server reports in its first `session` event).
  const isStreaming = streamBelongsTo(streamState, activeSessionId);
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

  // Onboarding step 4: persist that at least one question has been asked, so
  // the welcome checklist stays complete across restarts.
  useEffect(() => {
    if (!currentSess?.messages?.some(m => m.role === 'user')) return;
    try {
      localStorage.setItem('palimind:onboarding-asked', '1');
    } catch {
      // storage unavailable; the checklist falls back to probing sessions
    }
  }, [currentSess?.messages]);

  const scope = resolveScope(activeView, {
    agentId: selectedAgentId,
    projectId: activeProjectId,
  });

  // Global search jumps to a specific message: scroll it into view and
  // flash the bubble so it is easy to spot in a long thread.
  useEffect(() => {
    const onGoto = (event: Event) => {
      const detail = (
        event as CustomEvent<{ sessionId?: string; messageId?: number; messageIndex?: number }>
      ).detail;
      const messageId = detail?.messageId;
      const messageIndex = detail?.messageIndex;
      if (messageId == null && messageIndex == null) return;
      if (detail.sessionId && detail.sessionId !== activeSessionId) return;
      const timer = window.setTimeout(() => {
        const selector =
          messageId != null
            ? `[data-message-id="${messageId}"]`
            : `[data-message-index="${messageIndex}"]`;
        const el = messagesRef.current?.querySelector<HTMLElement>(selector);
        el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
        el?.classList.add('message-flash');
        window.setTimeout(() => el?.classList.remove('message-flash'), 2400);
      }, 60);
      return () => window.clearTimeout(timer);
    };
    window.addEventListener('palimind:goto-message', onGoto);
    return () => window.removeEventListener('palimind:goto-message', onGoto);
  }, [activeSessionId]);

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

  /**
   * Fence artifacts are addressed by position (`fence-<msgIndex>-<n>`), so a
   * regenerate or edit-and-resend replaces them in place and the previous
   * content would be unrecoverable. Snapshot every artifact of the messages
   * about to be truncated into the local vault (keyed by session, the same
   * scheme the artifact panel uses) before the overwrite happens.
   */
  const snapshotArtifactsBeforeTruncate = useCallback(
    (messages: ChatMessage[] | undefined, dropFromIndex: number, sessionId: string | null) => {
      if (!messages || !sessionId) return;
      for (let i = Math.max(0, dropFromIndex); i < messages.length; i++) {
        const msg = messages[i];
        if (msg.role === 'user') continue;
        for (const artifact of parseArtifacts(msg.content, i)) {
          void saveToVault(
            {
              id: `${sessionId}:${artifact.id}`,
              type: artifact.type,
              language: artifact.language,
              title: artifact.title,
              content: artifact.content,
            },
            'Snapshot before regeneration',
          ).catch(() => undefined);
        }
      }
    },
    [],
  );

  const handleRegenerate = useCallback(
    async (index: number) => {
      if (!currentSess || !activeSessionId) return;
      // Truncating mid-stream would drop the reply while the resend is
      // refused by the composer (it ignores sends while generating).
      if (isGenerating) {
        addToast('Wait for the current response to finish.');
        return;
      }
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
      snapshotArtifactsBeforeTruncate(messages, userIndex, activeSessionId);
      try {
        const data = await api.sessions.truncate(activeSessionId, userIndex, scope);
        applySessions(data);
        await refreshSessions();
        await triggerRegenerate(messages[userIndex].content);
      } catch {
        addToast('Could not regenerate response.');
      }
    },
    [currentSess, activeSessionId, isGenerating, scope, addToast, applySessions, refreshSessions, triggerRegenerate, snapshotArtifactsBeforeTruncate],
  );

  const handleSaveEdit = useCallback(
    async (index: number, content: string) => {
      if (!activeSessionId) return;
      if (isGenerating) {
        addToast('Wait for the current response to finish.');
        return;
      }
      const trimmed = content.trim();
      if (!trimmed) {
        addToast('Message cannot be empty.');
        return;
      }
      snapshotArtifactsBeforeTruncate(currentSess?.messages, index, activeSessionId);
      try {
        const data = await api.sessions.truncate(activeSessionId, index, scope);
        applySessions(data);
        await refreshSessions();
        await triggerRegenerate(trimmed);
      } catch {
        addToast('Could not edit message.');
      }
    },
    [activeSessionId, isGenerating, scope, addToast, applySessions, refreshSessions, triggerRegenerate, snapshotArtifactsBeforeTruncate, currentSess?.messages],
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

  /**
   * Fork from a message: the composer arms for a new direction and the next
   * send becomes the first message of a new branch (the old path stays
   * switchable at the fork point).
   */
  const handleFork = useCallback(
    (index: number) => {
      if (!activeSessionId) return;
      if (isGenerating) {
        addToast('Wait for the current response to finish.');
        return;
      }
      const msg = currentSess?.messages?.[index];
      if (!msg?.id) return;
      window.dispatchEvent(
        new CustomEvent('palimind:fork-armed', {
          detail: { sessionId: activeSessionId, messageId: msg.id },
        }),
      );
      addToast('Type the new direction — your next message starts a branch.');
    },
    [activeSessionId, currentSess?.messages, isGenerating, addToast],
  );

  const handleSwitchBranch = useCallback(
    async (leafId: number) => {
      if (!activeSessionId) return;
      try {
        const data = await api.sessions.switchBranch(activeSessionId, leafId, scope);
        applySessions(data);
        await refreshSessions();
      } catch {
        addToast('Could not switch branch.');
      }
    },
    [activeSessionId, scope, addToast, applySessions, refreshSessions],
  );

  const handleShare = useCallback(
    (format: ConversationExportFormat | 'copy' = 'copy') => {
      if (!currentSess?.messages?.length) {
        addToast('Nothing to share yet.');
        return;
      }
      const conversation = {
        title: currentSess.name || 'Conversation',
        createdAt: currentSess.created_at,
        messages: currentSess.messages,
      };
      if (format === 'copy') {
        const transcript = currentSess.messages
          .map((m) => `${m.role === 'user' ? 'You' : 'Assistant'}:\n${m.content}`)
          .join('\n\n---\n\n');
        navigator.clipboard
          .writeText(transcript)
          .then(() => addToast('Conversation transcript copied to clipboard'))
          .catch(() => addToast('Could not access the clipboard'));
        return;
      }
      const label = format === 'md' ? 'Markdown' : format === 'pdf' ? 'PDF' : 'Word';
      exportConversation(conversation, format)
        .then((filename) => addToast(`Exported as ${label}: ${filename}`, { tone: 'success' }))
        .catch((error: unknown) =>
          addToast(
            `Export failed: ${error instanceof Error ? error.message : 'unknown error'}`,
            { tone: 'error' },
          ),
        );
    },
    [currentSess, addToast],
  );

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

  // Opening a conversation or sending a new prompt always jumps to the end,
  // even if the user had scrolled up in the previous view.
  useEffect(() => {
    pinnedToBottom.current = true;
  }, [activeSessionId, streamState.startedAt]);

  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    if (pinnedToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messagesKey, streamState.revision, activeSessionId]);

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
          {!isEmpty && currentSess?.messages?.map((msg, i) => (
            <MessageComponent
              key={`${i}-${msg.role}`}
              msg={msg}
              index={i}
              bookmarked={isBookmarked(msg)}
              branchOptions={currentSess?.branches?.[String(msg.id ?? '')]}
              onSwitchBranch={handleSwitchBranch}
              onFork={handleFork}
              onRegenerate={handleRegenerate}
              onSaveEdit={handleSaveEdit}
              onDelete={handleDelete}
              onShare={handleShare}
              onOpenArtifact={openArtifact}
              onToggleBookmark={toggleBookmark}
              onRemember={() => addChatMemory(msg.content.slice(0, 500))}
              onPin={() =>
                pinContext({
                  id: `msg:${activeSessionId ?? 'draft'}:${msg.id ?? i}`,
                  kind: 'message',
                  title: msg.content.replace(/^#+\s*/, '').split('\n')[0].slice(0, 90) || 'Pinned message',
                  content: msg.content,
                })
              }
              onUseArtifactContext={(artifact) =>
                pinContext({
                  id: `${activeSessionId ?? 'draft'}:${artifact.id}`,
                  kind: 'artifact',
                  title: artifact.title,
                  content: artifact.content,
                })
              }
              activityMode={activityMode}
              sessionId={activeSessionId}
              showFollowUps={!isStreaming && i === (currentSess?.messages?.length ?? 0) - 1}
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
      <span className="chat-hero__spark" aria-hidden="true">
        <PixelAssemble>
          <PixelGlyph sprite="spark" cell={3} />
        </PixelAssemble>
      </span>
      <h1 className="chat-hero-title">{greeting}</h1>
    </div>
  );
}

interface MessageComponentProps {
  msg: ChatMessage;
  index: number;
  bookmarked: boolean;
  /** Alternative continuations hanging off this message (branch switcher). */
  branchOptions?: BranchChild[];
  onSwitchBranch: (leafId: number) => void;
  onFork: (index: number) => void;
  onRegenerate: (index: number) => void;
  onSaveEdit: (index: number, content: string) => void;
  onDelete: (index: number) => void;
  onShare: (format?: ConversationExportFormat | 'copy') => void;
  onOpenArtifact: (artifactId: string) => void;
  onToggleBookmark: (msg: ChatMessage) => void;
  onRemember: () => void;
  onPin: () => void;
  onUseArtifactContext: (artifact: Artifact) => void;
  activityMode: ActivityMode;
  sessionId: string | null;
  showFollowUps?: boolean;
}

const MessageComponent = memo(function MessageComponent({
  msg,
  index,
  bookmarked,
  branchOptions,
  onSwitchBranch,
  onFork,
  onRegenerate,
  onSaveEdit,
  onDelete,
  onShare,
  onOpenArtifact,
  onToggleBookmark,
  onRemember,
  onPin,
  onUseArtifactContext,
  activityMode,
  sessionId,
  showFollowUps = false,
}: MessageComponentProps) {
  const isUser = msg.role === 'user';
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(msg.content);

  useEffect(() => {
    setDraft(msg.content);
  }, [msg.content]);

  const historySources = !isUser ? msg.sources ?? [] : [];
  const speechState = useSpeech();
  const messageKey = `msg:${sessionId ?? ''}:${msg.id ?? `i${index}`}`;
  const speaking = speechState.messageId === messageKey && speechState.status !== 'idle';
  const speakLoading = speechState.messageId === messageKey && speechState.status === 'loading';
  const onSpeak =
    !isUser && msg.content.trim()
      ? () => speech.toggle(messageKey, msg.content, getVoice())
      : undefined;
  const artifacts = useMemo(
    () =>
      isUser
        ? []
        : parseArtifacts(msg.content, index).filter((artifact) =>
            shouldAutoOpenArtifact(artifact),
          ),
    [isUser, msg.content, index],
  );

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

  return (
    <div
      className={`message ${isUser ? 'user-message' : 'system-message'} history-message`}
      data-message-id={msg.id}
      data-message-index={index}
    >
      <div className="message-wrapper">
        {!isUser && (
          <HistoryActivity
            sessionId={sessionId}
            messageIndex={index}
            mode={activityMode}
            citations={msg.citations}
          />
        )}
        {isUser && msg.attachments && msg.attachments.length > 0 && (
          <MessageAttachments attachments={msg.attachments} />
        )}
        {artifacts.length > 0 ? (
          <ArtifactAnswerBlock
            artifacts={artifacts}
            onOpen={onOpenArtifact}
            onUseContext={onUseArtifactContext}
          />
        ) : (
          <>
            <MessageContent
              content={msg.content}
              citations={msg.citations}
              messageIndex={isUser ? undefined : index}
              commandChip={isUser}
              onOpenArtifact={onOpenArtifact}
            />
            {!isUser && (
              <SourcesPanel citations={msg.citations} legacySources={historySources} />
            )}
          </>
        )}
        <MessageActions
          content={msg.content}
          isUser={isUser}
          bookmarked={bookmarked}
          onRegenerate={!isUser ? () => onRegenerate(index) : undefined}
          onEdit={isUser ? () => setEditing(true) : undefined}
          onSpeak={onSpeak}
          speaking={speaking}
          speakLoading={speakLoading}
          onFork={msg.id ? () => onFork(index) : undefined}
          onDelete={() => onDelete(index)}
          onShare={onShare}
          onToggleBookmark={() => onToggleBookmark(msg)}
          onRemember={onRemember}
          onPin={onPin}
        />
        {showFollowUps && !isUser && (
          <FollowUpChips
            suggestions={msg.suggestions}
            artifacts={artifacts}
            onOpenArtifact={onOpenArtifact}
          />
        )}
        {branchOptions && branchOptions.length > 0 && (
          <BranchSwitcher options={branchOptions} onSwitch={onSwitchBranch} />
        )}
      </div>
    </div>
  );
});

/**
 * Branch switcher under a fork point: cycles between the continuations that
 * hang off this message (the active one is the visible transcript).
 */
function BranchSwitcher({
  options,
  onSwitch,
}: {
  options: BranchChild[];
  onSwitch: (leafId: number) => void;
}) {
  const [busy, setBusy] = useState<number | null>(null);
  const activeIndex = Math.max(
    0,
    options.findIndex((option) => option.active),
  );
  const go = (delta: number) => {
    const next = (activeIndex + delta + options.length) % options.length;
    const option = options[next];
    if (!option || option.active) return;
    setBusy(option.leaf_id);
    Promise.resolve(onSwitch(option.leaf_id)).finally(() => setBusy(null));
  };
  return (
    <div className="branch-switcher" role="group" aria-label="Conversation branches">
      <button
        type="button"
        className="branch-switcher__btn"
        aria-label="Previous branch"
        disabled={options.length < 2 || busy !== null}
        onClick={() => go(-1)}
      >
        ‹
      </button>
      <span className="branch-switcher__label">
        {activeIndex + 1} / {options.length}
      </span>
      <button
        type="button"
        className="branch-switcher__btn"
        aria-label="Next branch"
        disabled={options.length < 2 || busy !== null}
        onClick={() => go(1)}
      >
        ›
      </button>
      <span className="branch-switcher__hint">branch</span>
    </div>
  );
}