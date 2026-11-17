/**
 * Speech playback for assistant messages.
 *
 * A module-level singleton (not context state) because only the speaking
 * message and the app shell need to react to it. Audio is synthesized by the
 * local backend (`/api/voice/synthesize`, Kokoro) in sentence-sized chunks so
 * the first sound arrives fast and Stop can cut in between chunks.
 */
import { useSyncExternalStore } from 'react';
import { api } from '../api';
import { cleanSentenceForTTS } from './audio';

export type SpeechStatus = 'idle' | 'loading' | 'playing';

export interface SpeechState {
  /** Identifier of the message currently spoken, or null when idle. */
  messageId: string | null;
  status: SpeechStatus;
}

/** Longest text run sent to the synthesizer per request. */
const CHUNK_MAX = 280;

/**
 * Split text into sentence-sized chunks for the synthesizer.
 * Exported for tests; users go through `speech.play`.
 */
export function splitForSpeech(text: string, max = CHUNK_MAX): string[] {
  const clean = cleanSentenceForTTS(text);
  if (!clean) return [];
  // Sentence-ish segments; the fallback keeps words without punctuation.
  const segments = clean.match(/[^.!?]+[.!?]*\s*|\S+/g) ?? [clean];
  const packed: string[] = [];
  let current = '';

  const pushCurrent = () => {
    const value = current.trim();
    if (value) packed.push(value);
    current = '';
  };

  for (const segment of segments) {
    const sentence = segment.trim();
    if (!sentence) continue;
    if (current && (current + ' ' + sentence).length > max) pushCurrent();
    current = current ? `${current} ${sentence}` : sentence;
    // A single run way past the limit (no sentence boundaries) is packed
    // word-by-word so one giant paragraph cannot block playback.
    while (current.length > max) {
      const words = current.split(/\s+/);
      let part = '';
      let cursor = 0;
      while (cursor < words.length) {
        const candidate = part ? `${part} ${words[cursor]}` : words[cursor];
        if (part && candidate.length > max) break;
        part = candidate;
        cursor += 1;
      }
      packed.push(part);
      current = words.slice(cursor).join(' ');
    }
  }
  pushCurrent();
  return packed;
}

let state: SpeechState = { messageId: null, status: 'idle' };
const listeners = new Set<(state: SpeechState) => void>();

let generation = 0;
let abortController: AbortController | null = null;
let currentAudio: HTMLAudioElement | null = null;
let currentUrl: string | null = null;

function emit() {
  for (const listener of listeners) listener(state);
}

function setState(next: SpeechState) {
  state = next;
  emit();
}

function teardown() {
  abortController?.abort();
  abortController = null;
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.removeAttribute('src');
    currentAudio = null;
  }
  if (currentUrl) {
    URL.revokeObjectURL(currentUrl);
    currentUrl = null;
  }
}

function stop() {
  generation += 1;
  teardown();
  setState({ messageId: null, status: 'idle' });
}

/** Play one WAV blob to completion; rejects on error or teardown. */
function playBlob(blob: Blob, gen: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudio = audio;
    currentUrl = url;
    let settled = false;

    const cleanup = () => {
      audio.removeEventListener('ended', onEnded);
      audio.removeEventListener('error', onError);
      if (currentAudio === audio) {
        currentAudio = null;
        currentUrl = null;
      }
      URL.revokeObjectURL(url);
    };
    const onEnded = () => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve();
    };
    const onError = () => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error('audio playback failed'));
    };
    audio.addEventListener('ended', onEnded);
    audio.addEventListener('error', onError);
    void audio.play().catch((error: unknown) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error instanceof Error ? error : new Error('playback blocked'));
    });
    if (gen !== generation) {
      // A newer request already took over; exit without flipping state.
      settled = true;
      cleanup();
      resolve();
    }
  });
}

async function play(messageId: string, text: string, voice: string) {
  const chunks = splitForSpeech(text);
  if (!chunks.length) return;
  generation += 1;
  const gen = generation;
  teardown();
  abortController = new AbortController();
  setState({ messageId, status: 'loading' });

  for (const chunk of chunks) {
    if (gen !== generation) return;
    let blob: Blob;
    try {
      blob = await api.voice.synthesize(chunk, voice, {
        signal: abortController.signal,
      });
    } catch {
      // Aborted because a newer playback took over: stay silent. A genuine
      // network/TTS failure just ends this playback.
      if (gen === generation) {
        teardown();
        setState({ messageId: null, status: 'idle' });
      }
      return;
    }
    if (gen !== generation) return;
    setState({ messageId, status: 'playing' });
    try {
      await playBlob(blob, gen);
    } catch {
      break;
    }
  }
  if (gen === generation) {
    teardown();
    setState({ messageId: null, status: 'idle' });
  }
}

export const speech = {
  getState: (): SpeechState => state,
  subscribe(listener: (next: SpeechState) => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  /** Speak a message, replacing anything already playing. */
  play,
  /** Toggle: speaks a message, or stops it if that message is playing. */
  toggle(messageId: string, text: string, voice: string) {
    if (state.messageId === messageId && state.status !== 'idle') stop();
    else void play(messageId, text, voice);
  },
  stop,
};

/** React binding: re-renders the caller while speech state changes. */
export function useSpeech(): SpeechState {
  return useSyncExternalStore(speech.subscribe, speech.getState);
}
