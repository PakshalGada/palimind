import { useEffect, useState } from 'react';
import type { Passage, ResultItem } from '../model';
import { Icon } from '../icons';
import { Favicon } from '../primitives/Favicon';

export function SourcesList({
  sources,
  passages,
  onActivate,
}: {
  sources: readonly ResultItem[];
  passages: readonly Passage[];
  onActivate?: (index: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState<number | null>(null);
  const items = [...sources, ...passages];

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ marker?: number | null }>).detail;
      if (!detail?.marker) return;
      setOpen(true);
      requestAnimationFrame(() => {
        const target = document.querySelector(
          `[data-citation-marker="${detail.marker}"]`,
        );
        target?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      });
    };
    window.addEventListener('palimind:focus-citation', handler);
    return () => window.removeEventListener('palimind:focus-citation', handler);
  }, []);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ marker?: number | null }>).detail;
      setHighlight(detail?.marker ?? null);
    };
    window.addEventListener('palimind:hover-citation', handler);
    return () => window.removeEventListener('palimind:hover-citation', handler);
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="act act-sources">
      <button
        type="button"
        className="act-sources__head"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Icon name="book-open" size={13} />
        <span>
          {items.length} {items.length === 1 ? 'source' : 'sources'}
        </span>
        <span className="act-chevron" data-open={open} aria-hidden="true">
          <Icon name="chevron-right" size={13} />
        </span>
      </button>
      <div className="act-disclosure" data-open={open}>
        <div className="act-disclosure__inner">
          <ol className="act-sources__list">
            {sources.map((item, index) => (
              <li
                key={`s-${item.id}`}
                data-citation-marker={item.marker ?? index + 1}
                className={highlight === (item.marker ?? index + 1) ? 'is-highlighted' : undefined}
              >
                <a
                  className="act-sources__item"
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <span className="act-sources__marker">[{item.marker ?? index + 1}]</span>
                  <Favicon domain={item.domain} title={item.title} />
                  <span style={{ minWidth: 0 }}>
                    <span className="act-row__label">{item.title}</span>
                    {item.snippet && (
                      <span className="act-result__snippet act-line-clamp-2">{item.snippet}</span>
                    )}
                  </span>
                </a>
              </li>
            ))}
            {passages.map((item, index) => (
              <li
                key={`p-${item.id}`}
                data-citation-marker={item.marker ?? sources.length + index + 1}
                className={
                  highlight === (item.marker ?? sources.length + index + 1)
                    ? 'is-highlighted'
                    : undefined
                }
              >
                <button
                  type="button"
                  className="act-sources__item"
                  onClick={() => onActivate?.(sources.length + index)}
                >
                  <span className="act-sources__marker">
                    [{item.marker ?? sources.length + index + 1}]
                  </span>
                  <Icon name="file-text" size={13} />
                  <span style={{ minWidth: 0 }}>
                    <span className="act-row__label">{item.docName}</span>
                    {item.page != null && <span className="act-muted"> p. {item.page}</span>}
                    {item.text && (
                      <span className="act-result__snippet act-line-clamp-2">{item.text}</span>
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
