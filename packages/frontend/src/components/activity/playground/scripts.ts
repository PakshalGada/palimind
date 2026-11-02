import type { ActivityEvent, Passage, ResultItem } from '../model';

export interface PlaygroundStep {
  at: number;
  event?: ActivityEvent;
  buffer?: { key: string; text: string };
}

export interface Scenario {
  id: string;
  label: string;
  answer: string;
  steps: PlaygroundStep[];
}

const web: ResultItem[] = [
  {
    id: 'w1',
    title: 'Scaling laws for retrieval augmented generation',
    url: 'https://arxiv.org/abs/2401.00001',
    domain: 'arxiv.org',
    snippet: 'We study how retrieval depth and context length interact in grounded generation.',
    meta: { authors: ['Ana Ruiz', 'Ken Ito'], year: 2024, citations: 128 },
  },
  {
    id: 'w2',
    title: 'A practical guide to agent tool approval',
    url: 'https://example.com/agents/approval',
    domain: 'example.com',
    snippet: 'Approval gates keep destructive tools reviewable without breaking flow.',
  },
];

const passages: Passage[] = [
  {
    id: 'p1',
    docId: 'notes/retrieval.md',
    docName: 'retrieval.md',
    page: 4,
    text: 'Hybrid search combines dense embeddings with BM25 keyword matching, then reranks the top candidates.',
    score: 0.91,
  },
  {
    id: 'p2',
    docId: 'notes/agents.md',
    docName: 'agents.md',
    page: 2,
    text: 'A tool approval should show the exact command, path, or browser element before it runs.',
    score: 0.84,
  },
  {
    id: 'p3',
    docId: 'notes/agents.md',
    docName: 'agents.md',
    page: 9,
    text: 'Browser sessions group navigation, clicks and screenshots into one reviewable card.',
    score: 0.77,
  },
  {
    id: 'p4',
    docId: 'notes/retrieval.md',
    docName: 'retrieval.md',
    page: 11,
    text: 'Passages keep their document, page and score so citations remain stable across reloads.',
    score: 0.66,
  },
];

function answerFor(topic: string): string {
  return `Here is the short answer on ${topic}.\n\nThe evidence points in one direction: retrieve a small set of high-quality passages, keep the process visible while it runs, then fold it away once the answer starts. Sources stay one click away.`;
}

export const SCENARIOS: Scenario[] = [  {
    id: 'default',
    label: 'Default with reasoning',
    answer: answerFor('retrieval'),
    steps: [
      { at: 0, event: { type: 'run.start', runId: 'pg-default', mode: 'default', startedAt: 0 } },
      { at: 200, event: { type: 'reasoning.delta', text: 'The user wants a concise explanation. ' } },
      { at: 500, event: { type: 'reasoning.delta', text: 'I should mention retrieval depth and reranking.\n' } },
      { at: 1200, event: { type: 'reasoning.delta', text: 'Check whether a citation would help here. ' } },
      { at: 1600, event: { type: 'reasoning.end' } },
      { at: 2200, event: { type: 'text.delta' } },
      { at: 2600, event: { type: 'run.end', status: 'done' } },
    ],
  },
  {
    id: 'moe',
    label: 'Mixture of experts',
    answer: answerFor('routing across experts'),
    steps: [
      { at: 0, event: { type: 'run.start', runId: 'pg-moe', mode: 'moe', startedAt: 0 } },
      { at: 200, event: { type: 'phase', phase: 'routing' } },
      { at: 600, event: { type: 'expert.start', id: 'e1', name: 'Retrieval expert' } },
      { at: 640, event: { type: 'expert.start', id: 'e2', name: 'Evaluation expert' } },
      { at: 680, event: { type: 'expert.start', id: 'e3', name: 'Systems expert' } },
      { at: 1100, event: { type: 'expert.delta', id: 'e1', text: 'Hybrid retrieval beats either half alone.\n' } },
      { at: 1500, event: { type: 'expert.delta', id: 'e2', text: 'Rerank before generation to keep context small.\n' } },
      { at: 1900, event: { type: 'expert.delta', id: 'e3', text: 'Cache favicons and passages outside React.\n' } },
      { at: 2400, event: { type: 'expert.end', id: 'e1' } },
      { at: 2500, event: { type: 'expert.end', id: 'e2' } },
      { at: 2600, event: { type: 'expert.end', id: 'e3' } },
      { at: 2800, event: { type: 'phase', phase: 'synthesizing' } },
      { at: 3800, event: { type: 'text.delta' } },
      { at: 4200, event: { type: 'run.end', status: 'done' } },
    ],
  },
  {
    id: 'deep_research',
    label: 'Deep research',
    answer: answerFor('research synthesis'),
    steps: [
      { at: 0, event: { type: 'run.start', runId: 'pg-dr', mode: 'deep_research', startedAt: 0 } },
      {
        at: 200,
        event: {
          type: 'plan.set',
          steps: [
            { id: 'pl1', label: 'Map the retrieval literature' },
            { id: 'pl2', label: 'Compare reranking strategies' },
            { id: 'pl3', label: 'Summarize evaluation gaps' },
          ],
        },
      },
      { at: 400, event: { type: 'plan.step', id: 'pl1', status: 'running' } },
      { at: 600, event: { type: 'phase', phase: 'searching' } },
      {
        at: 700,
        event: { type: 'tool.start', id: 'd1', name: 'web_search', args: { query: 'hybrid retrieval reranking' } },
      },
      { at: 900, event: { type: 'source.add', item: web[0] } },
      { at: 1400, event: { type: 'tool.end', id: 'd1', name: 'web_search', status: 'success', output: web } },
      { at: 1600, event: { type: 'plan.step', id: 'pl1', status: 'done' } },
      { at: 1700, event: { type: 'plan.step', id: 'pl2', status: 'running' } },
      { at: 1800, event: { type: 'phase', phase: 'reading' } },
      {
        at: 1900,
        event: { type: 'tool.start', id: 'd2', name: 'arxiv_search', args: { query: 'reranking evaluation' } },
      },
      { at: 2200, event: { type: 'source.add', item: web[1] } },
      { at: 2600, event: { type: 'tool.end', id: 'd2', name: 'arxiv_search', status: 'success', output: web } },
      { at: 2800, event: { type: 'plan.step', id: 'pl2', status: 'done' } },
      { at: 2900, event: { type: 'plan.step', id: 'pl3', status: 'running' } },
      { at: 3000, event: { type: 'phase', phase: 'analyzing' } },
      { at: 3400, event: { type: 'plan.step', id: 'pl3', status: 'done' } },
      { at: 3500, event: { type: 'phase', phase: 'writing' } },
      { at: 3600, event: { type: 'text.delta' } },
      { at: 4200, event: { type: 'run.end', status: 'done' } },
    ],
  },
  {
    id: 'agent',
    label: 'Agent with everything',
    answer: answerFor('agent tooling'),
    steps: [
      { at: 0, event: { type: 'run.start', runId: 'pg-agent', mode: 'agent', startedAt: 0 } },
      { at: 200, event: { type: 'reasoning.delta', text: 'Plan: search three sources in parallel, then read the best page.\n' } },
      {
        at: 400,
        event: { type: 'tool.start', id: 'a1', name: 'web_search', args: { query: 'tool approval patterns' } },
      },
      {
        at: 420,
        event: { type: 'tool.start', id: 'a2', name: 'arxiv_search', args: { query: 'agent reliability' } },
      },
      {
        at: 440,
        event: { type: 'tool.start', id: 'a3', name: 'hn_search', args: { query: 'agent UI patterns' } },
      },
      { at: 900, event: { type: 'tool.end', id: 'a1', name: 'web_search', status: 'success', output: web } },
      { at: 1000, event: { type: 'tool.end', id: 'a2', name: 'arxiv_search', status: 'error', error: 'Rate limited, try again shortly' } },
      { at: 1200, event: { type: 'tool.end', id: 'a3', name: 'hn_search', status: 'success', output: [{ title: 'Show HN: approval gates', url: 'https://news.ycombinator.com/item?id=1', points: 240, comments: 88 }] } },
      {
        at: 1400,
        event: {
          type: 'tool.start',
          id: 'a4',
          name: 'run_shell',
          args: { command: 'grep -R "approval" --include="*.ts" src' },
          awaitingApproval: true,
          approval: { agentId: 'agent-1', runId: 'run-1', tool: 'run_shell', args: { command: 'grep -R "approval" --include="*.ts" src' } },
        },
      },
      { at: 2200, event: { type: 'tool.end', id: 'a4', name: 'run_shell', status: 'success', output: 'src/approval.ts:12: needs approval' } },
      {
        at: 2400,
        event: { type: 'tool.start', id: 'b1', name: 'browser_open', args: { url: 'https://example.com/docs' }, groupKey: 'browser-1' },
      },
      {
        at: 2600,
        event: { type: 'tool.start', id: 'b2', name: 'browser_click', args: { label: 'Sign in', selector: 'button.primary' }, groupKey: 'browser-1' },
      },
      {
        at: 2800,
        event: { type: 'tool.start', id: 'b3', name: 'browser_screenshot', args: {}, groupKey: 'browser-1' },
      },
      {
        at: 3000,
        event: { type: 'tool.end', id: 'b3', name: 'browser_screenshot', status: 'success', output: { title: 'Docs', screenshot: 'data:image/svg+xml;utf8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="320" height="200" fill="#1d1d1d"/><rect x="24" y="28" width="180" height="12" rx="4" fill="#555"/><rect x="24" y="54" width="250" height="8" rx="4" fill="#333"/><rect x="24" y="72" width="220" height="8" rx="4" fill="#333"/><rect x="24" y="104" width="96" height="28" rx="6" fill="#d7d7d7"/></svg>') } },
      },
      { at: 3200, event: { type: 'tool.end', id: 'b1', name: 'browser_open', status: 'success', output: { title: 'Docs', url: 'https://example.com/docs' } } },
      { at: 3300, event: { type: 'tool.end', id: 'b2', name: 'browser_click', status: 'success', output: 'clicked' } },
      {
        at: 3400,
        event: { type: 'tool.start', id: 'a5', name: 'delegate', args: { task: 'Audit the approval copy' } },
      },
      {
        at: 3500,
        event: { type: 'tool.start', id: 'a5c1', name: 'read_file', args: { path: 'src/approval.ts' }, parentId: 'a5' },
      },
      { at: 3700, event: { type: 'tool.end', id: 'a5c1', name: 'read_file', status: 'success', output: 'export const approval = true;' } },
      { at: 3800, event: { type: 'tool.end', id: 'a5', name: 'delegate', status: 'success', output: 'Copy is consistent.' } },
      {
        at: 4000,
        event: { type: 'tool.start', id: 'a6', name: 'run_python', args: { code: 'for i in range(3):\n    print("row", i)\n' } },
      },
      { at: 4100, event: { type: 'tool.delta', id: 'a6', text: 'row 0\n' } },
      { at: 4300, buffer: { key: 'tool:a6', text: 'row 0\n' } },
      { at: 4500, event: { type: 'tool.delta', id: 'a6', text: 'row 1\n' } },
      { at: 4700, buffer: { key: 'tool:a6', text: 'row 1\n' } },
      { at: 4900, event: { type: 'tool.delta', id: 'a6', text: 'row 2\n' } },
      { at: 5100, buffer: { key: 'tool:a6', text: 'row 2\n' } },
      { at: 5300, event: { type: 'tool.end', id: 'a6', name: 'run_python', status: 'success', output: { exit_code: 0, stdout: 'row 0\nrow 1\nrow 2\n' } } },
      { at: 5600, event: { type: 'text.delta' } },
      { at: 6000, event: { type: 'run.end', status: 'done' } },
    ],
  },
  {
    id: 'knowledge_hit',
    label: 'Knowledge base, hit',
    answer: answerFor('your documents'),
    steps: [
      { at: 0, event: { type: 'run.start', runId: 'pg-kb', mode: 'knowledge_base', startedAt: 0 } },
      { at: 200, event: { type: 'phase', phase: 'searching' } },
      { at: 500, event: { type: 'retrieval.result', passages: passages.slice(0, 2) } },
      { at: 900, event: { type: 'retrieval.result', passages: passages.slice(2) } },
      { at: 1400, event: { type: 'phase', phase: 'reading' } },
      { at: 1800, event: { type: 'text.delta' } },
      { at: 2200, event: { type: 'run.end', status: 'done' } },
    ],
  },
  {
    id: 'knowledge_miss',
    label: 'Knowledge base, no hit',
    answer: 'I could not find this in your documents.',
    steps: [
      { at: 0, event: { type: 'run.start', runId: 'pg-kb-miss', mode: 'knowledge_base', startedAt: 0 } },
      { at: 200, event: { type: 'phase', phase: 'searching' } },
      { at: 1200, event: { type: 'text.delta' } },
      { at: 1500, event: { type: 'run.end', status: 'done' } },
    ],
  },
  {
    id: 'stopped',
    label: 'Stopped mid-run',
    answer: '',
    steps: [
      { at: 0, event: { type: 'run.start', runId: 'pg-stop', mode: 'agent', startedAt: 0 } },
      { at: 200, event: { type: 'tool.start', id: 's1', name: 'web_search', args: { query: 'long running query' } } },
      { at: 600, event: { type: 'tool.start', id: 's2', name: 'fetch_url', args: { url: 'https://example.com' } } },
      { at: 1400, event: { type: 'run.end', status: 'stopped' } },
    ],
  },
  {
    id: 'history',
    label: 'History load',
    answer: answerFor('a previous run'),
    steps: [
      { at: 0, event: { type: 'run.start', runId: 'pg-history', mode: 'agent', startedAt: 0 } },
      { at: 10, event: { type: 'tool.start', id: 'h1', name: 'web_search', args: { query: 'prior run' } } },
      { at: 20, event: { type: 'tool.end', id: 'h1', name: 'web_search', status: 'success', output: web } },
      { at: 30, event: { type: 'text.delta' } },
      { at: 40, event: { type: 'run.end', status: 'done' } },
    ],
  },
];
