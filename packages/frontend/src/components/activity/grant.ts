/**
 * Pure helpers for the approval receipt — kept out of the .tsx so unit tests
 * can import them directly.
 */

import { previewForTool } from './toolRegistry';
import type { ToolStep } from './model';

export type GrantDecision = 'once' | 'run' | 'deny';

/* ── plain-English action line ─────────────────────────────────────────── */

function str(args: unknown, keys: readonly string[]): string {
  if (!args || typeof args !== 'object') return '';
  const record = args as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number') return String(value);
  }
  return '';
}

function truncated(text: string, max: number): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

function host(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, '');
  } catch {
    return truncated(url, 48);
  }
}

/**
 * One-line, plain-English description of what approving would do, e.g.
 * "Write src/agents/runtime.ts", "Run npm test", "Click \"Sign in\" on example.com".
 */
export function plainAction(step: ToolStep): string {
  const args = step.args;
  const path = str(args, ['path', 'file', 'filepath', 'file_path', 'filename']);
  switch (step.name) {
    case 'write_file':
      return path ? `Write ${path}` : 'Write file';
    case 'search_replace':
      return path ? `Edit ${path}` : 'Edit file';
    case 'run_shell': {
      const command = str(args, ['command', 'cmd', 'shell']);
      return command ? `Run ${truncated(command, 72)}` : 'Run command';
    }
    case 'run_python': {
      const code = str(args, ['code', 'source', 'script']);
      const first = code.split('\n').find((line) => line.trim()) ?? '';
      return first ? `Run ${truncated(first, 72)}` : 'Run Python';
    }
    case 'browser_open':
      return `Open ${host(str(args, ['url', 'uri', 'href', 'link']) || 'page')}`;
    case 'browser_click':
    case 'browser_press': {
      const label = str(args, ['label', 'element', 'selector', 'name', 'ref']);
      const domain = host(str(args, ['url', 'domain', 'page']) || '');
      const action = step.name === 'browser_click' ? 'Click' : 'Press';
      if (label && domain) return `${action} "${truncated(label, 48)}" on ${domain}`;
      if (label) return `${action} "${truncated(label, 48)}"`;
      return action;
    }
    case 'browser_type': {
      const label = str(args, ['label', 'element', 'selector', 'name', 'ref']);
      const domain = host(str(args, ['url', 'domain', 'page']) || '');
      if (label && domain) return `Type into "${truncated(label, 48)}" on ${domain}`;
      if (label) return `Type into "${truncated(label, 48)}"`;
      return 'Type into page';
    }
    default: {
      const preview = previewForTool(step.name, args);
      return preview ? truncated(preview, 72) : 'Run tool';
    }
  }
}

/* ── secret masking ────────────────────────────────────────────────────── */

const KEY_VALUE =
  /((?:password|passwd|pwd|secret|token|api[-_]?key|auth(?:orization)?|access[-_]?key|client[-_]?secret|private[-_]?key)(?:["']?\s*[:=]\s*["']?|\s+))([^\s"';&|,}]+)/gi;
const FLAG_VALUE =
  /(--(?:password|passwd|pwd|secret|token|api[-_]?key|auth|access[-_]?key|private[-_]?key)(?:=|\s+))([^\s"'`;&|,}]+)/gi;
const BEARER = /(bearer\s+)([A-Za-z0-9._~+/=-]{8,})/gi;
const QUOTED_ASSIGN =
  /((?:password|passwd|pwd|secret|token|api[-_]?key|access[-_]?key|client[-_]?secret|private[-_]?key)\s*=\s*)(["'])([^"'\n]{4,})\2/gi;

/** Replace secret-looking values with a fixed mask. Display only. */
export function maskSecrets(text: string): string {
  return text
    .replace(QUOTED_ASSIGN, '$1$2••••••••$2')
    .replace(FLAG_VALUE, '$1••••••••')
    .replace(KEY_VALUE, '$1••••••••')
    .replace(BEARER, '$1••••••••');
}

/* ── destructive heuristic ─────────────────────────────────────────────── */

const DESTRUCTIVE = [
  /\brm\s+-[a-z]*[rf]/i,
  /\bsudo\b/i,
  /\bmkfs\b/i,
  /\bdd\s+if=/i,
  /\bshutdown\b|\breboot\b/i,
  /\bchmod\s+-R\s+777/i,
  /curl[^|]*\|\s*(sh|bash|zsh)/i,
  /wget[^|]*\|\s*(sh|bash|zsh)/i,
  />\s*\/(etc|usr|bin|sbin|var|boot)\//i,
  /\b(format|fdisk|parted)\b/i,
];

export function isDestructiveCommand(command: string): boolean {
  return DESTRUCTIVE.some((pattern) => pattern.test(command));
}

/** True for writes aimed outside a typical workspace (absolute or parent-relative). */
export function writesOutsideWorkspace(step: ToolStep): boolean {
  const path = str(step.args, ['path', 'file', 'filepath', 'file_path', 'filename']);
  if (!path) return false;
  return /^(\/|[A-Za-z]:\\|\\\\|\.\.[\\/])/.test(path.trim());
}

export function destructiveReason(step: ToolStep): string | null {
  const command = str(step.args, ['command', 'cmd', 'shell']);
  if (command && isDestructiveCommand(command)) return 'Review carefully';
  if (writesOutsideWorkspace(step)) return 'Review carefully';
  return null;
}

/* ── keyboard resolution ───────────────────────────────────────────────── */

export interface GrantKeyEvent {
  key: string;
  /** True when the event originated on an interactive control. */
  targetIsButton: boolean;
}

/**
 * Map a keypress inside the approval card to a decision.
 * Enter activates the card's default action (allow once) unless the focus is
 * on a button, where the button's own activation wins. `A` and `Esc` work
 * regardless of focus so the three decisions are always one key away.
 */
export function grantDecisionForKey(event: GrantKeyEvent): GrantDecision | null {
  if (event.key === 'Escape') return 'deny';
  if (event.key === 'Enter' && !event.targetIsButton) return 'once';
  const key = event.key.toLowerCase();
  if (key === 'a') return 'run';
  return null;
}
