import type { CreateArtifactKind } from './artifactPrompts';

/**
 * Composer slash commands.
 *
 * Typing `/` at the start of a message (or after whitespace) opens this menu;
 * typing more characters filters it. Commands that create an artifact open the
 * topic dialog with the right type already selected.
 */
export type SlashCommandId =
  | 'doc'
  | 'slides'
  | 'page'
  | 'code'
  | 'default'
  | 'moe'
  | 'research'
  | 'web';

export interface SlashCommand {
  id: SlashCommandId;
  command: string;
  label: string;
  description: string;
  keywords?: string[];
  /** Artifact type to pre-select in the create dialog. */
  artifact?: CreateArtifactKind;
  /** LLM mode to switch to. */
  mode?: 'default' | 'moe' | 'deep_research';
  /** Toggle live web search. */
  toggleWeb?: boolean;
}

export const SLASH_COMMANDS: readonly SlashCommand[] = [
  {
    id: 'doc',
    command: '/doc',
    label: 'Document',
    description: 'Write a structured Markdown document',
    keywords: ['write', 'markdown', 'report', 'article'],
    artifact: 'document',
  },
  {
    id: 'slides',
    command: '/slides',
    label: 'Slide deck',
    description: 'Build a presentation with real slide preview and PPTX export',
    keywords: ['deck', 'presentation', 'powerpoint', 'pptx'],
    artifact: 'slides',
  },
  {
    id: 'page',
    command: '/page',
    label: 'Web page',
    description: 'Create a self-contained HTML page',
    keywords: ['html', 'landing', 'site', 'website'],
    artifact: 'webpage',
  },
  {
    id: 'code',
    command: '/code',
    label: 'Code file',
    description: 'Write a complete source file',
    keywords: ['program', 'script', 'file'],
    artifact: 'code',
  },
  {
    id: 'default',
    command: '/default',
    label: 'Default mode',
    description: 'Single-model chat',
    keywords: ['chat', 'single', 'llm'],
    mode: 'default',
  },
  {
    id: 'moe',
    command: '/moe',
    label: 'Mixture of Experts',
    description: 'Parallel expert agents with tools',
    keywords: ['experts', 'parallel', 'agents'],
    mode: 'moe',
  },
  {
    id: 'research',
    command: '/research',
    label: 'Deep Research',
    description: 'Plan, research and write a cited report',
    keywords: ['deep', 'report', 'sources', 'investigate'],
    mode: 'deep_research',
  },
  {
    id: 'web',
    command: '/web',
    label: 'Toggle web search',
    description: 'Turn live web search on or off',
    keywords: ['internet', 'search', 'online'],
    toggleWeb: true,
  },
];

export interface SlashToken {
  query: string;
  /** Index of the `/`. */
  start: number;
  /** Index just after the typed command text. */
  end: number;
}

export function findSlashToken(text: string, cursor = text.length): SlashToken | null {
  const upto = text.slice(0, Math.max(0, Math.min(cursor, text.length)));
  const match = /(^|\s)\/([\w-]*)$/.exec(upto);
  if (!match) return null;
  const start = upto.length - match[2].length - 1;
  return { query: match[2], start, end: upto.length };
}

export function filterSlashCommands(query: string): SlashCommand[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...SLASH_COMMANDS];
  return SLASH_COMMANDS.filter((item) => {
    const haystack = [item.command.slice(1), item.label, item.description, ...(item.keywords ?? [])]
      .join(' ')
      .toLowerCase();
    return haystack.includes(needle);
  });
}

/** Remove the typed slash token before running the command. */
export function stripSlashToken(text: string, token: SlashToken): string {
  return `${text.slice(0, token.start)}${text.slice(token.end)}`.replace(/\s{2,}/g, ' ').trim();
}
