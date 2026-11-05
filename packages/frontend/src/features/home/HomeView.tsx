import { useMemo } from 'react';
import {
  ArrowRight,
  Bot,
  FolderOpen,
  MessageSquare,
  Plus,
  Search,
} from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import { runCommand } from '../../commands/registry';
import { PixelGlyph } from '../../components/pixel/PixelGlyph';
import { PixelLoader } from '../../components/pixel/PixelLoader';
import { PixelStamp } from '../../components/pixel/PixelStamp';
import AgentAvatar from '../../components/AgentAvatar';
import { EmptyState } from '../../ui/primitives';
import { greeting, relativeTime, exactTime } from '../../utils/time';
import { resolveScope } from '../../lib/scope';
import './home.css';

const MAX_RECENT = 5;

export default function HomeView() {
  const {
    sessions,
    setSessions,
    setActiveSessionId,
    setActiveView,
    activeField,
    activeProjectName,
    activeProjectId,
    selectedAgentId,
    overview,
    isIndexing,
    indexingStatus,
    setCommandPaletteOpen,
  } = useApp();

  const recentChats = useMemo(
    () =>
      [...sessions]
        .sort((a, b) => {
          const aTime = a.messages[a.messages.length - 1]?.timestamp ?? a.created_at ?? 0;
          const bTime = b.messages[b.messages.length - 1]?.timestamp ?? b.created_at ?? 0;
          return bTime - aTime;
        })
        .slice(0, MAX_RECENT),
    [sessions],
  );
  const recentRuns = useMemo(() => (overview?.recent ?? []).slice(0, MAX_RECENT), [overview]);
  const counts = overview?.counts;

  const team = useMemo(() => {
    if (!overview) return [];
    return [...overview.agents, ...overview.teams].slice(0, 8);
  }, [overview]);

  const isFresh =
    recentChats.length === 0 && recentRuns.length === 0 && team.length === 0;

  const openChat = async (id: string) => {
    setActiveView('chat');
    try {
      const data = await api.sessions.setActive(
        id,
        resolveScope('home', { agentId: selectedAgentId, projectId: activeProjectId }),
      );
      if (!data.error) {
        setSessions(data.sessions as typeof sessions);
        setActiveSessionId(data.active_session_id);
      }
    } catch {
      setActiveSessionId(id);
    }
  };

  const newChat = () => {
    setActiveView('chat');
    runCommand('chat.new');
  };

  const statusLine = isIndexing
    ? indexingStatus || 'Indexing knowledge'
    : counts
      ? `${counts.agents} agents · ${counts.teams} teams · ${
          counts.working > 0 ? `${counts.working} working` : 'all idle'
        }`
      : 'Local workspace';

  return (
    <div className="home-view">
      <div className="home-view__scroll">
        <section className="home-hero">
          <div className="home-hero__eyebrow">
            {isIndexing ? (
              <PixelLoader cell={1.25} label="Indexing" />
            ) : (
              <PixelGlyph sprite="checker" cell={1.25} />
            )}
            {statusLine}
          </div>
          <h1 className="home-hero__title">{greeting()}</h1>
          <p className="home-hero__lede">
            Everything runs on this machine. Pick up a conversation, hand work to an
            agent, or start from a clean page.
          </p>

          {!isFresh && (
            <div className="home-actions">
              <button type="button" className="home-action home-action--primary" onClick={newChat}>
                <Plus size={15} />
                New chat
              </button>
              <button
                type="button"
                className="home-action"
                onClick={() => setActiveView('agents')}
              >
                <Bot size={15} />
                Ask an agent
              </button>
              <button
                type="button"
                className="home-action"
                onClick={() => setActiveView('projects')}
              >
                <FolderOpen size={15} />
                Projects
              </button>
              <button
                type="button"
                className="home-action"
                onClick={() => setCommandPaletteOpen(true)}
              >
                <Search size={15} />
                Search
              </button>
            </div>
          )}
        </section>

        <section className="home-paper" aria-label="Current workspace">
          <div className="home-paper__main">
            <span className="home-paper__label">{activeProjectId ? 'Active project' : 'Workspace'}</span>
            <span className="home-paper__name">
              {activeProjectId
                ? activeProjectName || 'Project'
                : activeField
                  ? activeField.split(/[\\/]/).filter(Boolean).pop()
                  : 'No workspace selected'}
            </span>
            <span className="home-paper__path">
              {activeProjectId
                ? 'Sessions, knowledge and artifacts are scoped to this project.'
                : activeField ?? 'Add a folder to index documents locally.'}
            </span>
          </div>
          <button
            type="button"
            className="home-paper__action"
            onClick={() => setActiveView(activeProjectId ? 'projects' : 'knowledge')}
          >
            {activeProjectId ? 'Manage project' : activeField ? 'Manage knowledge' : 'Add a folder'}
            <ArrowRight size={14} />
          </button>
        </section>

        {isFresh ? (
          <section className="home-start" aria-label="Start here">
            <div className="home-start__head">
              <span className="home-start__glyph" aria-hidden="true">
                <PixelGlyph sprite="spark" cell={3} />
              </span>
              <div>
                <h2>Start here</h2>
                <p>
                  Pick one thing and the workspace will fill in around you. Everything
                  stays on this machine.
                </p>
              </div>
            </div>
            <div className="home-start__actions">
              <button type="button" className="home-action home-action--primary" onClick={newChat}>
                <Plus size={15} /> New chat
              </button>
              <button
                type="button"
                className="home-action"
                onClick={() => setActiveView('projects')}
              >
                <FolderOpen size={15} /> Create a project
              </button>
              <button
                type="button"
                className="home-action"
                onClick={() => {
                  setActiveView('agents');
                  window.dispatchEvent(new CustomEvent('palimind:new-agent'));
                }}
              >
                <Bot size={15} /> Create an agent
              </button>
            </div>
            <div className="home-start__hint">
              Tip: press <kbd>⌘K</kbd> to search commands, chats and files.
            </div>
          </section>
        ) : (
          <>
        <div className="home-grid">
          <section className="home-panel">
            <header className="home-panel__head">
              <h2>Recent chats</h2>
              <button type="button" className="home-panel__more" onClick={() => setActiveView('chat')}>
                All chats
              </button>
            </header>
            {recentChats.length === 0 ? (
              <EmptyState
                compact
                glyph={<PixelGlyph sprite="terminal" cell={3} />}
                title="No conversations yet"
                description="Start a chat and it will show up here."
              />
            ) : (
              <ul className="home-list">
                {recentChats.map((session) => {
                  const last = session.messages[session.messages.length - 1];
                  return (
                    <li key={session.id}>
                      <button
                        type="button"
                        className="home-row"
                        onClick={() => void openChat(session.id)}
                      >
                        <MessageSquare size={14} className="home-row__icon" />
                        <span className="home-row__body">
                          <span className="home-row__title">{session.name}</span>
                          <span className="home-row__meta">
                            {last ? `${last.role === 'user' ? 'You' : 'Assistant'} · ` : ''}
                            {relativeTime(last?.timestamp ?? session.created_at)}
                          </span>
                        </span>
                        <ArrowRight size={13} className="home-row__chevron" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="home-panel">
            <header className="home-panel__head">
              <h2>Recent runs</h2>
              <button
                type="button"
                className="home-panel__more"
                onClick={() => setActiveView('agents')}
              >
                All runs
              </button>
            </header>
            {recentRuns.length === 0 ? (
              <EmptyState
                compact
                glyph={<PixelGlyph sprite="checker" cell={3} />}
                title="Nothing has run yet"
                description="Agent runs and routines appear here."
              />
            ) : (
              <ul className="home-list">
                {recentRuns.map((run) => (
                  <li key={`${run.target_id}-${run.run_id}`}>
                    <button
                      type="button"
                      className="home-row"
                      onClick={() => setActiveView('agents')}
                    >
                      {run.status === 'completed' || run.status === 'success' ? (
                        <PixelStamp tone="done" size={14} />
                      ) : (
                        <PixelGlyph sprite="pause" cell={1.75} />
                      )}
                      <span className="home-row__body">
                        <span className="home-row__title">
                          {run.target_name} · <span className="home-row__mono">{run.status}</span>
                        </span>
                        <span className="home-row__meta" title={exactTime(run.timestamp)}>
                          {run.input || 'Run'} · {relativeTime(run.timestamp)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <section className="home-team" aria-label="Your team">
          <header className="home-panel__head">
            <h2>Your team</h2>
            <button
              type="button"
              className="home-panel__more"
              onClick={() => setActiveView('agents')}
            >
              Manage
            </button>
          </header>
          {team.length === 0 ? (
            <EmptyState
              compact
              glyph={<PixelGlyph sprite="spark" cell={3} />}
              title="No agents yet"
              description="Create a teammate to run work in the background."
              action={
                <button
                  type="button"
                  className="home-action home-action--sm"
                  onClick={() => {
                    setActiveView('agents');
                    window.dispatchEvent(new CustomEvent('palimind:new-agent'));
                  }}
                >
                  <Plus size={13} /> Create teammate
                </button>
              }
            />
          ) : (
            <ul className="home-team__list">
              {team.map((member) => (
                <li key={`${member.target_type}-${member.id}`} className="home-team__member">
                  <AgentAvatar
                    config={member.avatar_config}
                    type={member.avatar_type}
                    upload={member.avatar_upload}
                    size={34}
                    interactive={false}
                    paused
                  />
                  <span className="home-team__body">
                    <span className="home-team__name">{member.display_name || member.name}</span>
                    <span className="home-team__role">
                      {member.title || member.target_type}
                    </span>
                  </span>
                  <span className={`home-team__state is-${member.status}`}>
                    <span className="home-team__glyph" aria-hidden="true">
                      {member.status === 'working' ? (
                        <PixelGlyph sprite="checker" cell={1.25} />
                      ) : member.status === 'waiting' ? (
                        <PixelGlyph sprite="diamond" cell={1.25} />
                      ) : member.status === 'error' ? (
                        <PixelGlyph sprite="cross" cell={1.25} />
                      ) : (
                        <PixelGlyph sprite="tick" cell={1.25} />
                      )}
                    </span>
                    {member.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
          </>
        )}

        <footer className="home-foot">
          <PixelGlyph sprite="spark" cell={1.25} />
          <span>All models and files stay on this device.</span>
        </footer>
      </div>
    </div>
  );
}
