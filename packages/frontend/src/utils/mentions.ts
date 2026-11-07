/**
 * Agent @mention parsing for the composer.
 *
 * Mentions are recognized at the cursor (`@query` right before it) when the
 * `@` follows whitespace or the start of the message, so email addresses do
 * not open the picker.
 */

export interface MentionToken {
  /** Text typed after `@` (may be empty). */
  query: string;
  /** Index of the `@` character. */
  start: number;
  /** Index just after the last typed character. */
  end: number;
}

export function findMentionToken(text: string, cursor = text.length): MentionToken | null {
  const upto = text.slice(0, Math.max(0, Math.min(cursor, text.length)));
  const match = /(^|\s)@([\w-]*)$/.exec(upto);
  if (!match) return null;
  const start = upto.length - match[2].length - 1;
  return { query: match[2], start, end: upto.length };
}

/** Insert a chosen agent mention, replacing the typed query. */
export function applyMention(
  text: string,
  token: MentionToken,
  agentName: string,
): { text: string; cursor: number } {
  const before = text.slice(0, token.start);
  // The inserted mention already ends with a space, so drop any whitespace
  // that preceded the cursor to avoid a double space.
  const after = text.slice(token.end).replace(/^\s+/, '');
  const inserted = `@${agentName} `;
  return { text: `${before}${inserted}${after}`, cursor: before.length + inserted.length };
}

/** The first agent mention anywhere in a message (backend routing hint). */
export function firstAgentMention(text: string): string | null {
  const match = /(^|\s)@([\w-]+)/.exec(text);
  return match ? match[2] : null;
}
