import type { ActivityState, ToolStep } from './model';
import { getToolDefinition } from './toolRegistry';

export type StepIntent = 'research' | 'writing' | 'running';

export interface TimelineUnit {
  key: string;
  kind: 'step' | 'browser' | 'parallel' | 'cluster';
  steps: ToolStep[];
  /** Set only on cluster units. */
  intent?: StepIntent;
}

/** Main intent of a step, or undefined when it does not cluster. */
export function intentOf(step: ToolStep): StepIntent | undefined {
  if (step.groupKey || step.parentId) return undefined;
  const name = step.name;
  if (name === 'write_file' || name === 'search_replace') return 'writing';
  if (name === 'run_python' || name === 'run_shell') return 'running';
  const family = getToolDefinition(name).family;
  if (family === 'code-run') return 'running';
  // Research: searches, fetched pages, feeds and knowledge lookups.
  if (family === 'search' || family === 'page' || family === 'feed') return 'research';
  if (family === 'passages' || family === 'graph') return 'research';
  if (/^(fetch|browse|read_pdf|rss|wikipedia)/.test(name)) return 'research';
  return undefined;
}

function awaiting(step: ToolStep): boolean {
  return step.status === 'awaiting_approval';
}

/** Merge browser steps into one card and completed parallel calls into one row. */
export function unitsOf(steps: readonly ToolStep[]): TimelineUnit[] {
  const units: TimelineUnit[] = [];
  const consumed = new Set<string>();
  for (const step of steps) {
    if (consumed.has(step.id)) continue;
    // A pending approval always stays its own row so its prompt is never
    // folded inside a collapsed browser card or cluster.
    if (step.groupKey && !awaiting(step)) {
      const group = steps.filter(
        (entry) => entry.groupKey === step.groupKey && !awaiting(entry),
      );
      group.forEach((entry) => consumed.add(entry.id));
      units.push({ key: step.groupKey, kind: 'browser', steps: group });
      continue;
    }
    if (step.startedAt != null && step.status === 'success') {
      const stepEnd = step.endedAt ?? step.startedAt + (step.durationMs ?? 0);
      const parallel = steps.filter((entry) => {
        if (
          entry.id === step.id ||
          entry.groupKey ||
          consumed.has(entry.id) ||
          entry.status !== 'success' ||
          entry.startedAt == null
        ) {
          return false;
        }
        const entryEnd = entry.endedAt ?? entry.startedAt + (entry.durationMs ?? 0);
        const closeInTime = Math.abs(entry.startedAt - step.startedAt!) < 600;
        const overlap = entry.startedAt < stepEnd && step.startedAt! < entryEnd;
        return closeInTime && overlap;
      });
      if (parallel.length > 0) {
        [step, ...parallel].forEach((entry) => consumed.add(entry.id));
        units.push({ key: `parallel-${step.id}`, kind: 'parallel', steps: [step, ...parallel] });
        continue;
      }
    }
    consumed.add(step.id);
    units.push({ key: step.id, kind: 'step', steps: [step] });
  }
  return clusterIntents(units);
}

/**
 * Fold consecutive same-intent units into one disclosure row. A parallel unit
 * counts as its members when every member shares the intent, so a burst of
 * three searches still reads "Searched 3 sources".
 */
function clusterIntents(units: readonly TimelineUnit[]): TimelineUnit[] {
  const result: TimelineUnit[] = [];
  let pending: { intent: StepIntent; steps: ToolStep[] } | null = null;

  const flush = () => {
    if (!pending) return;
    if (pending.steps.length >= 2) {
      result.push({
        key: `cluster-${pending.steps[0].id}`,
        kind: 'cluster',
        intent: pending.intent,
        steps: pending.steps,
      });
    } else {
      result.push({ key: pending.steps[0].id, kind: 'step', steps: pending.steps });
    }
    pending = null;
  };

  const intentOfUnit = (unit: TimelineUnit): StepIntent | undefined => {
    // Browser cards and "Ran N tools" parallel rows keep their own identity.
    if (unit.kind !== 'step' || unit.steps.some(awaiting)) return undefined;
    const intents = unit.steps.map(intentOf);
    if (intents.some((intent) => intent === undefined)) return undefined;
    return intents[0];
  };

  for (const unit of units) {
    const intent = intentOfUnit(unit);
    if (intent === undefined) {
      flush();
      result.push(unit);
      continue;
    }
    if (pending && pending.intent === intent) {
      pending.steps = [...pending.steps, ...unit.steps];
      continue;
    }
    flush();
    pending = { intent, steps: [...unit.steps] };
  }
  flush();
  return result;
}

/** Wall-clock span of the steps, falling back to the sum of durations. */
export function spanOf(steps: readonly ToolStep[]): number | undefined {
  const starts = steps
    .map((step) => step.startedAt)
    .filter((value): value is number => value != null);
  if (starts.length === 0) {
    const total = steps.reduce((sum, step) => sum + (step.durationMs ?? 0), 0);
    return total > 0 ? total : undefined;
  }
  const ends = steps.map((step) => {
    if (step.endedAt != null) return step.endedAt;
    if (step.startedAt != null) return step.startedAt + (step.durationMs ?? 0);
    return step.startedAt ?? 0;
  });
  return Math.max(0, Math.max(...ends) - Math.min(...starts));
}

export function timelineOverlaps(steps: readonly ToolStep[]): boolean {
  const intervals = steps
    .filter((step) => step.startedAt != null)
    .map((step) => ({
      start: step.startedAt as number,
      end: step.endedAt ?? (step.startedAt as number) + (step.durationMs ?? 0),
    }));
  return intervals.some((left, index) =>
    intervals.slice(index + 1).some((right) => left.start < right.end && right.start < left.end),
  );
}

/** Direct children of a delegate step, in event order. */
export function childrenOf(state: ActivityState, parentId: string): ToolStep[] {
  return state.steps.filter((step) => step.parentId === parentId);
}

/** Nesting depth of a step, used to cap delegate recursion. */
export function depthOf(state: ActivityState, step: ToolStep): number {
  let depth = 0;
  let current = step;
  const seen = new Set<string>([step.id]);
  while (current.parentId) {
    if (seen.has(current.parentId)) break;
    seen.add(current.parentId);
    const parent = state.steps.find((entry) => entry.id === current.parentId);
    if (!parent) break;
    depth += 1;
    current = parent;
  }
  return depth;
}
