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

test('auto-speak is off by default and toggles globally', async () => {
  installStorage();
  const prefs = await import('../src/utils/voicePrefs.ts');
  assert.equal(prefs.isAutoSpeakOn(null), false);
  prefs.setAutoSpeak(true);
  assert.equal(prefs.isAutoSpeakOn(null), true);
  assert.equal(prefs.isAutoSpeakOn('chat'), true);
  prefs.setAutoSpeak(false);
  assert.equal(prefs.isAutoSpeakOn(null), false);
});

test('per-agent voice overrides the global voice', async () => {
  installStorage();
  const prefs = await import('../src/utils/voicePrefs.ts');
  prefs.setVoice('af_bella');
  assert.equal(prefs.getVoice(null), 'af_bella');
  prefs.setVoice('am_adam', 'agent-1');
  assert.equal(prefs.getVoice('agent:agent-1'), 'am_adam');
});
