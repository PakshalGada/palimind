/**
 * The single normalized model every activity surface renders. The adapter and
 * reducer own these types; UI components never read raw backend payloads.
 */

export type RunMode = 'default' | 'moe' | 'deep_research' | 'agent' | 'knowledge_base';

export type RunStatus =
  | 'idle'
  | 'thinking'
  | 'working'
  | 'awaiting_approval'
  | 'awaiting_input'
  | 'done'
  | 'stopped'
  | 'error';

export type ToolStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'success'
  | 'error'
  | 'denied'
  | 'cancelled';

export type PlanStatus = 'pending' | 'running' | 'done' | 'error';

export type RunPhase = 'routing' | 'searching' | 'reading' | 'analyzing' | 'synthesizing' | 'writing';

export type ToolFamily =
  | 'search'
  | 'page'
  | 'feed'
  | 'file'
  | 'tree'
  | 'matches'
  | 'diff'
  | 'passages'
  | 'graph'
  | 'data'
  | 'code-run'
  | 'text'
  | 'subagent'
  | 'browser'
  | 'iot'
  | 'weather'
  | 'visual'
  | 'generic';

export interface ApprovalMeta {
  agentId: string;
  runId?: string;
  tool: string;
  args?: unknown;
}

export interface ToolStep {
  id: string;
  name: string;
  status: ToolStatus;
  args: unknown;
  output?: unknown;
  /** Key into the append-only buffer registry for streamed text. */
  streamedOutputRef?: string;
  error?: string;
  startedAt?: number;
  endedAt?: number;
  durationMs?: number;
  /** Delegate nesting. */
  parentId?: string;
  /** Browser session grouping. */
  groupKey?: string;
  approval?: ApprovalMeta;
  /** Last streamed delta ordinal, used to drop duplicates. */
  seq?: number;
}

export interface ResultMeta {
  authors?: string[];
  year?: number;
  venue?: string;
  citations?: number;
  stars?: number;
  points?: number;
  comments?: number;
  form?: string;
  filer?: string;
  date?: string;
  size?: number;
  status?: number;
  pages?: number;
}

export interface ResultItem {
  id: string;
  title: string;
  url?: string;
  domain?: string;
  snippet?: string;
  /** Citation marker, when the item came from a citation payload. */
  marker?: number;
  meta?: ResultMeta;
}

export interface Passage {
  id: string;
  docId: string;
  docName: string;
  page?: number;
  text: string;
  score?: number;
  marker?: number;
}

export interface PlanStep {
  id: string;
  label: string;
  status: PlanStatus;
}

/** A mid-run question the agent is blocked on. */
export interface QuestionState {
  id: string;
  text: string;
  options: string[];
  allowFreeText: boolean;
  status: 'pending' | 'answered' | 'timeout' | 'cancelled';
  answer?: string;
}

export interface Expert {
  id: string;
  name: string;
  status: 'running' | 'done';
  snippet?: string;
}

export interface ReasoningState {
  text: string;
  done: boolean;
  startedAt?: number;
  durationMs?: number;
  seq?: number;
}

export interface ActivityState {
  runId: string;
  mode: RunMode;
  status: RunStatus;
  startedAt: number;
  endedAt?: number;
  title?: string;
  reasoning?: ReasoningState;
  plan?: PlanStep[];
  question?: QuestionState;
  phase?: RunPhase;
  experts?: Expert[];
  steps: ToolStep[];
  sources: ResultItem[];
  passages: Passage[];
  /** True once the first answer token has arrived. */
  answerStarted: boolean;
  error?: string;
}

export type ActivityEvent =
  | { type: 'run.start'; runId: string; mode: RunMode; startedAt: number; title?: string }
  | { type: 'run.end'; status: 'done' | 'stopped' | 'error'; at?: number; error?: string }
  | { type: 'run.error'; message: string; at?: number }
  | { type: 'text.delta'; text?: string }
  | { type: 'reasoning.delta'; text: string; seq?: number; at?: number }
  | { type: 'reasoning.end'; at?: number }
  | {
      type: 'plan.set';
      steps: readonly { id: string; label: string; status?: PlanStatus }[];
    }
  | { type: 'plan.step'; id: string; status: PlanStatus }
  | { type: 'plan.edit'; steps: readonly { id: string; label: string; status?: PlanStatus }[] }
  | {
      type: 'question.set';
      question: QuestionState;
    }
  | {
      type: 'question.answer';
      status: 'answered' | 'timeout' | 'cancelled';
      answer?: string;
    }
  | { type: 'phase'; phase: RunPhase }
  | { type: 'expert.start'; id: string; name: string }
  | { type: 'expert.delta'; id: string; text: string }
  | { type: 'expert.end'; id: string }
  | {
      type: 'tool.start';
      id?: string;
      name: string;
      args?: unknown;
      parentId?: string;
      groupKey?: string;
      approval?: ApprovalMeta;
      awaitingApproval?: boolean;
      startedAt?: number;
    }
  | { type: 'tool.delta'; id: string; text: string; seq?: number }
  | {
      type: 'tool.end';
      id: string;
      name?: string;
      status: 'success' | 'error' | 'cancelled' | 'denied';
      output?: unknown;
      error?: string;
      at?: number;
    }
  | {
      type: 'tool.approval';
      id: string;
      status: 'awaiting_approval' | 'running' | 'denied' | 'cancelled';
      at?: number;
    }
  | { type: 'source.add'; item: ResultItem }
  | { type: 'retrieval.result'; passages: readonly Passage[] };

export type ActivityCollapsePref = 'auto' | 'expanded' | 'collapsed';

export interface ActivitySettings {
  collapse: ActivityCollapsePref;
  timeline: 'rail' | 'gantt';
}

export const ACTIVITY_SETTINGS_KEY = 'palimind:activity-settings';

export const DEFAULT_SETTINGS: ActivitySettings = { collapse: 'auto', timeline: 'rail' };

export function loadActivitySettings(): ActivitySettings {
  if (typeof localStorage === 'undefined') return DEFAULT_SETTINGS;
  try {
    const raw = localStorage.getItem(ACTIVITY_SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<ActivitySettings>;
    const collapse =
      parsed.collapse === 'expanded' || parsed.collapse === 'collapsed' ? parsed.collapse : 'auto';
    const timeline = parsed.timeline === 'gantt' ? 'gantt' : 'rail';
    return { collapse, timeline };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveActivitySettings(settings: ActivitySettings): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(ACTIVITY_SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Storage can be unavailable in private windows; settings stay in memory.
  }
}

export function emptyActivity(runId: string, mode: RunMode = 'default', startedAt = 0): ActivityState {
  return {
    runId,
    mode,
    status: 'thinking',
    startedAt,
    steps: [],
    sources: [],
    passages: [],
    answerStarted: false,
  };
}

export const TERMINAL_STATUSES: ReadonlySet<RunStatus> = new Set([
  'done',
  'stopped',
  'error',
]);

export function isTerminal(status: RunStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

export function hasPendingApproval(state: ActivityState): boolean {
  return state.steps.some((step) => step.status === 'awaiting_approval');
}

export function hasPendingQuestion(state: ActivityState): boolean {
  return state.question?.status === 'pending';
}

export function errorCount(state: ActivityState): number {
  return state.steps.filter((step) => step.status === 'error').length;
}

export function runningToolCount(state: ActivityState): number {
  return state.steps.filter((step) => step.status === 'running').length;
}

/** "8s", "1m 12s". Whole seconds, tabular-friendly. */
export function formatRunDuration(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${minutes}m` : `${minutes}m ${rest}s`;
}

/** "1.2s" under ten seconds, then "12s", "1m 4s". Used by row badges. */
export function formatToolDuration(ms: number): string {
  if (ms < 10_000) return `${(Math.max(0, ms) / 1000).toFixed(1)}s`;
  return formatRunDuration(ms);
}

export function elapsedMs(state: ActivityState, now = Date.now()): number {
  return Math.max(0, (state.endedAt ?? now) - state.startedAt);
}
