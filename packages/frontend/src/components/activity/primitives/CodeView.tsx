import { useEffect, useMemo, useState } from 'react';
import { CopyButton } from './CopyButton';

const MAX_LINES = 120;

interface HighlightState {
  html: string;
  ready: boolean;
}

export function CodeView({
  code,
  language,
  title,
  lineNumbers = false,
  maxLines = MAX_LINES,
  copy = true,
}: {
  code: string;
  language?: string;
  title?: string;
  lineNumbers?: boolean;
  maxLines?: number;
  copy?: boolean;
}) {
  const [showAll, setShowAll] = useState(false);
  const lines = useMemo(() => code.replace(/\r\n/g, '\n').split('\n'), [code]);
  const truncated = !showAll && lines.length > maxLines;
  const visible = truncated ? lines.slice(0, maxLines) : lines;
  const visibleCode = visible.join('\n');
  const [highlight, setHighlight] = useState<HighlightState>({ html: '', ready: false });

  useEffect(() => {
    if (lineNumbers) return undefined;
    let cancelled = false;
    setHighlight({ html: '', ready: false });
    void import('highlight.js/lib/common')
      .then((module) => {
        if (cancelled) return;
        const hljs = module.default;
        try {
          const result = language
            ? hljs.highlight(visibleCode, { language, ignoreIllegals: true })
            : hljs.highlightAuto(visibleCode);
          setHighlight({ html: result.value, ready: true });
        } catch {
          setHighlight({ html: '', ready: false });
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [visibleCode, language, lineNumbers]);

  return (
    <div className="act-code">
      <div className="act-code__head">
        <span className="act-row__label">{title ?? language ?? 'Code'}</span>
        <span style={{ marginInlineStart: 'auto', display: 'inline-flex', gap: 4 }}>
          {truncated && (
            <button type="button" className="act-btn act-btn--ghost" onClick={() => setShowAll(true)}>
              Show all
            </button>
          )}
          {copy && <CopyButton value={code} />}
        </span>
      </div>
      {highlight.ready && !lineNumbers ? (
        <pre className="act-code__body">
          <code dangerouslySetInnerHTML={{ __html: highlight.html }} />
        </pre>
      ) : (
        <pre className="act-code__body">
          {visible.map((line, index) => (
            <div key={index}>
              {lineNumbers && <span className="act-code__gutter">{index + 1}</span>}
              {line || ' '}
            </div>
          ))}
        </pre>
      )}
    </div>
  );
}
