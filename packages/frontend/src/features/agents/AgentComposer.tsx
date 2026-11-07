import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AtSign, ArrowUp, Square } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import { useChatStreamActions } from '../../stream/context';
import { firstAgentMention, findMentionToken, applyMention } from '../../utils/mentions';
import ModelPicker from './ModelPicker';
import type { AgentListItem } from '../../types';
import './AgentComposer.css';

/**
 * The agent chat composer. It keeps the useful bits of the global composer
 * (mentions, model choice, stop) while dropping the multi-mode chrome: an
 * agent chat is a conversation, not a control panel.
 */
export default function AgentComposer({
  agent,
  agents,
  teamId,
  channelId,
  channelName,
  onLocalSend,
  disabled,
}: {
  agent?: AgentListItem | null;
  agents: AgentListItem[];
  teamId?: string;
  channelId?: string;
  channelName?: string;
  onLocalSend?: (text: string) => Promise<void> | void;
  disabled?: boolean;
}) {
  const {
    activeSessionId,
    isGenerating,
    addToast,
  } = useApp();
  const { send, stop } = useChatStreamActions();
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [mention, setMention] = useState<ReturnType<typeof findMentionToken>>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sendingRef = useRef(false);

  const mentionMatches = useMemo(() => {
    if (!mention) return [];
    const q = mention.query.toLowerCase();
    return agents
      .filter(
        (item) =>
          item.name.toLowerCase().includes(q) ||
          (item.display_name || '').toLowerCase().includes(q),
      )
      .slice(0, 6);
  }, [agents, mention]);

  const refreshMention = useCallback((text: string, cursor: number) => {
    const token = findMentionToken(text, cursor);
    setMention(token);
    setMentionIndex(0);
  }, []);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [value]);

  useEffect(() => {
    const onPrefill = (event: Event) => {
      const text = (event as CustomEvent<{ text?: string }>).detail?.text;
      if (!text) return;
      setValue(text);
      requestAnimationFrame(() => textareaRef.current?.focus());
    };
    window.addEventListener('palimind:agent-prefill', onPrefill);
    return () => window.removeEventListener('palimind:agent-prefill', onPrefill);
  }, []);

  useEffect(() => {
    const onSend = (event: Event) => {
      const text = (event as CustomEvent<{ text?: string }>).detail?.text;
      if (!text) return;
      void sendMessage(text);
    };
    window.addEventListener('palimind:agent-send', onSend);
    return () => window.removeEventListener('palimind:agent-send', onSend);
  });

  const chooseMention = (item: AgentListItem) => {
    if (!mention) return;
    const result = applyMention(value, mention, item.name);
    setValue(result.text);
    setMention(null);
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(result.cursor, result.cursor);
    });
  };

  const mentionedAgent = useMemo(() => {
    const name = firstAgentMention(value);
    return name ? agents.find((item) => item.name === name) : undefined;
  }, [agents, value]);

  const target = mentionedAgent || agent || null;
  const group = Boolean(teamId || channelId);

  const sendMessage = async (override?: string) => {
    const text = (override ?? value).trim();
    if (!text || busy || disabled) return;
    if (sendingRef.current) return;
    if (group) {
      if (!onLocalSend) return;
      sendingRef.current = true;
      setBusy(true);
      try {
        setValue('');
        setMention(null);
        await onLocalSend(text);
      } catch (e) {
        addToast(e instanceof Error ? e.message : 'Could not send message', { tone: 'error' });
      } finally {
        setBusy(false);
        sendingRef.current = false;
      }
      return;
    }
    if (!agent) return;
    sendingRef.current = true;
    setBusy(true);
    try {
      setValue('');
      setMention(null);
      send({
        text,
        userText: text,
        mode: 'llm',
        scope: `agent:${agent.id}`,
        sessionId: activeSessionId,
        activity: {
          mode: 'agent',
          title: target?.display_name || target?.name || agent.display_name || agent.name,
          subtitle: 'agent',
          seed: target?.id,
          agentAvatar: target
            ? {
                config: target.avatar_config,
                type: target.avatar_type,
                upload: target.avatar_upload,
              }
            : undefined,
        },
        agentLoading: target ? { seed: target.id, name: target.name } : null,
      });
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not send message', { tone: 'error' });
    } finally {
      setBusy(false);
      sendingRef.current = false;
    }
  };

  const setModel = async (model: string) => {
    if (!agent) return;
    const res = await api.config.setModel(model, `agent:${agent.id}`);
    if (res.error) {
      addToast(res.error, { tone: 'error' });
      return;
    }
    window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!group && isGenerating && event.key === 'Escape') {
      event.preventDefault();
      stop();
      return;
    }
    if (mention && mentionMatches.length > 0) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setMentionIndex((index) => (index + 1) % mentionMatches.length);
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setMentionIndex((index) => (index - 1 + mentionMatches.length) % mentionMatches.length);
        return;
      }
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        chooseMention(mentionMatches[mentionIndex]);
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        setMention(null);
        return;
      }
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  };

  const generating = !group && isGenerating;
  const placeholder = group
    ? channelId
      ? `Message #${channelName || 'channel'}…`
      : 'Message the team…'
    : agent
      ? `Message ${agent.display_name || agent.name}…`
      : 'Select an agent to start…';

  return (
    <div className={`ag-composer${generating ? ' is-generating' : ''}`}>
      <div className="ag-composer__box">
        {mention && (
          <div className="ag-composer__mentions" role="listbox" aria-label="Call an agent">
            <div className="ag-composer__mentions-head">Call an agent</div>
            {mentionMatches.length === 0 ? (
              <div className="ag-composer__mentions-empty">No matching agents</div>
            ) : (
              mentionMatches.map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  role="option"
                  aria-selected={index === mentionIndex}
                  className={`ag-composer__mention${index === mentionIndex ? ' is-on' : ''}`}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    chooseMention(item);
                  }}
                >
                  <AgentAvatar
                    config={item.avatar_config}
                    type={item.avatar_type === 'upload' ? 'upload' : 'bot'}
                    upload={item.avatar_upload}
                    size={20}
                  />
                  <span>
                    {item.display_name || item.name}
                    <em>@{item.name}</em>
                  </span>
                </button>
              ))
            )}
          </div>
        )}

        {target && mentionedAgent && (
          <div className="ag-composer__target">
            <AtSign size={11} />
            This turn goes to {mentionedAgent.display_name || mentionedAgent.name}
          </div>
        )}

        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          placeholder={placeholder}
          onChange={(event) => {
            setValue(event.target.value);
            refreshMention(event.target.value, event.target.selectionStart ?? event.target.value.length);
          }}
          onKeyDown={onKeyDown}
          onBlur={() => window.setTimeout(() => setMention(null), 120)}
          aria-label={placeholder}
        />

        <div className="ag-composer__bar">
          <button
            type="button"
            className="ag-composer__at"
            title="Call an agent"
            aria-label="Call an agent"
            onClick={() => {
              const insert = value.endsWith(' ') || value.length === 0 ? '@' : ' @';
              const next = value + insert;
              setValue(next);
              setMention(findMentionToken(next, next.length));
              requestAnimationFrame(() => textareaRef.current?.focus());
            }}
          >
            <AtSign size={14} />
          </button>

          {!group && agent && (
            <ModelPicker
              value={agent.model || ''}
              onChange={(model) => void setModel(model)}
              placeholder="Default model"
            />
          )}

          <span className="ag-composer__hint">
            {generating ? 'Esc to stop' : 'Enter to send · Shift+Enter for a new line'}
          </span>

          {generating ? (
            <button
              type="button"
              className="ag-composer__send is-stop"
              onClick={stop}
              aria-label="Stop"
              title="Stop"
            >
              <Square size={12} />
            </button>
          ) : (
            <button
              type="button"
              className="ag-composer__send"
              disabled={!value.trim() || busy || disabled}
              onClick={() => void sendMessage()}
              aria-label="Send"
              title="Send"
            >
              <ArrowUp size={15} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
