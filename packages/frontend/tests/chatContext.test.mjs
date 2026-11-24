import test from 'node:test';
import assert from 'node:assert/strict';
import {
  estimateTokens,
  summarizeContextBudget,
  summarizePinnedContext,
} from '../src/utils/chatContext.ts';

const pinned = [
  {
    id: 'a1',
    kind: 'artifact',
    title: 'Q3 review',
    content: 'A'.repeat(400),
    createdAt: 1,
  },
  {
    id: 'm1',
    kind: 'message',
    title: 'Decision',
    content: 'B'.repeat(200),
    createdAt: 2,
  },
];

test('estimates tokens from characters', () => {
  assert.equal(estimateTokens('a'.repeat(400)), 100);
});

test('summarizes the context budget into message, pinned and memory tokens', () => {
  const summary = summarizeContextBudget({
    pinnedContext: pinned,
    messages: [{ content: 'C'.repeat(800) }],
    memory: ['D'.repeat(80)],
    budget: 4096,
  });
  assert.equal(summary.contextTokens, 151);
  assert.equal(summary.messageTokens, 200);
  assert.equal(summary.memoryTokens, 20);
  assert.equal(summary.totalTokens, 371);
  assert.equal(summary.pct, 9);
});

test('compacts multiple pinned items into one summary', () => {
  const summary = summarizePinnedContext(pinned);
  assert.equal(summary?.title, 'Compacted context (2 items)');
  assert.match(summary?.content ?? '', /Q3 review/);
  assert.match(summary?.content ?? '', /Decision/);
  assert.equal(summarizePinnedContext(pinned.slice(0, 1)), null);
});
