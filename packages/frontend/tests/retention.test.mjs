import test from 'node:test';
import assert from 'node:assert/strict';

function installStorage() {
  const values = new Map();
  globalThis.localStorage = {
    getItem: (key) => (values.has(key) ? values.get(key) : null),
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
  };
}

test('retention defaults, saves and validates per chat', async () => {
  installStorage();
  const retention = await import('../src/utils/retention.ts');
  assert.equal(retention.loadRetention('s1'), 0);
  retention.saveRetention('s1', 30);
  assert.equal(retention.loadRetention('s1'), 30);
  assert.equal(retention.loadRetention('s2'), 0);
  assert.equal(retention.retentionLabel(30), 'Keep for 30 days');
  assert.equal(retention.retentionLabel(0), 'Keep until I delete');
});
