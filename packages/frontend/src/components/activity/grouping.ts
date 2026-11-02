import type { ActivityState, ToolStep } from './model';

export interface TimelineUnit {
  key: string;
  kind: 'step' | 'browser' | 'parallel';
  steps: ToolStep[];
}

/** Merge browser steps into one card and completed parallel calls into one row. */
export function unitsOf(steps: readonly ToolStep[]): TimelineUnit[] {
  const units: TimelineUnit[] = [];
  const consumed = new Set<string>();
  for (const step of steps) {
    if (consumed.has(step.id)) continue;
    if (step.groupKey) {
      const group = steps.filter((entry) => entry.groupKey === step.groupKey);
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
  return units;
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
