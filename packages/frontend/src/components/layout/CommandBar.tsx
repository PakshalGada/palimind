import {
  Bell,
  Menu,
  Moon,
  Plus,
  Search,
  Sun,
} from 'lucide-react';
import { useApp } from '../../AppContext';
import { runCommand } from '../../commands/registry';
import { PixelGlyph } from '../pixel/PixelGlyph';
import { PixelLoader } from '../pixel/PixelLoader';
import type { AgentsView } from '../../types';
import './CommandBar.css';

const VIEW_LABEL: Record<string, string> = {
  home: 'Home',
  chat: 'Chat',
  agents: 'Agents',
  knowledge: 'Knowledge',
  projects: 'Projects',
  artifacts: 'Artifacts',
};

const AGENT_TABS: { id: AgentsView; label: string }[] = [
  { id: 'home', label: 'Overview' },
  { id: 'chat', label: 'Chat' },
  { id: 'teams', label: 'Teams' },
  { id: 'kanban', label: 'Tasks' },
  { id: 'runs', label: 'Runs' },
];

export default function CommandBar() {
  const {
    activeView,
    agentsView,
    setAgentsView,
    sessions,
    activeSessionId,
    theme,
    setTheme,
    setCommandPaletteOpen,
    inbox,
    isIndexing,
    indexingStatus,
    overview,
    toggleSidebar,
    currentModel,
    activeProjectId,
    activeProjectName,
    setActiveProjectId,
    setActiveProjectName,
  } = useApp();

  const sessionName =
    activeView === 'chat'
      ? sessions.find((s) => s.id === activeSessionId)?.name ?? 'New chat'
      : null;

  const working = overview?.counts.working ?? 0;
  const waiting = overview?.counts.waiting ?? inbox.length;

  const status = isIndexing
    ? { busy: true, label: indexingStatus || 'Indexing' }
    : working > 0
      ? { busy: true, label: `${working} working` }
      : { busy: false, label: 'Local' };

  const primary = (() => {
    switch (activeView) {
      case 'chat':
        return { label: 'New chat', icon: Plus, run: () => runCommand('chat.new') };
      case 'agents':
        return {
          label: 'New agent',
          icon: Plus,
          run: () => window.dispatchEvent(new CustomEvent('palimind:new-agent')),
        };
      default:
        return null;
    }
  })();

  const titledSurface =
    activeView === 'projects' || activeView === 'knowledge' || activeView === 'artifacts';

  return (
    <header className="command-bar" role="banner">
      <button
        type="button"
        className="command-bar__icon command-bar__menu"
        onClick={toggleSidebar}
        aria-label="Open navigation"
        title="Open navigation"
      >
        <Menu size={16} />
      </button>

      <div className="command-bar__brand">
        <span className="command-bar__wordmark">PaliMind</span>
      </div>

      <nav className="command-bar__context" aria-label="Current context">
        <span className={`command-bar__view${titledSurface ? ' is-implicit' : ''}`}>
          {VIEW_LABEL[activeView] ?? activeView}
        </span>
        {activeProjectId && (
          <span className="command-bar__project" title={activeProjectName ?? 'Active project'}>
            <PixelGlyph sprite="folder" cell={1.25} />
            <span className="command-bar__project-name">
              {activeProjectName ?? 'Project'}
            </span>
            <button
              type="button"
              className="command-bar__project-leave"
              title="Leave project context"
              aria-label="Leave project context"
              onClick={() => {
                setActiveProjectId(null);
                setActiveProjectName(null);
              }}
            >
              ×
            </button>
          </span>
        )}
        {sessionName && activeView === 'chat' && (
          <span className="command-bar__session" title={sessionName}>
            {sessionName}
          </span>
        )}
        {activeView === 'agents' && !activeProjectId && (
          <span className="command-bar__session">Local agents</span>
        )}
      </nav>

      <div className="command-bar__center">
        {activeView === 'agents' ? (
          <div className="command-bar__tabs" role="tablist" aria-label="Agents sections">
            {AGENT_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={agentsView === tab.id}
                className={`command-bar__tab${agentsView === tab.id ? ' is-active' : ''}`}
                onClick={() => setAgentsView(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        ) : (
          <button
            type="button"
            className="command-bar__command"
            onClick={() => setCommandPaletteOpen(true)}
            aria-label="Search or run a command"
          >
            <Search size={14} />
            <span className="command-bar__command-label">Search or run a command</span>
            <kbd className="command-bar__kbd">⌘K</kbd>
          </button>
        )}
      </div>

      <div className="command-bar__right">
        <span
          className={`command-bar__status${status.busy ? ' is-busy' : ''}`}
          title={status.busy ? status.label : `${status.label} · ${currentModel}`}
        >
          {status.busy ? (
            <PixelLoader cell={1} label={status.label} />
          ) : (
            <PixelGlyph sprite="checker" cell={1} className="command-bar__idle" />
          )}
          <span className="command-bar__status-label">{status.label}</span>
        </span>

        {primary && (
          <button type="button" className="command-bar__primary" onClick={primary.run}>
            <primary.icon size={14} />
            <span className="command-bar__primary-label">{primary.label}</span>
          </button>
        )}

        <button
          type="button"
          className="command-bar__icon"
          title={waiting > 0 ? `${waiting} waiting on you` : 'Approvals inbox'}
          aria-label="Approvals inbox"
          onClick={() => window.dispatchEvent(new CustomEvent('palimind:open-inbox'))}
        >
          <Bell size={15} />
          {waiting > 0 && <span className="command-bar__badge">{waiting}</span>}
        </button>

        <button
          type="button"
          className="command-bar__icon"
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        >
          {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>
    </header>
  );
}
