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
  | 'docx'
  | 'pptx'
  | 'page'
  | 'code'
  | 'default'
  | 'moe'
  | 'research';

export interface SlashCommand {
  /** Built-in id or `skill:<skill-id>` for an installed skill. */
  id: string;
  command: string;
  label: string;
  description: string;
  keywords?: string[];
  /** Artifact kind this skill produces. */
  artifact?: CreateArtifactKind;
  /** Backend skill whose detailed instructions power this command. */
  skillId?: string;
  /** LLM mode to switch to. */
  mode?: 'default' | 'moe' | 'deep_research';
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
    id: 'docx',
    command: '/docx',
    label: 'Word document',
    description: 'Write a detailed document and download a real .docx file',
    keywords: ['word', 'document', 'office', 'download'],
    artifact: 'word',
    skillId: 'document-docx',
  },
  {
    id: 'pptx',
    command: '/pptx',
    label: 'PowerPoint deck',
    description: 'Build a designed deck with preview and download a real .pptx file',
    keywords: ['deck', 'presentation', 'powerpoint', 'office', 'slides', 'slide'],
    artifact: 'pptx',
    skillId: 'presentation-pptx',
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

export function filterSlashCommands(
  query: string,
  commands: readonly SlashCommand[] = SLASH_COMMANDS,
): SlashCommand[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...commands];
  const matches = commands.filter((item) => {
    const haystack = [item.command.slice(1), item.label, item.description, ...(item.keywords ?? [])]
      .join(' ')
      .toLowerCase();
    return haystack.includes(needle);
  });
  // The command whose name is exactly what was typed must be the default
  // selection, even when other commands share its keywords.
  const exact = matches.find((item) => item.command.slice(1).toLowerCase() === needle);
  return exact ? [exact, ...matches.filter((item) => item.id !== exact.id)] : matches;
}

/** Remove the typed slash token before running the command. */
export function stripSlashToken(text: string, token: SlashToken): string {
  return `${text.slice(0, token.start)}${text.slice(token.end)}`.replace(/\s{2,}/g, ' ').trim();
}

/**
 * Resolve a fully typed command such as ``/pptx Q3 review`` even after the
 * slash menu has closed. Only artifact-producing skills are returned; mode
 * commands keep their normal inline behavior.
 */
export function parseArtifactCommand(
  text: string,
  commands: readonly SlashCommand[] = SLASH_COMMANDS,
): { command: SlashCommand; query: string } | null {
  const match = /^\/([A-Za-z0-9][\w-]*)\s+([\s\S]*)$/.exec(text.trim());
  if (!match) return null;
  const command = commands.find(
    (item) => item.command.toLowerCase() === `/${match[1].toLowerCase()}`,
  );
  if (!command?.artifact && !command?.skillId) return null;
  return { command, query: match[2].trim() };
}
