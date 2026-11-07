import { useMemo, useState } from 'react';
import { Check, Copy, Trash2 } from 'lucide-react';
import MessageContent from '../../components/MessageContent';
import AgentAvatar from '../../components/AgentAvatar';
import { HistoryActivity } from '../../components/activity/shell/HistoryActivity';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { useConfirm } from '../../components/ConfirmDialog';
import type { AgentListItem, CitationPayload } from '../../types';
import './AgentMessage.css';

interface ThreadMessage {
  role: string;
  content: string;
  timestamp?: number;
  citations?: CitationPayload;
  mode_params?: { agent_name?: string; agent_id?: string; [key: string]: unknown };
}

function longAnswer(content: string): boolean {
  if (content.length > 900) return true;
  return content.split('\n').length > 12;
}

export default function AgentMessage({
  message,
  index,
  sessionId,
  agents,
  fallbackAgent,
  showAuthor,
  onDeleted,
  onOpenArtifact,
}: {
  message: ThreadMessage;
  index: number;
  sessionId: string | null;
  agents: AgentListItem[];
  fallbackAgent?: AgentListItem | null;
  showAuthor: boolean;
  onDeleted?: () => void;
  onOpenArtifact?: (artifactId: string) => void;
}) {
  const { addToast, refreshSessions } = useApp();
  const confirm = useConfirm();
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const author = useMemo(() => {
    const name = message.mode_params?.agent_name;
    const id = message.mode_params?.agent_id;
    if (id) return agents.find((agent) => agent.id === id) || fallbackAgent || null;
    if (name) return agents.find((agent) => agent.name === name) || fallbackAgent || null;
    return fallbackAgent || null;
  }, [agents, fallbackAgent, message.mode_params]);

  const isUser = message.role === 'user';
  const timestamp = message.timestamp
    ? new Date(message.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  const copy = () => {
    navigator.clipboard
      .writeText(message.content)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1400);
      })
      .catch(() => addToast('Could not copy the message.', { tone: 'error' }));
  };

  const remove = async () => {
    if (!sessionId) return;
    const ok = await confirm('Delete this message? This cannot be undone.', {
      title: 'Delete message',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.sessions.deleteMessage(sessionId, index, `agent:${fallbackAgent?.id || ''}`);
      await refreshSessions();
      onDeleted?.();
    } catch {
      addToast('Could not delete the message.', { tone: 'error' });
    }
  };

  if (isUser) {
    return (
      <div className="ag-msg ag-msg--user">
        <div className="ag-msg__user-body">
          <div className="ag-msg__user-bubble">
            <MessageContent content={message.content} onOpenArtifact={onOpenArtifact} />
          </div>
          <div className="ag-msg__user-meta">
            {timestamp}
            <button type="button" onClick={copy} title="Copy" aria-label="Copy message">
              {copied ? <Check size={11} /> : <Copy size={11} />}
            </button>
            <button type="button" onClick={() => void remove()} title="Delete" aria-label="Delete message">
              <Trash2 size={11} />
            </button>
          </div>
        </div>
      </div>
    );
  }

  const collapsible = longAnswer(message.content) && !expanded;

  return (
    <div className="ag-msg ag-msg--agent">
      <div className="ag-msg__avatar">
        <AgentAvatar
          config={author?.avatar_config}
          type={author?.avatar_type === 'upload' ? 'upload' : 'bot'}
          upload={author?.avatar_upload}
          size={24}
        />
      </div>
      <div className="ag-msg__body">
        {showAuthor && (
          <div className="ag-msg__meta">
            <span className="ag-msg__author">{author?.display_name || author?.name || 'Agent'}</span>
            {author?.name && <span className="ag-msg__handle">@{author.name}</span>}
            {timestamp && <span className="ag-msg__time">{timestamp}</span>}
          </div>
        )}
        <div className="ag-msg__activity">
          <HistoryActivity
            sessionId={sessionId}
            messageIndex={index}
            mode="agent"
            citations={message.citations}
          />
        </div>
        <div className={`ag-msg__prose${collapsible ? ' is-collapsed' : ''}`}>
          <MessageContent
            content={message.content}
            citations={message.citations}
            messageIndex={index}
            onOpenArtifact={onOpenArtifact}
          />
        </div>
        {collapsible && (
          <button type="button" className="ag-msg__more" onClick={() => setExpanded(true)}>
            Show full answer
          </button>
        )}
        <div className="ag-msg__actions">
          <button type="button" onClick={copy} title="Copy" aria-label="Copy message">
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
          <button type="button" onClick={() => void remove()} title="Delete" aria-label="Delete message">
            <Trash2 size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}
