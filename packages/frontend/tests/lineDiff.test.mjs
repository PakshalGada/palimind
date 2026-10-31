import test from 'node:test';
import assert from 'node:assert/strict';
import { diffLines } from '../src/utils/lineDiff.ts';

test('identical content produces only same rows', () => {
  const diff = diffLines('a\nb\nc', 'a\nb\nc');
  assert.equal(diff.added, 0);
  assert.equal(diff.removed, 0);
  assert.equal(diff.rows.length, 3);
  assert.ok(diff.rows.every(row => row.left.kind === 'same' && row.right.kind === 'same'));
});

test('marks changed lines as removed and added', () => {
  const diff = diffLines('one\ntwo\nthree', 'one\nTWO\nthree');
  assert.equal(diff.removed, 1);
  assert.equal(diff.added, 1);
  assert.deepEqual(
    diff.rows.map(row => [row.left?.text, row.right?.text]),
    [
      ['one', 'one'],
      ['two', undefined],
      [undefined, 'TWO'],
      ['three', 'three'],
    ],
  );
});

test('detects inserted lines', () => {
  const diff = diffLines('a\nc', 'a\nb\nc');
  assert.equal(diff.added, 1);
  assert.equal(diff.removed, 0);
  assert.deepEqual(
    diff.rows.map(row => row.right?.text),
    ['a', 'b', 'c'],
  );
});

test('detects removed lines', () => {
  const diff = diffLines('a\nb\nc', 'a\nc');
  assert.equal(diff.added, 0);
  assert.equal(diff.removed, 1);
  assert.equal(diff.rows[1].left.text, 'b');
  assert.equal(diff.rows[1].right, undefined);
});

test('line numbers stay aligned on both sides', () => {
  const diff = diffLines('a\nb\nc\nd', 'a\nb\nX\nd');
  const leftNumbers = diff.rows.map(row => row.left?.number).filter(Boolean);
  const rightNumbers = diff.rows.map(row => row.right?.number).filter(Boolean);
  assert.deepEqual(leftNumbers, [1, 2, 3, 4]);
  assert.deepEqual(rightNumbers, [1, 2, 3, 4]);
});

test('handles very large files without building a huge matrix', () => {
  const before = Array.from({ length: 700 }, (_, index) => `line ${index}`).join('\n');
  const after = before.replace('line 350', 'line changed');
  const diff = diffLines(before, after);
  assert.equal(diff.removed, 1);
  assert.equal(diff.added, 1);
  assert.ok(diff.rows.length > 690);
});
