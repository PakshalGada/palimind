import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ArrowRight, Clock, CornerDownLeft, Search } from 'lucide-react';
import { useApp } from '../AppContext';
import { api } from '../api';
import { VISIBLE_COMMANDS } from '../commands/catalog';
import { CommandIconView } from '../commands/icons';
import { runCommand } from '../commands/registry';
import { useAvailableCommands, useCommandRegistryVersion } from '../commands/useCommand';
import { formatShortcut } from '../utils/shortcuts';
import { fuzzyRank } from '../utils/fuzzy';
import type { AgentListItem, TreeNode } from '../types';
import './CommandPalette.css';

const RECENT_KEY = 'palimind:command-recent';
const MAX_RECENT = 6;

type PaletteKind = 'command' | 'agent' | 'session' | 'file';

interface PaletteItem {
  key: string;
  kind: PaletteKind;
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  shortcut?: string;
  disabled?: boolean;
  run: () => void;
}

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : [];
  } catch {
    return [];
  }
}

function pushRecent(key: string): string[] {
  const next = [key, ...loadRecent().filter((k) => k !== key)].slice(0, MAX_RECENT);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // ignore
  }
  return next;
}

function flattenFiles(nodes: TreeNode[], out: TreeNode[] = []): TreeNode[] {
  for (const node of nodes) {
    if (node.type === 'file') out.push(node);
    if (node.children?.length) flattenFiles(node.children, out);
  }
  return out;
}

export default function CommandPalette() {
  const {
    commandPaletteOpen,
    setCommandPaletteOpen,
    activeView,
    activeField,
    selectedAgentId,
    setSelectedAgentId,
    setActiveView,
    sessions,
    activeSessionId,
    setSessions,
    setActiveSessionId,
    addToast,
  } = useApp();

  const isAvailable = useAvailableCommands();
  const commandVersion = useCommandRegistryVersion();
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [files, setFiles] = useState<TreeNode[]>([]);
  const [recent, setRecent] = useState<string[]>(() => loadRecent());

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const scope =
    activeView === 'agents'
      ? selectedAgentId
        ? `agent:${selectedAgentId}`
        : ''
      : activeView === 'chat'
        ? 'chat'
        : 'field';

  const close = useCallback(() => {
    setCommandPaletteOpen(false);
  }, [setCommandPaletteOpen]);

  const remember = useCallback((key: string) => {
    setRecent(pushRecent(key));
  }, []);

  // Reset and load data each time the palette opens.
  useEffect(() => {
    if (!commandPaletteOpen) return;
    setQuery('');
    setActiveIndex(0);
    setRecent(loadRecent());
    api.agents
      .list()
      .then((d) => setAgents(d.agents || []))
      .catch(() => setAgents([]));
    if (activeField) {
      api.files
        .tree()
        .then((d) => setFiles(flattenFiles(d.tree || [])))
        .catch(() => setFiles([]));
    } else {
      setFiles([]);
    }
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [commandPaletteOpen, activeField]);

  const items = useMemo<PaletteItem[]>(() => {
    // Referenced so the list recomputes when handlers register/unregister.
    void commandVersion;
    const list: PaletteItem[] = [];

    for (const cmd of VISIBLE_COMMANDS) {
      const available = isAvailable(cmd.id);
      list.push({
        key: `command:${cmd.id}`,
        kind: 'command',
        title: cmd.title,
        subtitle: cmd.description ?? cmd.category,
        icon: <CommandIconView icon={cmd.icon} size={16} />,
        shortcut: cmd.defaultShortcut ? formatShortcut(cmd.defaultShortcut) : undefined,
        disabled: !available,
        run: () => {
          if (!runCommand(cmd.id)) addToast('That action is not available right now.');
        },
      });
    }

    for (const agent of agents) {
      list.push({
        key: `agent:${agent.id}`,
        kind: 'agent',
        title: agent.name,
        subtitle: agent.running ? 'Agent · running' : 'Agent',
        icon: <CommandIconView icon="bot" size={16} />,
        run: () => {
          setActiveView('agents');
          setSelectedAgentId(agent.id);
        },
      });
    }

    for (const session of sessions) {
      list.push({
        key: `session:${session.id}`,
        kind: 'session',
        title: session.name,
        subtitle: session.id === activeSessionId ? 'Session · current' : 'Session',
        icon: <CommandIconView icon="message" size={16} />,
        run: () => {
          if (session.id === activeSessionId) return;
          api.sessions
            .setActive(session.id, scope)
            .then((data) => {
              if (data.error) {
                addToast(data.error);
                return;
              }
              setSessions(data.sessions as typeof sessions);
              setActiveSessionId(data.active_session_id);
            })
            .catch(() => addToast('Could not switch session'));
        },
      });
    }

    for (const file of files) {
      list.push({
        key: `file:${file.path}`,
        kind: 'file',
        title: file.name,
        subtitle: file.path,
        icon: <CommandIconView icon="canvas" size={16} />,
        run: () => window.dispatchEvent(new CustomEvent('palimind:open-file-tree')),
      });
    }

    return list;
  }, [
    agents,
    sessions,
    files,
    activeSessionId,
    scope,
    isAvailable,
    commandVersion,
    addToast,
    setActiveView,
    setSelectedAgentId,
    setSessions,
    setActiveSessionId,
  ]);

  const groups = useMemo(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      const result: { label: string; items: PaletteItem[] }[] = [];
      const recentItems = recent
        .map((key) => items.find((i) => i.key === key))
        .filter((i): i is PaletteItem => Boolean(i));
      if (recentItems.length) result.push({ label: 'Recent', items: recentItems });
      const commands = items.filter((i) => i.kind === 'command');
      if (commands.length) result.push({ label: 'Commands', items: commands });
      const agentItems = items.filter((i) => i.kind === 'agent').slice(0, 8);
      if (agentItems.length) result.push({ label: 'Agents', items: agentItems });
      const sessionItems = items.filter((i) => i.kind === 'session').slice(0, 8);
      if (sessionItems.length) result.push({ label: 'Sessions', items: sessionItems });
      return result;
    }

    const ranked = fuzzyRank(items, trimmed, (i) => [i.title, i.subtitle ?? '', i.kind]);
    return [{ label: 'Results', items: ranked.map((r) => r.item) }];
  }, [query, items, recent]);

  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  // Clamp the highlight whenever the result set changes.
  useEffect(() => {
    setActiveIndex((i) => (flat.length === 0 ? 0 : Math.min(i, flat.length - 1)));
  }, [flat.length]);

  const execute = useCallback(
    (item: PaletteItem | undefined) => {
      if (!item) return;
      if (item.disabled) {
        addToast('That action is not available right now.');
        return;
      }
      remember(item.key);
      close();
      // Run after the palette unmounts so focus returns to the app first.
      requestAnimationFrame(() => item.run());
    },
    [addToast, close, remember],
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => (flat.length === 0 ? 0 : (i + 1) % flat.length));
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => (flat.length === 0 ? 0 : (i - 1 + flat.length) % flat.length));
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      execute(flat[activeIndex]);
    }
  };

  // Keep the highlighted row in view.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  if (!commandPaletteOpen) return null;

  let runningIndex = -1;
  return (
    <div className="command-palette-overlay" onMouseDown={close} role="presentation">
      <div
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="command-palette-input-row">
          <Search size={17} strokeWidth={2} className="command-palette-search-icon" />
          <input
            ref={inputRef}
            className="command-palette-input"
            placeholder="Search commands, agents, sessions, files…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={onKeyDown}
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="command-palette-esc">Esc</kbd>
        </div>

        <div className="command-palette-list" ref={listRef} role="listbox">
          {flat.length === 0 && <div className="command-palette-empty">No matching results.</div>}
          {groups.map((group) => (
            <div key={group.label} className="command-palette-group">
              <div className="command-palette-group-label">
                {group.label === 'Recent' ? <Clock size={12} /> : null}
                {group.label}
              </div>
              {group.items.map((item) => {
                runningIndex += 1;
                const index = runningIndex;
                const active = index === activeIndex;
                return (
                  <button
                    key={item.key}
                    type="button"
                    data-index={index}
                    role="option"
                    aria-selected={active}
                    className={`command-palette-item${active ? ' is-active' : ''}${item.disabled ? ' is-disabled' : ''}`}
                    onMouseEnter={() => setActiveIndex(index)}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      execute(item);
                    }}
                  >
                    <span className="command-palette-item-icon">{item.icon}</span>
                    <span className="command-palette-item-text">
                      <span className="command-palette-item-title">{item.title}</span>
                      {item.subtitle && (
                        <span className="command-palette-item-subtitle">{item.subtitle}</span>
                      )}
                    </span>
                    {item.kind !== 'command' && (
                      <span className="command-palette-item-kind">{item.kind}</span>
                    )}
                    {item.shortcut && <kbd className="command-palette-item-kbd">{item.shortcut}</kbd>}
                    {active && !item.shortcut && (
                      <ArrowRight size={14} className="command-palette-item-enter" />
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        <div className="command-palette-footer">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> navigate
          </span>
          <span>
            <CornerDownLeft size={11} /> select
          </span>
          <span>
            <kbd>Ctrl</kbd>+<kbd>K</kbd> close
          </span>
        </div>
      </div>
    </div>
  );
}
