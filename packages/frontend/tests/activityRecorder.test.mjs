import test from 'node:test';
import assert from 'node:assert/strict';
import { emptyActivity } from '../src/components/activity/model.ts';
import { reduceActivity } from '../src/components/activity/reducer.ts';
import { RunRecorder } from '../src/components/activity/recorder.ts';
import { BufferRegistry } from '../src/components/activity/buffers.ts';

/** Synchronous stand-in for ActivityStore (no animation frames). */
function fakeStore() {
  let state = null;
  return {
    buffers: new BufferRegistry(),
    getState: () => state,
    dispatch(event) {
      state = reduceActivity(state ?? emptyActivity('run', 'agent'), event);
    },
  };
}

test('call-then-gate approval pauses the running row instead of adding one', () => {
  const store = fakeStore();
  const recorder = new RunRecorder(store, 'agent');
  recorder.start('run-1');
  recorder.observe({ type: 'agent:tool_call', tool: 'run_shell', args: { command: 'ls' } });
  recorder.observe({ type: 'agent:waiting_for_human', tool: 'run_shell', agent_id: 'a1', args: { command: 'ls' } });
  let state = store.getState();
  assert.equal(state.steps.length, 1);
  assert.equal(state.steps[0].status, 'awaiting_approval');
  assert.equal(state.steps[0].approval.agentId, 'a1');
  store.dispatch({ type: 'tool.approval', id: state.steps[0].id, status: 'running' });
  recorder.observe({ type: 'agent:tool_result', tool: 'run_shell', result: 'ok' });
  state = store.getState();
  assert.equal(state.steps.length, 1);
  assert.equal(state.steps[0].status, 'success');
});

test('gate-then-call approval continues the approval row', () => {
  const store = fakeStore();
  const recorder = new RunRecorder(store, 'agent');
  recorder.start('run-1');
  recorder.observe({ type: 'agent:waiting_for_human', tool: 'write_file', agent_id: 'a1', args: {} });
  const id = store.getState().steps[0].id;
  store.dispatch({ type: 'tool.approval', id, status: 'running' });
  recorder.observe({ type: 'agent:tool_call', tool: 'write_file', args: {} });
  recorder.observe({ type: 'agent:tool_result', tool: 'write_file', result: 'written' });
  const state = store.getState();
  assert.equal(state.steps.length, 1);
  assert.equal(state.steps[0].status, 'success');
  assert.equal(state.steps[0].output, 'written');
});

test('a denied gate-then-call approval stays denied', () => {
  const store = fakeStore();
  const recorder = new RunRecorder(store, 'agent');
  recorder.start('run-1');
  recorder.observe({ type: 'agent:waiting_for_human', tool: 'run_shell', agent_id: 'a1', args: {} });
  const id = store.getState().steps[0].id;
  store.dispatch({ type: 'tool.approval', id, status: 'denied' });
  recorder.observe({ type: 'agent:tool_call', tool: 'run_shell', args: {} });
  recorder.observe({ type: 'agent:tool_result', tool: 'run_shell', result: 'Denied by user' });
  const state = store.getState();
  assert.equal(state.steps.length, 1);
  assert.equal(state.steps[0].status, 'denied');
});

test('an error event followed by end leaves no running tool or live reasoning', () => {
  const store = fakeStore();
  const recorder = new RunRecorder(store, 'agent');
  recorder.start('run-1');
  recorder.observe({ type: 'agent:thought', text: 'Looking it up' });
  recorder.observe({ type: 'agent:tool_call', tool: 'web_search', args: { query: 'x' } });
  recorder.observe({ type: 'error', text: 'Backend failed' });
  recorder.end('error');
  const state = store.getState();
  assert.equal(state.status, 'error');
  assert.equal(state.error, 'Backend failed');
  assert.equal(state.reasoning.done, true);
  assert.equal(state.steps[0].status, 'error');
});

test('agent todo events become a live plan checklist', () => {
  const store = fakeStore();
  const recorder = new RunRecorder(store, 'agent');
  recorder.start('run-1');
  recorder.observe({
    type: 'agent:todo',
    items: [
      { id: '1', label: 'Find sources', status: 'completed' },
      { id: '2', label: 'Read pages', status: 'in_progress' },
      { id: '3', label: 'Write brief', status: 'pending' },
    ],
  });
  const state = store.getState();
  assert.deepEqual(
    state.plan.map((step) => [step.label, step.status]),
    [
      ['Find sources', 'done'],
      ['Read pages', 'running'],
      ['Write brief', 'pending'],
    ],
  );
});

test('a later todo update replaces statuses and keeps the run alive', () => {
  const store = fakeStore();
  const recorder = new RunRecorder(store, 'agent');
  recorder.start('run-1');
  recorder.observe({
    type: 'agent:todo',
    items: [{ id: '1', label: 'A', status: 'in_progress' }],
  });
  recorder.observe({
    type: 'agent:todo',
    items: [
      { id: '1', label: 'A', status: 'completed' },
      { id: '2', label: 'B', status: 'in_progress' },
    ],
  });
  const state = store.getState();
  assert.equal(state.plan.length, 2);
  assert.equal(state.plan[0].status, 'done');
  assert.equal(state.plan[1].status, 'running');
  recorder.end('done');
  assert.equal(store.getState().status, 'done');
});
