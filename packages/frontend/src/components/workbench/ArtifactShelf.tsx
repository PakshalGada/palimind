import { useMemo, useState } from 'react';
import { Package, Search } from 'lucide-react';
import { ARTIFACT_TYPE_LABEL, type Artifact } from '../../utils/artifacts';
import ArtifactIcon from '../artifact/ArtifactIcon';

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'visual', label: 'Visual' },
  { id: 'document', label: 'Docs' },
  { id: 'slides', label: 'Slides' },
  { id: 'code', label: 'Code' },
] as const;

type FilterId = (typeof FILTERS)[number]['id'];

function matchesFilter(artifact: Artifact, filter: FilterId): boolean {
  if (filter === 'all') return true;
  if (filter === 'visual') {
    return artifact.type === 'html' || artifact.type === 'svg' || artifact.type === 'mermaid';
  }
  if (filter === 'document') {
    return artifact.type === 'document' || artifact.type === 'markdown' || artifact.type === 'table';
  }
  if (filter === 'slides') return artifact.type === 'slide-outline';
  return artifact.type === 'code' || artifact.type === 'code-file' || artifact.type === 'react';
}

export default function ArtifactShelf({
  artifacts,
  activeId,
  onSelect,
  onOpenLibrary,
}: {
  artifacts: Artifact[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onOpenLibrary: () => void;
}) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<FilterId>('all');

  const visible = useMemo(() => {
    const search = query.trim().toLowerCase();
    return artifacts.filter((artifact) => {
      if (!matchesFilter(artifact, filter)) return false;
      if (!search) return true;
      return (
        artifact.title.toLowerCase().includes(search) ||
        ARTIFACT_TYPE_LABEL[artifact.type].toLowerCase().includes(search)
      );
    });
  }, [artifacts, filter, query]);

  return (
    <div className="wb-shelf" aria-label="Artifact shelf">
      <div className="wb-shelf__head">
        <span className="wb-shelf__title">This chat</span>
        <button
          type="button"
          className="wb-shelf__library"
          onClick={onOpenLibrary}
          title="Open saved artifact library"
        >
          <Package size={13} />
        </button>
      </div>

      <label className="wb-shelf__search">
        <Search size={13} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Find an artifact"
          aria-label="Find an artifact"
        />
      </label>

      <div className="wb-shelf__filters" role="group" aria-label="Artifact filters">
        {FILTERS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`wb-shelf__filter${filter === item.id ? ' is-active' : ''}`}
            onClick={() => setFilter(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="wb-shelf__list">
        {visible.length === 0 ? (
          <p className="wb-shelf__empty">
            {artifacts.length === 0 ? 'No artifacts in this chat yet.' : 'No matching artifacts.'}
          </p>
        ) : (
          visible.map((artifact) => (
            <button
              key={artifact.id}
              type="button"
              className={`wb-shelf__item${artifact.id === activeId ? ' is-active' : ''}`}
              onClick={() => onSelect(artifact.id)}
              title={artifact.title}
            >
              <span className="wb-shelf__icon">
                <ArtifactIcon type={artifact.type} size={14} />
              </span>
              <span className="wb-shelf__text">
                <strong>{artifact.title}</strong>
                <small>
                  {ARTIFACT_TYPE_LABEL[artifact.type]}
                  {artifact.streaming ? ' · live' : ''}
                </small>
              </span>
              {artifact.streaming && <span className="wb-shelf__live" aria-label="Streaming" />}
            </button>
          ))
        )}
      </div>
    </div>
  );
}
