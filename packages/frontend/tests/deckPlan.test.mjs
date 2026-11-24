import test from 'node:test';
import assert from 'node:assert/strict';
import { parseChart, parseDeckOutline, planDeckLocal } from '../src/utils/deckPlan.ts';

test('chart directive parses categories and values', () => {
  const chart = parseChart('[chart: bar] Quarterly revenue ($M) | Q1: 4.2 | Q2: 5.1 | Q3: 6.0');
  assert.equal(chart?.kind, 'bar');
  assert.equal(chart?.title, 'Quarterly revenue');
  assert.equal(chart?.unit, '$M');
  assert.deepEqual(chart?.categories, ['Q1', 'Q2', 'Q3']);
  assert.deepEqual(chart?.values, [4.2, 5.1, 6]);
});

test('invalid chart data does not invent a chart', () => {
  assert.equal(parseChart('[chart: bar] Revenue | Q1: n/a'), null);
  assert.equal(parseChart('not a chart'), null);
});

test('outline planning infers layouts and keeps charts', () => {
  const slides = parseDeckOutline(
    [
      '# Revenue grew 18% in Q3',
      '- Growth accelerated for three quarters',
      '[chart: bar] Quarterly revenue ($M) | Q1: 4.2 | Q2: 5.1 | Q3: 6.0',
      '',
      '# What we will cover',
      '- Results',
      '- Drivers',
      '- Next steps',
      '',
      '# Current vs proposed',
      '- Current: one plan',
      '- Proposed: three tiers',
    ].join('\n'),
    'Q3 review',
  );
  assert.equal(slides[0].layout, 'chart');
  assert.equal(slides[0].chart?.values[1], 5.1);
  assert.equal(slides[1].layout, 'agenda');
  assert.equal(slides[2].layout, 'comparison');
});

test('local deck plan always has a title', () => {
  const plan = planDeckLocal('', '# One\n- A');
  assert.equal(plan.title, 'Presentation');
  assert.ok(plan.slides.length >= 1);
});
