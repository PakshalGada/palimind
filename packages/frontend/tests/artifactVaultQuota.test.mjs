import test from 'node:test';
import assert from 'node:assert/strict';

class QuotaStorage {
  constructor() {
    this.map = new Map();
    this.full = false;
  }
  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }
  setItem(key, value) {
    if (this.full) throw new Error('QuotaExceededError');
    this.map.set(key, String(value));
  }
  removeItem(key) {
    this.map.delete(key);
  }
}

const storage = new QuotaStorage();
globalThis.localStorage = storage;

function artifact(content) {
  return { id: 'quota', type: 'markdown', language: 'md', title: 'Quota', content };
}

test('a save that cannot persist metadata fails instead of reporting success', async () => {
  const { saveToVault, loadVault, getVaultVersionContent } = await import(
    '../src/utils/artifactVault.ts'
  );
  const first = await saveToVault(artifact('first body'), 'First');
  const firstVersion = first.versionId;

  storage.full = true;
  await assert.rejects(saveToVault(artifact('second body'), 'Second'), /storage is full/);
  storage.full = false;

  const saved = (await loadVault()).find(item => item.id === 'quota');
  assert.equal(saved.versions.length, 1);
  assert.equal(saved.content, 'first body');
  assert.equal(await getVaultVersionContent('quota', firstVersion), 'first body');
});

test('deleting fails without dropping version bodies when metadata cannot persist', async () => {
  const { removeFromVault, loadVault } = await import('../src/utils/artifactVault.ts');
  storage.full = true;
  await assert.rejects(removeFromVault('quota'), /storage is full/);
  storage.full = false;
  const saved = (await loadVault()).find(item => item.id === 'quota');
  assert.equal(saved.content, 'first body');
});
