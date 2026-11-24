import test from 'node:test';
import assert from 'node:assert/strict';
import { routeChatSubMode } from '../src/utils/chatRouting.ts';

test('auto routing leaves explicit modes alone', () => {
  assert.equal(routeChatSubMode('research this topic', 'moe', true), 'moe');
  assert.equal(routeChatSubMode('hello', 'deep_research', true), 'deep_research');
});

test('auto routing sends research prompts to deep research', () => {
  assert.equal(routeChatSubMode('Find sources and cite them', 'default', true), 'deep_research');
  assert.equal(routeChatSubMode('fact-check this claim', 'default', true), 'deep_research');
});

test('auto routing sends complex prompts to the council', () => {
  assert.equal(routeChatSubMode('Compare these two strategies', 'default', true), 'moe');
  assert.equal(routeChatSubMode('x'.repeat(450), 'default', true), 'moe');
});

test('auto routing keeps simple prompts default and is off by default', () => {
  assert.equal(routeChatSubMode('What is the capital of France?', 'default', true), 'default');
  assert.equal(routeChatSubMode('Compare these two strategies', 'default', false), 'default');
});
