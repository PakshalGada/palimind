import { useCallback, useEffect, useRef, useState } from 'react';
import { Square, Users } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import MessageContent from '../../components/MessageContent';
import ConversationHeader from './ConversationHeader';
import InputArea from '../../components/InputArea';
import type { AgentListItem, Team, TeamMessage } from '../../types';
import './TeamChat.css';

interface LiveMember {
  name: string;
  status: string;
  task?: string;
}

function relTime(ts?: number): string {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function authorName(author: string): string {
  if (!author) return 'Team';
  return author.replace(/^agent:/, '').split(':')[0];
}

export default function TeamChat({
  teamId,
  agents,
  onOpenSettings,
}: {
  teamId: string;
  agents: AgentListItem[];
  onOpenSettings?: () => void;
}) {
  const { addToast, refreshOverview } = useApp();
  const [team, setTeam] = useState<Team | null>(null);
  const [messages, setMessages] = useState<TeamMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [liveMembers, setLiveMembers] = useState<Record<string, LiveMember>>({});
  const threadRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [detail, msgs] = await Promise.all([api.teams.get(teamId), api.teams.messages(teamId, 200)]);
      if (detail.team) setTeam(detail.team);
      setMessages(msgs.messages || []);
    } catch {
      // best effort
    }
  }, [teamId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 8000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const el = threadRef.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [messages.length, liveMembers]);

  const send = async (text: string) => {
    if (busy) return;
    setBusy(true);
    setLiveMembers({});
    try {
      await api.teams.runStream(teamId, text, (event) => {
        if (event.type === 'team:message' && event.message) {
          const message = event.message as TeamMessage;
          setMessages((previous) =>
            previous.some((item) => item.id === message.id) ? previous : [...previous, message],
          );
        } else if (event.type === 'team:member_started') {
          const id = String(event.agent_id);
          setLiveMembers((previous) => ({
            ...previous,
            [id]: {
              name: String(event.name || 'Member'),
              status: 'working',
              task: String(event.task || ''),
            },
          }));
        } else if (event.type === 'team:member_result') {
          const id = String(event.agent_id);
          setLiveMembers((previous) => ({
            ...previous,
            [id]: { ...(previous[id] || { name: String(event.name || 'Member') }), status: String(event.status || 'ok') },
          }));
        } else if (event.type === 'team:member_step' || event.type === 'agent:thought') {
          const id = String(event.agent_id || '');
          if (!id) return;
          setLiveMembers((previous) => ({
            ...previous,
            [id]: {
              ...(previous[id] || { name: String(event.name || 'Member') }),
              status: 'working',
              task: String(event.text || '').slice(0, 160),
            },
          }));
        }
      });
      await refresh();
      void refreshOverview();
    } catch (e) {
      addToast(e instanceof Error ? e.message : 'Team run failed', { tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    await api.teams.cancel(teamId);
    setBusy(false);
    addToast('Stopped the team', { tone: 'info' });
  };

  const onScroll = () => {
    const el = threadRef.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const findingMember = (author: string) => {
    const raw = author.replace(/^agent:/, '');
    return agents.find((agent) => agent.id === raw || agent.name === raw);
  };

  return (
    <div className="ag-chat">
      <ConversationHeader team={team} onSettings={onOpenSettings} />
      <div className="ag-thread" ref={threadRef} onScroll={onScroll}>
        {messages.length === 0 && !busy ? (
          <div className="ag-chat-empty">
            <Users size={34} />
            <h2>{team?.display_name || team?.name || 'Team'}</h2>
            <p>{team?.description || 'Give the team a task. The manager will delegate it.'}</p>
          </div>
        ) : (
          messages.map((message) => {
            const isUser = message.role === 'user';
            const author = findingMember(message.author);
            if (isUser) {
              return (
                <div key={message.id} className="ag-msg ag-msg--user">
                  <div className="ag-msg__user-body">
                    <div className="ag-msg__user-bubble">
                      <MessageContent content={message.content} />
                    </div>
                    <div className="ag-msg__user-meta">{relTime(message.created_at)}</div>
                  </div>
                </div>
              );
            }
            if (message.role === 'handoff' || message.role === 'approval') {
              return (
                <div key={message.id} className="ag-msg ag-msg--system">
                  <span>{message.content}</span>
                  <time>{relTime(message.created_at)}</time>
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
                      {author?.display_name || authorName(message.author) || 'Team'}
                    </span>
                    <span className="ag-msg__handle">{message.role}</span>
                    <span className="ag-msg__time">{relTime(message.created_at)}</span>
                  </div>
                  <div className="ag-msg__prose">
                    <MessageContent content={message.content} />
                  </div>
                </div>
              </div>
            );
          })
        )}
        {Object.entries(liveMembers).map(([id, member]) => (
          <div key={`live-${id}`} className="ag-team-live">
            <span className="ag-team-live__pulse" />
            <span>
              {member.name} {member.status === 'working' ? 'is working' : member.status}
              {member.task ? ` · ${member.task}` : ''}
            </span>
          </div>
        ))}
        {busy && <div className="ag-team-live"><span className="ag-team-live__pulse" />The team is working…</div>}
      </div>
      {busy && (
        <div className="ag-team-stop">
          <button type="button" onClick={() => void stop()}>
            <Square size={11} /> Stop team
          </button>
        </div>
      )}
      <InputArea
        onLocalSend={send}
        disabled={busy}
        placeholder="Message the team..."
      />
    </div>
  );
}
