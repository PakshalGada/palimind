import { useState, useEffect, useCallback } from "react";
import {
  BookOpen,
  Bot,
  Folder,
  FolderKanban,
  FolderPlus,
  LayoutGrid,
  MessageSquare,
  Moon,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Sun,
  X,
  type LucideIcon,
} from "lucide-react";
import { useApp } from "../AppContext";
import { api } from "../api";
import FileTreeView from "./FileTreeView";
import ContextMenu from "./ContextMenu";
import { useCommandHandlers } from "../commands/useCommand";
import { getCommand } from "../commands/catalog";
import { runCommand } from "../commands/registry";
import { formatShortcut } from "../utils/shortcuts";
import {
  Avatar,
  EmptyState,
  InlineError,
  Kbd,
  Scrollbar,
  SkeletonList,
} from "../ui/primitives";

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

interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
  shortcutId: string;
  onSelect: () => void;
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
    sidebarCollapsed,
    toggleSidebar,
    setSidebarCollapsed,
    shortcutOverrides,
    theme,
    setTheme,
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
  const [fieldsLoading, setFieldsLoading] = useState(true);
  const [fieldsError, setFieldsError] = useState<string | null>(null);
  const [syncText, setSyncText] = useState("Sync Active Knowledge Base");
  const [treeField, setTreeField] = useState<string | null>(null);
  const [ctxMenu, setCtxMenu] = useState<CtxMenu | null>(null);
  const [researchOpen, setResearchOpen] = useState(false);

  const fetchFields = useCallback(async () => {
    setFieldsLoading(true);
    setFieldsError(null);
    try {
      const data = await api.fields.list();
      setFields(data.fields);
      setActiveField(data.active_field);
      setIsIndexing(data.is_indexing);
      if (data.is_indexing) {
        setIndexingStatus(data.indexing_status || "Indexing knowledge base...");
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : "Could not reach the local backend.";
      setFieldsError(message);
    } finally {
      setFieldsLoading(false);
    }
  }, [setActiveField, setIsIndexing, setIndexingStatus]);

  useEffect(() => {
    void fetchFields();
  }, [fetchFields]);

  // The command palette can request the workspace file tree for the active
  // knowledge base.
  useEffect(() => {
    const handler = () => {
      if (activeField) setTreeField(activeField);
    };
    window.addEventListener("palimind:open-file-tree", handler);
    return () => window.removeEventListener("palimind:open-file-tree", handler);
  }, [activeField]);

  // ResearchManager announces when its modal opens/closes so Projects can show
  // an active state even though it is not a routed view.
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ open?: boolean }>).detail;
      setResearchOpen(Boolean(detail?.open));
    };
    window.addEventListener("palimind:research-visibility", handler);
    return () => window.removeEventListener("palimind:research-visibility", handler);
  }, []);

  const handleSetActive = async (path: string) => {
    try {
      await api.fields.setActive(path);
      await fetchFields();
    } catch (e) {
      console.error(e);
      addToast("Could not switch knowledge base.", { tone: "error" });
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
          { tone: "success" },
        );
      } else {
        setSyncText(`Error: ${data.error}`);
        addToast(`Sync error: ${data.error}`, { tone: "error" });
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "unknown";
      setSyncText("Error!");
      addToast(`Sync failed: ${msg}`, { tone: "error" });
    }
    setTimeout(() => setSyncText("Sync Active Knowledge Base"), 3000);
  };

  const handleNewSession = async () => {
    if (!chatScope()) {
      addToast("Select an agent to start a session.");
      return;
    }
    try {
      const data = await api.sessions.new(`Session ${sessions.length + 1}`, chatScope());
      if (!data.error) {
        setSessions(data.sessions as typeof sessions);
        setActiveSessionId(data.active_session_id);
      }
    } catch (e) {
      console.error(e);
      addToast("Could not create a new chat.", { tone: "error" });
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
      addToast("Could not delete the session.", { tone: "error" });
    }
  };

  const handleOpenGraph = () => {
    const modal = document.getElementById("graph-modal");
    if (modal) modal.style.display = "flex";
    window.dispatchEvent(new CustomEvent("palimind:open-graph"));
  };

  const openSettings = () => {
    runCommand("general.settings");
  };

  const openResearch = () => {
    window.dispatchEvent(new CustomEvent("palimind:open-research"));
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

  const shortcutFor = (commandId: string): string => {
    const combo = shortcutOverrides[commandId] ?? getCommand(commandId)?.defaultShortcut ?? "";
    return combo ? formatShortcut(combo) : "";
  };

  const navItems: NavItem[] = [
    {
      id: "chats",
      label: "Chats",
      icon: MessageSquare,
      active: activeView === "chat",
      shortcutId: "nav.chat",
      onSelect: () => {
        setActiveView("chat");
        setChatMode("llm");
      },
    },
    {
      id: "projects",
      label: "Projects",
      icon: FolderKanban,
      active: researchOpen,
      shortcutId: "research.projects",
      onSelect: openResearch,
    },
    {
      id: "agents",
      label: "Agents",
      icon: Bot,
      active: activeView === "agents",
      shortcutId: "nav.agents",
      onSelect: () => setActiveView("agents"),
    },
    {
      id: "knowledge",
      label: "Knowledge Base",
      icon: BookOpen,
      active: activeView === "fields",
      shortcutId: "nav.knowledge",
      onSelect: () => {
        setActiveView("fields");
        setChatMode("document");
      },
    },
  ];

  const openDirPicker = () => {
    const modal = document.getElementById("dir-picker-modal");
    if (modal) {
      modal.style.display = "flex";
      window.dispatchEvent(new CustomEvent("palimind:open-dir-picker"));
    }
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

  const sessionsSection = (
    <div className="sb-section">
      <div className="sb-section-head">
        <span className="sb-section-title sb-collapsible">
          {activeView === "chat" ? "Recent chats" : "Sessions"}
        </span>
        <button
          type="button"
          className="sb-icon-btn"
          title="New chat"
          aria-label="Create new chat"
          onClick={handleNewSession}
        >
          <Plus size={14} />
        </button>
      </div>
      {sessions.length === 0 ? (
        <EmptyState
          compact
          icon={<MessageSquare size={18} />}
          title="No chats yet"
          description="Start a conversation and it will appear here."
        />
      ) : (
        <div className="sb-list">
          {sessions.map((sess) => (
            <button
              key={sess.id}
              type="button"
              className={`sb-row${sess.id === activeSessionId ? " is-active" : ""}`}
              onClick={() => handleSwitchSession(sess.id)}
              onContextMenu={(e) => showSessionMenu(e, sess.id)}
              title={sess.name}
            >
              <span className="sb-row__label">{sess.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );

  const knowledgeSection = (
    <div className="sb-section">
      <div className="sb-section-head">
        <span className="sb-section-title sb-collapsible">Knowledge bases</span>
        <button
          type="button"
          className="sb-icon-btn"
          title="Add knowledge base"
          aria-label="Add knowledge base"
          onClick={openDirPicker}
        >
          <FolderPlus size={14} />
        </button>
      </div>

      {fieldsLoading ? (
        <SkeletonList rows={3} avatar={false} />
      ) : fieldsError ? (
        <InlineError
          title="Couldn't load knowledge bases"
          message={fieldsError}
          onRetry={() => void fetchFields()}
        />
      ) : fields.length === 0 ? (
        <EmptyState
          compact
          icon={<FolderPlus size={18} />}
          title="No knowledge bases"
          description="Add a folder to index documents locally."
          action={
            <button type="button" className="sb-action" onClick={openDirPicker}>
              Add folder
            </button>
          }
        />
      ) : (
        <div className="sb-list">
          {fields.map((path) => (
            <button
              key={path}
              type="button"
              className={`sb-row${path === activeField ? " is-active" : ""}`}
              title={path}
              onClick={() => handleSetActive(path)}
              onContextMenu={(e) => showFieldMenu(e, path)}
            >
              <Folder size={14} className="sb-row__icon" />
              <span className="sb-row__label">{getFieldDisplayTitle(path)}</span>
            </button>
          ))}
        </div>
      )}

      <button
        type="button"
        className="sb-action"
        style={{ display: activeField ? "flex" : "none" }}
        onClick={handleSync}
      >
        <RefreshCw size={13} />
        <span>{syncText}</span>
      </button>
      <button
        type="button"
        className="sb-action"
        style={{ display: activeField ? "flex" : "none" }}
        onClick={handleOpenGraph}
      >
        <Network size={13} />
        <span>Knowledge graph</span>
      </button>
    </div>
  );

  const agentsSection = (
    <div className="sb-section">
      <div className="sb-section-head">
        <span className="sb-section-title sb-collapsible">Workspace</span>
      </div>
      <div className="sb-list">
        <button
          type="button"
          className={`sb-row${agentsView === "chat" ? " is-active" : ""}`}
          onClick={() => setAgentsView("chat")}
        >
          <MessageSquare size={14} className="sb-row__icon" />
          <span className="sb-row__label">Agent chat</span>
        </button>
        <button
          type="button"
          className={`sb-row${agentsView === "kanban" ? " is-active" : ""}`}
          onClick={() => setAgentsView("kanban")}
        >
          <LayoutGrid size={14} className="sb-row__icon" />
          <span className="sb-row__label">Task board</span>
        </button>
      </div>
      <button
        type="button"
        className="sb-action"
        onClick={() => window.dispatchEvent(new CustomEvent("palimind:new-agent"))}
      >
        <Plus size={13} />
        <span>New agent</span>
      </button>
    </div>
  );

  const projectsSection = (
    <div className="sb-section">
      <div className="sb-section-head">
        <span className="sb-section-title sb-collapsible">Research</span>
      </div>
      <EmptyState
        compact
        icon={<FolderKanban size={18} />}
        title="Persistent projects"
        description="Collect notes, findings and sources in one research workspace."
        action={
          <button type="button" className="sb-action" onClick={openResearch}>
            <FolderKanban size={13} />
            <span>Open projects</span>
          </button>
        }
      />
    </div>
  );

  return (
    <aside className="sidebar" id="main-sidebar" aria-label="Primary navigation">
      <div className="sb-header">
        <div className="sb-brand">
          <span className="sb-wordmark sb-collapsible">Palimind</span>
        </div>
        <button
          type="button"
          className="sb-icon-btn"
          title={`${sidebarCollapsed ? "Expand" : "Collapse"} sidebar (${shortcutFor("view.toggle-sidebar")})`}
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={toggleSidebar}
        >
          {sidebarCollapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
        </button>
      </div>

      <button
        type="button"
        className="sb-search"
        onClick={() => setCommandPaletteOpen(true)}
        title={`Search or run a command (${shortcutFor("general.palette")})`}
        aria-label="Open command palette"
      >
        <Search size={14} />
        <span className="sb-search__label sb-collapsible">Search or run…</span>
        <Kbd className="sb-search__kbd sb-collapsible">{shortcutFor("general.palette")}</Kbd>
      </button>

      <nav className="sb-nav" aria-label="Workspace">
        {navItems.map((item) => {
          const Icon = item.icon;
          const shortcut = shortcutFor(item.shortcutId);
          return (
            <button
              key={item.id}
              type="button"
              className={`sb-nav-item${item.active ? " is-active" : ""}`}
              aria-current={item.active ? "page" : undefined}
              aria-expanded={item.id === "projects" ? researchOpen : undefined}
              title={shortcut ? `${item.label} (${shortcut})` : item.label}
              onClick={() => {
                item.onSelect();
                if (window.matchMedia("(max-width: 900px)").matches) {
                  setSidebarCollapsed(true);
                }
              }}
            >
              <span className="sb-nav-item__icon">
                <Icon size={16} />
              </span>
              <span className="sb-nav-item__label sb-collapsible">{item.label}</span>
              {shortcut && (
                <Kbd className="sb-nav-item__kbd sb-collapsible">{shortcut}</Kbd>
              )}
            </button>
          );
        })}
      </nav>

      <Scrollbar className="sb-context">
        {activeView === "chat" && sessionsSection}
        {activeView === "fields" && (
          <>
            {knowledgeSection}
            {sessionsSection}
          </>
        )}
        {activeView === "agents" && agentsSection}
        {researchOpen && projectsSection}
      </Scrollbar>

      <div className="sb-footer">
        <div className="sb-user">
          <Avatar name="Local workspace" size="sm" tone="accent" status="online" />
          <div className="sb-user__meta sb-collapsible">
            <span className="sb-user__name">Local workspace</span>
            <span className="sb-user__hint">Offline · private</span>
          </div>
          <button
            type="button"
            className="sb-icon-btn sb-collapsible"
            title={`Switch to ${theme === "dark" ? "light" : "dark"} theme (${shortcutFor("view.toggle-theme")})`}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          <button
            type="button"
            className="sb-icon-btn"
            title={`Settings (${shortcutFor("general.settings")})`}
            aria-label="Open settings"
            onClick={openSettings}
          >
            <Settings size={15} />
          </button>
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
                aria-label="Close"
              >
                <X size={15} />
              </button>
            </div>
            <div className="modal-body file-tree-modal-body">
              <FileTreeView modal />
            </div>
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
