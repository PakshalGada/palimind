import test from 'node:test';
import assert from 'node:assert/strict';
import {
  makeMemoryEntry,
  memoryForScope,
  searchMemory,
} from '../src/utils/chatMemory.ts';

const entries = [
  makeMemoryEntry('Prefers concise answers', 'global', ''),
  makeMemoryEntry('Project uses Next.js', 'project', 'p1'),
  makeMemoryEntry('This chat is about pricing', 'chat', 's1'),
  makeMemoryEntry('Other project fact', 'project', 'p2'),
];

test('memory scopes include global, the active project and the active chat', () => {
  const visible = memoryForScope(entries, { sessionId: 's1', projectId: 'p1' });
  assert.deepEqual(
    visible.map((entry) => entry.text),
    ['Prefers concise answers', 'Project uses Next.js', 'This chat is about pricing'],
  );
});

test('memory scopes do not leak another project or another chat', () => {
  const other = memoryForScope(entries, { sessionId: 's2', projectId: 'p2' });
  assert.ok(other.some((entry) => entry.text === 'Other project fact'));
  assert.ok(!other.some((entry) => entry.text === 'Project uses Next.js'));
  assert.ok(!other.some((entry) => entry.text === 'This chat is about pricing'));
});

test('memory search filters by text', () => {
  assert.deepEqual(
    searchMemory(entries, 'pricing').map((entry) => entry.text),
    ['This chat is about pricing'],
  );
  assert.equal(searchMemory(entries, '   ').length, entries.length);
});
