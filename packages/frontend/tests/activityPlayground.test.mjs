import test from 'node:test';
import assert from 'node:assert/strict';
import { SCENARIOS } from '../src/components/activity/playground/scripts.ts';
import { reduceActivity } from '../src/components/activity/reducer.ts';
import { emptyActivity, isTerminal } from '../src/components/activity/model.ts';
import { captionText } from '../src/components/activity/caption.ts';

/**
 * Replay every scripted scenario through the real reducer, the same way the
 * playground dispatches them. Guards against scenario drift and against
 * reducer regressions that only show up under realistic event bursts.
 */

function replay(scenario) {
  let state = emptyActivity('replay', 'default', 1000);
  let tick = 1000;
  for (const step of scenario.steps) {
    if (!step.event) continue;
    tick += 37;
    const event = { ...step.event };
    if (event.type === 'run.start') event.startedAt = 1000;
    else if (event.type === 'tool.start' && event.startedAt == null) event.startedAt = tick;
    else if ('at' in event && event.at == null) event.at = tick;
    state = reduceActivity(state, event);
  }
  return state;
}

const TERMINAL = (scenarioId) => SCENARIOS.find((scenario) => scenario.id === scenarioId);

for (const scenario of SCENARIOS) {
  if (scenario.restored) continue;
  test(`scenario "${scenario.id}" replays to a coherent state`, () => {
    const final = replay(scenario);
    if (scenario.steps.some((step) => step.event?.type === 'run.end')) {
      assert.ok(isTerminal(final.status), `${scenario.id} ends terminal`);
      assert.ok(
        final.steps.every((step) => step.status !== 'running' && step.status !== 'queued'),
        'no step is left running when the run ends',
      );
    }
  });
}

test('agent scenario ends with approval resolved', () => {
  const final = replay(TERMINAL('agent'));
  assert.equal(final.status, 'done');
  const approval = final.steps.find((step) => step.id === 'a4');
  assert.equal(approval.status, 'success');
});

test('stopped scenario cancels in-flight work', () => {
  const final = replay(TERMINAL('stopped'));
  assert.equal(final.status, 'stopped');
  assert.ok(final.steps.every((step) => step.status === 'cancelled'));
});

test('knowledge miss settles with the not-found caption', () => {
  const final = replay(TERMINAL('knowledge_miss'));
  assert.equal(final.passages.length, 0);
  assert.equal(captionText(final), 'Not found in your documents');
});

test('knowledge hit collects four passages', () => {
  const final = replay(TERMINAL('knowledge_hit'));
  assert.equal(final.passages.length, 4);
  assert.ok(captionText(final).length > 0);
});
