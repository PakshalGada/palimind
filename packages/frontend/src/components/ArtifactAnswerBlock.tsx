import { ArrowUpRight } from 'lucide-react';
import ArtifactIcon from './artifact/ArtifactIcon';
import type { Artifact } from '../utils/artifacts';
import './ArtifactAnswerBlock.css';

/**
 * The compact transcript form of an artifact answer.
 *
 * Models used to paste the whole document/deck into the conversation and the
 * artifact panel. The transcript now keeps one small block per artifact and
 * opens the full content in the panel on demand.
 */
export default function ArtifactAnswerBlock({
  artifacts,
  onOpen,
}: {
  artifacts: Artifact[];
  onOpen: (artifactId: string) => void;
}) {
  if (artifacts.length === 0) return null;
  return (
    <div className="artifact-answer-stack">
      {artifacts.map((artifact) => (
        <div key={artifact.id} className="artifact-answer-block">
          <span className="artifact-answer-block__icon">
            <ArtifactIcon type={artifact.type} size={16} />
          </span>
          <span className="artifact-answer-block__text">
            <span className="artifact-answer-block__title">{artifact.title}</span>
          </span>
          <button
            type="button"
            className="artifact-answer-block__open"
            onClick={() => onOpen(artifact.id)}
          >
            Open in artifact
            <ArrowUpRight size={12} aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
}
