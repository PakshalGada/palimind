/**
 * Artifact detection.
 *
 * Scans assistant Markdown for fenced code blocks that describe a rich,
 * renderable output, for unfenced Markdown tables, and for long-form prose
 * that is clearly document-shaped. Detected artifacts are made available to
 * the side panel for preview, editing, export and saving.
 *
 * Detection is line-based rather than regex-only so partial fences can be
 * surfaced while the model streams. Identifiers are derived from the fence's
 * position in the message, which keeps an artifact stable while its content
 * grows token by token.
 */

export type ArtifactType =
  | 'html'
  | 'svg'
  | 'mermaid'
  | 'react'
  | 'markdown'
  | 'code'
  | 'document'
  | 'slide-outline'
  | 'table'
  | 'code-file'
  | 'multi-file';

export interface ArtifactFile {
  /** Path from the `--- file: path ---` header. */
  path: string;
  content: string;
  /** Highlight.js-friendly language derived from the file extension. */
  language: string;
}

export interface Artifact {
  /** Stable id derived from the artifact's position in the message. */
  id: string;
  type: ArtifactType;
  /** The raw fence language as written (e.g. `tsx`). */
  language: string;
  title: string;
  content: string;
  /** Index of the source message within the session. */
  messageIndex: number;
  /** Paths extracted from `--- file: path ---` headers. */
  filePaths?: string[];
  /** Individual files extracted from `--- file: path ---` sections. */
  files?: ArtifactFile[];
  /** True while the fence is still open and the assistant is streaming. */
  streaming?: boolean;
  /** False when the fence never closed (truncated response). */
  closed?: boolean;
}

/**
 * Fence languages that are allowed to create an artifact.
 *
 * The product rule is: only generated Office/PowerPoint deliverables open the
 * artifact panel. Markdown answers, tables, prose, HTML, SVG, diagrams and
 * code fences stay inline in the conversation.
 */
const LANGUAGE_MAP: Record<string, ArtifactType> = {
  document: 'document',
  doc: 'document',
  docx: 'document',
  word: 'document',
  slides: 'slide-outline',
  slide: 'slide-outline',
  deck: 'slide-outline',
  ppt: 'slide-outline',
  pptx: 'slide-outline',
  presentation: 'slide-outline',
  'slide-outline': 'slide-outline',
};

const FILE_HEADER_RE = /^\s*---\s*file:\s*(.+?)\s*---\s*$/;

const EXTENSION_LANGUAGES: Record<string, string> = {
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  py: 'python',
  rb: 'ruby',
  rs: 'rust',
  md: 'markdown',
  markdown: 'markdown',
  mdx: 'markdown',
  html: 'html',
  htm: 'html',
  xml: 'xml',
  svg: 'xml',
  css: 'css',
  scss: 'scss',
  less: 'less',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  toml: 'ini',
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  sql: 'sql',
  go: 'go',
  java: 'java',
  kt: 'kotlin',
  kts: 'kotlin',
  swift: 'swift',
  c: 'c',
  h: 'c',
  cpp: 'cpp',
  cc: 'cpp',
  hpp: 'cpp',
  cs: 'csharp',
  php: 'php',
  dart: 'dart',
  lua: 'lua',
  graphql: 'graphql',
  diff: 'diff',
  txt: 'text',
};

/** Derive a highlight.js language name from a file path. */
export function languageForPath(path: string): string {
  const extension = path.split('.').pop()?.toLowerCase() || '';
  return EXTENSION_LANGUAGES[extension] || extension || 'text';
}

function firstHeading(content: string): string | undefined {
  return content.match(/^\s*#{1,6}\s+(.+)$/m)?.[1]?.trim();
}

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

/**
 * Split multi-file artifact content into a file list.
 *
 * ```
 * --- file: src/app.ts ---
 * export const app = ...
 * --- file: styles.css ---
 * body { ... }
 * ```
 */
export function parseArtifactFiles(content: string): ArtifactFile[] {
  const byPath = new Map<string, string[]>();
  let current: { path: string; lines: string[] } | null = null;

  const flush = () => {
    if (!current) return;
    const body = current.lines.join('\n').replace(/^\n+|\s+$/g, '');
    byPath.set(current.path, body.split('\n'));
    current = null;
  };

  for (const line of content.split('\n')) {
    const match = line.match(FILE_HEADER_RE);
    if (match) {
      flush();
      const path = match[1].trim();
      if (path) current = { path, lines: [] };
      continue;
    }
    if (current) current.lines.push(line);
  }
  flush();

  return [...byPath.entries()].map(([path, lines]) => ({
    path,
    content: lines.join('\n'),
    language: languageForPath(path),
  }));
}

function deriveTitle(
  type: ArtifactType,
  language: string,
  content: string,
  files: ArtifactFile[],
  context = '',
): string {
  if (type === 'multi-file') {
    const names = files.map(file => fileName(file.path));
    return `${files.length || 'Multiple'} files — ${names.slice(0, 2).join(', ')}`.slice(0, 72);
  }
  if (type === 'code-file' && files[0]) {
    return fileName(files[0].path).slice(0, 72);
  }

  const heading = firstHeading(content);
  if (heading) return heading.slice(0, 72);

  if (type === 'slide-outline') {
    const firstLine = content
      .split('\n')
      .map(line => line.trim())
      .find(line => line.length > 0);
    if (firstLine) {
      return firstLine
        .replace(/^#+\s*/, '')
        .replace(/^slide\s*\d+\s*[:.-]\s*/i, '')
        .replace(/^[-*]\s*/, '')
        .slice(0, 72);
    }
  }
  if (type === 'table' && context) return context.slice(0, 72);
  if (type === 'html') {
    const title = content.match(/<title[^>]*>([^<]+)<\/title>/i)?.[1]?.trim();
    if (title) return title.slice(0, 72);
  }

  const label =
    type === 'code'
      ? language || 'Code'
      : type === 'markdown' || type === 'document'
        ? 'Document'
        : type === 'slide-outline'
          ? 'Slide outline'
          : type === 'table'
            ? 'Table'
            : type === 'code-file'
              ? 'Code file'
              : type.charAt(0).toUpperCase() + type.slice(1);
  return `${label} artifact`;
}

function fenceLanguage(info: string): string {
  const token = info.trim().split(/\s+/)[0] || '';
  const cleaned = token.replace(/^\{\.?/, '').replace(/\}$/, '').toLowerCase();
  return /^[a-z0-9+#._-]+$/.test(cleaned) ? cleaned : '';
}

interface ScannedFence {
  ordinal: number;
  language: string;
  content: string;
  closed: boolean;
}

interface FenceScan {
  fences: ScannedFence[];
}

const OPEN_FENCE_RE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
const CLOSE_FENCE_RE = /^ {0,3}(`{3,}|~{3,})\s*$/;

/**
 * Walk the message line by line, tracking fence state.
 *
 * Unlike a `/\`\`\`([\s\S]*?)\`\`\`/g` scan this keeps an unclosed fence open
 * until the end of the message, which lets the panel show an artifact while
 * the model is still writing it.
 */
function scanFences(markdown: string): FenceScan {
  const lines = markdown.split('\n');
  const fences: ScannedFence[] = [];

  let open: {
    char: string;
    length: number;
    info: string;
    body: string[];
    start: number;
  } | null = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (!open) {
      const match = line.match(OPEN_FENCE_RE);
      if (!match) continue;
      const char = match[1][0];
      const info = match[2].trim();
      // A backtick fence's info string may not contain another backtick,
      // which keeps inline ``code`` from being mistaken for a fence.
      if (char === '`' && info.includes('`')) continue;
      open = { char, length: match[1].length, info, body: [], start: i };
      continue;
    }

    const close = line.match(CLOSE_FENCE_RE);
    if (close && close[1][0] === open.char && close[1].length >= open.length) {
      fences.push({
        ordinal: fences.length,
        language: fenceLanguage(open.info),
        content: open.body.join('\n').replace(/\s+$/, ''),
        closed: true,
      });
      open = null;
    } else {
      open.body.push(line);
    }
  }

  if (open) {
    fences.push({
      ordinal: fences.length,
      language: fenceLanguage(open.info),
      content: open.body.join('\n').replace(/\s+$/, ''),
      closed: false,
    });
  }

  return { fences };
}

function detectFenceArtifact(
  fence: ScannedFence,
  messageIndex: number,
  isStreaming: boolean,
): Artifact | null {
  const language = fence.language;
  const content = fence.content;
  if (!content.trim()) return null;

  // Only Office/PowerPoint fences create artifacts. Everything else
  // (Markdown, tables, HTML, SVG, diagrams, code) stays in the transcript.
  const type = LANGUAGE_MAP[language];
  if (!type) return null;

  return {
    id: `fence-${messageIndex}-${fence.ordinal}`,
    type,
    language: language || (type === 'slide-outline' ? 'slides' : ''),
    title: deriveTitle(type, language, content, []),
    content,
    messageIndex,
    ...(fence.closed || !isStreaming ? {} : { streaming: true }),
    closed: fence.closed,
  };
}

export interface ParseArtifactOptions {
  /** True while the assistant is still writing this message. */
  streaming?: boolean;
}

export function parseArtifacts(
  markdown: string,
  messageIndex = 0,
  options: ParseArtifactOptions = {},
): Artifact[] {
  if (!markdown) return [];

  const streaming = options.streaming === true;
  const { fences } = scanFences(markdown);
  const artifacts: Artifact[] = [];

  for (const fence of fences) {
    const artifact = detectFenceArtifact(fence, messageIndex, streaming);
    if (artifact) artifacts.push(artifact);
  }

  // De-duplicate by stable id while preserving message order.
  const seen = new Set<string>();
  return artifacts.filter(artifact => {
    if (seen.has(artifact.id)) return false;
    seen.add(artifact.id);
    return true;
  });
}

export interface ArtifactSource {
  role: string;
  content: string;
}

/**
 * Index the live assistant message will occupy once persisted.
 *
 * The client renders the in-flight turn separately, so the session normally
 * still ends at the previous assistant message. If a session refresh has
 * already stored the current user message, the assistant lands right after it
 * instead of one slot later.
 */
export function nextAssistantMessageIndex(
  messages: ArtifactSource[] | undefined,
): number {
  const list = messages ?? [];
  const last = list[list.length - 1];
  return last?.role === 'user' ? list.length : list.length + 1;
}

/** Collect artifacts from the assistant messages of a conversation. */
export function collectArtifacts(messages: ArtifactSource[] | undefined): Artifact[] {
  if (!messages?.length) return [];
  const out: Artifact[] = [];
  const seen = new Set<string>();
  messages.forEach((msg, index) => {
    if (msg.role === 'user') return;
    for (const artifact of parseArtifacts(msg.content || '', index)) {
      if (seen.has(artifact.id)) continue;
      seen.add(artifact.id);
      out.push(artifact);
    }
  });
  return out;
}

export const ARTIFACT_TYPE_LABEL: Record<ArtifactType, string> = {
  html: 'HTML',
  svg: 'SVG',
  mermaid: 'Diagram',
  react: 'React',
  markdown: 'Markdown',
  code: 'Code',
  document: 'Document',
  'slide-outline': 'Slides',
  table: 'Table',
  'code-file': 'Code file',
  'multi-file': 'Multi-file',
};

export const ARTIFACT_EXTENSION: Record<ArtifactType, string> = {
  html: 'html',
  svg: 'svg',
  mermaid: 'mmd',
  react: 'jsx',
  markdown: 'md',
  code: 'txt',
  document: 'md',
  'slide-outline': 'md',
  table: 'md',
  'code-file': 'txt',
  'multi-file': 'txt',
};

export type ExportFormat = 'md' | 'html' | 'pdf' | 'docx' | 'pptx' | 'png';

export const EXPORT_FORMAT_LABEL: Record<ExportFormat, string> = {
  md: 'Markdown (.md)',
  html: 'HTML (.html)',
  pdf: 'PDF (.pdf)',
  docx: 'Word (.docx)',
  pptx: 'PowerPoint (.pptx)',
  png: 'PNG image (.png)',
};

export function artifactFilename(
  artifact: Pick<Artifact, 'title' | 'type'>,
  extension?: string,
): string {
  const base = artifact.title.replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'artifact';
  return `${base}.${extension || ARTIFACT_EXTENSION[artifact.type]}`;
}

export function downloadArtifact(
  artifact: Pick<Artifact, 'type' | 'title' | 'content'>,
): void {
  const mime =
    artifact.type === 'html'
      ? 'text/html;charset=utf-8'
      : artifact.type === 'svg'
        ? 'image/svg+xml;charset=utf-8'
        : isMarkdownLikeType(artifact.type)
          ? 'text/markdown;charset=utf-8'
          : 'text/plain;charset=utf-8';
  const blob = new Blob([artifact.content], { type: mime });
  triggerDownload(blob, artifactFilename(artifact));
}

function isMarkdownLikeType(type: ArtifactType): boolean {
  return (
    type === 'markdown' ||
    type === 'document' ||
    type === 'table' ||
    type === 'slide-outline'
  );
}

export function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/**
 * Artifact kinds allowed to pop the side panel automatically.
 *
 * The panel is intentionally not opened for every detected block: tables and
 * short snippets should stay in the chat. Web pages, Markdown/Word-style
 * documents, slide decks and previewable code files open themselves.
 */
export function shouldAutoOpenArtifact(
  artifact: Pick<Artifact, 'type' | 'filePaths'>,
): boolean {
  if (artifact.type === 'document' || artifact.type === 'slide-outline') return true;
  // File-backed artifacts follow their extension even when the detector
  // classified them generically. Only Office files open the panel.
  return (artifact.filePaths ?? []).some((path) => /\.(docx|pptx)$/i.test(path));
}

/** True for artifacts that render as a web preview. */
export function isPreviewable(type: ArtifactType): boolean {
  return (
    type === 'html' ||
    type === 'svg' ||
    type === 'mermaid' ||
    type === 'markdown' ||
    type === 'document' ||
    type === 'table' ||
    type === 'slide-outline' ||
    type === 'multi-file'
  );
}
