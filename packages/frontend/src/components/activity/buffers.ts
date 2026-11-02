/**
 * Append-only streaming buffers. Text that arrives token by token never enters
 * React state: leaf components subscribe to a buffer and repaint at most once
 * per animation frame. Buffers keep a head and a tail when they exceed the cap
 * so the beginning of a long transcript survives.
 */

export interface BufferSnapshot {
  text: string;
  truncated: boolean;
  lines: number;
}

const MAX_BYTES = 256_000;
const HEAD_LINES = 200;
const TAIL_LINES = 1_800;

function schedule(callback: () => void): void {
  if (typeof requestAnimationFrame === 'function') {
    requestAnimationFrame(callback);
    return;
  }
  setTimeout(callback, 16);
}

export class StreamBuffer {
  private chunks: string[] = [];
  private size = 0;
  private snapshot: BufferSnapshot = { text: '', truncated: false, lines: 0 };
  private listeners = new Set<() => void>();
  private frame: number | null = null;

  append(text: string): void {
    if (!text) return;
    this.chunks.push(text);
    this.size += text.length;
    if (this.size > MAX_BYTES) this.compact();
    this.scheduleFlush();
  }

  reset(text = ''): void {
    this.chunks = text ? [text] : [];
    this.size = text.length;
    this.snapshot = this.build();
    this.notify();
  }

  getSnapshot = (): BufferSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private build(): BufferSnapshot {
    const text = this.chunks.join('');
    let lineCount = 0;
    for (let i = 0; i < text.length; i += 1) if (text[i] === '\n') lineCount += 1;
    return { text, truncated: lineCount > HEAD_LINES + TAIL_LINES, lines: lineCount + 1 };
  }

  private compact(): void {
    const text = this.chunks.join('');
    const lines = text.split('\n');
    if (lines.length <= HEAD_LINES + TAIL_LINES) {
      this.chunks = [text.slice(-MAX_BYTES)];
      this.size = this.chunks[0].length;
      return;
    }
    const head = lines.slice(0, HEAD_LINES).join('\n');
    const tail = lines.slice(-TAIL_LINES).join('\n');
    this.chunks = [head, '\n', tail];
    this.size = head.length + 1 + tail.length;
  }

  private scheduleFlush(): void {
    if (this.frame !== null) return;
    this.frame = 1;
    schedule(() => {
      this.frame = null;
      this.snapshot = this.build();
      this.notify();
    });
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}

export class BufferRegistry {
  private buffers = new Map<string, StreamBuffer>();

  get(key: string): StreamBuffer {
    let buffer = this.buffers.get(key);
    if (!buffer) {
      buffer = new StreamBuffer();
      this.buffers.set(key, buffer);
    }
    return buffer;
  }

  has(key: string): boolean {
    return this.buffers.has(key);
  }

  reset(): void {
    for (const buffer of this.buffers.values()) buffer.reset();
  }
}
