import { marked } from 'marked';
import markedKatex from 'marked-katex-extension';
import DOMPurify from 'dompurify';
import { highlightCode } from './highlight';

let configured = false;

// Cache for formatted markdown to avoid re-parsing identical content
const markdownCache = new Map<string, string>();
const MAX_CACHE_SIZE = 200;

export function formatMarkdown(text: string): string {
  if (!text) return '';

  // Check cache first
  const cached = markdownCache.get(text);
  if (cached !== undefined) return cached;

  if (!configured) {
    const renderer = new marked.Renderer();

    renderer.code = function ({ text, lang }: { text: string; lang?: string; escaped?: boolean }) {
      const { html: highlighted, language } = highlightCode(text, lang);
      const langLabel = language ? language.toUpperCase() : 'CODE';

      return `
        <div class="code-box">
          <div class="code-box-header">
            <span class="code-box-lang">${langLabel}</span>
            <button class="code-box-copy" type="button" aria-label="Copy code" onclick="(function(btn){var cb=btn.closest('.code-box');var cd=cb.querySelector('code').innerText;navigator.clipboard.writeText(cd).then(function(){btn.innerText='Copied!';btn.classList.add('copied');setTimeout(function(){btn.innerText='Copy';btn.classList.remove('copied')},2000)})})(this)">Copy</button>
          </div>
          <pre><code class="hljs language-${language}">${highlighted}</code></pre>
        </div>
      `;
    };

    marked.use(markedKatex({ throwOnError: false }));
    marked.use({ renderer, breaks: true });
    configured = true;
  }

  let htmlResult = marked.parse(text) as string;

  htmlResult = DOMPurify.sanitize(htmlResult, {
    ADD_TAGS: [
      'details', 'summary', 'div', 'span',
      'math', 'mi', 'mo', 'mn', 'ms', 'mspace', 'mtext', 'menclose',
      'merror', 'mpadded', 'mphantom', 'mroot', 'mrow', 'msqrt',
      'mstyle', 'mmultiscripts', 'mover', 'mprescripts', 'msub',
      'msubsup', 'msup', 'munder', 'munderover', 'none', 'semantics',
      'annotation', 'annotation-xml',
    ],
    ADD_ATTR: ['class', 'aria-hidden', 'mathvariant', 'encoding', 'display', 'xmlns', 'open'],
  });

  // Store in cache, evict oldest if too large
  if (markdownCache.size >= MAX_CACHE_SIZE) {
    const firstKey = markdownCache.keys().next().value;
    if (firstKey) markdownCache.delete(firstKey);
  }
  markdownCache.set(text, htmlResult);

  return htmlResult;
}
