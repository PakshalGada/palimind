import { useEffect, useMemo, useState } from 'react';
import { MessageCircle, SmilePlus } from 'lucide-react';
import MessageContent from '../../components/MessageContent';
import CollapsibleMessage from '../../components/CollapsibleMessage';
import ArtifactAnswerBlock from '../../components/ArtifactAnswerBlock';
import AgentAvatar from '../../components/AgentAvatar';
import MessageActions from '../../components/MessageActions';
import { parseArtifacts, shouldAutoOpenArtifact } from '../../utils/artifacts';
import { HistoryActivity } from '../../components/activity/shell/HistoryActivity';
import { useBookmarks } from '../../hooks/useBookmarks';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import type { AgentListItem, CitationPayload } from '../../types';
import './AgentMessage.css';

interface ThreadMessage {
  id?: number;
  role: string;
  content: string;
  /** "progress" for a short note sent with the agent's say tool. */
  kind?: string;
  timestamp?: number;
  citations?: CitationPayload;
  reply_to?: number;
  edited_at?: number;
  deleted_at?: number;
  reactions?: Reaction[];
  suggestions?: string[];
  mode_params?: { agent_name?: string; agent_id?: string; [key: string]: unknown };
}

interface Reaction {
  id?: string;
  emoji: string;
  actor_kind?: string;
  actor_id?: string;
}

const QUICK_REACTIONS = ['👍', '❤️', '🎉', '🤔', '👀', '🙏'];

function timeLabel(ts?: number): string {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function AgentMessage({
  message,
  index,
  sessionId,
  agents,
  fallbackAgent,
  showAuthor,
  grouped = false,
  onDeleted,
  onOpenArtifact,
  onReply,
  replyContent,
}: {
  message: ThreadMessage;
  index: number;
  sessionId: string | null;
  agents: AgentListItem[];
  fallbackAgent?: AgentListItem | null;
  showAuthor: boolean;
  /** True when the previous message is the same agent, within the same burst. */
  grouped?: boolean;
  onDeleted?: () => void;
  onOpenArtifact?: (artifactId: string) => void;
  onReply?: (message: ThreadMessage) => void;
  replyContent?: string;
}) {
  const { addToast, refreshSessions } = useApp();
  const { isBookmarked, toggle } = useBookmarks(sessionId);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  const [reactions, setReactions] = useState<Reaction[]>(message.reactions || []);
  const [reactOpen, setReactOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const author = useMemo(() => {
    const name = message.mode_params?.agent_name;
    const id = message.mode_params?.agent_id;
    if (id) return agents.find((agent) => agent.id === id) || fallbackAgent || null;
    if (name) return agents.find((agent) => agent.name === name) || fallbackAgent || null;
    return fallbackAgent || null;
  }, [agents, fallbackAgent, message.mode_params]);

  const isUser = message.role === 'user';
  const isProgress = !isUser && message.kind === 'progress';
  const timestamp = timeLabel(message.timestamp);
  const deleted = Boolean(message.deleted_at);
  const artifacts = useMemo(
    () =>
      isUser || deleted || isProgress
        ? []
        : parseArtifacts(message.content, index).filter((artifact) =>
            shouldAutoOpenArtifact(artifact),
          ),
    [isUser, deleted, isProgress, message.content, index],
  );

  useEffect(() => {
    setDraft(message.content);
  }, [message.content]);

  useEffect(() => {
    setReactions(message.reactions || []);
  }, [message.reactions]);

  useEffect(() => {
    if (!sessionId || !message.id) return;
    let cancelled = false;
    api.sessions
      .reactions(sessionId, message.id)
      .then((data) => {
        if (!cancelled) setReactions(data.reactions || []);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [sessionId, message.id]);

  const remove = async () => {
    if (!sessionId) return;
    try {
      if (message.id) {
        await api.sessions.deleteMessageById(sessionId, message.id, `agent:${fallbackAgent?.id || ''}`);
      } else {
        await api.sessions.deleteMessage(sessionId, index, `agent:${fallbackAgent?.id || ''}`);
      }
      await refreshSessions();
      onDeleted?.();
    } catch {
      addToast('Could not delete the message.', { tone: 'error' });
    }
  };

  const regenerate = async () => {
    if (!sessionId || !message.id) return;
    try {
      const data = await api.sessions.prepareRegenerate(
        sessionId,
        message.id,
        `agent:${fallbackAgent?.id || ''}`,
      );
      if (data.error || !data.input) {
        addToast(data.error || 'No prompt found to regenerate from.', { tone: 'error' });
        return;
      }
      await refreshSessions();
      window.dispatchEvent(
        new CustomEvent('palimind:regenerate-message', { detail: { content: data.input } }),
      );
    } catch {
      addToast('Could not regenerate the answer.', { tone: 'error' });
    }
  };

  const saveEdit = async () => {
    if (!sessionId || !message.id) return;
    const next = draft.trim();
    if (!next) {
      addToast('Message cannot be empty.', { tone: 'error' });
      return;
    }
    setBusy(true);
    try {
      // Remove the old message and everything after it, then replay the edited
      // text through the normal send path. This mirrors ChatArea: one user
      // message, one answer, no duplicate prompt.
      const data = await api.sessions.truncate(
        sessionId,
        index,
        `agent:${fallbackAgent?.id || ''}`,
      );
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      await refreshSessions();
      setEditing(false);
      window.dispatchEvent(
        new CustomEvent('palimind:regenerate-message', { detail: { content: next } }),
      );
    } catch {
      addToast('Could not edit the message.', { tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const toggleReaction = async (emoji: string) => {
    if (!sessionId || !message.id) return;
    setReactOpen(false);
    try {
      const data = await api.sessions.toggleReaction(sessionId, message.id, emoji);
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      setReactions(data.reactions || []);
    } catch {
      addToast('Could not update the reaction.', { tone: 'error' });
    }
  };

  const reply = () => {
    onReply?.(message);
    window.dispatchEvent(
      new CustomEvent('palimind:agent-reply', {
        detail: {
          messageId: message.id,
          author: isUser ? 'You' : author?.display_name || author?.name || 'Agent',
          content: message.content,
        },
      }),
    );
  };

  if (deleted) {
    return (
      <div className={`ag-msg ${isUser ? 'ag-msg--user' : 'ag-msg--agent'}`}>
        <div className="ag-msg__body">
          <div className="ag-msg__deleted">Message deleted</div>
        </div>
      </div>
    );
  }

  if (editing) {
    return (
      <div className={`ag-msg ${isUser ? 'ag-msg--user' : 'ag-msg--agent'}`}>
        <div className="ag-msg__body">
          <div className="ag-msg__edit">
            <textarea
              value={draft}
              autoFocus
              rows={3}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  setDraft(message.content);
                  setEditing(false);
                } else if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  void saveEdit();
                }
              }}
            />
            <div className="ag-msg__edit-actions">
              <button type="button" className="is-primary" disabled={busy} onClick={() => void saveEdit()}>
                Save &amp; resend
              </button>
              <button
                type="button"
                onClick={() => {
                  setDraft(message.content);
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

  const actions = (
    <div className="ag-msg__toolbar">
      <button type="button" onClick={reply} title="Reply" aria-label="Reply to message">
        <MessageCircle size={12} />
      </button>
      <div className="ag-msg__react">
        <button
          type="button"
          onClick={() => setReactOpen((value) => !value)}
          title="React"
          aria-label="React to message"
          aria-expanded={reactOpen}
        >
          <SmilePlus size={12} />
        </button>
        {reactOpen && (
          <div className="ag-msg__react-menu" role="menu">
            {QUICK_REACTIONS.map((emoji) => (
              <button
                key={emoji}
                type="button"
                role="menuitem"
                onClick={() => void toggleReaction(emoji)}
              >
                {emoji}
              </button>
            ))}
          </div>
        )}
      </div>
      <MessageActions
        content={message.content}
        isUser={isUser}
        bookmarked={isBookmarked(message)}
        onRegenerate={
          !isUser && !isProgress && message.id ? () => void regenerate() : undefined
        }
        onEdit={isUser && message.id ? () => setEditing(true) : undefined}
        onDelete={() => void remove()}
        onShare={() => {
          navigator.clipboard
            .writeText(message.content)
            .then(() => addToast('Message copied to clipboard'))
            .catch(() => addToast('Could not access the clipboard'));
        }}
        onToggleBookmark={() => toggle(message)}
      />
    </div>
  );

  const reactionRow =
    reactions.length > 0 ? (
      <div className="ag-msg__reactions" aria-label="Reactions">
        {reactions.map((reaction) => (
          <button
            key={`${reaction.emoji}:${reaction.actor_id || reaction.id || ''}`}
            type="button"
            className={`ag-msg__reaction${reaction.actor_id === 'user' ? ' is-mine' : ''}`}
            title={reaction.actor_id === 'user' ? 'Remove your reaction' : 'React'}
            onClick={() => void toggleReaction(reaction.emoji)}
          >
            {reaction.emoji}
          </button>
        ))}
      </div>
    ) : null;

  if (isUser) {
    return (
      <div className="ag-msg ag-msg--user">
        <div className="ag-msg__user-body">
          {replyContent ? <ReplyQuote content={replyContent} /> : null}
          <div className="ag-msg__user-bubble">
            <MessageContent content={message.content} onOpenArtifact={onOpenArtifact} />
          </div>
          <div className="ag-msg__user-meta">
            {timestamp}
            {message.edited_at ? <span>edited</span> : null}
          </div>
          {reactionRow}
          {actions}
        </div>
      </div>
    );
  }

  return (
    <div
      className={`ag-msg ag-msg--agent${grouped ? ' ag-msg--grouped' : ''}${
        isProgress ? ' ag-msg--note' : ''
      }`}
    >
      {grouped ? (
        <div className="ag-msg__avatar ag-msg__avatar--spacer" aria-hidden="true" />
      ) : (
        <div className="ag-msg__avatar">
          <AgentAvatar
            config={author?.avatar_config}
            type={author?.avatar_type === 'upload' ? 'upload' : 'bot'}
            upload={author?.avatar_upload}
            size={24}
          />
        </div>
      )}
      <div className="ag-msg__body">
        {showAuthor && !grouped && (
          <div className="ag-msg__meta">
            <span className="ag-msg__author">{author?.display_name || author?.name || 'Agent'}</span>
            {author?.name && <span className="ag-msg__handle">@{author.name}</span>}
            {timestamp && <span className="ag-msg__time">{timestamp}</span>}
            {message.edited_at ? <span className="ag-msg__time">edited</span> : null}
          </div>
        )}
        {replyContent ? <ReplyQuote content={replyContent} /> : null}
        {!isProgress && (
          <div className="ag-msg__activity">
            <HistoryActivity
              sessionId={sessionId}
              messageIndex={index}
              mode="agent"
              citations={message.citations}
            />
          </div>
        )}
        {artifacts.length > 0 ? (
          <ArtifactAnswerBlock
            artifacts={artifacts}
            onOpen={(artifactId) => onOpenArtifact?.(artifactId)}
          />
        ) : (
          <CollapsibleMessage
            content={message.content}
            citations={message.citations}
            messageIndex={index}
            onOpenArtifact={onOpenArtifact}
            className="ag-msg__prose"
            fold={!isProgress}
          />
        )}
        {!isUser && !isProgress && !message.deleted_at && (
          <QuickActions
            onAction={(text) =>
              window.dispatchEvent(
                new CustomEvent('palimind:agent-prefill', { detail: { text } }),
              )
            }
          />
        )}
        {reactionRow}
        {actions}
      </div>
    </div>
  );
}

function QuickActions({ onAction }: { onAction: (text: string) => void }) {
  const actions = [
    { label: 'Tell me more', text: 'Tell me more about that.' },
    { label: 'Make it shorter', text: 'Make that shorter and more conversational.' },
    { label: 'Show sources', text: 'Show the sources for that answer.' },
    { label: 'Turn into a task', text: 'Turn that into a task and run it.' },
    { label: 'Remember this', text: 'Remember this for later: ' },
  ];
  return (
    <div className="ag-msg__quick" aria-label="Suggested actions">
      {actions.map((action) => (
        <button key={action.label} type="button" onClick={() => onAction(action.text)}>
          {action.label}
        </button>
      ))}
    </div>
  );
}

function ReplyQuote({ content }: { content: string }) {
  return (
    <div className="ag-msg__reply-quote">
      <span>Replying to</span>
      <p>{content.replace(/\s+/g, ' ').slice(0, 160)}</p>
    </div>
  );
}
