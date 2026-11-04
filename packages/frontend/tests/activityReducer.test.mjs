import test from 'node:test';
import assert from 'node:assert/strict';
import {
  emptyActivity,
  formatRunDuration,
  formatToolDuration,
} from '../src/components/activity/model.ts';
import { reduceActivity, reduceEvents } from '../src/components/activity/reducer.ts';

const start = () => ({
  ...emptyActivity('run-1', 'agent', 1000),
  status: 'thinking',
});

test('run.start initializes the run and is idempotent', () => {
  const state = reduceActivity(emptyActivity('run-0', 'default', 0), {
    type: 'run.start',
    runId: 'run-1',
    mode: 'moe',
    startedAt: 1000,
  });
  assert.equal(state.runId, 'run-1');
  assert.equal(state.mode, 'moe');
  assert.equal(reduceActivity(state, {
    type: 'run.start',
    runId: 'run-1',
    mode: 'moe',
    startedAt: 1000,
  }), state);
});

test('reasoning deltas only track lifecycle; text lives in the buffer', () => {
  let state = start();
  state = reduceActivity(state, { type: 'reasoning.delta', text: 'first ', at: 1000 });
  state = reduceActivity(state, { type: 'reasoning.delta', text: 'second', at: 1200 });
  assert.equal(state.reasoning.text, '');
  assert.equal(state.reasoning.startedAt, 1000);
  state = reduceActivity(state, { type: 'reasoning.end', at: 8000 });
  assert.equal(state.reasoning.done, true);
  assert.equal(state.reasoning.durationMs, 7000);
});

test('reasoning delta seq drops duplicates', () => {
  let state = start();
  state = reduceActivity(state, { type: 'reasoning.delta', text: 'a', seq: 2, at: 1000 });
  const same = reduceActivity(state, { type: 'reasoning.delta', text: 'a', seq: 2, at: 1000 });
  assert.equal(same, state);
  state = reduceActivity(state, { type: 'reasoning.delta', text: 'b', seq: 3, at: 1100 });
  assert.equal(state.reasoning.seq, 3);
});

test('tool.end before tool.start creates the step', () => {
  const state = reduceActivity(start(), {
    type: 'tool.end',
    id: 't1',
    name: 'web_search',
    status: 'success',
    output: 'ok',
    at: 1500,
  });
  assert.equal(state.steps.length, 1);
  assert.equal(state.steps[0].name, 'web_search');
  assert.equal(state.steps[0].status, 'success');
});

test('duplicate tool start never downgrades a settled step', () => {
  let state = reduceActivity(start(), {
    type: 'tool.start',
    id: 't1',
    name: 'read_file',
    startedAt: 1100,
  });
  state = reduceActivity(state, {
    type: 'tool.end',
    id: 't1',
    status: 'success',
    at: 1600,
  });
  const same = reduceActivity(state, {
    type: 'tool.start',
    id: 't1',
    name: 'read_file',
    startedAt: 1100,
  });
  assert.equal(same, state);
  assert.equal(state.steps[0].status, 'success');
  assert.equal(state.steps[0].durationMs, 500);
});

test('duplicate tool.end is idempotent and fills missing output', () => {
  let state = reduceActivity(start(), { type: 'tool.start', id: 't1', name: 'run_shell', startedAt: 1000 });
  state = reduceActivity(state, { type: 'tool.end', id: 't1', status: 'success', at: 1200 });
  const same = reduceActivity(state, { type: 'tool.end', id: 't1', status: 'success', at: 1300 });
  assert.equal(same, state);
  const filled = reduceActivity(state, {
    type: 'tool.end',
    id: 't1',
    status: 'success',
    output: 'late',
    at: 1400,
  });
  assert.equal(filled.steps[0].output, 'late');
  assert.equal(filled.steps[0].durationMs, 200);
});

test('tool error keeps the message and status', () => {
  let state = reduceActivity(start(), { type: 'tool.start', id: 't1', name: 'web_search', startedAt: 1000 });
  state = reduceActivity(state, {
    type: 'tool.end',
    id: 't1',
    status: 'error',
    error: 'Rate limited',
    at: 1500,
  });
  assert.equal(state.steps[0].status, 'error');
  assert.equal(state.steps[0].error, 'Rate limited');
});

test('sources and passages dedupe by id', () => {
  let state = start();
  const item = { id: 's1', title: 'A' };
  state = reduceActivity(state, { type: 'source.add', item });
  state = reduceActivity(state, { type: 'source.add', item });
  assert.equal(state.sources.length, 1);
  const passage = { id: 'p1', docId: 'd', docName: 'd.md', text: 'hello' };
  state = reduceActivity(state, { type: 'retrieval.result', passages: [passage] });
  state = reduceActivity(state, { type: 'retrieval.result', passages: [passage] });
  assert.equal(state.passages.length, 1);
});

test('plan steps update by id without duplicating', () => {
  let state = reduceActivity(start(), {
    type: 'plan.set',
    steps: [
      { id: 'a', label: 'Search' },
      { id: 'b', label: 'Read' },
    ],
  });
  state = reduceActivity(state, { type: 'plan.step', id: 'a', status: 'running' });
  state = reduceActivity(state, { type: 'plan.step', id: 'a', status: 'done' });
  assert.equal(state.plan.length, 2);
  assert.equal(state.plan[0].status, 'done');
  assert.equal(state.plan[1].status, 'pending');
});

test('approval resolution moves the step to running or denied', () => {
  let state = reduceActivity(start(), {
    type: 'tool.start',
    id: 't1',
    name: 'run_shell',
    awaitingApproval: true,
  });
  assert.equal(state.status, 'awaiting_approval');
  state = reduceActivity(state, { type: 'tool.approval', id: 't1', status: 'running' });
  assert.equal(state.steps[0].status, 'running');
  assert.equal(state.status, 'working');
  state = reduceActivity(state, { type: 'tool.approval', id: 't2', status: 'denied' });
  assert.equal(state.steps.length, 1);
});

test('run.end cancels running work and is idempotent', () => {
  let state = reduceActivity(start(), { type: 'tool.start', id: 't1', name: 'fetch_url', startedAt: 1000 });
  state = reduceActivity(state, { type: 'run.end', status: 'stopped', at: 2000 });
  assert.equal(state.status, 'stopped');
  assert.equal(state.steps[0].status, 'cancelled');
  const same = reduceActivity(state, { type: 'run.end', status: 'done', at: 3000 });
  assert.equal(same, state);
});

test('text.delta marks the answer as started', () => {
  const state = reduceActivity(start(), { type: 'text.delta' });
  assert.equal(state.answerStarted, true);
});

test('batched events equal sequential reduction', () => {
  const events = [
    { type: 'tool.start', id: 't1', name: 'web_search', startedAt: 1200 },
    { type: 'source.add', item: { id: 's1', title: 'A' } },
    { type: 'tool.end', id: 't1', status: 'success', output: 'ok', at: 1500 },
  ];
  const batched = reduceEvents(start(), events);
  const sequential = events.reduce(reduceActivity, start());
  assert.deepEqual(batched, sequential);
});

test('experts start, stream and finish', () => {
  let state = reduceActivity(start(), { type: 'expert.start', id: 'e1', name: 'Retrieval' });
  assert.equal(state.experts.length, 1);
  state = reduceActivity(state, { type: 'expert.delta', id: 'e1', text: 'one ' });
  state = reduceActivity(state, { type: 'expert.delta', id: 'e1', text: 'two' });
  assert.equal(state.experts[0].snippet, 'one two');
  state = reduceActivity(state, { type: 'expert.end', id: 'e1' });
  assert.equal(state.experts[0].status, 'done');
  const same = reduceActivity(state, { type: 'expert.end', id: 'e1' });
  assert.equal(same, state);
});

test('phase changes are idempotent', () => {
  const state = reduceActivity(start(), { type: 'phase', phase: 'reading' });
  assert.equal(state.phase, 'reading');
  assert.equal(reduceActivity(state, { type: 'phase', phase: 'reading' }), state);
});

test('run.error records the message and timestamp', () => {
  const state = reduceActivity(start(), { type: 'run.error', message: 'Network lost', at: 5000 });
  assert.equal(state.status, 'error');
  assert.equal(state.error, 'Network lost');
  assert.equal(state.endedAt, 5000);
});

test('tool.delta publishes the streamed output reference once', () => {
  let state = reduceActivity(start(), { type: 'tool.start', id: 't1', name: 'run_shell', startedAt: 1000 });
  state = reduceActivity(state, { type: 'tool.delta', id: 't1', text: '' });
  assert.equal(state.steps[0].streamedOutputRef, 'tool:t1');
  const same = reduceActivity(state, { type: 'tool.delta', id: 't1', text: 'more' });
  assert.equal(same, state);
});

test('duration formatters match the copy deck', () => {
  assert.equal(formatRunDuration(8000), '8s');
  assert.equal(formatRunDuration(72_000), '1m 12s');
  assert.equal(formatRunDuration(60_000), '1m');
  assert.equal(formatToolDuration(1200), '1.2s');
  assert.equal(formatToolDuration(12_000), '12s');
});
