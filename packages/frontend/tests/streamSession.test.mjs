import test from 'node:test';
import assert from 'node:assert/strict';
import { streamBelongsTo, streamReducer } from '../src/stream/reducer.ts';
import { initialStreamState } from '../src/stream/types.ts';

const start = (sessionId) =>
  streamReducer(initialStreamState, { type: 'start', userText: 'hi', sessionId });

test('a new-chat stream adopts the session id the server reports', () => {
  const s0 = start(null);
  assert.equal(s0.sessionId, null);
  const s1 = streamReducer(s0, { type: 'setSession', sessionId: 'abc' });
  assert.equal(s1.sessionId, 'abc');
  assert.ok(s1.revision > s0.revision);
});

test('a bound stream never moves to another session', () => {
  const s0 = start('xyz');
  assert.equal(streamReducer(s0, { type: 'setSession', sessionId: 'abc' }), s0);
});

test('setSession is ignored when idle', () => {
  assert.equal(
    streamReducer(initialStreamState, { type: 'setSession', sessionId: 'abc' }),
    initialStreamState,
  );
});

test('the live turn renders only in its own session', () => {
  const pending = start(null);
  // Before the session event: only the "no session" view it started from.
  assert.equal(streamBelongsTo(pending, null), true);
  assert.equal(streamBelongsTo(pending, 'other'), false);

  const bound = streamReducer(pending, { type: 'setSession', sessionId: 'abc' });
  assert.equal(streamBelongsTo(bound, 'abc'), true);
  assert.equal(streamBelongsTo(bound, 'other'), false);
  assert.equal(streamBelongsTo(bound, null), false);

  assert.equal(streamBelongsTo(initialStreamState, null), false);
  // Finished turns (awaiting the refresh) still belong to their session.
  const done = streamReducer(bound, { type: 'finish', status: 'done' });
  assert.equal(streamBelongsTo(done, 'abc'), true);
});

test('usage, suggestions and escalation survive the stream reducer', () => {
  let state = start('abc');
  state = streamReducer(state, {
    type: 'setUsage',
    usage: { prompt_tokens: 1200, completion_tokens: 800, estimated_cost_usd: 0 },
  });
  state = streamReducer(state, {
    type: 'setSuggestions',
    suggestions: ['What changed?', 'Write a brief'],
  });
  state = streamReducer(state, {
    type: 'setEscalation',
    escalation: 'Escalated to strong-model',
  });
  assert.equal(state.usage.prompt_tokens, 1200);
  assert.equal(state.usage.completion_tokens, 800);
  assert.deepEqual(state.suggestions, ['What changed?', 'Write a brief']);
  assert.equal(state.escalation, 'Escalated to strong-model');
  // A new turn clears them.
  const fresh = streamReducer(state, { type: 'start', userText: 'next', sessionId: 'abc' });
  assert.equal(fresh.usage, null);
  assert.deepEqual(fresh.suggestions, []);
  assert.equal(fresh.escalation, null);
});
