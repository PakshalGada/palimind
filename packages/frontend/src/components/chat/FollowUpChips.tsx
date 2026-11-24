import { ArrowUpRight, Sparkles } from 'lucide-react';
import type { Artifact } from '../../utils/artifacts';
import './FollowUpChips.css';

const DEFAULT_PROMPTS = [
  'Give me the key takeaways',
  'Turn this into a table',
  'What should I do next?',
];

export default function FollowUpChips({
  suggestions,
  artifacts,
  onOpenArtifact,
}: {
  suggestions?: string[];
  artifacts: Artifact[];
  onOpenArtifact: (id: string) => void;
}) {
  const prompts = (suggestions?.length ? suggestions : DEFAULT_PROMPTS).slice(0, 4);
  const firstArtifact = artifacts[0];

  const prefill = (text: string) => {
    window.dispatchEvent(
      new CustomEvent('palimind:prefill-composer', { detail: { text } }),
    );
  };

  return (
    <div className="follow-up-chips" aria-label="Suggested follow-ups">
      {firstArtifact && (
        <button
          type="button"
          className="follow-up-chip follow-up-chip--artifact"
          onClick={() => onOpenArtifact(firstArtifact.id)}
          title={firstArtifact.title}
        >
          <ArrowUpRight size={12} />
          Open {firstArtifact.title.slice(0, 32)}
        </button>
      )}
      {prompts.map((prompt) => (
        <button
          key={prompt}
          type="button"
          className="follow-up-chip"
          onClick={() => prefill(prompt)}
        >
          <Sparkles size={11} />
          {prompt}
        </button>
      ))}
    </div>
  );
}
