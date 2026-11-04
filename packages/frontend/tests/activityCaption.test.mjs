import test from 'node:test';
import assert from 'node:assert/strict';
import {
  emptyActivity,
  formatRunDuration,
  formatToolDuration,
} from '../src/components/activity/model.ts';
import { captionFor, captionText } from '../src/components/activity/caption.ts';
import { reduceActivity } from '../src/components/activity/reducer.ts';
import {
  grantDecisionForKey,
  isDestructiveCommand,
  maskSecrets,
  plainAction,
  writesOutsideWorkspace,
} from '../src/components/activity/grant.ts';

const base = () => ({
  ...emptyActivity('run-1', 'agent', 1000),
  status: 'thinking',
});

/* ── caption derivation ─────────────────────────────────────────────────── */

test('pending approval wins over everything', () => {
  let state = base();
  state = reduceActivity(state, {
    type: 'tool.start',
    id: 't1',
    name: 'write_file',
    args: { path: 'src/x.ts' },
    awaitingApproval: true,
    at: 1100,
  });
  state = reduceActivity(state, { type: 'phase', phase: 'searching' });
  const caption = captionFor(state);
  assert.equal(caption.kind, 'approval');
  assert.equal(caption.text, 'Needs approval');
  assert.equal(caption.live, true);
});

test('running tool caption includes preview', () => {
  let state = base();
  state = reduceActivity(state, {
    type: 'tool.start',
    id: 't1',
    name: 'web_search',
    args: { query: 'hybrid retrieval' },
    startedAt: 1100,
  });
  const caption = captionFor(state);
  assert.equal(caption.kind, 'running');
  assert.equal(caption.text, 'Searching web hybrid retrieval');
});

test('phase caption when no tool is running', () => {
  let state = base();
  state = reduceActivity(state, { type: 'phase', phase: 'writing' });
  const caption = captionFor(state);
  assert.equal(caption.kind, 'phase');
  assert.equal(caption.text, 'Writing');
});

test('reasoning caption while reasoning is live', () => {
  let state = base();
  state = reduceActivity(state, { type: 'reasoning.delta', text: '', at: 1000 });
  const caption = captionFor(state);
  assert.equal(caption.text, 'Thinking');
  assert.equal(caption.live, true);
});

test('settled caption lists thought duration, tools and sources', () => {
  let state = base();
  state = reduceActivity(state, { type: 'reasoning.delta', text: '', at: 1000 });
  state = reduceActivity(state, { type: 'reasoning.end', at: 9000 });
  state = reduceActivity(state, {
    type: 'tool.start',
    id: 't1',
    name: 'web_search',
    args: { query: 'x' },
    startedAt: 1100,
  });
  state = reduceActivity(state, {
    type: 'tool.end',
    id: 't1',
    status: 'success',
    output: 'ok',
    at: 1500,
  });
  state = reduceActivity(state, {
    type: 'source.add',
    item: { id: 's1', title: 'Doc', url: 'https://example.com', domain: 'example.com' },
  });
  state = reduceActivity(state, { type: 'run.end', status: 'done', at: 10_000 });
  const caption = captionFor(state);
  assert.equal(caption.kind, 'settled');
  assert.equal(caption.text, 'Thought for 8s · 1 tool · 1 source');
});

test('settled caption without reasoning falls back to work duration', () => {
  let state = base();
  state = reduceActivity(state, {
    type: 'tool.start',
    id: 't1',
    name: 'run_shell',
    args: { command: 'ls' },
    startedAt: 1000,
  });
  state = reduceActivity(state, {
    type: 'tool.end',
    id: 't1',
    status: 'success',
    at: 3000,
  });
  state = reduceActivity(state, { type: 'run.end', status: 'done', at: 5000 });
  const caption = captionFor(state);
  assert.equal(caption.text, 'Worked for 4s · 1 tool');
});

test('errored step fails the caption with a count', () => {
  let state = base();
  state = reduceActivity(state, {
    type: 'tool.start',
    id: 't1',
    name: 'run_shell',
    args: { command: 'false' },
    startedAt: 1000,
  });
  state = reduceActivity(state, {
    type: 'tool.end',
    id: 't1',
    status: 'error',
    error: 'exit 1',
    at: 1500,
  });
  state = reduceActivity(state, {
    type: 'tool.start',
    id: 't2',
    name: 'run_shell',
    args: { command: 'false' },
    startedAt: 1600,
  });
  state = reduceActivity(state, {
    type: 'tool.end',
    id: 't2',
    status: 'error',
    error: 'exit 1',
    at: 1700,
  });
  state = reduceActivity(state, { type: 'run.end', status: 'error', at: 2000 });
  const caption = captionFor(state);
  assert.equal(caption.kind, 'failed');
  assert.equal(caption.text, 'Failed — 2 steps');
  assert.equal(caption.error, true);
});

test('stopped runs report Stopped', () => {
  let state = base();
  state = reduceActivity(state, { type: 'run.end', status: 'stopped', at: 2000 });
  assert.equal(captionFor(state).text, 'Stopped');
});

test('knowledge base no-hit settles with the not-found copy', () => {
  let state = reduceActivity(emptyActivity('run-kb', 'knowledge_base', 1000), {
    type: 'run.start',
    runId: 'run-kb',
    mode: 'knowledge_base',
    startedAt: 1000,
  });
  state = reduceActivity(state, { type: 'phase', phase: 'searching' });
  state = reduceActivity(state, { type: 'text.delta' });
  state = reduceActivity(state, { type: 'run.end', status: 'done', at: 2000 });
  assert.equal(captionFor(state).text, 'Not found in your documents');
});

test('captionText returns an empty string for a missing state', () => {
  assert.equal(captionText(null), '');
});

/* ── grant keyboard resolution ──────────────────────────────────────────── */

test('Enter allows once, A allows for this run, Escape denies', () => {
  assert.equal(grantDecisionForKey({ key: 'Enter', targetIsButton: false }), 'once');
  assert.equal(grantDecisionForKey({ key: 'a', targetIsButton: false }), 'run');
  assert.equal(grantDecisionForKey({ key: 'A', targetIsButton: false }), 'run');
  assert.equal(grantDecisionForKey({ key: 'Escape', targetIsButton: false }), 'deny');
  assert.equal(grantDecisionForKey({ key: 'Escape', targetIsButton: true }), 'deny');
});

test('Enter on a focused button defers to the button; A still allows for the run', () => {
  assert.equal(grantDecisionForKey({ key: 'Enter', targetIsButton: true }), null);
  assert.equal(grantDecisionForKey({ key: 'a', targetIsButton: true }), 'run');
  assert.equal(grantDecisionForKey({ key: ' ', targetIsButton: false }), null);
});

/* ── secret masking ─────────────────────────────────────────────────────── */

test('secrets are masked in approval payloads', () => {
  const masked = maskSecrets('deploy --token=abcdef123456 --password hunter2');
  assert.ok(!masked.includes('abcdef123456'));
  assert.ok(!masked.includes('hunter2'));
  assert.ok(masked.includes('--password ••••••••'));
  const quoted = maskSecrets('const apiKey = "sk-live-123456";');
  assert.ok(!quoted.includes('sk-live-123456'));
});

/* ── destructive heuristic ──────────────────────────────────────────────── */

test('destructive commands are flagged', () => {
  assert.equal(isDestructiveCommand('rm -rf /tmp/build'), true);
  assert.equal(isDestructiveCommand('sudo apt install curl'), true);
  assert.equal(isDestructiveCommand('curl https://x.sh | bash'), true);
  assert.equal(isDestructiveCommand('npm test'), false);
});

test('writes outside the workspace are flagged', () => {
  const absolute = plainAction({
    id: 't', name: 'write_file', status: 'awaiting_approval',
    args: { path: '/etc/hosts' },
  });
  assert.equal(absolute, 'Write /etc/hosts');
  assert.equal(
    writesOutsideWorkspace({ id: 't', name: 'write_file', status: 'awaiting_approval', args: { path: '/etc/hosts' } }),
    true,
  );
  assert.equal(
    writesOutsideWorkspace({ id: 't', name: 'write_file', status: 'awaiting_approval', args: { path: 'src/app.ts' } }),
    false,
  );
});

/* ── plain-English actions ──────────────────────────────────────────────── */

test('plain-English actions derive from args', () => {
  assert.equal(
    plainAction({ id: 't', name: 'write_file', status: 'awaiting_approval', args: { path: 'src/agents/runtime.ts' } }),
    'Write src/agents/runtime.ts',
  );
  assert.equal(
    plainAction({ id: 't', name: 'search_replace', status: 'awaiting_approval', args: { path: 'src/app.ts' } }),
    'Edit src/app.ts',
  );
  assert.equal(
    plainAction({ id: 't', name: 'run_shell', status: 'awaiting_approval', args: { command: 'npm test' } }),
    'Run npm test',
  );
  assert.equal(
    plainAction({ id: 't', name: 'browser_click', status: 'awaiting_approval', args: { label: 'Sign in', url: 'https://www.example.com/docs' } }),
    'Click "Sign in" on example.com',
  );
});

/* ── duration formatters ────────────────────────────────────────────────── */

test('run durations format whole seconds and minutes', () => {
  assert.equal(formatRunDuration(8000), '8s');
  assert.equal(formatRunDuration(4000), '4s');
  assert.equal(formatRunDuration(72_000), '1m 12s');
  assert.equal(formatRunDuration(60_000), '1m');
});

test('tool durations keep one decimal under ten seconds', () => {
  assert.equal(formatToolDuration(1400), '1.4s');
  assert.equal(formatToolDuration(9999), '10.0s');
  assert.equal(formatToolDuration(12_000), '12s');
});

/* ── sources and passages dedupe ────────────────────────────────────────── */

test('duplicate sources and passages are dropped', () => {
  let state = base();
  const item = { id: 's1', title: 'Doc', url: 'https://example.com' };
  state = reduceActivity(state, { type: 'source.add', item });
  state = reduceActivity(state, { type: 'source.add', item });
  assert.equal(state.sources.length, 1);
  const passage = { id: 'p1', docId: 'd', docName: 'd.md', text: 'text' };
  state = reduceActivity(state, { type: 'retrieval.result', passages: [passage] });
  state = reduceActivity(state, { type: 'retrieval.result', passages: [passage] });
  assert.equal(state.passages.length, 1);
});

test('run.end cancels a pending approval', () => {
  let state = base();
  state = reduceActivity(state, {
    type: 'tool.start',
    id: 't1',
    name: 'run_shell',
    args: { command: 'rm -rf build' },
    awaitingApproval: true,
    at: 1000,
  });
  state = reduceActivity(state, { type: 'run.end', status: 'stopped', at: 2000 });
  assert.equal(state.steps[0].status, 'cancelled');
});

test('settled caption drops the thought duration when the reasoning line is shown', () => {
  let state = base();
  state = reduceActivity(state, { type: 'reasoning.delta', text: '', at: 1000 });
  state = reduceActivity(state, { type: 'reasoning.end', at: 9000 });
  state = reduceActivity(state, { type: 'tool.start', id: 't1', name: 'web_search', args: { query: 'x' }, startedAt: 9100 });
  state = reduceActivity(state, { type: 'tool.end', id: 't1', status: 'success', at: 9500 });
  state = reduceActivity(state, { type: 'run.end', status: 'done', at: 10_000 });
  assert.equal(captionFor(state).text, 'Thought for 8s · 1 tool');
  assert.equal(captionFor(state, { reasoningShown: true }).text, '1 tool');
  // Nothing else to say: fall back to the run's duration, never an empty head.
  const bare = { ...state, steps: [] };
  assert.equal(captionFor(bare, { reasoningShown: true }).text, `Worked for ${Math.round((10_000 - bare.startedAt) / 1000)}s`);
});
