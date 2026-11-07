import type { CitationPayload, CitationSource } from '../../types';
import type { StreamEvent, TextCitation, MediaCitation } from '../../stream/types';
import {
  emptyActivity,
  type ActivityEvent,
  type ApprovalMeta,
  type Passage,
  type ResultItem,
  type RunMode,
  type RunPhase,
} from './model';
import { normalizeToolName } from './toolRegistry';
import { normalizePassages, normalizeResults } from './toolOutput';
import type { ActivityStore } from './store';

function hostOf(url: string): string | undefined {
  try {
    return new URL(url).host.replace(/^www\./, '');
  } catch {
    return undefined;
  }
}

function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

function parseArgs(args: unknown): unknown {
  if (typeof args !== 'string') return args;
  const trimmed = args.trim();
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return args;
  try {
    return JSON.parse(trimmed);
  } catch {
    return args;
  }
}

export function phaseFromText(text: string): RunPhase | undefined {
  const value = text.toLowerCase();
  if (/routing|classif|dispatch/.test(value)) return 'routing';
  if (/search|retriev|gather|look/.test(value)) return 'searching';
  if (/read|fetch|crawl|open |brows/.test(value)) return 'reading';
  if (/analy|verif|critique|review|reason/.test(value)) return 'analyzing';
  if (/synthesi|combin|merg/.test(value)) return 'synthesizing';
  if (/writ|generat|report|answer/.test(value)) return 'writing';
  return undefined;
}

export function resultsFromSources(
  citations: CitationPayload | null | undefined,
  textCitations: readonly TextCitation[] = [],
  mediaCitations: readonly MediaCitation[] = [],
): { sources: ResultItem[]; passages: Passage[] } {
  const sources: ResultItem[] = [];
  const passages: Passage[] = [];
  for (const source of citations?.sources ?? []) {
    pushCitationSource(sources, passages, source);
  }
  textCitations.forEach((citation, index) => {
    passages.push({
      id: `text-${citation.chunk_id ?? index}`,
      docId: citation.file,
      docName: baseName(citation.file),
      text: citation.snippet || citation.section || citation.file,
      page: undefined,
    });
  });
  mediaCitations.forEach((citation, index) => {
    sources.push({
      id: `media-${index}-${citation.start}`,
      title: `${baseName(citation.file)} at ${Math.floor(citation.start / 60)}:${String(
        Math.floor(citation.start % 60),
      ).padStart(2, '0')}`,
      domain: 'media',
      snippet: citation.snippet,
    });
  });
  return { sources, passages };
}

function pushCitationSource(
  sources: ResultItem[],
  passages: Passage[],
  source: CitationSource,
): void {
  if (source.kind === 'web' || source.url) {
    sources.push({
      id: `cite-${source.marker}`,
      title: source.title || hostOf(source.url) || 'Source',
      url: source.url || undefined,
      domain: source.url ? hostOf(source.url) : undefined,
      snippet: source.snippet || source.content || undefined,
      marker: source.marker,
    });
    return;
  }
  const docName = source.file || source.title || 'Document';
  passages.push({
    id: `cite-${source.marker}`,
    docId: docName,
    docName: baseName(docName),
    page: undefined,
    text: source.snippet || source.content || source.title || '',
    score: source.score || undefined,
    marker: source.marker,
  });
}

/**
 * Translates the backend SSE vocabulary into normalized activity events. This
 * is the only place that knows raw event names.
 */
export class RunRecorder {
  private seq = 0;
  private lastToolId: string | null = null;
  private lastToolName = '';
  /** Approval requested before its tool call (gate-then-call backends). */
  private pendingApproval: { id: string; name: string } | null = null;
  private browserGroup = 0;
  private groupOpen = false;
  private reasoningStartedAt: number | null = null;
  private readonly store: ActivityStore;
  private mode: RunMode;
  private answerStarted = false;

  constructor(store: ActivityStore, mode: RunMode) {
    this.store = store;
    this.mode = mode;
  }

  start(runId: string, title?: string): void {
    const startedAt = Date.now();
    this.reasoningStartedAt = startedAt;
    this.store.dispatch({ type: 'run.start', runId, mode: this.mode, startedAt, title });
  }

  end(status: 'done' | 'stopped' | 'error', error?: string): void {
    this.groupOpen = false;
    this.pendingApproval = null;
    if (this.mode === 'knowledge_base' && status === 'done' && this.store.getState()?.passages.length === 0) {
      this.store.dispatch({ type: 'phase', phase: 'searching' });
    }
    this.store.dispatch({ type: 'run.end', status, at: Date.now(), error });
  }

  setMode(mode: RunMode): void {
    this.mode = mode;
  }

  observe(event: StreamEvent): void {
    switch (event.type) {
      case 'reasoning':
        this.noteStatus(String(event.text ?? ''));
        break;

      case 'thinking': {
        const text = String(event.text ?? '').trim();
        if (!text) break;
        this.appendReasoning(`${text}\n`);
        break;
      }

      case 'progress':
        this.noteStatus(String(event.text ?? ''));
        break;

      case 'agent_progress': {
        const id = `expert-${event.agent_id}`;
        if ((event.status || 'working') === 'complete') {
          this.store.dispatch({ type: 'expert.end', id });
        } else {
          this.store.dispatch({
            type: 'expert.start',
            id,
            name: event.label || `Expert ${event.agent_id}`,
          });
          this.store.dispatch({ type: 'phase', phase: 'analyzing' });
        }
        const plan = this.store.getState()?.plan ?? [];
        if (plan.length) {
          // Plans come from MoE (`moe-1`) and deep research (`research-1`);
          // match the agent id through any of those prefixes.
          const target =
            plan.find((step) => step.id === `plan-${event.agent_id}`) ??
            plan.find((step) => step.id.endsWith(`-${event.agent_id}`));
          if (target) {
            this.store.dispatch({
              type: 'plan.step',
              id: target.id,
              status: (event.status || 'working') === 'complete' ? 'done' : 'running',
            });
          }
        }
        break;
      }

      case 'agent_thinking':
        this.store.dispatch({
          type: 'expert.delta',
          id: `expert-${event.agent_id}`,
          text: `${String(event.text ?? '')}\n`,
        });
        break;

      case 'agent:thought': {
        const text = String(event.text ?? '').replace(/\s+/g, ' ').trim();
        if (!text || text.startsWith('FINAL_ANSWER')) break;
        this.appendReasoning(`${text}\n`);
        break;
      }

      case 'agent:tool_call': {
        const name = normalizeToolName(String(event.tool || 'tool'));
        // The call that follows its own approval request continues that row
        // instead of opening a second one that the approval row shadows.
        const approved = this.pendingApproval?.name === name ? this.pendingApproval.id : null;
        this.pendingApproval = null;
        const id = approved ?? `tool-${(this.seq += 1)}`;
        this.lastToolId = id;
        this.lastToolName = name;
        const groupKey = name.startsWith('browser_') ? this.browserGroupKey() : undefined;
        if (!name.startsWith('browser_')) this.groupOpen = false;
        this.store.dispatch({
          type: 'tool.start',
          id,
          name,
          args: parseArgs(event.args),
          groupKey,
          startedAt: Date.now(),
        });
        this.store.dispatch({ type: 'phase', phase: phaseFromText(name) ?? 'analyzing' });
        break;
      }

      case 'agent:tool_result': {
        const toolName = normalizeToolName(String(event.tool || this.lastToolName || 'tool'));
        // Parallel tools finish out of order; match the result to the oldest
        // still-running row with the same tool name instead of whichever
        // call happened to start last.
        const running = (this.store.getState()?.steps ?? []).find(
          (step) => step.name === toolName && step.status === 'running',
        );
        const toolId = running?.id ?? this.lastToolId;
        if (!toolId) break;
        const status =
          typeof event.result === 'string' && /^error:/i.test(event.result.trim())
            ? 'error'
            : 'success';
        const output = parseArgs(event.result);
        this.store.dispatch({
          type: 'tool.end',
          id: toolId,
          name: toolName,
          status,
          output,
          error: status === 'error' ? String(event.result) : undefined,
          at: Date.now(),
        });
        if (status === 'success') this.ingestOutput(toolName, output, toolId);
        this.lastToolId = null;
        break;
      }

      case 'agent:waiting_for_human': {
        const name = normalizeToolName(String(event.tool || 'tool'));
        // Call-then-gate backends request approval for the tool that is
        // already running: pause that row rather than adding a new one.
        const current = this.lastToolId && this.lastToolName === name ? this.lastToolId : null;
        const id = current ?? `approval-${(this.seq += 1)}`;
        this.pendingApproval = current ? null : { id, name };
        const approval: ApprovalMeta = {
          agentId: String(event.agent_id ?? ''),
          runId: event.run_id ? String(event.run_id) : undefined,
          tool: name,
          args: parseArgs(event.args),
        };
        this.lastToolId = id;
        this.lastToolName = name;
        this.store.dispatch({
          type: 'tool.start',
          id,
          name,
          args: approval.args,
          approval,
          awaitingApproval: true,
          startedAt: Date.now(),
        });
        break;
      }

      case 'agent:todo': {
        const items = Array.isArray(event.items) ? event.items : [];
        this.store.dispatch({
          type: 'plan.set',
          steps: items.map((item, index) => {
            const status =
              item.status === 'completed'
                ? 'done'
                : item.status === 'in_progress'
                  ? 'running'
                  : 'pending';
            return {
              id: item.id || `todo-${index}`,
              label: item.label || `Step ${index + 1}`,
              status,
            };
          }),
        });
        break;
      }

      case 'agent:plan': {
        const steps = Array.isArray(event.steps) ? event.steps : [];
        this.store.dispatch({
          type: 'plan.set',
          steps: steps.map((step, index) => {
            if (typeof step === 'string') return { id: `plan-${index}`, label: step };
            if (step && typeof step === 'object') {
              const record = step as Record<string, unknown>;
              const label = record.label ?? record.title ?? record.task ?? record.step;
              return {
                id: String(record.id ?? `plan-${index}`),
                label: typeof label === 'string' ? label : `Step ${index + 1}`,
              };
            }
            return { id: `plan-${index}`, label: `Step ${index + 1}` };
          }),
        });
        break;
      }

      case 'research_plan': {
        // Deep research pauses for plan review: mirror the sub-topics into the
        // plan model so the activity panel shows the approved research plan.
        const plan = Array.isArray((event as { plan?: unknown[] }).plan)
          ? ((event as { plan?: unknown[] }).plan as unknown[])
          : [];
        this.store.dispatch({
          type: 'plan.set',
          steps: plan.map((item, index) => {
            const record = (item && typeof item === 'object' ? item : {}) as Record<
              string,
              unknown
            >;
            const label =
              (typeof record.title === 'string' && record.title) ||
              (typeof record.research_question === 'string' && record.research_question) ||
              `Research area ${index + 1}`;
            return { id: `research-${record.subtopic_id ?? index + 1}`, label };
          }),
        });
        this.store.dispatch({ type: 'phase', phase: 'routing' });
        break;
      }

      case 'sources': {
        (event.sources ?? []).forEach((source, index) => {
          this.store.dispatch({
            type: 'source.add',
            item: { id: `file-${index}-${source}`, title: baseName(source), domain: 'document' },
          });
        });
        break;
      }

      case 'media_citations': {
        (event.citations ?? []).forEach((citation, index) => {
          this.store.dispatch({
            type: 'source.add',
            item: {
              id: `media-${index}-${citation.start}`,
              title: `${baseName(citation.file)} at ${Math.floor(citation.start / 60)}:${String(
                Math.floor(citation.start % 60),
              ).padStart(2, '0')}`,
              domain: 'media',
              snippet: citation.snippet,
            },
          });
        });
        break;
      }

      case 'citations': {
        this.store.dispatch({
          type: 'retrieval.result',
          passages: (event.citations ?? []).map((citation) => ({
            id: `text-${citation.chunk_id ?? citation.file}`,
            docId: citation.file,
            docName: baseName(citation.file),
            text: citation.snippet || citation.section || citation.file,
          })),
        });
        break;
      }

      case 'citation_map': {
        const { sources, passages } = resultsFromSources(event as CitationPayload);
        for (const item of sources) this.store.dispatch({ type: 'source.add', item });
        if (passages.length) this.store.dispatch({ type: 'retrieval.result', passages });
        break;
      }

      case 'agent:token':
      case 'token':
        if ('reset' in event && event.reset) {
          this.beginAnswer();
          break;
        }
        this.beginAnswer();
        break;

      case 'agent:completed':
      case 'answer_final':
        this.beginAnswer();
        break;

      case 'agent:effort':
      case 'agent:needs_review':
      case 'agent:verification':
      case 'orchestrator':
        break;

      case 'error':
        this.store.dispatch({
          type: 'run.error',
          message: String(event.text ?? 'Unknown error'),
          at: Date.now(),
        });
        break;

      case 'done':
        break;

      default:
        break;
    }
  }

  beginAnswer(): void {
    if (this.answerStarted) return;
    this.answerStarted = true;
    this.store.dispatch({ type: 'text.delta' });
    this.store.dispatch({ type: 'reasoning.end', at: Date.now() });
  }

  private noteStatus(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    const phase = phaseFromText(trimmed);
    if (phase) this.store.dispatch({ type: 'phase', phase });
    if (this.mode === 'knowledge_base' || this.mode === 'moe' || this.mode === 'deep_research') {
      return;
    }
    this.appendReasoning(`${trimmed}\n`);
  }

  /** Reasoning text stays in an append-only buffer, never in React state. */
  private appendReasoning(text: string): void {
    const now = Date.now();
    this.reasoningStartedAt = this.reasoningStartedAt ?? now;
    const buffer = this.store.buffers.get('reasoning');
    buffer.append(text);
    if (!this.store.getState()?.reasoning) {
      this.store.dispatch({ type: 'reasoning.delta', text: '', at: now });
    }
  }

  private browserGroupKey(): string {
    if (!this.groupOpen) {
      this.groupOpen = true;
      this.browserGroup += 1;
    }
    return `browser-${this.browserGroup}`;
  }

  /** Search results and retrieved passages also feed citations and sources. */
  private ingestOutput(name: string, output: unknown, stepId: string): void {
    if (name === 'document_search' || name === 'memory_search') {
      const passages = normalizePassages(output);
      if (passages.length) this.store.dispatch({ type: 'retrieval.result', passages });
      return;
    }
    if (!name.endsWith('_search') && name !== 'fetch_url' && name !== 'browse_url') return;
    const results = normalizeResults(output);
    for (const item of results) {
      if (!item.url) continue;
      this.store.dispatch({
        type: 'source.add',
        item: { ...item, id: `${stepId}-${item.id}` },
      });
    }
  }
}

export function initialStateFor(mode: RunMode, runId: string): ActivityEvent {
  return { type: 'run.start', runId, mode, startedAt: Date.now() };
}

export { emptyActivity };
