import { useEffect, useMemo, useRef, useState } from 'react';
import { Sparkles, KeyRound, AlertTriangle, X, ChevronUp, ChevronDown } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import StreamingTurn from '../../stream/StreamingTurn';
import { useChatStreamContext } from '../../stream/context';
import { streamBelongsTo } from '../../stream/reducer';
import AgentMessage from './AgentMessage';
import AgentPresence from './AgentPresence';
import InputArea from '../../components/InputArea';
import ConversationHeader from './ConversationHeader';
import type { AgentListItem, BrowserTakeover } from '../../types';
import './DirectChat.css';

interface ThreadMessage {
  id?: number;
  role: string;
  content: string;
  timestamp?: number;
  reply_to?: number;
  suggestions?: string[];
  citations?: import('../../types').CitationPayload;
  mode_params?: { agent_name?: string; agent_id?: string; [key: string]: unknown };
}

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
  const { sessions, activeSessionId, selectedAgentId, openArtifact } = useApp();
  const { state, activityStore } = useChatStreamContext();
  const threadRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const [starters, setStarters] = useState<string[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchIndex, setSearchIndex] = useState(0);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const rowRefs = useRef(new Map<number, HTMLDivElement>());

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

  useEffect(() => {
    const key = `palimind:agent-first-task:${agent.id}`;
    let text = '';
    try {
      text = localStorage.getItem(key) || '';
      if (text) localStorage.removeItem(key);
    } catch {
      // storage is optional
    }
    if (!text) return;
    const timer = window.setTimeout(() => {
      window.dispatchEvent(new CustomEvent('palimind:agent-prefill', { detail: { text } }));
    }, 80);
    return () => window.clearTimeout(timer);
  }, [agent.id]);

  const prompts =
    starters.length > 0
      ? starters
      : ['Say hi and tell me what you can do.', 'Give me a quick status update.', 'Help me plan the next step.'];

  const currentSess = sessions.find((session) => session.id === activeSessionId);
  const messages = useMemo(
    () => ((currentSess?.messages ?? []) as ThreadMessage[]),
    [currentSess?.messages],
  );
  const streamingHere = streamBelongsTo(state, activeSessionId);
  const isEmpty = !streamingHere && messages.length === 0;

  const lastMessage = messages[messages.length - 1];
  const messageKey =
    messages.length === 0 ? 'empty' : `${messages.length}-${lastMessage?.content?.length || 0}`;

  const byId = useMemo(() => {
    const map = new Map<number, ThreadMessage>();
    for (const message of messages) {
      if (typeof message.id === 'number') map.set(message.id, message);
    }
    return map;
  }, [messages]);

  const matches = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return [] as number[];
    return messages
      .map((message, index) => ({ message, index }))
      .filter(({ message }) => message.content.toLowerCase().includes(q))
      .map(({ index }) => index);
  }, [messages, searchQuery]);

  const jumpToMatch = (nextIndex: number) => {
    if (matches.length === 0) return;
    const normalized = ((nextIndex % matches.length) + matches.length) % matches.length;
    setSearchIndex(normalized);
    const row = rowRefs.current.get(matches[normalized]);
    row?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  };

  useEffect(() => {
    if (!searchOpen) return;
    searchInputRef.current?.focus();
  }, [searchOpen]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f') {
        event.preventDefault();
        setSearchOpen(true);
      } else if (event.key === 'Escape' && searchOpen) {
        setSearchOpen(false);
        setSearchQuery('');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [searchOpen]);

  useEffect(() => {
    pinned.current = true;
  }, [activeSessionId, state.startedAt]);

  useEffect(() => {
    const el = threadRef.current;
    if (!el || !pinned.current) return;
    el.scrollTop = el.scrollHeight;
  }, [messageKey, state.revision, activeSessionId, streamingHere]);

  useEffect(() => {
    if (!activeSessionId || streamingHere) return;
    const last = messages[messages.length - 1];
    if (!last || typeof last.id !== 'number') return;
    api.sessions
      .markRead(activeSessionId, last.id, `agent:${agent.id}`)
      .then(() => window.dispatchEvent(new CustomEvent('palimind:agents-changed')))
      .catch(() => undefined);
  }, [activeSessionId, agent.id, messages, streamingHere]);

  const onScroll = () => {
    const el = threadRef.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const prefill = (text: string) => {
    window.dispatchEvent(new CustomEvent('palimind:agent-prefill', { detail: { text } }));
  };

  const suggestions = !streamingHere ? lastMessage?.suggestions ?? [] : [];

  return (
    <div className="ag-chat">
      <ConversationHeader agent={agent} onSearch={() => setSearchOpen(true)} />
      {searchOpen && (
        <div className="ag-search" role="search">
          <input
            ref={searchInputRef}
            value={searchQuery}
            placeholder="Find in this conversation…"
            aria-label="Find in this conversation"
            onChange={(event) => {
              setSearchQuery(event.target.value);
              setSearchIndex(0);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                jumpToMatch(event.shiftKey ? searchIndex - 1 : searchIndex + 1);
              }
            }}
          />
          <span className="ag-search__count">
            {searchQuery.trim()
              ? matches.length
                ? `${searchIndex + 1}/${matches.length}`
                : 'No matches'
              : ''}
          </span>
          <button
            type="button"
            aria-label="Previous match"
            disabled={matches.length === 0}
            onClick={() => jumpToMatch(searchIndex - 1)}
          >
            <ChevronUp size={13} />
          </button>
          <button
            type="button"
            aria-label="Next match"
            disabled={matches.length === 0}
            onClick={() => jumpToMatch(searchIndex + 1)}
          >
            <ChevronDown size={13} />
          </button>
          <button
            type="button"
            aria-label="Close search"
            onClick={() => {
              setSearchOpen(false);
              setSearchQuery('');
            }}
          >
            <X size={13} />
          </button>
        </div>
      )}
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
            <p>{agent.description || agent.title || 'Ready when you are.'}</p>
            <div className="ag-chat-empty__prompts">
              {prompts.map((prompt) => (
                <button key={prompt} type="button" onClick={() => prefill(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
            <div className="ag-chat-empty__sample" aria-hidden="true">
              <div className="ag-chat-empty__sample-prompt">“Draft a brief on what changed this week.”</div>
              <div className="ag-chat-empty__sample-step">Searching the web</div>
              <div className="ag-chat-empty__sample-step">Reading 3 sources</div>
              <div className="ag-chat-empty__sample-step">Writing the brief</div>
            </div>
            <span className="ag-chat-empty__hint">
              <Sparkles size={11} /> Use @ to call another agent in this chat.
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
              const replied = message.reply_to ? byId.get(message.reply_to) : undefined;
              const isMatch = matches.includes(index);
              return (
                <div
                  key={`${message.id ?? index}-${message.role}`}
                  ref={(node) => {
                    if (node) rowRefs.current.set(index, node);
                    else rowRefs.current.delete(index);
                  }}
                  className={isMatch ? 'ag-search-hit' : undefined}
                >
                  <AgentMessage
                    message={message}
                    index={index}
                    sessionId={activeSessionId}
                    agents={agents}
                    fallbackAgent={agent}
                    showAuthor={showAuthor}
                    replyContent={replied?.content}
                    onOpenArtifact={openArtifact}
                  />
                </div>
              );
            })}
            <StreamingTurn activeSessionId={activeSessionId} />
          </>
        )}
      </div>
      {suggestions.length > 0 && (
        <div className="ag-suggestions" aria-label="Suggested next steps">
          {suggestions.map((suggestion) => (
            <button key={suggestion} type="button" onClick={() => prefill(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
      )}
      {state.modelNotice && (
        <div className="ag-model-notice" role="alert">
          <AlertTriangle size={14} />
          <span>{state.modelNotice.message}</span>
          {state.modelNotice.action === 'add-key' && (
            <button
              type="button"
              onClick={() =>
                window.dispatchEvent(
                  new CustomEvent('palimind:open-settings', { detail: { section: 'opencode' } }),
                )
              }
            >
              <KeyRound size={12} /> Add OpenCode key
            </button>
          )}
          {state.modelNotice.action === 'choose-model' && (
            <button
              type="button"
              onClick={() =>
                window.dispatchEvent(new CustomEvent('palimind:open-agent-config', {
                  detail: { agentId: agent.id, tab: 'instructions' },
                }))
              }
            >
              Choose a model
            </button>
          )}
        </div>
      )}
      <AgentPresence
        agent={agent}
        streaming={streamingHere}
        store={activityStore}
        startedAt={state.startedAt}
        activityLabel={state.activityLabel}
      />
      <InputArea
        disabled={!selectedAgentId}
        placeholder={`Message ${agent.display_name || agent.name}...`}
      />
    </div>
  );
}
