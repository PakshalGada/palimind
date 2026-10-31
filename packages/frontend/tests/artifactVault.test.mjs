import test from 'node:test';
import assert from 'node:assert/strict';

class MemoryStorage {
  constructor() {
    this.map = new Map();
  }
  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }
  setItem(key, value) {
    this.map.set(key, String(value));
  }
  removeItem(key) {
    this.map.delete(key);
  }
  clear() {
    this.map.clear();
  }
}

const storage = new MemoryStorage();
globalThis.localStorage = storage;

const KEY = 'palimind:artifacts';
let vaultModule;
const vault = () => (vaultModule ??= import('../src/utils/artifactVault.ts'));

function artifact(content, id) {
  return { id, type: 'markdown', language: 'md', title: 'Test artifact', content };
}

test('artifact vault', async t => {
  await t.test('migrates legacy localStorage content into IndexedDB', async () => {
    storage.clear();
    storage.setItem(
      KEY,
      JSON.stringify([
        {
          id: 'legacy',
          type: 'markdown',
          language: 'md',
          title: 'Legacy artifact',
          content: 'current body',
          savedAt: 1000,
          currentVersionId: 'legacy:v2',
          versions: [
            {
              id: 'legacy:v1',
              artifactId: 'legacy',
              content: 'older body',
              savedAt: 900,
              note: 'First',
            },
            {
              id: 'legacy:v2',
              artifactId: 'legacy',
              content: 'current body',
              savedAt: 1000,
              note: 'Second',
            },
          ],
        },
      ]),
    );

    const { loadVault, getVaultVersionContent } = await vault();
    const items = await loadVault();
    assert.equal(items.length, 1);
    assert.equal(items[0].content, 'current body');
    assert.equal(items[0].versions.length, 2);
    assert.equal(items[0].versions[0].size, 'older body'.length);
    assert.equal(await getVaultVersionContent('legacy', 'legacy:v1'), 'older body');
    assert.equal(await getVaultVersionContent('legacy', 'legacy:v2'), 'current body');

    const raw = storage.getItem(KEY) ?? '';
    assert.ok(!raw.includes('"content"'), 'localStorage should only hold metadata');
  });

  await t.test('does not duplicate unchanged versions', async () => {
    const { saveToVault } = await vault();
    const first = await saveToVault(artifact('same body', 'dup'), 'First');
    assert.equal(first.created, true);
    const second = await saveToVault(artifact('same body', 'dup'), 'Second');
    assert.equal(second.created, false);
    const saved = second.items.find(item => item.id === 'dup');
    assert.equal(saved.versions.length, 1);
    assert.equal(saved.versions[0].note, 'First');
  });

  await t.test('restores by moving the current pointer without duplicating', async () => {
    const { saveToVault, restoreVaultVersion, loadVault } = await vault();
    const a = await saveToVault(artifact('A body', 'restore'), 'A');
    const aVersion = a.items
      .find(item => item.id === 'restore')
      .versions.find(version => version.note === 'A');
    await saveToVault(artifact('B body', 'restore'), 'B');
    await restoreVaultVersion('restore', aVersion.id);

    const items = await loadVault();
    const saved = items.find(item => item.id === 'restore');
    assert.equal(saved.content, 'A body');
    assert.equal(saved.currentVersionId, aVersion.id);
    assert.equal(saved.versions.length, 2);
  });

  await t.test('autosave drafts skip unchanged content and mark autosaved', async () => {
    const { saveDraft, loadVault } = await vault();
    const unchanged = await saveDraft(artifact('A body', 'restore'), 'Before restore');
    assert.equal(unchanged.created, false);

    const changed = await saveDraft(artifact('draft body', 'restore'), 'Before close');
    assert.equal(changed.created, true);
    const saved = (await loadVault()).find(item => item.id === 'restore');
    assert.equal(saved.content, 'draft body');
    assert.equal(saved.versions.at(-1).autosaved, true);
    assert.equal(saved.versions.at(-1).note, 'Before close');
  });

  await t.test('deleting an artifact removes its version bodies', async () => {
    const { removeFromVault, getVaultVersionContent, loadVault } = await vault();
    const dup = (await loadVault()).find(item => item.id === 'dup');
    const versionId = dup.versions[0].id;
    await removeFromVault('dup');
    assert.equal(await getVaultVersionContent('dup', versionId), null);
  });
});
