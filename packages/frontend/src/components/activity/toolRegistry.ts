import type { IconName } from './icons';
import type { ToolFamily } from './model';

export interface ToolDefinition {
  icon: IconName;
  /** Present participle, shown while the tool runs. */
  running: string;
  /** Past tense, shown once the tool settles. */
  done: string;
  family: ToolFamily;
  preview: (args: unknown) => string;
  approval?: true;
  /** Sub-kind used by the search body to pick the meta line. */
  itemKind?: 'web' | 'x' | 'news' | 'hn' | 'github' | 'stack' | 'paper' | 'filing' | 'wiki';
}

type Args = Record<string, unknown>;

function asArgs(args: unknown): Args {
  if (args && typeof args === 'object' && !Array.isArray(args)) return args as Args;
  return {};
}

function str(args: Args, keys: readonly string[]): string {
  for (const key of keys) {
    const value = args[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number') return String(value);
  }
  return '';
}

export function truncatePreview(text: string, max = 64): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

function firstLine(value: string, max = 64): string {
  return truncatePreview(value.split('\n')[0] ?? '', max);
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, '');
  } catch {
    return truncatePreview(url, 40);
  }
}

function urlHost(args: unknown): string {
  const value = str(asArgs(args), ['url', 'uri', 'href', 'link']);
  return value ? hostOf(value) : '';
}

function query(args: unknown): string {
  const a = asArgs(args);
  return truncatePreview(
    str(a, ['query', 'q', 'search_query', 'question', 'prompt', 'term', 'keywords']),
  );
}

function path(args: unknown): string {
  const a = asArgs(args);
  const raw = str(a, ['path', 'file', 'filepath', 'file_path', 'filename', 'directory', 'dir']);
  if (!raw) return '';
  return truncatePreview(raw.split(/[\\/]/).pop() || raw);
}

function code(args: unknown): string {
  const a = asArgs(args);
  return firstLine(str(a, ['code', 'source', 'script', 'snippet']));
}

function command(args: unknown): string {
  const a = asArgs(args);
  return firstLine(str(a, ['command', 'cmd', 'shell']));
}

function sql(args: unknown): string {
  const a = asArgs(args);
  return firstLine(str(a, ['sql', 'query', 'statement']));
}

function browserTarget(args: unknown): string {
  const a = asArgs(args);
  const label = str(a, ['label', 'element', 'selector', 'role', 'name', 'ref']);
  if (!label) return '';
  const secretLike =
    /password|passwd|secret|token|api[-_ ]?key|card|ssn/i.test(label) ||
    a.secret === true ||
    a.sensitive === true;
  const text = str(a, ['text', 'value']);
  if (!text) return truncatePreview(label);
  return `${truncatePreview(label, 28)} ${secretLike ? '********' : truncatePreview(text, 28)}`;
}

const search = (queryText: string, name: string): string => queryText || name;

export const TOOL_REGISTRY: Record<string, ToolDefinition> = {
  web_search: {
    icon: 'globe',
    running: 'Searching web',
    done: 'Searched web',
    family: 'search',
    itemKind: 'web',
    preview: (args) => search(query(args), 'web'),
  },
  x_search: {
    icon: 'x-brand',
    running: 'Searching X',
    done: 'Searched X',
    family: 'search',
    itemKind: 'x',
    preview: (args) => search(query(args), 'X'),
  },
  news_search: {
    icon: 'newspaper',
    running: 'Searching news',
    done: 'Searched news',
    family: 'search',
    itemKind: 'news',
    preview: (args) => search(query(args), 'news'),
  },
  hn_search: {
    icon: 'hacker-news',
    running: 'Searching Hacker News',
    done: 'Searched Hacker News',
    family: 'search',
    itemKind: 'hn',
    preview: (args) => search(query(args), 'Hacker News'),
  },
  github_search: {
    icon: 'github',
    running: 'Searching GitHub',
    done: 'Searched GitHub',
    family: 'search',
    itemKind: 'github',
    preview: (args) => search(query(args), 'GitHub'),
  },
  stackexchange_search: {
    icon: 'stack-exchange',
    running: 'Searching Stack Exchange',
    done: 'Searched Stack Exchange',
    family: 'search',
    itemKind: 'stack',
    preview: (args) => search(query(args), 'Stack Exchange'),
  },
  arxiv_search: {
    icon: 'arxiv',
    running: 'Searching arXiv',
    done: 'Searched arXiv',
    family: 'search',
    itemKind: 'paper',
    preview: (args) => search(query(args), 'arXiv'),
  },
  semantic_scholar_search: {
    icon: 'graduation-cap',
    running: 'Searching Semantic Scholar',
    done: 'Searched Semantic Scholar',
    family: 'search',
    itemKind: 'paper',
    preview: (args) => search(query(args), 'papers'),
  },
  openalex_search: {
    icon: 'openalex',
    running: 'Searching OpenAlex',
    done: 'Searched OpenAlex',
    family: 'search',
    itemKind: 'paper',
    preview: (args) => search(query(args), 'OpenAlex'),
  },
  crossref_search: {
    icon: 'quote',
    running: 'Searching Crossref',
    done: 'Searched Crossref',
    family: 'search',
    itemKind: 'paper',
    preview: (args) => search(query(args), 'Crossref'),
  },
  pubmed_search: {
    icon: 'heart-pulse',
    running: 'Searching PubMed',
    done: 'Searched PubMed',
    family: 'search',
    itemKind: 'paper',
    preview: (args) => search(query(args), 'PubMed'),
  },
  sec_edgar_search: {
    icon: 'landmark',
    running: 'Searching SEC filings',
    done: 'Searched SEC filings',
    family: 'search',
    itemKind: 'filing',
    preview: (args) => search(query(args), 'filings'),
  },
  wikipedia_search: {
    icon: 'book-open',
    running: 'Searching Wikipedia',
    done: 'Searched Wikipedia',
    family: 'search',
    itemKind: 'wiki',
    preview: (args) => search(query(args), 'Wikipedia'),
  },
  wikipedia_page: {
    icon: 'book-open-text',
    running: 'Reading Wikipedia',
    done: 'Read Wikipedia',
    family: 'page',
    preview: (args) => {
      const a = asArgs(args);
      return truncatePreview(str(a, ['title', 'page', 'query', 'topic']));
    },
  },
  fetch_url: {
    icon: 'download',
    running: 'Fetching page',
    done: 'Fetched page',
    family: 'page',
    preview: urlHost,
  },
  browse_url: {
    icon: 'compass',
    running: 'Browsing page',
    done: 'Browsed page',
    family: 'page',
    preview: urlHost,
  },
  pdf_read: {
    icon: 'file-text',
    running: 'Reading PDF',
    done: 'Read PDF',
    family: 'page',
    preview: (args) => path(args) || urlHost(asArgs(args)),
  },
  fetch_rss: {
    icon: 'rss',
    running: 'Reading feed',
    done: 'Read feed',
    family: 'feed',
    preview: urlHost,
  },
  read_file: {
    icon: 'file',
    running: 'Reading file',
    done: 'Read file',
    family: 'file',
    preview: path,
  },
  write_file: {
    icon: 'file-pen',
    running: 'Writing file',
    done: 'Wrote file',
    family: 'diff',
    approval: true,
    preview: path,
  },
  list_files: {
    icon: 'folder-open',
    running: 'Listing files',
    done: 'Listed files',
    family: 'tree',
    preview: (args) => path(args) || '.',
  },
  glob_files: {
    icon: 'folder-search',
    running: 'Matching files',
    done: 'Matched files',
    family: 'tree',
    preview: (args) => {
      const a = asArgs(args);
      return truncatePreview(str(a, ['pattern', 'glob']));
    },
  },
  grep_files: {
    icon: 'text-search',
    running: 'Searching files',
    done: 'Searched files',
    family: 'matches',
    preview: (args) => {
      const a = asArgs(args);
      return truncatePreview(str(a, ['pattern', 'query', 'regex']));
    },
  },
  search_replace: {
    icon: 'replace',
    running: 'Editing file',
    done: 'Edited file',
    family: 'diff',
    approval: true,
    preview: path,
  },
  document_search: {
    icon: 'files',
    running: 'Searching documents',
    done: 'Searched documents',
    family: 'passages',
    preview: (args) => search(query(args), 'documents'),
  },
  memory_search: {
    icon: 'brain',
    running: 'Recalling memory',
    done: 'Recalled memory',
    family: 'passages',
    preview: (args) => search(query(args), 'memory'),
  },
  query_graph: {
    icon: 'share-2',
    running: 'Querying graph',
    done: 'Queried graph',
    family: 'graph',
    preview: (args) => search(query(args), 'graph'),
  },
  csv_query: {
    icon: 'table',
    running: 'Querying CSV',
    done: 'Queried CSV',
    family: 'data',
    preview: (args) => sql(args) || path(args),
  },
  sqlite_query: {
    icon: 'database',
    running: 'Querying database',
    done: 'Queried database',
    family: 'data',
    preview: sql,
  },
  run_python: {
    icon: 'terminal-square',
    running: 'Running Python',
    done: 'Ran Python',
    family: 'code-run',
    approval: true,
    preview: code,
  },
  run_shell: {
    icon: 'terminal',
    running: 'Running command',
    done: 'Ran command',
    family: 'code-run',
    approval: true,
    preview: command,
  },
  todo_write: {
    icon: 'list-tree',
    running: 'Updating plan',
    done: 'Updated plan',
    family: 'text',
    preview: (args) => {
      const a = asArgs(args);
      const items = Array.isArray(a.items) ? a.items : [];
      return items.length ? `${items.length} ${items.length === 1 ? 'item' : 'items'}` : 'checklist';
    },
  },
  summarize: {
    icon: 'align-left',
    running: 'Summarizing',
    done: 'Summarized',
    family: 'text',
    preview: (args) => {
      const a = asArgs(args);
      return truncatePreview(str(a, ['source', 'url', 'path', 'text', 'title']));
    },
  },
  delegate: {
    icon: 'git-fork',
    running: 'Delegating',
    done: 'Delegated',
    family: 'subagent',
    preview: (args) => {
      const a = asArgs(args);
      return truncatePreview(str(a, ['task', 'prompt', 'goal', 'instruction']));
    },
  },
  browser_open: {
    icon: 'app-window',
    running: 'Opening page',
    done: 'Opened page',
    family: 'browser',
    preview: urlHost,
  },
  browser_snapshot: {
    icon: 'scan',
    running: 'Reading page',
    done: 'Read page',
    family: 'browser',
    preview: () => '',
  },
  browser_click: {
    icon: 'mouse-pointer-click',
    running: 'Clicking',
    done: 'Clicked',
    family: 'browser',
    approval: true,
    preview: browserTarget,
  },
  browser_type: {
    icon: 'keyboard',
    running: 'Typing',
    done: 'Typed',
    family: 'browser',
    approval: true,
    preview: browserTarget,
  },
  browser_press: {
    icon: 'corner-down-left',
    running: 'Pressing key',
    done: 'Pressed key',
    family: 'browser',
    approval: true,
    preview: (args) => {
      const a = asArgs(args);
      return truncatePreview(str(a, ['key', 'keys']));
    },
  },
  browser_scroll: {
    icon: 'arrow-down-up',
    running: 'Scrolling',
    done: 'Scrolled',
    family: 'browser',
    preview: (args) => {
      const a = asArgs(args);
      const direction = str(a, ['direction', 'dir']) || 'down';
      const amount = str(a, ['amount']);
      return amount ? `${direction} ${amount}` : direction;
    },
  },
  browser_back: {
    icon: 'arrow-left',
    running: 'Going back',
    done: 'Went back',
    family: 'browser',
    preview: () => '',
  },
  browser_forward: {
    icon: 'arrow-right',
    running: 'Going forward',
    done: 'Went forward',
    family: 'browser',
    preview: () => '',
  },
  browser_extract: {
    icon: 'scissors',
    running: 'Extracting',
    done: 'Extracted',
    family: 'browser',
    preview: (args) => {
      const a = asArgs(args);
      return truncatePreview(str(a, ['selector', 'goal', 'query']));
    },
  },
  browser_screenshot: {
    icon: 'camera',
    running: 'Capturing screenshot',
    done: 'Captured screenshot',
    family: 'browser',
    preview: () => '',
  },
  browser_tabs: {
    icon: 'layout-panel-top',
    running: 'Switching tabs',
    done: 'Switched tabs',
    family: 'browser',
    preview: (args) => {
      const a = asArgs(args);
      return truncatePreview(str(a, ['tab', 'index', 'title']));
    },
  },
  browser_close: {
    icon: 'x',
    running: 'Closing browser',
    done: 'Closed browser',
    family: 'browser',
    preview: () => '',
  },
  mqtt: {
    icon: 'radio',
    running: 'Using MQTT',
    done: 'Used MQTT',
    family: 'iot',
    preview: (args) => {
      const a = asArgs(args);
      const topic = str(a, ['topic']);
      const action = str(a, ['action', 'direction']) || 'publish';
      return truncatePreview(topic ? `${action} ${topic}` : action);
    },
  },
  open_meteo: {
    icon: 'cloud-sun',
    running: 'Checking weather',
    done: 'Checked weather',
    family: 'weather',
    preview: (args) => {
      const a = asArgs(args);
      const location = str(a, ['location', 'city', 'name', 'place']);
      if (location) return truncatePreview(location);
      const lat = a.latitude ?? a.lat;
      const lng = a.longitude ?? a.lng ?? a.lon;
      if (lat != null && lng != null) return `${lat}, ${lng}`;
      return '';
    },
  },
};

/** `web-search`, `web search` and `WebSearch` all resolve to `web_search`. */
export function normalizeToolName(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[\s.-]+/g, '_')
    .replace(/^tools?_/, '');
}

export function humanizeToolName(name: string): string {
  const words = normalizeToolName(name).split('_').filter(Boolean);
  if (words.length === 0) return 'Tool';
  const sentence = words.join(' ');
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

export function getToolDefinition(name: string): ToolDefinition {
  return (
    TOOL_REGISTRY[normalizeToolName(name)] ?? {
      icon: 'wrench',
      running: 'Working',
      done: 'Worked',
      family: 'generic',
      preview: (args) => {
        const a = asArgs(args);
        const value = str(a, ['query', 'path', 'url', 'command', 'input', 'text']);
        return value ? truncatePreview(value) : '';
      },
    }
  );
}

export function toolLabel(name: string, status: string): string {
  const def = getToolDefinition(name);
  return status === 'success' || status === 'error' || status === 'denied' || status === 'cancelled'
    ? def.done
    : def.running;
}

export function previewForTool(name: string, args: unknown): string {
  return getToolDefinition(name).preview(args);
}

export function toolDisplayName(name: string): string {
  const normalized = normalizeToolName(name);
  return TOOL_REGISTRY[normalized] ? humanizeToolName(normalized) : humanizeToolName(name);
}

export const TOOL_COUNT = Object.keys(TOOL_REGISTRY).length;