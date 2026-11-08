import type { Passage, ResultItem, ResultMeta, ToolStep } from './model';
import { hostOf } from './toolRegistry';

type Json = Record<string, unknown>;

function isRecord(value: unknown): value is Json {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function parseOutput(value: unknown, depth = 0): unknown {
  if (typeof value !== 'string') return value;
  const text = value.trim();
  if (!text || depth > 2) return value;
  if (!text.startsWith('{') && !text.startsWith('[')) return value;
  try {
    return parseOutput(JSON.parse(text), depth + 1);
  } catch {
    return value;
  }
}

function asArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (!isRecord(value)) return [];
  for (const key of ['results', 'items', 'hits', 'papers', 'works', 'entries', 'data', 'documents', 'filings']) {
    const candidate = value[key];
    if (Array.isArray(candidate)) return candidate;
  }
  return [];
}

function pick(record: Json, keys: readonly string[]): unknown {
  for (const key of keys) {
    const value = record[key];
    if (value !== undefined && value !== null && value !== '') return value;
  }
  return undefined;
}

function asText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return String(value);
  return '';
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value.replace(/,/g, ''));
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function authorsOf(value: unknown): string[] | undefined {
  if (typeof value === 'string' && value.trim()) {
    return value.split(/,\s*/).filter(Boolean).slice(0, 6);
  }
  if (Array.isArray(value)) {
    const names = value
      .map((entry) => {
        if (typeof entry === 'string') return entry;
        if (isRecord(entry)) {
          const author = entry.author;
          if (isRecord(author)) return asText(author.display_name ?? author.name);
          return asText(entry.name ?? entry.display_name);
        }
        return '';
      })
      .filter(Boolean);
    return names.length ? names.slice(0, 6) : undefined;
  }
  return undefined;
}

function metaOf(record: Json): ResultMeta {
  const date = asText(pick(record, ['date', 'published_at', 'published', 'publication_date', 'updated']));
  return {
    authors: authorsOf(pick(record, ['authors', 'author', 'authorships'])),
    year: asNumber(pick(record, ['year', 'publication_year', 'published_year'])),
    venue: asText(pick(record, ['venue', 'journal', 'container_title'])) || undefined,
    citations: asNumber(pick(record, ['citations', 'citationCount', 'cited_by', 'cited_by_count', 'num_citations'])),
    stars: asNumber(pick(record, ['stars', 'stargazers_count', 'star_count'])),
    points: asNumber(pick(record, ['points', 'score'])),
    comments: asNumber(pick(record, ['comments', 'descendants', 'num_comments', 'comment_count'])),
    form: asText(pick(record, ['form', 'form_type', 'filing_type'])) || undefined,
    filer: asText(pick(record, ['filer', 'company_name', 'entity_name'])) || undefined,
    date: date || undefined,
    status: asNumber(pick(record, ['status', 'status_code'])),
    size: asNumber(pick(record, ['size', 'bytes', 'content_length'])),
    pages: asNumber(pick(record, ['pages', 'page_count', 'num_pages'])),
  };
}

function urlOf(record: Json): string {
  const raw = asText(pick(record, ['url', 'link', 'html_url', 'permalink', 'doi', 'landing_page_url', 'href', 'story_url']));
  if (!raw) return '';
  if (raw.startsWith('http')) return raw;
  if (raw.startsWith('10.')) return `https://doi.org/${raw}`;
  return raw;
}

export function normalizeResults(output: unknown): ResultItem[] {
  const value = parseOutput(output);
  const items = asArray(value);
  const results: ResultItem[] = [];
  // Ids double as React keys and source identities; repeats (e.g. the same URL
  // returned twice) get an index suffix so neither entry is dropped.
  const seen = new Set<string>();
  const uniqueId = (id: string, index: number): string => {
    let next = id;
    if (seen.has(next)) next = `${id}#${index}`;
    for (let n = 2; seen.has(next); n += 1) next = `${id}#${index}-${n}`;
    seen.add(next);
    return next;
  };
  items.forEach((entry, index) => {
    if (typeof entry === 'string') {
      results.push({ id: uniqueId(`r${index}`, index), title: entry.slice(0, 160) });
      return;
    }
    if (!isRecord(entry)) return;
    const url = urlOf(entry);
    const title =
      asText(pick(entry, ['title', 'name', 'headline', 'story_title', 'display_name', 'paper_title'])) ||
      url ||
      `Result ${index + 1}`;
    const snippet = asText(
      pick(entry, ['snippet', 'abstract', 'description', 'summary', 'content', 'text', 'selftext']),
    );
    results.push({
      id: uniqueId(asText(pick(entry, ['id', 'objectID', 'doi', 'url'])) || `r${index}`, index),
      title: title.replace(/\s+/g, ' ').trim(),
      url: url || undefined,
      domain: url ? hostOf(url) : undefined,
      snippet: snippet ? snippet.replace(/\s+/g, ' ').trim().slice(0, 320) : undefined,
      meta: metaOf(entry),
    });
  });
  return results;
}

export function normalizePassages(output: unknown): Passage[] {
  const value = parseOutput(output);
  const items = asArray(value);
  const passages: Passage[] = [];
  items.forEach((entry, index) => {
    if (!isRecord(entry)) return;
    const docName = asText(
      pick(entry, ['docName', 'doc_name', 'file', 'file_path', 'source', 'title', 'document']),
    );
    const text = asText(pick(entry, ['text', 'content', 'snippet', 'chunk', 'quote']));
    if (!text) return;
    passages.push({
      id: asText(pick(entry, ['id', 'chunk_id', 'chunk_db_id'])) || `p${index}`,
      docId: asText(pick(entry, ['docId', 'doc_id', 'file', 'file_path', 'source'])) || docName,
      docName: docName.split(/[\\/]/).pop() || docName || 'Document',
      page: asNumber(pick(entry, ['page', 'page_number', 'pageNo'])),
      text: text.slice(0, 4_000),
      score: asNumber(pick(entry, ['score', 'relevance', 'similarity'])),
    });
  });
  return passages;
}

export interface TableData {
  columns: string[];
  rows: Record<string, unknown>[];
}

export function normalizeTable(output: unknown): TableData {
  const value = parseOutput(output);
  const rows = asArray(value).filter(isRecord);
  const columns: string[] = [];
  for (const row of rows.slice(0, 50)) {
    for (const key of Object.keys(row)) if (!columns.includes(key)) columns.push(key);
  }
  return { columns, rows };
}

export type ToolUIColor = 'default' | 'success' | 'warn' | 'danger';

export interface ToolUI {
  type: 'table' | 'keyvalue' | 'chart' | 'text';
  title?: string;
  columns?: string[];
  rows?: (string | number)[][];
  items?: { label: string; value: string | number }[];
  labels?: string[];
  values?: number[];
  text?: string;
  tone?: ToolUIColor;
}

const UI_TYPES = new Set(['table', 'keyvalue', 'chart', 'text']);

/**
 * A tool may return `{"ui": {...}, "text": "..."}` to render a typed,
 * interactive result instead of prose. This is the single dispatcher contract;
 * unknown shapes fall back to the normal family renderer.
 */
export function uiOf(output: unknown): ToolUI | null {
  const value = parseOutput(output);
  if (!isRecord(value)) return null;
  const candidate = isRecord(value.ui) ? value.ui : value;
  const type = asText(candidate.type);
  if (!UI_TYPES.has(type)) return null;
  const ui: ToolUI = { type: type as ToolUI['type'] };
  ui.title = asText(candidate.title) || undefined;
  ui.text = asText(candidate.text) || undefined;
  const tone = asText(candidate.tone);
  if (tone === 'success' || tone === 'warn' || tone === 'danger') ui.tone = tone;
  if (Array.isArray(candidate.columns)) ui.columns = candidate.columns.map(String);
  if (Array.isArray(candidate.rows)) {
    ui.rows = candidate.rows.map((row) =>
      Array.isArray(row) ? row.map((cell) => (typeof cell === 'number' ? cell : String(cell))) : [],
    );
  }
  if (Array.isArray(candidate.items)) {
    ui.items = candidate.items
      .filter(isRecord)
      .map((item) => ({ label: asText(item.label), value: asText(item.value) }))
      .filter((item) => item.label);
  }
  if (Array.isArray(candidate.labels)) ui.labels = candidate.labels.map(String);
  if (Array.isArray(candidate.values)) {
    ui.values = candidate.values.map((entry) => asNumber(entry) ?? 0);
  }
  return ui;
}

export function visualOf(output: unknown): import('../../types').VisualReply | null {
  const value = parseOutput(output);
  if (!isRecord(value)) return null;
  const record = isRecord(value.visual) ? value.visual : value;
  const url = asText(record.url ?? value.preview_url);
  const id = asText(record.id);
  if (!url && !id) return null;
  if (!url) return null;
  return {
    id: id || url,
    token: asText(record.token),
    title: asText(record.title) || 'Visual reply',
    height: asNumber(record.height) ?? 600,
    agent_id: asText(record.agent_id),
    message: asText(record.message),
    created_at: asNumber(record.created_at) ?? 0,
    url,
  };
}

export function textOf(output: unknown): string {
  const value = parseOutput(output);
  if (typeof value === 'string') return value;
  if (value == null) return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export interface DiffPayload {
  path: string;
  before?: string;
  after?: string;
  isNew?: boolean;
}

export function diffFromStep(output: unknown, args: unknown): DiffPayload {
  const value = parseOutput(output);
  const a = isRecord(args) ? args : {};
  const out = isRecord(value) ? value : {};
  const path =
    asText(pick(out, ['path', 'file', 'file_path'])) ||
    asText(pick(a, ['path', 'file', 'file_path', 'filename'])) ||
    'File';
  const before =
    asText(pick(out, ['old', 'before', 'old_string', 'original'])) ||
    asText(pick(a, ['old_string', 'old', 'before'])) ||
    undefined;
  const after =
    asText(pick(out, ['new', 'after', 'new_string', 'content'])) ||
    asText(pick(a, ['new_string', 'new', 'content'])) ||
    (typeof value === 'string' ? value : undefined);
  const isNew = out.created === true || a.create === true || (!before && Boolean(after));
  return { path, before, after, isNew };
}

export interface BrowserShot {
  src: string;
  label: string;
}

export function screenshotsOf(steps: readonly ToolStep[]): BrowserShot[] {
  const shots: BrowserShot[] = [];
  for (const step of steps) {
    if (step.name !== 'browser_screenshot' && step.name !== 'browser_open') continue;
    const value = parseOutput(step.output);
    if (typeof value === 'string' && value.startsWith('data:image')) {
      shots.push({ src: value, label: step.name });
      continue;
    }
    if (isRecord(value)) {
      const src = asText(pick(value, ['screenshot', 'image', 'data', 'path']));
      if (src.startsWith('data:image') || /\.(png|jpe?g|webp)$/i.test(src)) {
        shots.push({ src, label: step.name });
      }
    }
  }
  return shots;
}

export function pageTitleOf(steps: readonly ToolStep[]): string {
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const step = steps[i];
    const value = parseOutput(step.output);
    if (isRecord(value)) {
      const title = asText(pick(value, ['title', 'page_title']));
      if (title) return title;
    }
  }
  return '';
}

export interface WeatherData {
  location: string;
  temperature?: number;
  unit: string;
  condition?: string;
  hours: { label: string; value: number }[];
}

export function weatherOf(output: unknown, args: unknown): WeatherData {
  const value = parseOutput(output);
  const out = isRecord(value) ? value : {};
  const a = isRecord(args) ? args : {};
  const current = isRecord(out.current) ? out.current : out;
  const hourly = isRecord(out.hourly) ? out.hourly : {};
  const times = Array.isArray(hourly.time) ? hourly.time : [];
  const temps = Array.isArray(hourly.temperature_2m) ? hourly.temperature_2m : [];
  const hours: { label: string; value: number }[] = [];
  for (let i = 0; i < Math.min(times.length, temps.length, 8); i += 1) {
    const temperature = asNumber(temps[i]);
    if (temperature === undefined) continue;
    const label = typeof times[i] === 'string' ? String(times[i]).slice(11, 16) : `${i}`;
    hours.push({ label, value: temperature });
  }
  return {
    location:
      asText(pick(out, ['location', 'city', 'name'])) ||
      asText(pick(a, ['location', 'city', 'name'])) ||
      'Location',
    temperature: asNumber(pick(current, ['temperature', 'temperature_2m', 'temp'])),
    unit: asText(out.temperature_unit) || 'C',
    condition: asText(pick(current, ['condition', 'weather', 'summary'])) || undefined,
    hours,
  };
}

export interface GraphNode {
  id: string;
  label: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: { from: string; to: string; label?: string }[];
}

export function graphOf(output: unknown): GraphData {
  const value = parseOutput(output);
  if (!isRecord(value)) return { nodes: [], edges: [] };
  const rawNodes = Array.isArray(value.nodes) ? value.nodes : [];
  const nodes: GraphNode[] = rawNodes.slice(0, 30).map((entry, index) => {
    if (typeof entry === 'string') return { id: entry, label: entry };
    if (isRecord(entry)) {
      const id = asText(pick(entry, ['id', 'name', 'title'])) || `n${index}`;
      return { id, label: asText(pick(entry, ['label', 'name', 'title'])) || id };
    }
    return { id: `n${index}`, label: `Node ${index + 1}` };
  });
  const known = new Set(nodes.map((node) => node.id));
  const rawEdges = Array.isArray(value.edges) ? value.edges : [];
  const edges: GraphData['edges'] = [];
  for (const entry of rawEdges) {
    if (!entry || typeof entry !== 'object') continue;
    const record = entry as Record<string, unknown>;
    const from = asText(pick(record, ['from', 'source', 'src']));
    const to = asText(pick(record, ['to', 'target', 'dst']));
    if (!from || !to || !known.has(from) || !known.has(to)) continue;
    edges.push({ from, to, label: asText(pick(record, ['label', 'relation', 'type'])) || undefined });
  }
  return { nodes, edges };
}
