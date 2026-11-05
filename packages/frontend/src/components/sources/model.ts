import type { CitationPayload, CitationSource } from '../../types';
import type { MediaCitation, TextCitation } from '../../stream/types';

export type SourceKind = 'web' | 'document' | 'media' | 'agent';

export interface SourcePanelItem {
  id: string;
  marker?: number;
  kind: SourceKind;
  title: string;
  url?: string;
  file?: string;
  section?: string;
  snippet?: string;
  start?: number;
  end?: number | null;
}

function baseName(path: string): string {
  const parts = String(path || '').split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export function hostOf(url: string | undefined): string {
  if (!url) return '';
  try {
    return new URL(url).host.replace(/^www\./, '');
  } catch {
    return '';
  }
}

/** URL used by the local files router to open a document source. */
export function localFileHref(file: string, section?: string): string {
  const params = new URLSearchParams();
  params.set('path', file);
  if (section) params.set('section', section);
  return `/api/files/open?${params.toString()}`;
}

function sourceKey(source: CitationSource): string {
  if (source.url) return `url:${source.url}`;
  return `doc:${source.file}:${source.section || ''}`;
}

/**
 * Merge citation_map, text citations, media citations and legacy source
 * strings into one de-duplicated source list for the chat surface.
 */
export function buildSourceItems(
  citations?: CitationPayload | null,
  textCitations: readonly TextCitation[] = [],
  mediaCitations: readonly MediaCitation[] = [],
  legacySources: readonly string[] = [],
): SourcePanelItem[] {
  const items: SourcePanelItem[] = [];
  const seen = new Set<string>();
  const seenFiles = new Set<string>();

  for (const source of citations?.sources ?? []) {
    const key = sourceKey(source);
    if (seen.has(key)) continue;
    seen.add(key);
    if (source.file) seenFiles.add(source.file);
    const isWeb = source.kind === 'web' || Boolean(source.url);
    items.push({
      id: `citation-${source.marker}-${key}`,
      marker: source.marker,
      kind: isWeb ? (source.kind === 'agent' ? 'agent' : 'web') : 'document',
      title: source.title || hostOf(source.url) || baseName(source.file) || 'Source',
      url: source.url || undefined,
      file: source.file || undefined,
      section: source.section || undefined,
      snippet: source.snippet || source.content || undefined,
    });
  }

  textCitations.forEach((citation, index) => {
    const key = `doc:${citation.file}:${citation.section || ''}`;
    if (seen.has(key)) return;
    seen.add(key);
    if (citation.file) seenFiles.add(citation.file);
    items.push({
      id: `text-${citation.chunk_id ?? index}-${key}`,
      kind: 'document',
      title: citation.section || baseName(citation.file) || 'Document',
      file: citation.file,
      section: citation.section,
      snippet: citation.snippet,
    });
  });

  mediaCitations.forEach((citation, index) => {
    const key = `media:${citation.file}:${citation.start}`;
    if (seen.has(key)) return;
    seen.add(key);
    items.push({
      id: `media-${index}-${key}`,
      kind: 'media',
      title: `${baseName(citation.file)} @ ${formatTimestamp(citation.start)}`,
      file: citation.file,
      snippet: citation.snippet,
      start: citation.start,
      end: citation.end,
    });
  });

  legacySources.forEach((value, index) => {
    const text = String(value || '').trim();
    if (!text) return;
    const isUrl = /^https?:\/\//i.test(text);
    const key = isUrl ? `url:${text}` : `doc:${text}:`;
    if (seen.has(key)) return;
    // A legacy source carries no section, so treat it as a duplicate of any
    // already-listed document with the same path.
    if (!isUrl && seenFiles.has(text)) return;
    seen.add(key);
    if (!isUrl) seenFiles.add(text);
    items.push({
      id: `legacy-${index}-${key}`,
      kind: isUrl ? 'web' : 'document',
      title: isUrl ? hostOf(text) || text : baseName(text),
      url: isUrl ? text : undefined,
      file: isUrl ? undefined : text,
    });
  });

  return items;
}

export function formatTimestamp(seconds: number): string {
  const safe = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, '0')}`;
}
