import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
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
  messageIndex,
  streaming = false,
  onOpenArtifact,
}: {
  content: string;
  citations?: CitationPayload;
  sources?: string[];
  messageIndex?: number;
  streaming?: boolean;
  onOpenArtifact?: (artifactId: string) => void;
}) {
  const html = useMemo(
    () =>
      formatMarkdown(annotateCitationMarkers(content, citations), {
        messageIndex,
        streaming,
      }),
    [content, citations, messageIndex, streaming],
  );
  const sourceLookup = useMemo(() => sourceMap(citations), [citations]);
  const [hover, setHover] = useState<HoverState | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const collapsedArtifactsRef = useRef<Set<string>>(new Set());
  const initializedDefaultsRef = useRef<Set<string>>(new Set());

  // Re-apply collapse state after streamed content re-renders the HTML.
  useLayoutEffect(() => {
    const root = contentRef.current;
    if (!root) return;
    root.querySelectorAll('.artifact-block').forEach(block => {
      const id = block.getAttribute('data-artifact-id') ?? '';
      // Large blocks start collapsed in the generated markup; remember that
      // default so it survives streaming re-renders.
      if (id && !initializedDefaultsRef.current.has(id)) {
        initializedDefaultsRef.current.add(id);
        if (block.classList.contains('is-collapsed')) {
          collapsedArtifactsRef.current.add(id);
        }
      }
      const collapsed = collapsedArtifactsRef.current.has(id);
      block.classList.toggle('is-collapsed', collapsed);
      const toggle = block.querySelector('.artifact-block-toggle');
      toggle?.setAttribute('aria-expanded', String(!collapsed));
      toggle?.setAttribute(
        'title',
        collapsed ? 'Expand artifact block' : 'Collapse artifact block',
      );
    });
  }, [html]);

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
    const target = e.target;
    if (target instanceof HTMLElement) {
      const copyButton = target.closest('.code-box-copy') as HTMLElement | null;
      if (copyButton) {
        e.preventDefault();
        const code = copyButton.closest('.code-box')?.querySelector('code');
        const value = code?.textContent ?? '';
        void navigator.clipboard
          .writeText(value)
          .then(() => {
            copyButton.textContent = 'Copied!';
            copyButton.classList.add('copied');
            window.setTimeout(() => {
              copyButton.textContent = 'Copy';
              copyButton.classList.remove('copied');
            }, 1600);
          })
          .catch(() => undefined);
        return;
      }

      const openButton = target.closest('[data-artifact-open]') as HTMLElement | null;
      if (openButton) {
        e.preventDefault();
        const artifactId = openButton.getAttribute('data-artifact-open');
        if (artifactId && onOpenArtifact) onOpenArtifact(artifactId);
        return;
      }

      const toggleButton = target.closest('.artifact-block-toggle') as HTMLElement | null;
      if (toggleButton) {
        e.preventDefault();
        const block = toggleButton.closest('.artifact-block');
        if (block) {
          const collapsed = block.classList.toggle('is-collapsed');
          const artifactId = block.getAttribute('data-artifact-id') ?? '';
          if (artifactId) {
            if (collapsed) collapsedArtifactsRef.current.add(artifactId);
            else collapsedArtifactsRef.current.delete(artifactId);
          }
          toggleButton.setAttribute('aria-expanded', String(!collapsed));
          toggleButton.setAttribute(
            'title',
            collapsed ? 'Expand artifact block' : 'Collapse artifact block',
          );
        }
        return;
      }
    }

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
        ref={contentRef}
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
