import { useMemo } from 'react';
import { highlightCode } from '../utils/highlight';

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
  const { html } = useMemo(() => highlightCode(code, language), [code, language]);
  return (
    <pre className={`artifact-code hljs ${className}`.trim()}>
      <code dangerouslySetInnerHTML={{ __html: html }} />
    </pre>
  );
}
