import { useEffect, useState } from 'react';
import { Download, FolderOpen, Package, Trash2 } from 'lucide-react';
import { Modal, EmptyState } from '../ui/primitives';
import { ARTIFACT_TYPE_LABEL, downloadArtifact } from '../utils/artifacts';
import { loadVault, removeFromVault, type SavedArtifact } from '../utils/artifactVault';
import './ArtifactPanel.css';

export default function ArtifactVault({
  open,
  onClose,
  onOpen,
}: {
  open: boolean;
  onClose: () => void;
  onOpen: (artifact: SavedArtifact) => void;
}) {
  const [items, setItems] = useState<SavedArtifact[]>([]);

  useEffect(() => {
    if (open) setItems(loadVault());
  }, [open]);

  const remove = (id: string) => setItems(removeFromVault(id));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Artifact Vault"
      subtitle="Saved artifacts are stored locally on this device."
      width={640}
    >
      {items.length === 0 ? (
        <EmptyState
          icon={<Package size={26} />}
          title="No saved artifacts"
          description="Save an artifact from the panel to keep it here for later."
        />
      ) : (
        <div className="vault-list">
          {items.map((artifact) => (
            <div key={artifact.id} className="vault-item">
              <span className="vault-item-type">{ARTIFACT_TYPE_LABEL[artifact.type]}</span>
              <span className="vault-item-text">
                <span className="vault-item-title">{artifact.title}</span>
                <span className="vault-item-meta">
                  {new Date(artifact.savedAt).toLocaleString()} · {artifact.content.length.toLocaleString()} chars
                </span>
              </span>
              <div className="vault-item-actions">
                <button
                  type="button"
                  className="ui-icon-btn"
                  title="Open"
                  aria-label={`Open ${artifact.title}`}
                  onClick={() => {
                    onOpen(artifact);
                    onClose();
                  }}
                >
                  <FolderOpen size={15} />
                </button>
                <button
                  type="button"
                  className="ui-icon-btn"
                  title="Download"
                  aria-label={`Download ${artifact.title}`}
                  onClick={() => downloadArtifact(artifact)}
                >
                  <Download size={15} />
                </button>
                <button
                  type="button"
                  className="ui-icon-btn"
                  title="Delete"
                  aria-label={`Delete ${artifact.title}`}
                  onClick={() => remove(artifact.id)}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
