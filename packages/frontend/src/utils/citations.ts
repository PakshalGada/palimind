import type { CitationPayload, CitationSource } from '../types';

const FENCE_RE = /```[\s\S]*?```/g;
const INLINE_CODE_RE = /`[^`]*`/g;
const MARKER_RE = /\[(\d+)\](?!\()/g;

function mask(text: string, pattern: RegExp): string {
  return text.replace(pattern, (match) => ' '.repeat(match.length));
}

function escapeAttr(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

export function sourceMap(payload?: CitationPayload): Map<number, CitationSource> {
  const map = new Map<number, CitationSource>();
  for (const source of payload?.sources ?? []) map.set(source.marker, source);
  return map;
}

/**
 * Turn inline `[n]` markers into interactive `<sup class="citation-ref">`
 * elements. Markers inside fenced/inline code are left untouched.
 */
export function annotateCitationMarkers(markdown: string, payload?: CitationPayload): string {
  if (!markdown || !payload?.sources?.length) return markdown;

  const sources = sourceMap(payload);
  const masked = mask(mask(markdown, FENCE_RE), INLINE_CODE_RE);

  const inserts: { start: number; end: number; marker: number }[] = [];
  MARKER_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = MARKER_RE.exec(masked)) !== null) {
    const marker = Number(match[1]);
    if (!sources.has(marker)) continue;
    inserts.push({ start: match.index, end: match.index + match[0].length, marker });
  }

  let out = markdown;
  for (let i = inserts.length - 1; i >= 0; i--) {
    const { start, end, marker } = inserts[i];
    const source = sources.get(marker);
    const title = escapeAttr(source?.title || `Source ${marker}`);
    const sup = `<sup class="citation-ref" data-citation="${marker}" title="${title}">[${marker}]</sup>`;
    out = out.slice(0, start) + sup + out.slice(end);
  }
  return out;
}
