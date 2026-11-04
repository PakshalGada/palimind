/**
 * Caption derivation — the one string the caption row, the composer line and
 * the aria-live region all render. Pure and synchronous so every consumer
 * selects a primitive and re-renders only when the string itself changes.
 *
 * Priority (see spec §3.3):
 *   1. pending approval          → "Needs approval"
 *   2. the current running tool  → "Searching arxiv.org"
 *   3. the last phase event      → "Searching"
 *   4. reasoning in flight       → "Thinking"
 *   5. settled                   → "Thought for 8s · 3 tools · 2 sources"
 *   6. any errored step          → "Failed — 2 steps"
 *   7. stopped                   → "Stopped"
 */

import {
  elapsedMs,
  errorCount,
  formatRunDuration,
  hasPendingApproval,
  isTerminal,
  type ActivityState,
  type RunPhase,
  type ToolStep,
} from './model';
import { getToolDefinition, hostOf, previewForTool } from './toolRegistry';
import { maskSecrets } from './grant';

export type CaptionKind =
  | 'approval'
  | 'running'
  | 'phase'
  | 'reasoning'
  | 'settled'
  | 'failed'
  | 'stopped';

export interface Caption {
  kind: CaptionKind;
  text: string;
  /** True while the run is live; drives the breathing dot and the one shimmer. */
  live: boolean;
  /** True when at least one step errored. */
  error: boolean;
  /** Id of the step the caption is about, when there is one. */
  stepId?: string;
}

const PHASE_CAPTION: Record<RunPhase, string> = {
  routing: 'Routing',
  searching: 'Searching',
  reading: 'Reading',
  analyzing: 'Analyzing',
  synthesizing: 'Combining',
  writing: 'Writing',
};

function runningStep(state: ActivityState): ToolStep | undefined {
  return state.steps.find((step) => step.status === 'running');
}

function settledCaption(state: ActivityState): string {
  if (state.mode === 'knowledge_base' && state.passages.length === 0 && state.sources.length === 0) {
    return 'Not found in your documents';
  }
  const reasoning = state.reasoning;
  const duration = reasoning?.durationMs;
  const parts: string[] = [];
  if (reasoning?.done && duration != null) {
    parts.push(`Thought for ${formatRunDuration(duration)}`);
  } else if (state.endedAt != null) {
    parts.push(`Worked for ${formatRunDuration(elapsedMs(state))}`);
  } else {
    parts.push('Worked');
  }
  const tools = state.steps.length;
  if (tools > 0) parts.push(`${tools} ${tools === 1 ? 'tool' : 'tools'}`);
  const sources = state.sources.length;
  if (sources > 0) parts.push(`${sources} ${sources === 1 ? 'source' : 'sources'}`);
  else if (state.passages.length > 0) {
    parts.push(`${state.passages.length} ${state.passages.length === 1 ? 'passage' : 'passages'}`);
  }
  return parts.join(' · ');
}

export function captionFor(state: ActivityState): Caption {
  const terminal = isTerminal(state.status);
  const errors = errorCount(state);

  if (hasPendingApproval(state)) {
    const step = state.steps.find((entry) => entry.status === 'awaiting_approval');
    return { kind: 'approval', text: 'Needs approval', live: true, error: errors > 0, stepId: step?.id };
  }

  if (!terminal) {
    const running = runningStep(state);
    if (running) {
      const definition = getToolDefinition(running.name);
      const preview = previewForTool(running.name, running.args);
      const safePreview = definition.approval ? maskSecrets(preview) : preview;
      const live = running.status === 'running';
      const base = safePreview ? `${definition.running} ${safePreview}` : definition.running;
      return { kind: 'running', text: base, live, error: errors > 0, stepId: running.id };
    }
    if (state.phase) {
      return { kind: 'phase', text: PHASE_CAPTION[state.phase], live: true, error: errors > 0 };
    }
    if (state.reasoning && !state.reasoning.done) {
      return { kind: 'reasoning', text: 'Thinking', live: true, error: errors > 0 };
    }
    if (state.status === 'thinking') {
      return { kind: 'reasoning', text: 'Thinking', live: true, error: errors > 0 };
    }
    // Nothing pending yet — optimistic preamble.
    return { kind: 'reasoning', text: 'Working', live: true, error: errors > 0 };
  }

  if (state.status === 'stopped') {
    return { kind: 'stopped', text: 'Stopped', live: false, error: false };
  }
  if (state.status === 'error' || errors > 0) {
    const text =
      errors === 1 ? 'Failed — 1 step' : errors > 1 ? `Failed — ${errors} steps` : 'Failed';
    return { kind: 'failed', text, live: false, error: true };
  }
  return { kind: 'settled', text: settledCaption(state), live: false, error: false };
}

/** The caption string alone — what the composer line and aria-live print. */
export function captionText(state: ActivityState | null): string {
  if (!state) return '';
  return captionFor(state).text;
}

/** Host used by "Searching arxiv.org" style captions; undefined when not a URL. */
export function captionHost(url: string): string | undefined {
  const host = hostOf(url);
  return host || undefined;
}
