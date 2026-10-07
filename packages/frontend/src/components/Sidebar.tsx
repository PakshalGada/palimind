import { useState, useEffect, useCallback } from "react";
import { useApp } from "../AppContext";
import { api } from "../api";
import FileTreeView from "./FileTreeView";
import ContextMenu from "./ContextMenu";
import { useCommandHandlers } from "../commands/useCommand";

const FIELD_TITLE_KEY = "palimind:field-display-titles";

function getPathLeaf(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

function titleCaseToken(token: string): string {
  if (/^[A-Z0-9]{2,5}$/.test(token)) return token;
  if (/^[a-z]{1,3}$/i.test(token)) return token.toUpperCase();
  return token.charAt(0).toUpperCase() + token.slice(1).toLowerCase();
}

function deriveFieldTitle(path: string): string {
  const leaf = getPathLeaf(path);
  if (!leaf) return "Knowledge Base";
  const cleaned = leaf
    .replace(/\b\d{8}T\d{6}Z(?:-\d+)*\b/gi, "")
    .replace(/\b\d{8,14}\b/g, "")
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const source = cleaned || leaf;
  const title = source.split(" ").filter(Boolean).map(titleCaseToken).join(" ");
  if (/^[A-Z0-9]{2,5}$/.test(title) || title.length <= 4)
    return `${title} Workspace`;
  return title || "Knowledge Base";
}

function getStoredTitles(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(FIELD_TITLE_KEY) || "{}");
  } catch {
    return {};
  }
}

function getFieldDisplayTitle(path: string): string {
  const titles = getStoredTitles();
  if (titles[path]) return titles[path];
  const title = deriveFieldTitle(path);
  try {
    titles[path] = title;
    localStorage.setItem(FIELD_TITLE_KEY, JSON.stringify(titles));
  } catch {}
  return title;
}

interface CtxMenu {
  x: number;
  y: number;
  items: { label: string; action: () => void; isDanger?: boolean }[];
}

export default function Sidebar() {
  const {
    activeView,
    setActiveView,
    activeField,
    setActiveField,
    activeSessionId,
    sessions,
    setSessions,
    setActiveSessionId,
    setIsIndexing,
    setIndexingStatus,
    addToast,
    selectedAgentId,
    agentsView,
    setAgentsView,
    setChatMode,
    setCommandPaletteOpen,
  } = useApp();

  const chatScope = () =>
    activeView === 'agents'
      ? selectedAgentId
        ? `agent:${selectedAgentId}`
        : ''
      : activeView === 'chat'
        ? 'chat'
        : 'field';

  const [fields, setFields] = useState<string[]>([]);
  const [syncText, setSyncText] = useState("Sync Active Knowledge Base");
  const [treeField, setTreeField] = useState<string | null>(null);
  const [ctxMenu, setCtxMenu] = useState<CtxMenu | null>(null);

  const fetchFields = useCallback(async () => {
    try {
      const data = await api.fields.list();
      setFields(data.fields);
      setActiveField(data.active_field);
      setIsIndexing(data.is_indexing);
      if (data.is_indexing) {
        setIndexingStatus(data.indexing_status || "Indexing knowledge base...");
      }
    } catch (e) {
      console.error("fetchFields error:", e);
    }
  }, []);

  useEffect(() => {
    fetchFields();
  }, []);

  // The command palette can request the workspace file tree for the active
  // knowledge base.
  useEffect(() => {
    const handler = () => {
      if (activeField) setTreeField(activeField);
    };
    window.addEventListener("palimind:open-file-tree", handler);
    return () => window.removeEventListener("palimind:open-file-tree", handler);
  }, [activeField]);

  const handleSetActive = async (path: string) => {
    try {
      await api.fields.setActive(path);
      await fetchFields();
    } catch (e) {
      console.error(e);
    }
  };

  const handleRemove = async (path: string) => {
    try {
      const data = await api.fields.remove(path);
      if (data.status === "success") await fetchFields();
    } catch (e) {
      console.error(e);
    }
  };

  const handleSync = async () => {
    setSyncText("Syncing...");
    try {
      const data = await api.sync();
      if (data.status === "success") {
        setSyncText(
          `Synced (${data.indexed_files} added, ${data.deleted_files} del)`,
        );
        addToast(
          `Synced successfully: ${data.indexed_files} added, ${data.deleted_files} deleted`,
        );
      } else {
        setSyncText(`Error: ${data.error}`);
        addToast(`Sync error: ${data.error}`);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "unknown";
      setSyncText("Error!");
      addToast(`Sync failed: ${msg}`);
    }
    setTimeout(() => setSyncText("Sync Active Knowledge Base"), 3000);
  };

  const handleNewSession = async () => {
    try {
      const data = await api.sessions.new(`Session ${sessions.length + 1}`, chatScope());
      if (!data.error) {
        setSessions(data.sessions as typeof sessions);
        setActiveSessionId(data.active_session_id);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleSwitchSession = async (id: string) => {
    try {
      const data = await api.sessions.setActive(id, chatScope());
      if (!data.error) {
        setSessions(data.sessions as typeof sessions);
        setActiveSessionId(data.active_session_id);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteSession = async (id: string) => {
    try {
      const data = await api.sessions.remove(id, chatScope());
      if (!data.error) {
        setSessions(data.sessions as typeof sessions);
        setActiveSessionId(data.active_session_id);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleOpenGraph = () => {
    const modal = document.getElementById("graph-modal");
    if (modal) modal.style.display = "flex";
    window.dispatchEvent(new CustomEvent("palimind:open-graph"));
  };

  useCommandHandlers({
    "chat.new": () => {
      if (!chatScope()) {
        addToast("Select an agent to start a session.");
        return;
      }
      void handleNewSession();
    },
    "nav.sync": () => {
      if (!activeField) {
        addToast("Select a knowledge base to sync.");
        return;
      }
      void handleSync();
    },
  });

  const showFieldMenu = (e: React.MouseEvent, path: string) => {
    e.preventDefault();
    e.stopPropagation();
    setCtxMenu({
      x: e.clientX,
      y: e.clientY,
      items: [
        {
          label: "View Folder Structure",
          action: () => setTreeField(path),
        },
        {
          label: "Delete Workspace Folder",
          action: () => handleRemove(path),
          isDanger: true,
        },
      ],
    });
  };

  const showSessionMenu = (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    setCtxMenu({
      x: e.clientX,
      y: e.clientY,
      items: [
        {
          label: "Delete Session",
          action: () => handleDeleteSession(id),
          isDanger: true,
        },
      ],
    });
  };

  const sessionsSidebar = (
    <div className="sessions-sidebar-container">
      <div className="sessions-sidebar-header">
        <h3>Sessions</h3>
        <button
          className="icon-btn"
          title="New Session"
          aria-label="Create new session"
          onClick={handleNewSession}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>
      <div className="session-list">
        {sessions.map((sess) => (
          <div
            key={sess.id}
            className={`session-tab ${sess.id === activeSessionId ? "active" : ""}`}
            onClick={() => handleSwitchSession(sess.id)}
            onContextMenu={(e) => showSessionMenu(e, sess.id)}
          >
            <span className="session-tab-name">{sess.name}</span>
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <aside className="sidebar" id="main-sidebar">
      <div className="logo">
        <h2 className="sidebar-wordmark">Palimind</h2>
        <button
          id="btn-settings"
          className="icon-btn"
          title="Settings"
          aria-label="Open settings"
          style={{ marginLeft: "auto" }}
          onClick={() => {
            const modal = document.getElementById("settings-modal");
            if (modal) modal.style.display = "flex";
          }}
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
      </div>

      <button
        type="button"
        className="sidebar-search-btn"
        onClick={() => setCommandPaletteOpen(true)}
        title="Search or run a command (Ctrl+K)"
        aria-label="Open command palette"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <span className="sidebar-search-label">Search or run…</span>
        <kbd className="sidebar-search-kbd">Ctrl K</kbd>
      </button>

      <nav className="sidebar-nav" aria-label="Workspace mode">
        <button
          className={`sidebar-nav-item${activeView === "chat" ? " active" : ""}`}
          aria-label="Chat mode"
          title="Chat — talk with a local LLM using general knowledge only"
          onClick={() => {
            setActiveView("chat");
            setChatMode("llm");
          }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          Chat
        </button>
        <button
          className={`sidebar-nav-item${activeView === "fields" ? " active" : ""}`}
          aria-label="Knowledge Base mode"
          title="Knowledge Base — chat with your indexed documents and workspaces"
          onClick={() => {
            setActiveView("fields");
            setChatMode("document");
          }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </svg>
          Knowledge Base
        </button>
        <button
          className={`sidebar-nav-item${activeView === "agents" ? " active" : ""}`}
          aria-label="Agents mode"
          title="Agents — chat with AI agents that can research, write code, and analyze data"
          onClick={() => setActiveView("agents")}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="4" y="8" width="16" height="12" rx="2" />
            <circle cx="9" cy="13.5" r="1.2" fill="currentColor" stroke="none" />
            <circle cx="15" cy="13.5" r="1.2" fill="currentColor" stroke="none" />
            <path d="M12 8V5M9 5h6" />
          </svg>
          Agents
        </button>
      </nav>

      {activeView === "chat" && (
        <div className="chat-sidebar-content">
          {sessionsSidebar}
        </div>
      )}

      {activeView === "fields" && (
      <div id="fields-sidebar-content">
        <div className="fields-container">
            <div className="fields-header">
              <h3>Knowledge Bases</h3>
              <button
                className="icon-btn"
                title="Add Knowledge Base"
                aria-label="Add knowledge base"
                onClick={() => {
                  const modal = document.getElementById("dir-picker-modal");
                  if (modal) {
                    modal.style.display = "flex";
                    window.dispatchEvent(
                      new CustomEvent("palimind:open-dir-picker"),
                    );
                  }
                }}
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
              </button>
            </div>
            <ul className="fields-list">
              {fields.map((path) => (
                <li
                  key={path}
                  className={`field-item ${path === activeField ? "active" : ""}`}
                  onContextMenu={(e) => showFieldMenu(e, path)}
                >
                  <span
                    className="field-name"
                    title={path}
                    onClick={() => handleSetActive(path)}
                  >
                    {getFieldDisplayTitle(path)}
                  </span>
                </li>
              ))}
            </ul>
            <button
              className="action-btn"
              style={{ display: activeField ? "block" : "none" }}
              onClick={handleSync}
            >
              {syncText}
            </button>
            <button
              className="action-btn graph-btn"
              style={{ display: activeField ? "block" : "none" }}
              onClick={handleOpenGraph}
            >
              View Knowledge Graph
            </button>
          </div>

          {sessionsSidebar}

          {treeField && (
            <div className="modal" onClick={() => setTreeField(null)}>
              <div
                className="modal-content file-tree-modal-content"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="modal-header">
                  <h2>Workspace Files</h2>
                  <button
                    className="icon-btn"
                    onClick={() => setTreeField(null)}
                  >
                    ×
                  </button>
                </div>
                <div className="modal-body file-tree-modal-body">
                  <FileTreeView modal />
                </div>
              </div>
            </div>
          )}
      </div>
      )}

      {activeView === "agents" && (
        <div className="sidebar-agents-content">
          <nav className="sidebar-subnav sidebar-subnav--top" aria-label="Agents workspace">
            <button
              className={`sidebar-subnav-item${agentsView === "chat" ? " active" : ""}`}
              onClick={() => setAgentsView("chat")}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
              Chat
            </button>
            <button
              className={`sidebar-subnav-item${agentsView === "workflows" ? " active" : ""}`}
              onClick={() => setAgentsView("workflows")}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="7" height="7" rx="1" />
                <rect x="14" y="3" width="7" height="7" rx="1" />
                <rect x="3" y="14" width="7" height="7" rx="1" />
                <path d="M10 6.5h4M10 17.5h4M6.5 10v4M17.5 10v4" />
              </svg>
              Workflows
            </button>
            <button
              className={`sidebar-subnav-item${agentsView === "kanban" ? " active" : ""}`}
              onClick={() => setAgentsView("kanban")}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="5" height="18" rx="1" />
                <rect x="10" y="3" width="5" height="12" rx="1" />
                <rect x="17" y="3" width="5" height="8" rx="1" />
              </svg>
              Tasks
            </button>
          </nav>
        </div>
      )}

      {ctxMenu && (
        <ContextMenu
          x={ctxMenu.x}
          y={ctxMenu.y}
          items={ctxMenu.items}
          onClose={() => setCtxMenu(null)}
        />
      )}
    </aside>
  );
}
