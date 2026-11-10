import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_BLOCK_CHARS,
  MAX_VISIBLE_BLOCKS,
  splitMessageBlocks,
  visibleMessageBlocks,
} from '../src/features/agents/messageBlocks.ts';

test('short chat answer becomes one bubble', () => {
  const blocks = splitMessageBlocks('I checked that. It is fine.');
  assert.equal(blocks.length, 1);
});

test('paragraphs become separate bubbles', () => {
  const blocks = splitMessageBlocks('First thought.\n\nSecond thought.\n\nThird thought.');
  assert.deepEqual(blocks, ['First thought.', 'Second thought.', 'Third thought.']);
});

test('code fences stay one block even with blank lines', () => {
  const code = 'Here is the fix:\n\n```ts\nconst a = 1;\n\nconst b = 2;\n```';
  const blocks = splitMessageBlocks(code);
  assert.equal(blocks.length, 2);
  assert.match(blocks[1], /const a = 1/);
  assert.match(blocks[1], /const b = 2/);
});

test('oversized paragraph splits at sentences', () => {
  const sentence = 'This is a useful sentence that explains one part of the answer. ';
  const blocks = splitMessageBlocks(sentence.repeat(12));
  assert.ok(blocks.length > 1);
  for (const block of blocks) {
    assert.ok(block.length <= MAX_BLOCK_CHARS + 4, block);
  }
});

test('lists stay together and are not cut', () => {
  const list = '- first\n- second\n- third';
  const blocks = splitMessageBlocks(list);
  assert.deepEqual(blocks, [list]);
});

test('only four bubbles are visible until expanded', () => {
  const blocks = ['1', '2', '3', '4', '5', '6'];
  assert.deepEqual(visibleMessageBlocks(blocks, false), blocks.slice(0, MAX_VISIBLE_BLOCKS));
  assert.deepEqual(visibleMessageBlocks(blocks, true), blocks);
});
