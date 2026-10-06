import { useCallback, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { BookOpen, ExternalLink, FileText, ShieldCheck } from 'lucide-react';
import { formatMarkdown } from '../utils/markdown';
import { annotateCitationMarkers, sourceMap } from '../utils/citations';
import type { CitationPayload, CitationSource } from '../types';
import './Citations.css';

interface HoverState {
  marker: number;
  x: number;
  y: number;
}

function findCitationRef(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof HTMLElement)) return null;
  return target.closest('.citation-ref');
}

export default function MessageContent({
  content,
  citations,
  sources,
}: {
  content: string;
  citations?: CitationPayload;
  sources?: string[];
}) {
  const html = useMemo(
    () => formatMarkdown(annotateCitationMarkers(content, citations)),
    [content, citations],
  );
  const sourceLookup = useMemo(() => sourceMap(citations), [citations]);
  const [hover, setHover] = useState<HoverState | null>(null);

  const activate = useCallback(
    (marker: number) => {
      const source = sourceLookup.get(marker);
      if (source?.url) {
        window.open(source.url, '_blank', 'noopener,noreferrer');
        return;
      }
      const el = document.getElementById(`citation-source-${marker}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('citation-source-flash');
        window.setTimeout(() => el.classList.remove('citation-source-flash'), 1400);
      }
    },
    [sourceLookup],
  );

  const onClick = (e: React.MouseEvent) => {
    const ref = findCitationRef(e.target);
    if (!ref) return;
    const marker = Number(ref.getAttribute('data-citation'));
    if (Number.isFinite(marker)) activate(marker);
  };

  const onMouseOver = (e: React.MouseEvent) => {
    const ref = findCitationRef(e.target);
    if (!ref) return;
    const marker = Number(ref.getAttribute('data-citation'));
    if (!Number.isFinite(marker) || !sourceLookup.has(marker)) return;
    const rect = ref.getBoundingClientRect();
    setHover({ marker, x: rect.left, y: rect.bottom + 8 });
  };

  const onMouseOut = (e: React.MouseEvent) => {
    if (findCitationRef(e.target)) setHover(null);
  };

  const hoverSource: CitationSource | undefined = hover ? sourceLookup.get(hover.marker) : undefined;
  const citedSources = citations?.sources ?? [];

  return (
    <>
      <div
        className="message-content"
        onClick={onClick}
        onMouseOver={onMouseOver}
        onMouseOut={onMouseOut}
        dangerouslySetInnerHTML={{ __html: html }}
      />

      {hover && hoverSource &&
        createPortal(
          <div
            className="citation-popover"
            style={{
              left: Math.min(hover.x, window.innerWidth - 340),
              top: Math.min(hover.y, window.innerHeight - 200),
            }}
            role="tooltip"
          >
            <div className="citation-popover-head">
              {hoverSource.url ? <ExternalLink size={13} /> : <FileText size={13} />}
              <span className="citation-popover-title">{hoverSource.title}</span>
            </div>
            {hoverSource.url && <div className="citation-popover-url">{hoverSource.url}</div>}
            {!hoverSource.url && hoverSource.file && (
              <div className="citation-popover-url">
                {hoverSource.file}
                {hoverSource.section ? ` → ${hoverSource.section}` : ''}
              </div>
            )}
            {hoverSource.snippet && (
              <div className="citation-popover-snippet">{hoverSource.snippet}</div>
            )}
          </div>,
          document.body,
        )}

      {citations && citedSources.length > 0 && (
        <details className="citation-bibliography" open>
          <summary className="citation-bibliography-summary">
            <BookOpen size={13} />
            <span>
              Sources ({citedSources.length})
            </span>
            {typeof citations.accuracy === 'number' && (
              <span
                className="citation-accuracy"
                title="How well the answer is grounded in the cited sources"
              >
                <ShieldCheck size={12} /> {Math.round(citations.accuracy * 100)}% grounded
              </span>
            )}
          </summary>
          <ol className="citation-source-list">
            {citedSources.map((source) => {
              const cited = citations.cited_markers?.includes(source.marker);
              return (
                <li
                  key={source.marker}
                  id={`citation-source-${source.marker}`}
                  className={`citation-source-item${cited ? ' is-cited' : ''}`}
                >
                  <span className="citation-source-marker">[{source.marker}]</span>
                  <span className="citation-source-body">
                    {source.url ? (
                      <a href={source.url} target="_blank" rel="noopener noreferrer">
                        {source.title}
                      </a>
                    ) : (
                      <span className="citation-source-title">{source.title}</span>
                    )}
                    {!source.url && source.file && (
                      <span className="citation-source-path">
                        {source.file}
                        {source.section ? ` → ${source.section}` : ''}
                      </span>
                    )}
                    {source.snippet && (
                      <span className="citation-source-snippet">{source.snippet}</span>
                    )}
                  </span>
                </li>
              );
            })}
          </ol>
        </details>
      )}

      {!citations && sources && sources.length > 0 && (
        <div className="legacy-sources">
          {sources.map((s) => (
            <span key={s} className="legacy-source-chip" title={s}>
              {s.split(/[\\/]/).pop()}
            </span>
          ))}
        </div>
      )}
    </>
  );
}
