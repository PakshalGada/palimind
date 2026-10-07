/**
 * Declarative catalog of every command in PaliMind.
 *
 * The catalog is intentionally static: it is the single source of truth shared
 * by the keyboard-shortcut system (1.3), the command palette (1.4) and the
 * per-message action toolbar (1.5). Actual behaviour is supplied at runtime by
 * components via `useCommandHandler` (see ./registry), which keeps this module
 * free of React and of any component-specific state.
 */

export type CommandCategory = 'Chat' | 'Navigation' | 'View' | 'Agents' | 'General';

/** Icon name resolved to a lucide-react component by consumers. */
export type CommandIcon =
  | 'plus'
  | 'message'
  | 'search'
  | 'command'
  | 'keyboard'
  | 'settings'
  | 'panel-left'
  | 'copy'
  | 'refresh'
  | 'square'
  | 'blocks'
  | 'canvas'
  | 'brain'
  | 'layers'
  | 'bot'
  | 'folder'
  | 'network'
  | 'sun'
  | 'sync'
  | 'model';

export interface CommandDef {
  /** Stable identifier, also used as the key for shortcut overrides. */
  id: string;
  /** Human-readable name shown in the palette and cheat sheet. */
  title: string;
  category: CommandCategory;
  description?: string;
  icon?: CommandIcon;
  /** Extra fuzzy-search terms. */
  keywords?: string[];
  /** Default binding, e.g. `Mod+K`. `Mod` = Ctrl (Cmd on macOS). */
  defaultShortcut?: string;
  /** Hidden commands never appear in the palette or cheat sheet. */
  hidden?: boolean;
}

export const COMMANDS: CommandDef[] = [
  // ── Chat ────────────────────────────────────────────────────────────
  {
    id: 'chat.new',
    title: 'New Chat',
    category: 'Chat',
    icon: 'plus',
    description: 'Start a fresh session in the current workspace',
    keywords: ['session', 'conversation', 'reset'],
    defaultShortcut: 'Mod+N',
  },
  {
    id: 'chat.copy-last',
    title: 'Copy Last Response',
    category: 'Chat',
    icon: 'copy',
    description: 'Copy the most recent assistant reply as Markdown',
    keywords: ['clipboard', 'markdown'],
    defaultShortcut: 'Mod+Shift+C',
  },
  {
    id: 'chat.regenerate',
    title: 'Regenerate Last Response',
    category: 'Chat',
    icon: 'refresh',
    description: 'Re-run the last user message',
    keywords: ['retry', 'again', 'rerun'],
    defaultShortcut: 'Mod+Shift+R',
  },
  {
    id: 'chat.stop',
    title: 'Stop Generating',
    category: 'Chat',
    icon: 'square',
    description: 'Abort the in-flight response',
    keywords: ['cancel', 'abort', 'halt'],
    defaultShortcut: 'Mod+Shift+S',
  },
  {
    id: 'chat.switch-model',
    title: 'Switch Model',
    category: 'Chat',
    icon: 'model',
    description: 'Open the model picker',
    keywords: ['llm', 'provider', 'ollama'],
    defaultShortcut: 'Mod+Shift+L',
  },
  {
    id: 'chat.attach',
    title: 'Attach Files',
    category: 'Chat',
    icon: 'folder',
    description: 'Focus the composer to drop attachments',
    keywords: ['upload', 'file', 'drop'],
  },
  {
    id: 'chat.toggle-mode',
    title: 'Toggle Document / LLM Mode',
    category: 'Chat',
    icon: 'layers',
    description: 'Switch between knowledge-base answers and direct chat',
    keywords: ['rag', 'knowledge', 'document', 'llm'],
  },

  // ── Navigation ──────────────────────────────────────────────────────
  {
    id: 'nav.chat',
    title: 'Go to Chat',
    category: 'Navigation',
    icon: 'message',
    keywords: ['llm', 'general'],
    defaultShortcut: 'Mod+1',
  },
  {
    id: 'nav.knowledge',
    title: 'Go to Knowledge Base',
    category: 'Navigation',
    icon: 'folder',
    keywords: ['documents', 'rag', 'fields', 'workspace'],
    defaultShortcut: 'Mod+2',
  },
  {
    id: 'nav.agents',
    title: 'Go to Agents',
    category: 'Navigation',
    icon: 'bot',
    keywords: ['automation', 'tools'],
    defaultShortcut: 'Mod+3',
  },
  {
    id: 'nav.graph',
    title: 'View Knowledge Graph',
    category: 'Navigation',
    icon: 'network',
    keywords: ['entities', 'relationships', 'visualise'],
    defaultShortcut: 'Mod+G',
  },
  {
    id: 'nav.sync',
    title: 'Sync Knowledge Base',
    category: 'Navigation',
    icon: 'sync',
    description: 'Index new and changed files',
    keywords: ['index', 'update', 'refresh'],
  },
  {
    id: 'nav.search',
    title: 'Search Knowledge Base',
    category: 'Navigation',
    icon: 'search',
    description: 'Open the command palette focused on search',
    keywords: ['find', 'query', 'lookup'],
    defaultShortcut: 'Mod+Shift+F',
  },
  {
    id: 'research.projects',
    title: 'Research Projects',
    category: 'Navigation',
    icon: 'brain',
    description: 'Persistent research workspaces with notes, findings and sources',
    keywords: ['projects', 'findings', 'sources', 'library', 'timeline'],
    defaultShortcut: 'Mod+Shift+P',
  },
  {
    id: 'research.compare',
    title: 'Compare Models',
    category: 'Navigation',
    icon: 'layers',
    description: 'Run the same research question across multiple models side by side',
    keywords: ['comparison', 'consensus', 'contradictions', 'models', 'multi-model'],
    defaultShortcut: 'Mod+Shift+K',
  },
  {
    id: 'research.social',
    title: 'X / Twitter Signals',
    category: 'Navigation',
    icon: 'network',
    description: 'Real-time social sentiment, trends and cited posts',
    keywords: ['twitter', 'social', 'sentiment', 'trends', 'x'],
  },

  // ── View ────────────────────────────────────────────────────────────
  {
    id: 'view.toggle-sidebar',
    title: 'Toggle Sidebar',
    category: 'View',
    icon: 'panel-left',
    keywords: ['collapse', 'hide', 'expand'],
    defaultShortcut: 'Mod+B',
  },
  {
    id: 'view.toggle-artifacts',
    title: 'Toggle Artifacts Panel',
    category: 'View',
    icon: 'blocks',
    description: 'Show or hide rich outputs (code, diagrams, HTML)',
    keywords: ['preview', 'code', 'mermaid', 'svg'],
    defaultShortcut: 'Mod+Shift+A',
  },
  {
    id: 'view.toggle-canvas',
    title: 'Toggle Canvas',
    category: 'View',
    icon: 'canvas',
    description: 'Open the side-by-side editing canvas',
    keywords: ['editor', 'document', 'write'],
    defaultShortcut: 'Mod+Shift+E',
  },
  {
    id: 'view.toggle-theme',
    title: 'Toggle Light / Dark Theme',
    category: 'View',
    icon: 'sun',
    keywords: ['appearance', 'dark', 'light'],
    defaultShortcut: 'Mod+Shift+D',
  },

  // ── Agents ──────────────────────────────────────────────────────────
  {
    id: 'agents.new',
    title: 'New Agent',
    category: 'Agents',
    icon: 'plus',
    description: 'Create a specialised agent',
    keywords: ['create', 'assistant'],
    defaultShortcut: 'Mod+Shift+N',
  },
  {
    id: 'agents.manage-memory',
    title: 'Manage Memory',
    category: 'Agents',
    icon: 'brain',
    description: 'Open the selected agent’s memory inspector',
    keywords: ['recall', 'forget', 'context'],
    defaultShortcut: 'Mod+Shift+M',
  },
  {
    id: 'agents.orchestrate',
    title: 'Multi-Agent Orchestration',
    category: 'Agents',
    icon: 'network',
    description: 'Fan out parallel agents and synthesise their results',
    keywords: ['parallel', 'fan-out', 'arena', 'swarm', 'synthesise'],
    defaultShortcut: 'Mod+Shift+O',
  },
  {
    id: 'agents.skills',
    title: 'Skill Manager',
    category: 'Agents',
    icon: 'blocks',
    description: 'Browse, create, install and share agent skills',
    keywords: ['slash', 'commands', 'marketplace', 'plugin'],
    defaultShortcut: 'Mod+Shift+I',
  },
  {
    id: 'agents.plans',
    title: 'Plan Review',
    category: 'Agents',
    icon: 'layers',
    description: 'Generate and approve a plan before the agent executes it',
    keywords: ['plan', 'approve', 'steps', 'rollback'],
  },
  {
    id: 'agents.tasks',
    title: 'Goals & Background Tasks',
    category: 'Agents',
    icon: 'bot',
    description: 'Monitor goals, scheduled runs and completion alerts',
    keywords: ['goals', 'loop', 'schedule', 'background', 'notifications'],
  },

  {
    id: 'workflows.builder',
    title: 'Workflow Builder',
    category: 'Agents',
    icon: 'blocks',
    description: 'Open the visual drag-and-drop workflow editor',
    keywords: ['workflow', 'canvas', 'nodes', 'pipeline', 'automation'],
  },
  {
    id: 'workflows.kanban',
    title: 'Task Board',
    category: 'Agents',
    icon: 'layers',
    description: 'Open the kanban task board for all agents',
    keywords: ['kanban', 'tasks', 'board', 'todo', 'progress'],
  },

  // ── General ─────────────────────────────────────────────────────────
  {
    id: 'general.palette',
    title: 'Open Command Palette',
    category: 'General',
    icon: 'command',
    description: 'Search every action, agent, session and file',
    keywords: ['run', 'actions', 'fuzzy'],
    defaultShortcut: 'Mod+K',
  },
  {
    id: 'general.shortcuts',
    title: 'Keyboard Shortcuts',
    category: 'General',
    icon: 'keyboard',
    description: 'View and customise key bindings',
    keywords: ['hotkeys', 'cheat sheet', 'bindings'],
    defaultShortcut: 'Mod+/',
  },
  {
    id: 'general.settings',
    title: 'Open Settings',
    category: 'General',
    icon: 'settings',
    keywords: ['preferences', 'config', 'options'],
    defaultShortcut: 'Mod+,',
  },
];

const BY_ID = new Map(COMMANDS.map((c) => [c.id, c]));

export function getCommand(id: string): CommandDef | undefined {
  return BY_ID.get(id);
}

export const COMMAND_CATEGORIES: CommandCategory[] = [
  'Chat',
  'Navigation',
  'View',
  'Agents',
  'General',
];

/** Catalog entries that should surface in the palette / cheat sheet. */
export const VISIBLE_COMMANDS = COMMANDS.filter((c) => !c.hidden);
