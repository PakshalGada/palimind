import { useState, useEffect, useCallback } from "react";
import { useApp } from "../AppContext";
import { api } from "../api";
import FileTreeView from "./FileTreeView";
import ContextMenu from "./ContextMenu";
import AgentAvatar from "./AgentAvatar";
import { useConfirm } from "./ConfirmDialog";
import type { AgentListItem } from "../types";

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
  if (!leaf) return "Field Workspace";
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
  return title || "Field Workspace";
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
    setSelectedAgentId,
  } = useApp();

  const [fields, setFields] = useState<string[]>([]);
  const [syncText, setSyncText] = useState("Sync Active Field");
  const [treeField, setTreeField] = useState<string | null>(null);
  const [ctxMenu, setCtxMenu] = useState<CtxMenu | null>(null);
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const confirm = useConfirm();

  const fetchFields = useCallback(async () => {
    try {
      const data = await api.fields.list();
      setFields(data.fields);
      setActiveField(data.active_field);
      setIsIndexing(data.is_indexing);
      if (data.is_indexing) {
        setIndexingStatus(data.indexing_status || "Indexing field...");
      }
    } catch (e) {
      console.error("fetchFields error:", e);
    }
  }, []);

  const fetchAgents = useCallback(async () => {
    try {
      const data = await api.agents.list();
      if (data.agents) {
        setAgents(data.agents);
        setSelectedAgentId(
          selectedAgentId && data.agents.some((a: AgentListItem) => a.id === selectedAgentId)
            ? selectedAgentId
            : (data.agents[0]?.id ?? null),
        );
      }
    } catch (e) {
      console.error("fetchAgents error:", e);
    }
  }, [selectedAgentId]);

  useEffect(() => {
    fetchFields();
  }, []);

  useEffect(() => {
    if (activeView !== "agents") return;
    fetchAgents();
    const onChanged = () => fetchAgents();
    window.addEventListener("palimind:agents-changed", onChanged);
    return () => window.removeEventListener("palimind:agents-changed", onChanged);
  }, [activeView, fetchAgents]);

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
    setTimeout(() => setSyncText("Sync Active Field"), 3000);
  };

  const handleNewSession = async () => {
    try {
      const data = await api.sessions.new(`Session ${sessions.length + 1}`);
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
      const data = await api.sessions.setActive(id);
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
      const data = await api.sessions.remove(id);
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

  const openAgentConfig = (agent: AgentListItem) => {
    setSelectedAgentId(agent.id);
    window.dispatchEvent(
      new CustomEvent("palimind:open-agent-config", {
        detail: { agentId: agent.id },
      }),
    );
  };

  const deleteAgent = async (agent: AgentListItem) => {
    const ok = await confirm(`Delete agent "${agent.name}"? This cannot be undone.`, {
      title: "Delete Agent",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.agents.remove(agent.id);
      if (selectedAgentId === agent.id) setSelectedAgentId(null);
      setAgents((prev) => prev.filter((a) => a.id !== agent.id));
      window.dispatchEvent(new CustomEvent("palimind:agents-changed"));
    } catch (e) {
      console.error("delete agent failed:", e);
    }
  };

  const showAgentMenu = (e: React.MouseEvent, agent: AgentListItem) => {
    e.preventDefault();
    e.stopPropagation();
    setCtxMenu({
      x: e.clientX,
      y: e.clientY,
      items: [
        {
          label: "Info",
          action: () => openAgentConfig(agent),
        },
        {
          label: "Delete Agent",
          action: () => deleteAgent(agent),
          isDanger: true,
        },
      ],
    });
  };

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

      <nav className="sidebar-nav" aria-label="Workspace mode">
        <button
          className={`sidebar-nav-item${activeView === "fields" ? " active" : ""}`}
          aria-label="Fields mode"
          onClick={() => setActiveView("fields")}
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
          PaliSpace
        </button>
        <button
          className={`sidebar-nav-item${activeView === "palivision" ? " active" : ""}`}
          aria-label="PaliVision mode"
          onClick={() => setActiveView("palivision")}
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
            <circle cx="12" cy="12" r="3" />
            <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z" />
          </svg>
          PaliVision
        </button>
        <button
          className={`sidebar-nav-item${activeView === "agents" ? " active" : ""}`}
          aria-label="Agents mode"
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
        <button
          className={`sidebar-nav-item${activeView === "teams" ? " active" : ""}`}
          aria-label="Paliteams"
          title="Share this Palispace over the LAN"
          onClick={() => setActiveView("teams")}
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
            <circle cx="18" cy="5" r="3" />
            <circle cx="6" cy="12" r="3" />
            <circle cx="18" cy="19" r="3" />
            <line x1="8.6" y1="13.5" x2="15.4" y2="17.5" />
            <line x1="15.4" y1="6.5" x2="8.6" y2="10.5" />
          </svg>
          Paliteams
        </button>
      </nav>

      {activeView === "fields" && (
      <div id="fields-sidebar-content">
        <div className="fields-container">
            <div className="fields-header">
              <h3>Fields</h3>
              <button
                className="icon-btn"
                title="Add Field"
                aria-label="Add field"
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
          <div className="fields-header">
            <h3>Agents</h3>
            <button
              className="icon-btn"
              data-tooltip="New Agent"
              aria-label="Create new agent"
              onClick={() =>
                window.dispatchEvent(new CustomEvent("palimind:new-agent"))
              }
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
            {agents.map((a) => (
              <div
                key={a.id}
                className={`session-tab agent-sidebar-tab${a.id === selectedAgentId ? " active" : ""}`}
                onClick={() => setSelectedAgentId(a.id)}
                onContextMenu={(e) => showAgentMenu(e, a)}
              >
                <AgentAvatar seed={a.color_seed || a.id + a.name} thinking={!!a.running} size={20} />
                <span className="session-tab-name">{a.name}</span>
                <span
                  className={`agent-status-dot${a.running ? " running" : ""}${!a.enabled ? " off" : ""}`}
                  title={a.running ? "running" : a.enabled ? "idle" : "disabled"}
                />
              </div>
            ))}
            {agents.length === 0 && (
              <div className="agents-empty">No agents yet.</div>
            )}
          </div>
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
