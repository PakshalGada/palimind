import { baseName, formatTimestamp } from './format';
import type { MediaCitation, TextCitation, VideoTarget } from './types';

/** Clickable timestamp chips for media-transcript hits. */
export function MediaCitations({
  citations,
  onOpen,
}: {
  citations: MediaCitation[];
  onOpen: (target: VideoTarget) => void;
}) {
  if (!citations.length) return null;
  return (
    <div className="stream-citations">
      {citations.map((c, i) => (
        <button
          key={`${c.file}:${c.start}:${i}`}
          type="button"
          className="stream-citation-chip"
          title={c.snippet || c.file}
          onClick={() => onOpen({ file: c.file, start: c.start, end: c.end })}
        >
          ▶ {baseName(c.file)} @ {formatTimestamp(c.start)}
        </button>
      ))}
    </div>
  );
}

/** Non-interactive chips for document sections used during retrieval. */
export function TextCitations({ citations }: { citations: TextCitation[] }) {
  if (!citations.length) return null;
  return (
    <div className="stream-citations">
      {citations.map((c, i) => (
        <span
          key={`${c.file}:${c.chunk_id ?? i}:${i}`}
          className="stream-citation-chip"
          title={c.snippet || c.file}
        >
          {baseName(c.file)}
          {c.section ? ` → ${c.section}` : ''}
        </span>
      ))}
    </div>
  );
}
