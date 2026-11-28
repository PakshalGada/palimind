import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { Folder, PanelLeftClose, PanelLeftOpen, PanelRight, Search } from 'lucide-react';
import { useApp } from '../../AppContext';
import type { AgentsView } from '../../types';
import './CommandBar.css';

const AGENT_TABS: { id: AgentsView; label: string }[] = [
  { id: 'chat', label: 'Chat' },
  { id: 'work', label: 'Work' },
];

/**
 * The conversation title. It truncates with an ellipsis when it doesn't fit,
 * and on hover the full title scrolls back and forth (marquee) so long chat
 * names stay readable without a tooltip.
 */
function ConversationTitle({ text }: { text: string }) {
  const outerRef = useRef<HTMLSpanElement>(null);
  const trackRef = useRef<HTMLSpanElement>(null);
  const [distance, setDistance] = useState(0);
  const overflowing = distance > 2;

  useLayoutEffect(() => {
    const outer = outerRef.current;
    const track = trackRef.current;
    if (!outer || !track) return;
    const measure = () => {
      const next = Math.max(0, track.scrollWidth - outer.clientWidth);
      setDistance(next);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(outer);
    return () => observer.disconnect();
  }, [text]);

  return (
    <span
      ref={outerRef}
      className={`command-bar__title${overflowing ? ' is-overflowing' : ''}`}
      title={text}
    >
      <span className="command-bar__title-static">{text}</span>
      <span
        ref={trackRef}
        className="command-bar__title-track"
        aria-hidden="true"
        style={
          {
            '--marquee-distance': `${distance}px`,
            '--marquee-duration': `${Math.max(6, distance / 45)}s`,
          } as CSSProperties
        }
      >
        {text}
      </span>
    </span>
  );
}

export default function CommandBar() {
  const {
    activeView,
    agentsView,
    setAgentsView,
    sessions,
    activeSessionId,
    setCommandPaletteOpen,
    sidebarCollapsed,
    toggleSidebar,
    activeProjectId,
    activeProjectName,
    setActiveProjectId,
    setActiveProjectName,
    workbenchOpen,
    workbenchTab,
    toggleWorkbench,
  } = useApp();

  const title =
    activeView === 'chat'
      ? sessions.find((s) => s.id === activeSessionId)?.name ?? null
      : null;

  return (
    <header className="command-bar" role="banner">
      <div className="command-bar__left">
        <div className="command-bar__brand">
          <span className="command-bar__wordmark">PaliMind</span>
        </div>

        <nav className="command-bar__context" aria-label="Current context">
          {activeProjectId && (
            <span className="command-bar__project" title={activeProjectName ?? 'Active project'}>
              <Folder size={12} aria-hidden="true" />
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
        </nav>

        <div className="command-bar__tools">
          <button
            type="button"
            className="command-bar__icon"
            onClick={() => setCommandPaletteOpen(true)}
            aria-label="Search or run a command"
            title="Search or run a command"
          >
            <Search size={16} />
          </button>

          <button
            type="button"
            className="command-bar__icon"
            onClick={toggleSidebar}
            aria-label={sidebarCollapsed ? 'Open navigation' : 'Close navigation'}
            aria-pressed={!sidebarCollapsed}
            title={sidebarCollapsed ? 'Open navigation' : 'Close navigation'}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>
      </div>

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
        ) : title ? (
          <ConversationTitle text={title} />
        ) : null}
      </div>

      <div className="command-bar__right">
        <button
          type="button"
          className={`command-bar__icon${workbenchOpen ? ' is-on' : ''}`}
          title={workbenchOpen ? `Hide ${workbenchTab}` : 'Open side panel'}
          aria-label={workbenchOpen ? 'Hide side panel' : 'Open side panel'}
          aria-pressed={workbenchOpen}
          onClick={() => toggleWorkbench(workbenchTab)}
        >
          <PanelRight size={16} />
        </button>
      </div>
    </header>
  );
}
