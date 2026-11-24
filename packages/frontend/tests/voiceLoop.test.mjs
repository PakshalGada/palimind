import test from 'node:test';
import assert from 'node:assert/strict';
import { shouldAutoSendVoice, shouldRestartVoice } from '../src/utils/voiceLoop.ts';

test('hands-free sends non-empty transcripts only', () => {
  assert.equal(shouldAutoSendVoice('hello', true), true);
  assert.equal(shouldAutoSendVoice('   ', true), false);
  assert.equal(shouldAutoSendVoice('hello', false), false);
});

test('hands-free restarts only after a reply settles', () => {
  const base = {
    voiceMode: true,
    wasGenerating: true,
    isGenerating: false,
    isRecording: false,
    isTranscribing: false,
  };
  assert.equal(shouldRestartVoice(base), true);
  assert.equal(shouldRestartVoice({ ...base, isGenerating: true }), false);
  assert.equal(shouldRestartVoice({ ...base, wasGenerating: false }), false);
  assert.equal(shouldRestartVoice({ ...base, voiceMode: false }), false);
  assert.equal(shouldRestartVoice({ ...base, isRecording: true }), false);
});
