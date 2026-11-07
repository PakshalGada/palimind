import type { ActivityMode, ActivityState as LegacyActivity, ActivityStep } from '../../AppContext';
import type { CitationPayload } from '../../types';
import type { MediaCitation, StreamState, TextCitation } from '../../stream/types';
import {
  emptyActivity,
  type ActivityState,
  type Passage,
  type ResultItem,
  type RunMode,
  type RunStatus,
  type ToolStep,
} from './model';
import { resultsFromSources } from './recorder';
import { normalizeToolName } from './toolRegistry';

export function modeFromActivityMode(mode: ActivityMode | string | null | undefined): RunMode {
  if (mode === 'document') return 'knowledge_base';
  if (mode === 'moe') return 'moe';
  if (mode === 'deep_research') return 'deep_research';
  if (mode === 'agent') return 'agent';
  return 'default';
}

export function modeFromSubMode(subMode: string | null | undefined): RunMode {
  if (subMode === 'moe') return 'moe';
  if (subMode === 'deep_research') return 'deep_research';
  return 'default';
}

export interface AdaptRunInput {
  runId: string;
  mode: RunMode;
  startedAt: number;
  status: RunStatus;
  endedAt?: number;
  answerStarted?: boolean;
  thinking?: string;
  /** Legacy tracker state, used for history and as a live fallback. */
  legacy?: LegacyActivity | null;
  citations?: CitationPayload | null;
  textCitations?: readonly TextCitation[];
  mediaCitations?: readonly MediaCitation[];
  stream?: Pick<StreamState, 'thinking' | 'status' | 'startedAt' | 'answerStarted'>;
}

function parseLegacyArgs(step: ActivityStep): unknown {
  if (!step.detail) return {};
  try {
    return JSON.parse(step.detail);
  } catch {
    return { command: step.detail };
  }
}

function stepFromLegacy(step: ActivityStep): ToolStep {
  return {
    id: step.id,
    name: normalizeToolName(step.tool || step.title),
    status:
      step.status === 'active'
        ? 'running'
        : step.status === 'error'
          ? 'error'
          : step.status === 'pending'
            ? 'queued'
            : 'success',
    args: parseLegacyArgs(step),
    output: step.result,
    startedAt: step.startedAt,
    endedAt: step.completedAt,
    durationMs:
      step.startedAt != null && step.completedAt != null
        ? Math.max(0, step.completedAt - step.startedAt)
        : undefined,
  };
}

/**
 * One adapter from stream fields and legacy parts to the normalized model.
 * Live runs are normally recorded event by event; this is the deterministic
 * path for history, reloads and agents whose traces were persisted.
 */
export function adaptRun(input: AdaptRunInput): ActivityState {
  const startedAt = input.startedAt || (input.stream?.startedAt ?? Date.now());
  const state: ActivityState = {
    ...emptyActivity(input.runId, input.mode, startedAt),
    status: input.status,
    endedAt: input.endedAt,
    answerStarted: input.answerStarted ?? input.stream?.answerStarted ?? false,
  };

  const legacySteps = input.legacy?.steps ?? [];
  const toolSteps = legacySteps.filter((step) => step.kind === 'tool').map(stepFromLegacy);
  const thoughtText = legacySteps
    .filter((step) => step.kind === 'thought' || step.kind === 'reason')
    .map((step) => step.detail || '')
    .filter(Boolean)
    .join('\n\n');
  const thinking = input.thinking ?? input.stream?.thinking ?? thoughtText;
  if (thinking) {
    state.reasoning = {
      text: thinking,
      done: input.status !== 'thinking' && input.status !== 'working',
      startedAt,
      durationMs: input.endedAt != null ? Math.max(0, input.endedAt - startedAt) : undefined,
    };
  }
  state.steps = toolSteps;

  const citations = input.citations ?? null;
  const { sources, passages } = resultsFromSources(
    citations,
    input.textCitations ?? [],
    input.mediaCitations ?? [],
  );
  state.sources = mergeItems(state.sources, sources);
  state.passages = mergePassages(state.passages, passages);
  return state;
}

function mergeItems(base: readonly ResultItem[], extra: readonly ResultItem[]): ResultItem[] {
  const seen = new Set(base.map((item) => item.id));
  return [...base, ...extra.filter((item) => !seen.has(item.id))];
}

function mergePassages(base: readonly Passage[], extra: readonly Passage[]): Passage[] {
  const seen = new Set(base.map((item) => item.id));
  return [...base, ...extra.filter((item) => !seen.has(item.id))];
}

/** Build tool rows from a persisted agent trace (Inspector history). */
export function stepsFromTrace(
  trace: readonly { type: string; tool?: string; args?: unknown; result?: unknown }[],
): ToolStep[] {
  const steps: ToolStep[] = [];
  let pending: ToolStep | null = null;
  trace.forEach((event, index) => {
    if (event.type === 'agent:tool_call' && typeof event.tool === 'string') {
      pending = {
        id: `${event.tool}-${index}`,
        name: normalizeToolName(event.tool),
        status: 'running',
        args: event.args,
      };
      steps.push(pending);
      return;
    }
    if (event.type === 'agent:tool_result' && pending) {
      pending.status =
        typeof event.result === 'string' && /^error:/i.test(event.result) ? 'error' : 'success';
      pending.output = event.result;
      pending = null;
    }
  });
  return steps;
}
