import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeResults, visualOf } from '../src/components/activity/toolOutput.ts';

test('normalizeResults gives duplicate URLs unique ids and keeps both', () => {
  const results = normalizeResults([
    { title: 'A', url: 'https://example.com/a' },
    { title: 'B', url: 'https://example.com/b' },
    { title: 'A again', url: 'https://example.com/a' },
    { id: 'x1', title: 'C', url: 'https://example.com/c' },
  ]);
  assert.equal(results.length, 4);
  const ids = results.map((r) => r.id);
  assert.equal(new Set(ids).size, ids.length);
  // Non-duplicates keep their natural ids.
  assert.equal(ids[0], 'https://example.com/a');
  assert.equal(ids[1], 'https://example.com/b');
  assert.equal(ids[3], 'x1');
  assert.notEqual(ids[2], ids[0]);
  assert.equal(results[2].url, 'https://example.com/a');
});

test('visualOf reads html_render output and preview urls', () => {
  const visual = visualOf(
    JSON.stringify({
      visual: {
        id: 'v1',
        token: 't',
        title: 'Chart',
        height: 420,
        agent_id: 'a1',
        url: '/api/visuals/v1?token=t',
      },
    }),
  );
  assert.equal(visual?.id, 'v1');
  assert.equal(visual?.height, 420);
  assert.equal(visual?.url, '/api/visuals/v1?token=t');
  assert.equal(visualOf({ preview_url: '/api/visuals/v2?token=x' })?.url, '/api/visuals/v2?token=x');
  assert.equal(visualOf('plain text'), null);
});
