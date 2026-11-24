import { ArrowUpRight, Pin } from 'lucide-react';
import ArtifactIcon from './artifact/ArtifactIcon';
import type { Artifact } from '../utils/artifacts';
import { parseDeckOutline } from '../utils/deckPlan';
import './ArtifactAnswerBlock.css';

function metaFor(artifact: Artifact): string {
  if (artifact.type === 'slide-outline') {
    const slides = parseDeckOutline(artifact.content).length;
    const charts = (artifact.content.match(/\[chart:/gi) || []).length;
    return `${slides} slide${slides === 1 ? '' : 's'}${charts ? ` · ${charts} chart${charts === 1 ? '' : 's'}` : ''}`;
  }
  if (artifact.type === 'document' || artifact.type === 'markdown' || artifact.type === 'table') {
    const words = artifact.content.trim().split(/\s+/).filter(Boolean).length;
    return `${words.toLocaleString()} words`;
  }
  if (artifact.type === 'html' || artifact.type === 'svg' || artifact.type === 'mermaid') {
    return artifact.type.toUpperCase();
  }
  return artifact.language || artifact.type;
}

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
  onUseContext,
}: {
  artifacts: Artifact[];
  onOpen: (artifactId: string) => void;
  onUseContext?: (artifact: Artifact) => void;
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
            <span className="artifact-answer-block__meta">{metaFor(artifact)}</span>
          </span>
          {onUseContext && (
            <button
              type="button"
              className="artifact-answer-block__context"
              onClick={() => onUseContext(artifact)}
              title="Use this artifact as chat context"
            >
              <Pin size={12} aria-hidden="true" />
              Use as context
            </button>
          )}
          <button
            type="button"
            className="artifact-answer-block__open"
            onClick={() => onOpen(artifact.id)}
          >
            Open
            <ArrowUpRight size={12} aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
}
