import test from 'node:test';
import assert from 'node:assert/strict';
import {
  applyMention,
  findMentionToken,
  firstAgentMention,
} from '../src/utils/mentions.ts';

test('finds an @mention at the cursor after whitespace', () => {
  const token = findMentionToken('Summarise this @res');
  assert.equal(token?.query, 'res');
  assert.equal(token?.start, 'Summarise this '.length);
  assert.equal(token?.end, 'Summarise this @res'.length);
});

test('does not treat an email address as a mention', () => {
  assert.equal(findMentionToken('mail me at a@b'), null);
});

test('finds a bare @ at the start of the message', () => {
  const token = findMentionToken('@');
  assert.equal(token?.query, '');
  assert.equal(token?.start, 0);
});

test('replaces the typed query with the chosen agent', () => {
  const text = 'Ask @res about the report';
  const token = findMentionToken('Ask @res', 8);
  assert.ok(token);
  const result = applyMention(text, token, 'researcher');
  assert.equal(result.text, 'Ask @researcher about the report');
  assert.equal(result.cursor, 'Ask @researcher '.length);
});

test('extracts the first mention anywhere in a message', () => {
  assert.equal(firstAgentMention('please ask @researcher about X'), 'researcher');
  assert.equal(firstAgentMention('a@b is an email'), null);
});
