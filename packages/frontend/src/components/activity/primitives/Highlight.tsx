import type { ReactNode } from 'react';

export function highlightTerms(text: string, terms: readonly string[]): ReactNode[] {
  const clean = terms.map((term) => term.trim()).filter((term) => term.length > 1);
  if (clean.length === 0) return [text];
  const pattern = new RegExp(`(${clean.map(escape).join('|')})`, 'gi');
  const parts = text.split(pattern);
  const matched = new Set(clean.map((term) => term.toLowerCase()));
  return parts.map((part, index) =>
    matched.has(part.toLowerCase()) ? (
      <mark key={index} className="act-mark">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function escape(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function Highlight({
  text,
  terms,
  className,
}: {
  text: string;
  terms: readonly string[];
  className?: string;
}) {
  return <span className={className}>{highlightTerms(text, terms)}</span>;
}
