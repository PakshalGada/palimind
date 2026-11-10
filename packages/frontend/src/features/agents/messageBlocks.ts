/**
 * Split one assistant answer into short chat bubbles.
 *
 * This is deliberately client-side: every provider (local Ollama, OpenCode,
 * ACP) streams one text answer, and the conversation should look the same no
 * matter which one produced it. Code fences, lists and tables stay together;
 * an oversized paragraph is split at sentence boundaries only as a fallback.
 */

export const MAX_BLOCK_CHARS = 320;
export const MAX_VISIBLE_BLOCKS = 4;

const SENTENCE_BREAK = /(?<=[.!?])\s+/;

function isFence(line: string): boolean {
  return /^\s*(```|~~~)/.test(line);
}

function isListLine(line: string): boolean {
  return /^\s*(?:[-*+]|\d+[.)])\s+/.test(line);
}

function isTableLine(line: string): boolean {
  return /^\s*\|/.test(line);
}

function splitParagraphs(text: string): string[] {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: string[] = [];
  let current: string[] = [];
  let inFence = false;

  const flush = () => {
    const value = current.join('\n').trim();
    if (value) blocks.push(value);
    current = [];
  };

  for (const line of lines) {
    if (isFence(line)) {
      inFence = !inFence;
      current.push(line);
      continue;
    }
    if (!inFence && !line.trim()) {
      flush();
      continue;
    }
    current.push(line);
  }
  flush();
  return blocks;
}

function splitLongBlock(block: string, maxChars: number): string[] {
  if (block.length <= maxChars) return [block];
  if (isFence(block.split('\n')[0] || '')) return [block];

  // Lists and tables read badly when cut at a sentence; keep them whole and
  // let the bubble scroll horizontally instead.
  const lines = block.split('\n');
  if (lines.some(isListLine) || lines.some(isTableLine)) return [block];

  const sentences = block.split(SENTENCE_BREAK).filter(Boolean);
  if (sentences.length <= 1) {
    // A single enormous sentence: split on words, keeping the text intact.
    const words = block.split(/\s+/);
    const out: string[] = [];
    let part = '';
    for (const word of words) {
      if (part && part.length + word.length + 1 > maxChars) {
        out.push(part);
        part = word;
      } else {
        part = part ? `${part} ${word}` : word;
      }
    }
    if (part) out.push(part);
    return out;
  }

  const out: string[] = [];
  let part = '';
  for (const sentence of sentences) {
    if (part && part.length + sentence.length + 1 > maxChars) {
      out.push(part);
      part = sentence;
    } else {
      part = part ? `${part} ${sentence}` : sentence;
    }
  }
  if (part) out.push(part);
  return out;
}

export function splitMessageBlocks(
  text: string,
  options: { maxChars?: number } = {},
): string[] {
  const maxChars = Math.max(80, options.maxChars ?? MAX_BLOCK_CHARS);
  const input = String(text || '').trim();
  if (!input) return [];
  const blocks: string[] = [];
  for (const paragraph of splitParagraphs(input)) {
    blocks.push(...splitLongBlock(paragraph, maxChars));
  }
  return blocks;
}

export function visibleMessageBlocks(
  blocks: readonly string[],
  expanded: boolean,
  maxVisible = MAX_VISIBLE_BLOCKS,
): string[] {
  if (expanded || blocks.length <= maxVisible) return [...blocks];
  return blocks.slice(0, maxVisible);
}
