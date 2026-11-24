import test from 'node:test';
import assert from 'node:assert/strict';
import { redactText, redactionCounts } from '../src/utils/redaction.ts';

test('redacts emails, tokens and API keys', () => {
  const result = redactText(
    'Mail alice@example.com, use Bearer abcdefghijklmnop1234 and sk-live-1234567890ABCDE.',
  );
  assert.doesNotMatch(result.text, /alice@example\.com/);
  assert.doesNotMatch(result.text, /abcdefghijklmnop1234/);
  assert.doesNotMatch(result.text, /sk-live-1234567890ABCDE/);
  assert.match(result.text, /\[REDACTED:EMAIL\]/);
  assert.match(result.text, /\[REDACTED:BEARER TOKEN\]/);
  assert.match(result.text, /\[REDACTED:API KEY\]/);
  const counts = redactionCounts(result.matches);
  assert.equal(counts.email, 1);
  assert.equal(counts.bearer, 1);
  assert.equal(counts['api-key'], 1);
});

test('leaves ordinary text alone', () => {
  const result = redactText('Revenue grew 18% in Q3 across 3 regions.');
  assert.equal(result.matches.length, 0);
  assert.equal(result.text, 'Revenue grew 18% in Q3 across 3 regions.');
});
