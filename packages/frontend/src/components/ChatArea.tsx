import { useRef, useEffect, useMemo, useState, useCallback } from 'react';
import { useApp } from '../AppContext';
import { api } from '../api';
import { formatMarkdown } from '../utils/markdown';
import { useBookmarks } from '../hooks/useBookmarks';
import IndexingProgress from './IndexingProgress';
import InputArea from './InputArea';
import MessageActions from './MessageActions';

interface ChatMessage {
  role: string;
  content: string;
  sources?: string[];
}

export default function ChatArea() {
  const {
    sessions,
    activeSessionId,
    activeView,
    selectedAgentId,
    setSessions,
    setActiveSessionId,
    refreshSessions,
    addToast,
    setCanvasOpen,
    setArtifactPanelOpen,
    canvasEnabled,
  } = useApp();
  const messagesRef = useRef<HTMLDivElement>(null);

  const currentSess = sessions.find(s => s.id === activeSessionId);
  const isEmpty = !currentSess || !currentSess.messages || currentSess.messages.length === 0;

  const { isBookmarked, toggle: toggleBookmark } = useBookmarks(activeSessionId);

  const scope =
    activeView === 'agents'
      ? selectedAgentId
        ? `agent:${selectedAgentId}`
        : ''
      : activeView === 'chat'
        ? 'chat'
        : 'field';

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

  const handleOpenCanvas = useCallback(
    (content: string) => {
      if (!canvasEnabled) {
        addToast('Canvas is disabled in Settings.');
        return;
      }
      const titleLine = content.match(/^\s*#{1,6}\s+(.+)$/m)?.[1]?.trim();
      window.dispatchEvent(
        new CustomEvent('palimind:canvas-open', {
          detail: { title: titleLine?.slice(0, 60) || 'Canvas', content },
        }),
      );
      setArtifactPanelOpen(false);
      setCanvasOpen(true);
    },
    [canvasEnabled, addToast, setArtifactPanelOpen, setCanvasOpen],
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

  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    if (pinnedToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messagesKey]);

  return (
    <main className="chat-area" id="main-area">
      <div id="chat-interface" className={`chat-interface${isEmpty ? ' empty-chat' : ''}`}>
        {activeView !== 'chat' && activeView !== 'agents' && <IndexingProgress />}

        <div id="messages-scroll-area" className="messages" ref={messagesRef} onScroll={handleScroll}>
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
              onOpenCanvas={handleOpenCanvas}
              onToggleBookmark={() => toggleBookmark(msg)}
            />
          ))}
          <div id="streaming-messages-container" style={{ display: 'flex', flexDirection: 'column', gap: '20px', width: '100%' }}></div>
        </div>

        <div className="chat-empty-hero" aria-hidden={!isEmpty}>
          <h1>Palimind</h1>
        </div>

        <InputArea />
      </div>
    </main>
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
  onOpenCanvas: (content: string) => void;
  onToggleBookmark: () => void;
}

function MessageComponent({
  msg,
  index,
  bookmarked,
  onRegenerate,
  onSaveEdit,
  onDelete,
  onShare,
  onOpenCanvas,
  onToggleBookmark,
}: MessageComponentProps) {
  const isUser = msg.role === 'user';
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(msg.content);

  useEffect(() => {
    setDraft(msg.content);
  }, [msg.content]);

  let contentText = '';
  if (msg.sources && msg.sources.length > 0) {
    contentText += `*Sources: ${msg.sources.join(', ')}*\n\n`;
  }
  contentText += msg.content;

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
    <div className={`message ${isUser ? 'user-message' : 'system-message'}`}>
      <div className="message-wrapper">
        <MessageActions
          content={msg.content}
          isUser={isUser}
          bookmarked={bookmarked}
          onRegenerate={!isUser ? () => onRegenerate(index) : undefined}
          onEdit={isUser ? () => setEditing(true) : undefined}
          onOpenCanvas={!isUser ? () => onOpenCanvas(msg.content) : undefined}
          onDelete={() => onDelete(index)}
          onShare={onShare}
          onToggleBookmark={onToggleBookmark}
        />
        <div
          className="message-content"
          dangerouslySetInnerHTML={{ __html: formatMarkdown(contentText) }}
        />
      </div>
    </div>
  );
}
