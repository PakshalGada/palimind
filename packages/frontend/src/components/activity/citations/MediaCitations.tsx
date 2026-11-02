import { baseName, formatTimestamp } from '../../../stream/format';
import type { MediaCitation, VideoTarget } from '../../../stream/types';
import { Icon } from '../icons';

export function MediaCitations({
  citations,
  onOpen,
}: {
  citations: readonly MediaCitation[];
  onOpen: (target: VideoTarget) => void;
}) {
  if (citations.length === 0) return null;
  return (
    <div className="act" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
      {citations.map((citation, index) => (
        <button
          key={`${citation.file}:${citation.start}:${index}`}
          type="button"
          className="act-btn"
          title={citation.snippet || citation.file}
          onClick={() =>
            onOpen({ file: citation.file, start: citation.start, end: citation.end })
          }
        >
          <Icon name="play" size={12} />
          <span className="act-mono">{baseName(citation.file)}</span>
          <span className="act-tabular act-muted">{formatTimestamp(citation.start)}</span>
        </button>
      ))}
    </div>
  );
}
