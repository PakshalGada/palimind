import test from 'node:test';
import assert from 'node:assert/strict';
import { emptyActivity } from '../src/components/activity/model.ts';
import { reduceActivity } from '../src/components/activity/reducer.ts';
import { RunRecorder } from '../src/components/activity/recorder.ts';
import { BufferRegistry } from '../src/components/activity/buffers.ts';
import { streamReducer } from '../src/stream/reducer.ts';
import { initialStreamState } from '../src/stream/types.ts';

/** Synchronous ActivityStore stand-in (no animation frames). */
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

test('agent capability UI flow: checklist, tools, usage and follow-ups', () => {
  const store = fakeStore();
  const recorder = new RunRecorder(store, 'agent');
  recorder.start('run-capability');

  recorder.observe({
    type: 'agent:todo',
    items: [
      { id: '1', label: 'Search the reports', status: 'completed' },
      { id: '2', label: 'Compare the numbers', status: 'in_progress' },
      { id: '3', label: 'Write the answer', status: 'pending' },
    ],
  });
  recorder.observe({
    type: 'agent:tool_call',
    tool: 'web_search',
    args: { query: 'alpha beta throughput' },
  });
  recorder.observe({
    type: 'agent:tool_result',
    tool: 'web_search',
    result: 'Source [1]: Alpha benchmark report\nURL: https://example.org/alpha',
  });
  recorder.observe({
    type: 'agent:todo',
    items: [
      { id: '1', label: 'Search the reports', status: 'completed' },
      { id: '2', label: 'Compare the numbers', status: 'completed' },
      { id: '3', label: 'Write the answer', status: 'completed' },
    ],
  });
  recorder.observe({ type: 'agent:token', text: 'Alpha improves throughput [1].' });
  recorder.end('done');

  const activity = store.getState();
  assert.equal(activity.status, 'done');
  assert.deepEqual(
    activity.plan.map((step) => step.status),
    ['done', 'done', 'done'],
  );
  assert.equal(activity.steps.length, 1);
  assert.equal(activity.steps[0].name, 'web_search');
  assert.equal(activity.steps[0].status, 'success');
  assert.equal(activity.answerStarted, true);

  // The same run's stream state must carry usage, escalation and follow-ups.
  let stream = streamReducer(initialStreamState, {
    type: 'start',
    userText: 'Research the reports',
    sessionId: 's1',
  });
  stream = streamReducer(stream, {
    type: 'setUsage',
    usage: { prompt_tokens: 1200, completion_tokens: 400, estimated_cost_usd: 0 },
  });
  stream = streamReducer(stream, {
    type: 'setEscalation',
    escalation: 'Escalated to strong-model',
  });
  stream = streamReducer(stream, {
    type: 'setSuggestions',
    suggestions: ['What are the key takeaways?', 'Compare the sources.'],
  });
  assert.equal(stream.usage.prompt_tokens, 1200);
  assert.equal(stream.escalation, 'Escalated to strong-model');
  assert.deepEqual(stream.suggestions, [
    'What are the key takeaways?',
    'Compare the sources.',
  ]);
});
