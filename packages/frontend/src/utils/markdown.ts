import { marked } from 'marked';
import markedKatex from 'marked-katex-extension';
import DOMPurify from 'dompurify';

let configured = false;

export function formatMarkdown(text: string): string {
  if (!text) return '';

  if (!configured) {
    const renderer = new marked.Renderer();

    renderer.code = function ({ text, lang }: { text: string; lang?: string; escaped?: boolean }) {
      const langLabel = lang ? lang.toUpperCase() : 'CODE';
      const escapedCode = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

      return `
        <div class="code-box">
          <div class="code-box-header">
            <span class="code-box-lang">${langLabel}</span>
            <button class="code-box-copy" type="button" aria-label="Copy code" onclick="(function(btn){var cb=btn.closest('.code-box');var cd=cb.querySelector('code').innerText;navigator.clipboard.writeText(cd).then(function(){btn.innerText='Copied!';btn.classList.add('copied');setTimeout(function(){btn.innerText='Copy';btn.classList.remove('copied')},2000)})})(this)">Copy</button>
          </div>
          <pre><code>${escapedCode}</code></pre>
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
    ADD_ATTR: ['class', 'style', 'aria-hidden', 'mathvariant', 'encoding', 'display', 'xmlns', 'open'],
  });


  return htmlResult;
}
