import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, Square, Users } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import CollapsibleMessage from '../../components/CollapsibleMessage';
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

/** Roles that read as teammates talking, not as run bookkeeping. */
function isChatRole(role: string): boolean {
  return role === 'chat' || role === 'manager' || role === 'synthesis';
}

type TeamRenderItem =
  | { kind: 'user'; message: TeamMessage }
  | { kind: 'notice'; message: TeamMessage }
  | { kind: 'chat'; author: string; messages: TeamMessage[] }
  | { kind: 'work'; messages: TeamMessage[] };

/** Collapse handoffs, results and system lines into one expandable run card. */
function TeamWorkGroup({
  messages,
  nameFor,
}: {
  messages: TeamMessage[];
  nameFor: (author: string) => string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="ag-work">
      <button
        type="button"
        className="ag-work__toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <ChevronRight size={12} className={open ? 'is-open' : undefined} />
        <span className="ag-work__title">Work</span>
        <span className="ag-work__count">
          {messages.length} step{messages.length === 1 ? '' : 's'}
        </span>
        <span className="ag-work__hint">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <div className="ag-work__body">
          {messages.map((message) => (
            <div key={message.id} className="ag-work__row">
              <div className="ag-work__meta">
                <span className="ag-work__author">{nameFor(message.author)}</span>
                <span className="ag-work__role">{message.role}</span>
                <time>{relTime(message.created_at)}</time>
              </div>
              <div className="ag-work__content">
                <MessageContent content={message.content} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
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
    const mention = text.match(/@([\w-]{1,64})/);
    const target =
      mention &&
      memberAgents.find(
        (agent) => agent.name === mention[1] || agent.display_name === mention[1],
      );
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
      }, { mode: team?.mode, targetAgentId: target?.id });
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

  const memberAgents = team
    ? agents.filter((agent) => team.members.some((member) => member.agent_id === agent.id))
    : agents;

  const renderItems = useMemo(() => {
    const items: TeamRenderItem[] = [];
    for (const message of messages) {
      if (message.role === 'user') {
        items.push({ kind: 'user', message });
        continue;
      }
      if (message.role === 'approval' || message.role === 'system') {
        items.push({ kind: 'notice', message });
        continue;
      }
      if (isChatRole(message.role)) {
        const previous = items[items.length - 1];
        if (previous?.kind === 'chat' && previous.author === message.author) {
          previous.messages.push(message);
        } else {
          items.push({ kind: 'chat', author: message.author, messages: [message] });
        }
        continue;
      }
      const previous = items[items.length - 1];
      if (previous?.kind === 'work') previous.messages.push(message);
      else items.push({ kind: 'work', messages: [message] });
    }
    return items;
  }, [messages]);

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
          renderItems.map((item, index) => {
            if (item.kind === 'user') {
              return (
                <div key={item.message.id} className="ag-msg ag-msg--user">
                  <div className="ag-msg__user-body">
                    <div className="ag-msg__user-bubble">
                      <MessageContent content={item.message.content} />
                    </div>
                    <div className="ag-msg__user-meta">{relTime(item.message.created_at)}</div>
                  </div>
                </div>
              );
            }
            if (item.kind === 'notice') {
              return (
                <div key={item.message.id} className="ag-msg ag-msg--system">
                  <span>{item.message.content}</span>
                  <time>{relTime(item.message.created_at)}</time>
                </div>
              );
            }
            if (item.kind === 'work') {
              return (
                <TeamWorkGroup
                  key={`work-${item.messages[0]?.id || index}`}
                  messages={item.messages}
                  nameFor={(author) => {
                    if (author === 'system') return 'Team';
                    return findingMember(author)?.display_name || authorName(author);
                  }}
                />
              );
            }
            const author = findingMember(item.author);
            return (
              <div key={`chat-${item.messages[0]?.id || index}`} className="ag-msg ag-msg--agent">
                <div className="ag-msg__avatar">
                  <AgentAvatar
                    config={author?.avatar_config}
                    type={author?.avatar_type === 'upload' ? 'upload' : 'bot'}
                    upload={author?.avatar_upload}
                    size={24}
                  />
                </div>
                <div className="ag-msg__body">
                  {item.messages.map((message, messageIndex) => (
                    <div key={message.id} className="ag-msg__chat-line">
                      {messageIndex === 0 && (
                        <div className="ag-msg__meta">
                          <span className="ag-msg__author">
                            {author?.display_name ||
                              (item.author === 'system' ? 'Team' : authorName(item.author))}
                          </span>
                          <span className="ag-msg__handle">
                            {message.role === 'synthesis' ? 'answer' : 'message'}
                          </span>
                          <span className="ag-msg__time">{relTime(message.created_at)}</span>
                        </div>
                      )}
                      <CollapsibleMessage content={message.content} />
                    </div>
                  ))}
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
        mentionAgents={memberAgents}
        placeholder="Message the team..."
      />
    </div>
  );
}
