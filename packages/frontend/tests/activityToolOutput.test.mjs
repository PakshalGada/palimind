import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeResults, uiOf, visualOf } from '../src/components/activity/toolOutput.ts';

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

test('uiOf reads the typed tool UI contract', () => {
  const table = uiOf(
    JSON.stringify({ ui: { type: 'table', title: 'Rows', columns: ['a'], rows: [[1]] } }),
  );
  assert.equal(table?.type, 'table');
  assert.deepEqual(table?.columns, ['a']);
  assert.deepEqual(table?.rows, [[1]]);

  const chart = uiOf({ type: 'chart', labels: ['x'], values: ['3'] });
  assert.equal(chart?.type, 'chart');
  assert.deepEqual(chart?.values, [3]);

  const kv = uiOf({ ui: { type: 'keyvalue', items: [{ label: 'Status', value: 'ok' }] } });
  assert.equal(kv?.items?.[0].label, 'Status');

  assert.equal(uiOf({ type: 'unknown' }), null);
  assert.equal(uiOf('plain'), null);
});
