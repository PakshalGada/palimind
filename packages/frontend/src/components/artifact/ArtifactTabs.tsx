import { memo } from 'react';
import { ARTIFACT_TYPE_LABEL, type Artifact } from '../../utils/artifacts';
import ArtifactIcon from './ArtifactIcon';

function ArtifactTabs({
  artifacts,
  activeId,
  newIds,
  onSelect,
}: {
  artifacts: Artifact[];
  activeId: string;
  newIds: Set<string>;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="artp-tabs" role="tablist" aria-label="Artifacts in this conversation">
      {artifacts.map(artifact => {
        const isActive = artifact.id === activeId;
        const isNew = !artifact.streaming && newIds.has(artifact.id);
        return (
          <button
            key={artifact.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            aria-busy={artifact.streaming || undefined}
            className={`artp-tab type-${artifact.type}${isActive ? ' is-active' : ''}${
              artifact.streaming ? ' is-live' : ''
            }`}
            onClick={() => onSelect(artifact.id)}
            title={`${artifact.title} · ${ARTIFACT_TYPE_LABEL[artifact.type]}`}
          >
            <span className="artp-tab-icon">
              <ArtifactIcon type={artifact.type} size={12} />
            </span>
            <span className="artp-tab-title">{artifact.title}</span>
            {artifact.streaming ? (
              <span className="artp-tab-dot is-live" aria-hidden="true" />
            ) : isNew ? (
              <span className="artp-tab-dot" title="New artifact" aria-label="New artifact" />
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export default memo(ArtifactTabs);
