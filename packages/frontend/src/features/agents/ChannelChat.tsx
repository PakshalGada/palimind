import { useCallback, useEffect, useRef, useState } from 'react';
import { Hash } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import MessageContent from '../../components/MessageContent';
import ConversationHeader from './ConversationHeader';
import AgentComposer from './AgentComposer';
import type { AgentListItem, Channel, ChannelMessage } from '../../types';
import './ChannelChat.css';

export default function ChannelChat({
  channelId,
  agents,
}: {
  channelId: string;
  agents: AgentListItem[];
}) {
  const { addToast } = useApp();
  const [channel, setChannel] = useState<Channel | null>(null);
  const [messages, setMessages] = useState<ChannelMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [detail, list] = await Promise.all([
        api.channels.get(channelId),
        api.channels.messages(channelId, 200),
      ]);
      setChannel((detail.channel || null) as unknown as Channel | null);
      setMessages((list.messages || []) as unknown as ChannelMessage[]);
    } catch {
      // best effort
    }
  }, [channelId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 6000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const el = threadRef.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  const send = async (text: string) => {
    setBusy(true);
    try {
      const result = await api.channels.send(channelId, text);
      if (result.error) throw new Error(result.error);
      await refresh();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Could not send to the channel', { tone: 'error' });
      throw e;
    } finally {
      setBusy(false);
    }
  };

  const agentFor = (message: ChannelMessage) => {
    if (message.author_kind !== 'agent') return undefined;
    return agents.find((agent) => agent.id === message.author_id || agent.name === message.author_id);
  };

  const onScroll = () => {
    const el = threadRef.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  return (
    <div className="ag-chat">
      <ConversationHeader channel={channel} />
      <div className="ag-thread" ref={threadRef} onScroll={onScroll}>
        {messages.length === 0 ? (
          <div className="ag-chat-empty">
            <Hash size={34} />
            <h2>#{channel?.name || 'channel'}</h2>
            <p>{channel?.purpose || 'A shared room for you and a few agents.'}</p>
          </div>
        ) : (
          messages.map((message) => {
            const isUser = message.author_kind === 'user';
            const author = agentFor(message);
            if (isUser) {
              return (
                <div key={message.id} className="ag-msg ag-msg--user">
                  <div className="ag-msg__user-body">
                    <div className="ag-msg__user-bubble">
                      <MessageContent content={message.text} />
                    </div>
                  </div>
                </div>
              );
            }
            return (
              <div key={message.id} className="ag-msg ag-msg--agent">
                <div className="ag-msg__avatar">
                  <AgentAvatar
                    config={author?.avatar_config}
                    type={author?.avatar_type === 'upload' ? 'upload' : 'bot'}
                    upload={author?.avatar_upload}
                    size={24}
                  />
                </div>
                <div className="ag-msg__body">
                  <div className="ag-msg__meta">
                    <span className="ag-msg__author">
                      {author?.display_name || author?.name || message.author_id}
                    </span>
                    <span className="ag-msg__handle">#{message.seq}</span>
                  </div>
                  <div className="ag-msg__prose">
                    <MessageContent content={message.text} />
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
      <AgentComposer
        agents={agents}
        channelId={channelId}
        channelName={channel?.name}
        onLocalSend={send}
        disabled={busy}
      />
    </div>
  );
}
