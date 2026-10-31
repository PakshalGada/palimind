import { marked } from 'marked';
import markedKatex from 'marked-katex-extension';
import DOMPurify from 'dompurify';
import { highlightCode } from './highlight';
import {
  ARTIFACT_TYPE_LABEL,
  parseArtifacts,
  type Artifact,
} from './artifacts';

let configured = false;
let katexCssRequested = false;

/**
 * KaTeX ships a ~280KB stylesheet. Load it only once a message actually
 * contains math, instead of blocking the app on a CDN request at startup.
 */
function ensureKatexCss(text: string): void {
  if (katexCssRequested) return;
  if (!/\$[^$\n]+\$|\\\(|\\\[/.test(text)) return;
  katexCssRequested = true;
  void import('katex/dist/katex.min.css');
}

// Cache for formatted markdown to avoid re-parsing identical content
const markdownCache = new Map<string, string>();
const MAX_CACHE_SIZE = 200;

export interface MarkdownRenderOptions {
  /** Session message index; enables collapsible artifact blocks. */
  messageIndex?: number;
  /** True while the assistant is still writing this message. */
  streaming?: boolean;
}

interface CodeRenderContext {
  fenceIndex: number;
  artifacts: Map<number, Artifact>;
  streaming: boolean;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function createCodeContext(
  text: string,
  messageIndex: number,
  streaming: boolean,
): CodeRenderContext {
  const artifacts = new Map<number, Artifact>();
  for (const artifact of parseArtifacts(text, messageIndex)) {
    const match = /^fence-\d+-(\d+)$/.exec(artifact.id);
    if (match) artifacts.set(Number(match[1]), artifact);
  }
  return { fenceIndex: 0, artifacts, streaming };
}

function renderCodeBlock(
  token: { text: string; lang?: string; indented?: boolean },
  context: CodeRenderContext | null,
): string {
  const { html: highlighted, language } = highlightCode(token.text, token.lang, {
    // Language auto-detection over a partially streamed block is the single
    // most expensive step in rendering a live answer.
    autoDetect: !context?.streaming,
  });
  const langLabel = escapeHtml(language ? language.toUpperCase() : 'CODE');
  const safeLanguage = escapeHtml(language);

  let artifact: Artifact | undefined;
  if (context && !token.indented) {
    artifact = context.artifacts.get(context.fenceIndex);
    context.fenceIndex += 1;
  }

  const copyButton = `<button type="button" class="code-box-copy" aria-label="Copy code">Copy</button>`;
  const code = `<pre><code class="hljs language-${safeLanguage}">${highlighted}</code></pre>`;

  if (!artifact) {
    return `
        <div class="code-box">
          <div class="code-box-header">
            <span class="code-box-lang">${langLabel}</span>
            ${copyButton}
          </div>
          ${code}
        </div>
      `;
  }

  const typeLabel =
    artifact.type === 'code'
      ? (artifact.language || ARTIFACT_TYPE_LABEL[artifact.type]).toUpperCase()
      : ARTIFACT_TYPE_LABEL[artifact.type];
  const lineCount = token.text ? token.text.split('\n').length : 0;
  const initiallyCollapsed =
    lineCount > 40 ||
    ((artifact.type === 'html' ||
      artifact.type === 'document' ||
      artifact.type === 'multi-file') &&
      lineCount > 20);
  return `
      <div
        class="code-box artifact-block artifact-block--${escapeHtml(artifact.type)}${
          initiallyCollapsed ? ' is-collapsed' : ''
        }"
        data-artifact-id="${escapeHtml(artifact.id)}"
      >
        <div class="code-box-header artifact-block-head">
          <button
            type="button"
            class="artifact-block-toggle"
            aria-expanded="${initiallyCollapsed ? 'false' : 'true'}"
            title="${initiallyCollapsed ? 'Expand artifact block' : 'Collapse artifact block'}"
          >
            <span class="artifact-block-chevron" aria-hidden="true"></span>
            <span class="code-box-lang">${escapeHtml(typeLabel)}</span>
            <span class="artifact-block-title">${escapeHtml(artifact.title)}</span>
            <span class="artifact-block-meta">${lineCount.toLocaleString()} lines</span>
            ${context?.streaming ? '<span class="artifact-block-live">live</span>' : ''}
          </button>
          <div class="artifact-block-actions">
            ${copyButton}
            <button
              type="button"
              class="artifact-block-open"
              data-artifact-open="${escapeHtml(artifact.id)}"
            >
              Open in Artifacts
            </button>
          </div>
        </div>
        <div class="artifact-block-body">${code}</div>
      </div>
    `;
}

export function formatMarkdown(
  text: string,
  options: MarkdownRenderOptions = {},
): string {
  if (!text) return '';

  ensureKatexCss(text);

  const { messageIndex, streaming = false } = options;
  const cacheKey =
    messageIndex != null
      ? `${messageIndex}:${streaming ? '1' : '0'}\u0000${text}`
      : text;

  // Check cache first
  const cached = markdownCache.get(cacheKey);
  if (cached !== undefined) return cached;

  if (!configured) {
    marked.use(markedKatex({ throwOnError: false }));
    configured = true;
  }

  const context =
    messageIndex != null
      ? createCodeContext(text, messageIndex, streaming)
      : null;
  const renderer = new marked.Renderer();
  renderer.code = function ({
    text: codeText,
    lang,
    codeBlockStyle,
  }: {
    text: string;
    lang?: string;
    codeBlockStyle?: 'indented';
  }) {
    return renderCodeBlock(
      { text: codeText, lang, indented: codeBlockStyle === 'indented' },
      context,
    );
  };

  let htmlResult = marked.parse(text, { renderer, breaks: true }) as string;

  htmlResult = DOMPurify.sanitize(htmlResult, {
    ADD_TAGS: [
      'details', 'summary', 'div', 'span', 'sup',
      'math', 'mi', 'mo', 'mn', 'ms', 'mspace', 'mtext', 'menclose',
      'merror', 'mpadded', 'mphantom', 'mroot', 'mrow', 'msqrt',
      'mstyle', 'mmultiscripts', 'mover', 'mprescripts', 'msub',
      'msubsup', 'msup', 'munder', 'munderover', 'none', 'semantics',
      'annotation', 'annotation-xml',
    ],
    ADD_ATTR: [
      'class', 'aria-hidden', 'mathvariant', 'encoding', 'display', 'xmlns',
      'open', 'data-citation', 'title', 'data-artifact-open', 'data-artifact-id',
      'aria-expanded',
    ],
  });

  // Store in cache, evict oldest if too large
  if (markdownCache.size >= MAX_CACHE_SIZE) {
    const firstKey = markdownCache.keys().next().value;
    if (firstKey) markdownCache.delete(firstKey);
  }
  markdownCache.set(cacheKey, htmlResult);

  return htmlResult;
}
