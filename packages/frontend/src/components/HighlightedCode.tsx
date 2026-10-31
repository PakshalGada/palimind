import { useMemo } from 'react';
import { highlightCode } from '../utils/highlight';

/** Very large files are shown as plain text to avoid a multi-second highlight. */
const MAX_HIGHLIGHT_CHARS = 120_000;

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/**
 * Read-only code block with syntax highlighting. Used by the artifact panel
 * for code/react artifacts (chat code blocks are highlighted inside
 * `formatMarkdown`).
 */
export default function HighlightedCode({
  code,
  language,
  className = '',
}: {
  code: string;
  language?: string;
  className?: string;
}) {
  const html = useMemo(() => {
    if (!code) return '';
    if (code.length > MAX_HIGHLIGHT_CHARS) return escapeHtml(code);
    return highlightCode(code, language, { autoDetect: false }).html;
  }, [code, language]);

  return (
    <pre className={`artifact-code hljs ${className}`.trim()}>
      <code dangerouslySetInnerHTML={{ __html: html }} />
    </pre>
  );
}
