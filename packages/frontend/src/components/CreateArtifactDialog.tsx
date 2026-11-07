import { useEffect, useState } from 'react';
import { FileText, Code2, Globe2, Presentation } from 'lucide-react';
import { Modal } from '../ui/primitives';
import {
  CREATE_ARTIFACT_OPTIONS,
  buildArtifactPrompt,
  type CreateArtifactKind,
} from '../utils/artifactPrompts';
import './CreateArtifactDialog.css';

const ICONS = {
  document: FileText,
  slides: Presentation,
  webpage: Globe2,
  code: Code2,
} as const;

export default function CreateArtifactDialog({
  open,
  onClose,
  onCreate,
  initialKind = 'document',
}: {
  open: boolean;
  onClose: () => void;
  onCreate: (prompt: string) => void;
  initialKind?: CreateArtifactKind;
}) {
  const [kind, setKind] = useState<CreateArtifactKind>(initialKind);
  const [topic, setTopic] = useState('');

  useEffect(() => {
    if (!open) return;
    setKind(initialKind);
    setTopic('');
  }, [open, initialKind]);

  const option = CREATE_ARTIFACT_OPTIONS.find((item) => item.kind === kind);
  const submit = () => {
    const prompt = buildArtifactPrompt(kind, topic);
    if (!prompt) return;
    onCreate(prompt);
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create an artifact"
      subtitle="Describe what you need; the answer opens in the artifact panel, not as a wall of chat text."
      width={680}
      footer={
        <div className="create-artifact-footer">
          <button type="button" className="ui-btn ui-btn--ghost ui-btn--sm" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="ui-btn ui-btn--primary ui-btn--sm"
            disabled={!topic.trim()}
            onClick={submit}
          >
            Create {option?.label.toLowerCase()}
          </button>
        </div>
      }
    >
      <div className="create-artifact-kinds" role="radiogroup" aria-label="Artifact type">
        {CREATE_ARTIFACT_OPTIONS.map((item) => {
          const Icon = ICONS[item.kind];
          return (
            <button
              key={item.kind}
              type="button"
              role="radio"
              aria-checked={kind === item.kind}
              className={`create-artifact-kind${kind === item.kind ? ' is-selected' : ''}`}
              onClick={() => setKind(item.kind)}
            >
              <Icon size={18} aria-hidden="true" />
              <span className="create-artifact-kind__label">{item.label}</span>
              <span className="create-artifact-kind__desc">{item.description}</span>
            </button>
          );
        })}
      </div>

      <label className="create-artifact-field">
        <span>Topic</span>
        <textarea
          value={topic}
          rows={3}
          autoFocus
          placeholder={option?.placeholder}
          onChange={(event) => setTopic(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              submit();
            }
          }}
        />
      </label>
      <p className="create-artifact-hint">
        The model writes one fenced artifact. When it closes, the preview opens in the artifact
        panel where you can edit, save and export it as Markdown, HTML, PDF, Word or PowerPoint.
      </p>
    </Modal>
  );
}
