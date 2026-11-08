import {
  emptyActivity,
  isTerminal,
  type ActivityEvent,
  type ActivityState,
  type Expert,
  type PlanStep,
  type ToolStep,
} from './model';

const MAX_EXPERT_SNIPPET = 4_000;

function withStep(steps: readonly ToolStep[], step: ToolStep): ToolStep[] {
  const index = steps.findIndex((entry) => entry.id === step.id);
  if (index === -1) return [...steps, step];
  const next = [...steps];
  next[index] = step;
  return next;
}

function findStep(steps: readonly ToolStep[], id: string): ToolStep | undefined {
  return steps.find((step) => step.id === id);
}

function deriveStatus(state: ActivityState): ActivityState['status'] {
  if (isTerminal(state.status)) return state.status;
  if (state.steps.some((step) => step.status === 'awaiting_approval')) return 'awaiting_approval';
  if (state.question?.status === 'pending') return 'awaiting_input';
  if (state.steps.some((step) => step.status === 'running' || step.status === 'queued')) {
    return 'working';
  }
  if (state.answerStarted) return 'working';
  return state.status === 'idle' ? 'thinking' : state.status;
}

/** Pure, idempotent, tolerant of duplicate and out-of-order events. */
export function reduceActivity(state: ActivityState, event: ActivityEvent): ActivityState {
  switch (event.type) {
    case 'run.start': {
      if (state.runId === event.runId && state.status !== 'idle') return state;
      return {
        ...emptyActivity(event.runId, event.mode, event.startedAt),
        title: event.title,
      };
    }

    case 'run.end': {
      if (isTerminal(state.status)) return state;
      return settleRun(state, event.status, event.at ?? undefined, event.error ?? state.error);
    }

    case 'run.error': {
      if (state.status === 'error' && state.error === event.message) return state;
      // An error event arrives before the stream's run.end, which is then a
      // no-op: settle in-flight work here so nothing spins after the failure.
      const settled = isTerminal(state.status)
        ? state
        : settleRun(state, 'error', event.at ?? undefined, event.message);
      return {
        ...settled,
        status: 'error',
        error: event.message,
        endedAt: event.at ?? settled.endedAt,
      };
    }

    case 'text.delta': {
      if (state.answerStarted) return state;
      return { ...state, answerStarted: true, status: deriveStatus({ ...state, answerStarted: true }) };
    }

    case 'reasoning.delta': {
      const reasoning = state.reasoning;
      if (event.seq != null && reasoning?.seq != null && event.seq <= reasoning.seq) return state;
      // Reasoning text lives in the append-only buffer outside React state;
      // state only carries start/done/duration. `text` in the event is
      // tolerated for backwards compatibility and ignored here.
      const startedAt = reasoning?.startedAt ?? event.at;
      const seq = event.seq ?? reasoning?.seq;
      if (reasoning && startedAt === reasoning.startedAt && seq === reasoning.seq) {
        return state;
      }
      return {
        ...state,
        status: deriveStatus(state),
        reasoning: {
          text: reasoning?.text ?? '',
          done: false,
          startedAt,
          seq,
        },
      };
    }

    case 'reasoning.end': {
      const reasoning = state.reasoning;
      if (!reasoning || reasoning.done) return state;
      return {
        ...state,
        reasoning: {
          ...reasoning,
          done: true,
          durationMs:
            reasoning.durationMs ??
            (reasoning.startedAt != null && event.at != null
              ? Math.max(0, event.at - reasoning.startedAt)
              : undefined),
        },
      };
    }

    case 'plan.set': {
      const previous = new Map((state.plan ?? []).map((step) => [step.id, step.status]));
      const plan: PlanStep[] = event.steps.map((step) => ({
        id: step.id,
        label: step.label,
        status: step.status ?? previous.get(step.id) ?? 'pending',
      }));
      return { ...state, plan, status: deriveStatus(state) };
    }

    case 'plan.edit': {
      const previous = new Map((state.plan ?? []).map((step) => [step.id, step.status]));
      const plan: PlanStep[] = event.steps.map((step) => ({
        id: step.id,
        label: step.label,
        status: step.status ?? previous.get(step.id) ?? 'pending',
      }));
      return { ...state, plan, status: deriveStatus({ ...state, plan }) };
    }

    case 'question.set': {
      return {
        ...state,
        question: event.question,
        status: deriveStatus({ ...state, question: event.question }),
      };
    }

    case 'question.answer': {
      const question = state.question;
      if (!question) return state;
      if (question.status !== 'pending') return state;
      const next = {
        ...state,
        question: { ...question, status: event.status, answer: event.answer ?? question.answer },
      };
      return { ...next, status: deriveStatus(next) };
    }

    case 'plan.step': {
      const plan = state.plan ?? [];
      const index = plan.findIndex((step) => step.id === event.id);
      if (index === -1) {
        return {
          ...state,
          plan: [...plan, { id: event.id, label: event.id, status: event.status }],
        };
      }
      if (plan[index].status === event.status) return state;
      const next = [...plan];
      next[index] = { ...next[index], status: event.status };
      return { ...state, plan: next };
    }

    case 'phase':
      if (state.phase === event.phase) return state;
      return { ...state, phase: event.phase };

    case 'expert.start': {
      const experts = state.experts ?? [];
      const existing = experts.find((expert) => expert.id === event.id);
      if (existing) {
        if (existing.name === event.name && existing.status === 'running') return state;
        return {
          ...state,
          experts: experts.map((expert) =>
            expert.id === event.id ? { ...expert, name: event.name } : expert,
          ),
        };
      }
      const expert: Expert = { id: event.id, name: event.name, status: 'running' };
      return { ...state, experts: [...experts, expert], status: deriveStatus({ ...state, status: 'working' }) };
    }

    case 'expert.delta': {
      const experts = state.experts ?? [];
      const index = experts.findIndex((expert) => expert.id === event.id);
      if (index === -1) {
        const expert: Expert = {
          id: event.id,
          name: event.id,
          status: 'running',
          snippet: event.text.slice(0, MAX_EXPERT_SNIPPET),
        };
        return { ...state, experts: [...experts, expert] };
      }
      const snippet = (experts[index].snippet ?? '') + event.text;
      const next = [...experts];
      next[index] = {
        ...experts[index],
        snippet: snippet.length > MAX_EXPERT_SNIPPET ? snippet.slice(-MAX_EXPERT_SNIPPET) : snippet,
      };
      return { ...state, experts: next };
    }

    case 'expert.end': {
      const experts = state.experts ?? [];
      const expert = experts.find((entry) => entry.id === event.id);
      if (!expert || expert.status === 'done') return state;
      return {
        ...state,
        experts: experts.map((entry) =>
          entry.id === event.id ? { ...entry, status: 'done' } : entry,
        ),
      };
    }

    case 'tool.start': {
      const existing = findStep(state.steps, event.id ?? '');
      if (existing) {
        // A duplicate start never downgrades a settled or running step. An
        // out-of-order start older than the stored one is ignored.
        // A running step may still pause for approval (call-then-gate).
        if (
          isTerminal(state.status) ||
          (existing.status === 'running' && !event.awaitingApproval) ||
          (existing.status === 'awaiting_approval' && event.awaitingApproval) ||
          isTerminalTool(existing) ||
          (existing.startedAt != null &&
            event.startedAt != null &&
            event.startedAt < existing.startedAt)
        ) {
          return state;
        }
      }
      const id = event.id ?? `tool-${state.steps.length + 1}`;
      const step: ToolStep = existing
        ? {
            ...existing,
            status: 'running',
            name: event.name || existing.name,
            args: event.args ?? existing.args,
            parentId: event.parentId ?? existing.parentId,
            groupKey: event.groupKey ?? existing.groupKey,
            startedAt: existing.startedAt ?? event.startedAt,
            approval: event.approval ?? existing.approval,
          }
        : {
            id,
            name: event.name,
            status: event.awaitingApproval ? 'awaiting_approval' : 'running',
            args: event.args,
            startedAt: event.startedAt,
            parentId: event.parentId,
            groupKey: event.groupKey,
            approval: event.approval,
          };
      if (event.awaitingApproval) step.status = 'awaiting_approval';
      const next = { ...state, steps: withStep(state.steps, step) };
      return { ...next, status: deriveStatus(next) };
    }

    case 'tool.delta': {
      const step = findStep(state.steps, event.id);
      if (!step || step.streamedOutputRef) return state;
      return {
        ...state,
        steps: withStep(state.steps, {
          ...step,
          seq: event.seq ?? step.seq,
          streamedOutputRef: `tool:${step.id}`,
        }),
      };
    }

    case 'tool.end': {
      const existing = findStep(state.steps, event.id);
      const at = event.at ?? undefined;
      if (existing && isTerminalTool(existing)) {
        // Late duplicate end: keep the first terminal state but fill output.
        if (existing.output === undefined && event.output !== undefined) {
          return {
            ...state,
            steps: withStep(state.steps, { ...existing, output: event.output }),
          };
        }
        return state;
      }
      const step: ToolStep = {
        id: event.id,
        name: existing?.name ?? event.name ?? event.id,
        status: event.status,
        args: existing?.args,
        output: event.output ?? existing?.output,
        streamedOutputRef: existing?.streamedOutputRef,
        error: event.error,
        startedAt: existing?.startedAt,
        endedAt: at,
        durationMs:
          existing?.startedAt != null && at != null
            ? Math.max(0, at - existing.startedAt)
            : existing?.durationMs,
        parentId: existing?.parentId,
        groupKey: existing?.groupKey,
        approval: existing?.approval,
        seq: existing?.seq,
      };
      const next = { ...state, steps: withStep(state.steps, step) };
      return { ...next, status: deriveStatus(next) };
    }

    case 'tool.approval': {
      const step = findStep(state.steps, event.id);
      if (!step || step.status === event.status) return state;
      if (step.status === 'success' || step.status === 'error') return state;
      const next = {
        ...state,
        steps: withStep(state.steps, {
          ...step,
          status: event.status,
          endedAt:
            event.status === 'cancelled' || event.status === 'denied'
              ? (event.at ?? step.endedAt)
              : step.endedAt,
        }),
      };
      return { ...next, status: deriveStatus(next) };
    }

    case 'source.add': {
      if (state.sources.some((item) => item.id === event.item.id)) return state;
      return { ...state, sources: [...state.sources, event.item] };
    }

    case 'retrieval.result': {
      const known = new Set(state.passages.map((passage) => passage.id));
      const fresh = event.passages.filter((passage) => !known.has(passage.id));
      if (fresh.length === 0) return state;
      return { ...state, passages: [...state.passages, ...fresh] };
    }

    default:
      return state;
  }
}

function isTerminalTool(step: ToolStep): boolean {
  return (
    step.status === 'success' ||
    step.status === 'error' ||
    step.status === 'denied' ||
    step.status === 'cancelled'
  );
}

/** Settle a run: finish reasoning and stop every step, plan item and expert
 *  that was still in flight so no spinner or timer outlives the run. */
function settleRun(
  state: ActivityState,
  status: 'done' | 'stopped' | 'error',
  at: number | undefined,
  error: string | undefined,
): ActivityState {
  return {
    ...state,
    status,
    endedAt: at,
    error,
    reasoning: state.reasoning
      ? {
          ...state.reasoning,
          done: true,
          durationMs:
            state.reasoning.durationMs ??
            (state.reasoning.startedAt != null && at != null
              ? Math.max(0, at - state.reasoning.startedAt)
              : undefined),
        }
      : undefined,
    steps: state.steps.map((step) =>
      step.status === 'running' || step.status === 'queued'
        ? { ...step, status: status === 'error' ? 'error' : 'cancelled', endedAt: at ?? step.endedAt }
        : step.status === 'awaiting_approval'
          ? // The run ended while the request was pending: cancel it so the
            // receipt never pulses forever.
            { ...step, status: 'cancelled', endedAt: at ?? step.endedAt }
          : step,
    ),
    plan: state.plan?.map((step) =>
      step.status === 'running'
        ? { ...step, status: status === 'done' ? 'done' : status === 'error' ? 'error' : 'pending' }
        : step,
    ),
    question:
      state.question?.status === 'pending'
        ? { ...state.question, status: 'cancelled' }
        : state.question,
    experts: state.experts?.map((expert) =>
      expert.status === 'running' ? { ...expert, status: 'done' } : expert,
    ),
  };
}

/** Apply a batch, returning the same reference when nothing changed. */
export function reduceEvents(
  state: ActivityState,
  events: readonly ActivityEvent[],
): ActivityState {
  let next = state;
  for (const event of events) next = reduceActivity(next, event);
  return next;
}
