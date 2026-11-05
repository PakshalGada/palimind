import { useCallback, useEffect, useId, useState } from 'react';
import { Favicon } from '@/components/activity/primitives/Favicon';
import { Icon } from '@/components/activity/icons';
import type { CitationPayload } from '../../types';
import type { MediaCitation, TextCitation, VideoTarget } from '../../stream/types';
import {
  buildSourceItems,
  hostOf,
  localFileHref,
  type SourcePanelItem,
} from './model';
import './SourcesPanel.css';

const MAX_INLINE = 4;

function iconName(item: SourcePanelItem): 'globe' | 'file-text' | 'play' | 'brain' {
  if (item.kind === 'web') return 'globe';
  if (item.kind === 'media') return 'play';
  if (item.kind === 'agent') return 'brain';
  return 'file-text';
}

function SourceIcon({ item, size = 14 }: { item: SourcePanelItem; size?: number }) {
  if (item.kind === 'web') {
    return <Favicon domain={hostOf(item.url)} title={item.title} size={size} />;
  }
  return <Icon name={iconName(item)} size={size} />;
}

function itemSubtitle(item: SourcePanelItem): string {
  if (item.url) return hostOf(item.url);
  if (item.kind === 'media') return item.file ?? '';
  if (item.file) return item.section ? `${item.file} / ${item.section}` : item.file;
  return item.section ?? '';
}

function itemHref(item: SourcePanelItem): string | undefined {
  if (item.url) return item.url;
  if (item.file) return localFileHref(item.file, item.section);
  return undefined;
}

export function SourcesPanel({
  citations,
  textCitations = [],
  mediaCitations = [],
  legacySources = [],
  onOpenVideo,
}: {
  citations?: CitationPayload | null;
  textCitations?: readonly TextCitation[];
  mediaCitations?: readonly MediaCitation[];
  legacySources?: readonly string[];
  onOpenVideo?: (target: VideoTarget) => void;
}) {
  const items = buildSourceItems(citations, textCitations, mediaCitations, legacySources);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState<number | null>(null);
  const panelId = useId();

  const close = useCallback(() => setOpen(false), []);

  // Citation markers in the answer ask the source list to reveal their row.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const reveal = (event: Event) => {
      const detail = (event as CustomEvent<{ marker?: number | null }>).detail;
      if (!detail?.marker) return;
      setOpen(true);
      setHighlight(detail.marker);
      window.requestAnimationFrame(() => {
        const target = document.querySelector(
          `[data-citation-marker="${detail.marker}"]`,
        );
        target?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      });
    };
    const hover = (event: Event) => {
      const detail = (event as CustomEvent<{ marker?: number | null }>).detail;
      setHighlight(detail?.marker ?? null);
    };
    window.addEventListener('palimind:focus-citation', reveal);
    window.addEventListener('palimind:hover-citation', hover);
    return () => {
      window.removeEventListener('palimind:focus-citation', reveal);
      window.removeEventListener('palimind:hover-citation', hover);
    };
  }, []);

  useEffect(() => {
    if (!open || typeof window === 'undefined') return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

  if (items.length === 0) return null;

  const visible = items.slice(0, MAX_INLINE);
  const extra = items.length - visible.length;

  const openMedia = (item: SourcePanelItem) => {
    if (item.start == null) return;
    onOpenVideo?.({ file: item.file ?? '', start: item.start, end: item.end });
  };

  const renderChip = (item: SourcePanelItem) => {
    const marker = item.marker != null ? (
      <span className="sources-chip__marker">[{item.marker}]</span>
    ) : null;
    const body = (
      <>
        {marker}
        <SourceIcon item={item} size={13} />
        <span className="sources-chip__label">{item.title}</span>
      </>
    );

    if (item.kind === 'media' && onOpenVideo) {
      return (
        <button
          type="button"
          className="sources-chip"
          title={item.snippet || item.title}
          onClick={() => openMedia(item)}
        >
          {body}
        </button>
      );
    }

    const href = itemHref(item);
    if (!href) {
      return (
        <span className="sources-chip" title={item.snippet || item.title}>
          {body}
        </span>
      );
    }
    return (
      <a
        className="sources-chip"
        href={href}
        title={item.snippet || item.title}
        target="_blank"
        rel="noopener noreferrer"
      >
        {body}
      </a>
    );
  };

  const renderRow = (item: SourcePanelItem) => {
    const subtitle = itemSubtitle(item);
    const content = (
      <>
        {item.marker != null && (
          <span className="sources-drawer__marker">[{item.marker}]</span>
        )}
        <span className="sources-drawer__icon">
          <SourceIcon item={item} />
        </span>
        <span className="sources-drawer__body">
          <span className="sources-drawer__item-title">{item.title}</span>
          {subtitle && <span className="sources-drawer__meta">{subtitle}</span>}
          {item.snippet && (
            <span className="sources-drawer__snippet">{item.snippet}</span>
          )}
        </span>
        {item.url && (
          <Icon name="external-link" size={13} className="sources-drawer__external" />
        )}
      </>
    );

    if (item.kind === 'media' && onOpenVideo) {
      return (
        <button
          type="button"
          className="sources-drawer__item"
          title={item.snippet || item.title}
          onClick={() => openMedia(item)}
        >
          {content}
        </button>
      );
    }

    const href = itemHref(item);
    if (!href) {
      return <span className="sources-drawer__item">{content}</span>;
    }
    return (
      <a
        className="sources-drawer__item"
        href={href}
        title={item.snippet || item.title}
        target="_blank"
        rel="noopener noreferrer"
      >
        {content}
      </a>
    );
  };

  return (
    <div className="sources-panel" data-open={open}>
      <div className="sources-panel__bar">
        <ul className="sources-panel__chips" aria-label="Sources">
          {visible.map((item) => (
            <li key={item.id}>{renderChip(item)}</li>
          ))}
          {extra > 0 && (
            <li>
              <button
                type="button"
                className="sources-chip sources-chip--more"
                onClick={() => setOpen(true)}
              >
                +{extra}
              </button>
            </li>
          )}
        </ul>
        <button
          type="button"
          className="sources-panel__toggle"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((value) => !value)}
        >
          <Icon name="list-tree" size={13} />
          <span>Sources · {items.length}</span>
          <Icon name="chevron-right" size={13} className="sources-panel__chevron" />
        </button>
      </div>

      {open && (
        <div
          className="sources-drawer__backdrop"
          role="presentation"
          onClick={close}
        >
          <div
            id={panelId}
            className="sources-drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby={`${panelId}-title`}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="sources-drawer__head">
              <h2 id={`${panelId}-title`} className="sources-drawer__title">
                Sources <span>{items.length}</span>
              </h2>
              <button
                type="button"
                className="sources-drawer__close"
                aria-label="Close sources"
                onClick={close}
              >
                <Icon name="x" size={14} />
              </button>
            </div>
            <ol className="sources-drawer__list">
              {items.map((item) => (
                <li
                  key={item.id}
                  data-citation-marker={item.marker ?? undefined}
                  className={
                    highlight === item.marker ? 'is-highlighted' : undefined
                  }
                >
                  {renderRow(item)}
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}
    </div>
  );
}

export default SourcesPanel;
