import test from 'node:test';
import assert from 'node:assert/strict';
import { childrenOf, depthOf, timelineOverlaps, unitsOf } from '../src/components/activity/grouping.ts';

const step = (overrides) => ({
  id: 't',
  name: 'web_search',
  status: 'success',
  args: {},
  ...overrides,
});

test('consecutive browser steps merge into one unit', () => {
  const steps = [
    step({ id: 'b1', name: 'browser_open', groupKey: 'browser-1' }),
    step({ id: 'b2', name: 'browser_click', groupKey: 'browser-1' }),
    step({ id: 'b3', name: 'browser_screenshot', groupKey: 'browser-1' }),
    step({ id: 't1', name: 'read_file' }),
  ];
  const units = unitsOf(steps);
  assert.equal(units.length, 2);
  assert.equal(units[0].kind, 'browser');
  assert.equal(units[0].steps.length, 3);
  assert.equal(units[1].kind, 'step');
});

test('parallel completed calls group into one row', () => {
  const steps = [
    step({ id: 'a', startedAt: 1000, endedAt: 2000, durationMs: 1000 }),
    step({ id: 'b', startedAt: 1100, endedAt: 1900, durationMs: 800 }),
    step({ id: 'c', startedAt: 1150, endedAt: 2100, durationMs: 950 }),
    step({ id: 'd', startedAt: 5000, endedAt: 5200, durationMs: 200 }),
  ];
  const units = unitsOf(steps);
  assert.equal(units.length, 2);
  assert.equal(units[0].kind, 'parallel');
  assert.equal(units[0].steps.length, 3);
  assert.equal(units[1].kind, 'step');
});

test('fast sequential same-intent calls cluster into one row', () => {
  const steps = [
    step({ id: 'a', startedAt: 1000, endedAt: 1100, durationMs: 100 }),
    step({ id: 'b', startedAt: 1200, endedAt: 1300, durationMs: 100 }),
  ];
  const units = unitsOf(steps);
  assert.equal(units.length, 1);
  assert.equal(units[0].kind, 'cluster');
  assert.equal(units[0].intent, 'research');
  assert.equal(units[0].steps.length, 2);
});

test('consecutive different-intent steps do not cluster', () => {
  const steps = [
    step({ id: 'a', name: 'web_search', startedAt: 1000, endedAt: 1100, durationMs: 100 }),
    step({ id: 'b', name: 'write_file', startedAt: 1200, endedAt: 1300, durationMs: 100 }),
    step({ id: 'c', name: 'run_shell', startedAt: 1400, endedAt: 1500, durationMs: 100 }),
  ];
  const units = unitsOf(steps);
  assert.equal(units.length, 3);
  assert.ok(units.every((unit) => unit.kind === 'step'));
});

test('running calls do not group as completed parallel work', () => {
  const steps = [
    step({ id: 'a', name: 'web_search', status: 'running', startedAt: 1000 }),
    step({ id: 'b', name: 'write_file', status: 'running', startedAt: 1000 }),
  ];
  const units = unitsOf(steps);
  assert.equal(units.length, 2);
  assert.ok(units.every((unit) => unit.kind === 'step'));
});

test('overlap detection handles concurrent intervals', () => {
  assert.equal(
    timelineOverlaps([
      step({ id: 'a', startedAt: 0, endedAt: 1000 }),
      step({ id: 'b', startedAt: 500, endedAt: 1500 }),
    ]),
    true,
  );
  assert.equal(
    timelineOverlaps([
      step({ id: 'a', startedAt: 0, endedAt: 1000 }),
      step({ id: 'b', startedAt: 1000, endedAt: 2000 }),
    ]),
    false,
  );
});

test('subagent nesting finds direct children and depth', () => {
  const state = {
    runId: 'r',
    mode: 'agent',
    status: 'working',
    startedAt: 0,
    steps: [
      step({ id: 'parent', name: 'delegate' }),
      step({ id: 'child', parentId: 'parent' }),
      step({ id: 'grandchild', parentId: 'child' }),
      step({ id: 'other' }),
    ],
    sources: [],
    passages: [],
    answerStarted: false,
  };
  assert.deepEqual(childrenOf(state, 'parent').map((entry) => entry.id), ['child']);
  assert.equal(depthOf(state, state.steps[2]), 2);
  assert.equal(depthOf(state, state.steps[3]), 0);
});

test('cycles in parent links do not loop forever', () => {
  const state = {
    runId: 'r',
    mode: 'agent',
    status: 'working',
    startedAt: 0,
    steps: [step({ id: 'a', parentId: 'b' }), step({ id: 'b', parentId: 'a' })],
    sources: [],
    passages: [],
    answerStarted: false,
  };
  assert.equal(depthOf(state, state.steps[0]), 1);
});

test('a pending approval is never folded into a cluster or browser card', () => {
  const shell = [
    step({ id: 'a', name: 'run_shell', startedAt: 1000, endedAt: 1100, durationMs: 100 }),
    step({ id: 'b', name: 'run_shell', status: 'awaiting_approval', startedAt: 1200 }),
  ];
  const units = unitsOf(shell);
  assert.equal(units.length, 2);
  assert.ok(units.every((unit) => unit.kind === 'step'));

  const browser = [
    step({ id: 'b1', name: 'browser_open', groupKey: 'browser-1' }),
    step({ id: 'b2', name: 'browser_click', groupKey: 'browser-1', status: 'awaiting_approval' }),
  ];
  const browserUnits = unitsOf(browser);
  assert.equal(browserUnits.length, 2);
  assert.equal(browserUnits[0].kind, 'browser');
  assert.deepEqual(browserUnits[0].steps.map((entry) => entry.id), ['b1']);
  assert.equal(browserUnits[1].kind, 'step');
  assert.equal(browserUnits[1].steps[0].id, 'b2');
});
