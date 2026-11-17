import { test } from 'node:test';
import assert from 'node:assert/strict';
import { splitForSpeech } from '../src/utils/speech.ts';

test('splitForSpeech drops markdown, code fences and sources lines', () => {
  const input = [
    '*Sources: a.pdf, b.md*',
    '## Heading',
    'Here is **bold** and `code`.',
    '```py',
    'print("never spoken")',
    '```',
    'Final sentence!',
  ].join('\n');
  const spoken = splitForSpeech(input).join(' ');
  assert.ok(!spoken.includes('Sources'));
  assert.ok(!spoken.includes('print'));
  assert.ok(!spoken.includes('##'));
  assert.ok(!spoken.includes('**'));
  assert.ok(spoken.includes('Here is bold and code.'));
  assert.ok(spoken.includes('Final sentence!'));
});

test('splitForSpeech keeps short text as one chunk', () => {
  assert.deepEqual(splitForSpeech('Short answer.'), ['Short answer.']);
});

test('splitForSpeech returns nothing for empty or markdown-only text', () => {
  assert.deepEqual(splitForSpeech(''), []);
  assert.deepEqual(splitForSpeech('```py\ncode()\n```'), []);
});

test('splitForSpeech packs oversized sentences below the limit', () => {
  const long = 'word '.repeat(80).trim() + '.';
  const chunks = splitForSpeech(long, 120);
  assert.ok(chunks.length > 1);
  for (const chunk of chunks) assert.ok(chunk.length <= 120);
  // No words lost.
  assert.equal(chunks.join(' ').split(/\s+/).length, 80);
});

test('splitForSpeech merges short sentences up to the limit', () => {
  const chunks = splitForSpeech('One. Two. Three. Four.', 12);
  assert.equal(chunks.length, 2);
  assert.equal(chunks[0], 'One. Two.');
  assert.equal(chunks[1], 'Three. Four.');
});
