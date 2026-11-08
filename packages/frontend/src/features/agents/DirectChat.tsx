import { useEffect, useRef, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import StreamingTurn from '../../stream/StreamingTurn';
import { useChatStreamContext } from '../../stream/context';
import { streamBelongsTo } from '../../stream/reducer';
import AgentMessage from './AgentMessage';
import InputArea from '../../components/InputArea';
import ConversationHeader from './ConversationHeader';
import type { AgentListItem, BrowserTakeover } from '../../types';
import './DirectChat.css';

export default function DirectChat({
  agent,
  agents,
  takeover,
  onTakeover,
}: {
  agent: AgentListItem;
  agents: AgentListItem[];
  takeover?: BrowserTakeover | null;
  onTakeover?: () => void;
}) {
  const {
    sessions,
    activeSessionId,
    selectedAgentId,
    openArtifact,
  } = useApp();
  const { state, activityStore } = useChatStreamContext();
  const threadRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const [starters, setStarters] = useState<string[]>([]);
  const [note, setNote] = useState('');
  const [noteSent, setNoteSent] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setStarters([]);
    api.agents
      .starters(agent.id)
      .then((data) => {
        if (!cancelled && Array.isArray(data.prompts) && data.prompts.length > 0) {
          setStarters(data.prompts);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [agent.id]);

  const prompts =
    starters.length > 0
      ? starters
      : [
          'What are you working on?',
          'Give me a quick status update.',
          'Help me plan the next step.',
        ];

  const currentSess = sessions.find((session) => session.id === activeSessionId);
  const messages = currentSess?.messages ?? [];
  const streamingHere = streamBelongsTo(state, activeSessionId);
  const isEmpty = !streamingHere && messages.length === 0;

  const lastMessage = messages[messages.length - 1];
  const messageKey =
    messages.length === 0 ? 'empty' : `${messages.length}-${lastMessage?.content?.length || 0}`;

  useEffect(() => {
    pinned.current = true;
  }, [activeSessionId, state.startedAt]);

  useEffect(() => {
    const el = threadRef.current;
    if (!el || !pinned.current) return;
    el.scrollTop = el.scrollHeight;
  }, [messageKey, state.revision, activeSessionId]);

  const onScroll = () => {
    const el = threadRef.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const prefill = (text: string) => {
    window.dispatchEvent(new CustomEvent('palimind:agent-prefill', { detail: { text } }));
  };

  const sendNote = async () => {
    const text = note.trim();
    if (!text) return;
    try {
      await api.agents.steer(agent.id, text, activityStore.getState()?.runId || '');
      setNote('');
      setNoteSent(true);
      window.setTimeout(() => setNoteSent(false), 2000);
    } catch {
      // the next reconcile will show the run state
    }
  };

  return (
    <div className="ag-chat">
      <ConversationHeader agent={agent} />
      {takeover && (
        <div className="ag-takeover-banner" role="status">
          <span className="ag-takeover-banner__dot" />
          <div className="ag-takeover-banner__text">
            <strong>{agent.display_name || agent.name} needs you in the browser</strong>
            <span>{takeover.reason || 'Complete the step, then hand control back.'}</span>
          </div>
          <button type="button" onClick={onTakeover}>
            Take over
          </button>
        </div>
      )}
      <div className="ag-thread" ref={threadRef} onScroll={onScroll}>
        {isEmpty ? (
          <div className="ag-chat-empty">
            <AgentAvatar
              config={agent.avatar_config}
              type={agent.avatar_type === 'upload' ? 'upload' : 'bot'}
              upload={agent.avatar_upload}
              size={44}
            />
            <h2>{agent.display_name || agent.name}</h2>
            <p>
              {agent.description || agent.title || 'Ready when you are.'}
            </p>
            <div className="ag-chat-empty__prompts">
              {prompts.map((prompt) => (
                <button key={prompt} type="button" onClick={() => prefill(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
            <span className="ag-chat-empty__hint">
              <AtHint /> Use @ to call another agent in this chat.
            </span>
          </div>
        ) : (
          <>
            {messages.map((message, index) => {
              const previous = messages[index - 1];
              const authorName =
                message.mode_params?.agent_name || message.mode_params?.agent_id || '';
              const previousName =
                previous?.mode_params?.agent_name || previous?.mode_params?.agent_id || '';
              const showAuthor =
                message.role !== 'user' &&
                (index === 0 ||
                  previous?.role === 'user' ||
                  authorName !== previousName);
              return (
                <AgentMessage
                  key={`${index}-${message.role}`}
                  message={message}
                  index={index}
                  sessionId={activeSessionId}
                  agents={agents}
                  fallbackAgent={agent}
                  showAuthor={showAuthor}
                  onOpenArtifact={openArtifact}
                />
              );
            })}
            <StreamingTurn activeSessionId={activeSessionId} />
          </>
        )}
      </div>
      {streamingHere && (
        <div className="ag-steer">
          <input
            value={note}
            placeholder="Send a note to this run…"
            aria-label="Send a note to this run"
            onChange={(event) => {
              setNote(event.target.value);
              if (noteSent) setNoteSent(false);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && note.trim()) {
                void sendNote();
              }
            }}
          />
          <button
            type="button"
            disabled={!note.trim()}
            onClick={() => void sendNote()}
          >
            {noteSent ? 'Sent' : 'Steer'}
          </button>
        </div>
      )}
      <InputArea
        disabled={!selectedAgentId}
        placeholder={`Message ${agent.display_name || agent.name}...`}
      />
    </div>
  );
}

function AtHint() {
  return (
    <span className="ag-at-hint" aria-hidden="true">
      <Sparkles size={11} />
    </span>
  );
}
