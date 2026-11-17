/**
 * Voice-output preferences, persisted in localStorage.
 *
 * There is one global default plus optional per-agent overrides: the global
 * switch controls plain chat, and an agent can have its own auto-speak and
 * voice choice (used by the agent Settings drawer).
 */

export const DEFAULT_TTS_VOICE = 'af_bella';

/** Kokoro voices bundled with the backend model files. */
export const TTS_VOICES: { id: string; label: string }[] = [
  { id: 'af_bella', label: 'Bella (female, US)' },
  { id: 'af_nicole', label: 'Nicole (female, US)' },
  { id: 'af_sarah', label: 'Sarah (female, US)' },
  { id: 'af_sky', label: 'Sky (female, US)' },
  { id: 'am_adam', label: 'Adam (male, US)' },
  { id: 'am_michael', label: 'Michael (male, US)' },
  { id: 'bf_emma', label: 'Emma (female, UK)' },
  { id: 'bf_isabella', label: 'Isabella (female, UK)' },
  { id: 'bm_george', label: 'George (male, UK)' },
  { id: 'bm_lewis', label: 'Lewis (male, UK)' },
];

const AUTO_KEY = 'palimind:voice:auto';
const VOICE_KEY = 'palimind:voice:name';

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // storage is optional
  }
}

/** Extract the agent id from a chat scope such as `agent:<id>`. */
export function agentIdFromScope(scope?: string | null): string | null {
  if (!scope || !scope.startsWith('agent:')) return null;
  const id = scope.slice('agent:'.length).trim();
  return id || null;
}

/**
 * Whether finished assistant replies in this scope should be spoken
 * automatically. A per-agent override wins over the global switch.
 */
export function isAutoSpeakOn(scope?: string | null): boolean {
  const agentId = agentIdFromScope(scope);
  if (agentId) {
    const override = autoSpeakOverride(agentId);
    if (override !== 'inherit') return override === 'on';
  }
  return read(AUTO_KEY) === '1';
}

/** The effective auto-speak mode for an agent: its override or `inherit`. */
export function autoSpeakOverride(agentId: string): 'inherit' | 'on' | 'off' {
  const value = read(`${AUTO_KEY}:${agentId}`);
  if (value === '1') return 'on';
  if (value === '0') return 'off';
  return 'inherit';
}

export function setAutoSpeak(on: boolean, agentId?: string | null) {
  write(agentId ? `${AUTO_KEY}:${agentId}` : AUTO_KEY, on ? '1' : '0');
}

/** Drop a per-agent override so the agent falls back to the global switch. */
export function clearAutoSpeak(agentId: string) {
  write(`${AUTO_KEY}:${agentId}`, null);
}

/** Synthesizer voice for a scope (per-agent pick beats the global pick). */
export function getVoice(scope?: string | null): string {
  const agentId = agentIdFromScope(scope);
  if (agentId) {
    const override = read(`${VOICE_KEY}:${agentId}`);
    if (override) return override;
  }
  return read(VOICE_KEY) || DEFAULT_TTS_VOICE;
}

export function setVoice(voice: string, agentId?: string | null) {
  write(agentId ? `${VOICE_KEY}:${agentId}` : VOICE_KEY, voice || null);
}
