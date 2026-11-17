/**
 * Prompt library helpers.
 *
 * A prompt is a reusable template saved by the user (backend /api/prompts).
 * `{variables}` inside the template are filled in by the composer before the
 * message is sent, so a saved prompt can adapt to each use.
 */
import type { SlashCommand } from './slashCommands';

export interface PromptTemplate {
  id: string;
  name: string;
  /** Slug used in the slash command, without the leading `/`. */
  command: string;
  template: string;
  description?: string;
  created_at?: number;
}

/** `{name}` — a letter, then letters/digits/dashes. */
const VARIABLE_PATTERN = /\{([A-Za-z][\w-]*)\}/g;

/** Unique variable names in the order they first appear. */
export function templateVariables(template: string): string[] {
  const seen = new Set<string>();
  for (const match of template.matchAll(VARIABLE_PATTERN)) seen.add(match[1]);
  return [...seen];
}

/**
 * Fill variables from `values`; variables with no value are left as
 * `{name}` so the user can still spot and edit them in the composer.
 */
export function renderPromptTemplate(
  template: string,
  values: Record<string, string>,
): string {
  return template.replace(VARIABLE_PATTERN, (whole, name: string) => {
    const value = values[name];
    return value && value.trim() ? value : whole;
  });
}

/** Check whether every variable has a value (used to enable the confirm button). */
export function promptVariablesFilled(
  template: string,
  values: Record<string, string>,
): boolean {
  return templateVariables(template).every((name) => Boolean(values[name]?.trim()));
}

/** Map a saved prompt onto a composer slash command entry. */
export function promptToSlashCommand(prompt: PromptTemplate): SlashCommand {
  return {
    id: `prompt:${prompt.id}`,
    command: `/${prompt.command}`,
    label: prompt.name,
    description:
      prompt.description?.trim() || prompt.template.replace(/\s+/g, ' ').slice(0, 80),
    keywords: ['prompt', 'saved', 'template', 'library'],
    promptId: prompt.id,
    template: prompt.template,
  };
}
