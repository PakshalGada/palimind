import { ChevronLeft, Layers3, Package, X } from 'lucide-react';

export default function ArtifactPanelHeader({
  count,
  external,
  streaming,
  onBack,
  onOpenLibrary,
  onClose,
}: {
  count: number;
  external: boolean;
  streaming: boolean;
  onBack: () => void;
  onOpenLibrary: () => void;
  onClose: () => void;
}) {
  return (
    <header className="artp-head">
      <div className="artp-head-title">
        {external && (
          <button
            type="button"
            className="artp-icon-btn artp-head-back"
            onClick={onBack}
            title="Back to conversation artifacts"
            aria-label="Back to conversation artifacts"
          >
            <ChevronLeft size={16} />
          </button>
        )}
        <span className="artp-head-icon" aria-hidden="true">
          <Layers3 size={15} />
        </span>
        <span className="artp-head-label">Artifacts</span>
        {count > 0 && !external && <span className="artp-count">{count}</span>}
        {streaming && (
          <span className="artp-live">
            <span className="artp-live-dot" aria-hidden="true" />
            live
          </span>
        )}
      </div>
      <div className="artp-head-actions">
        <button
          type="button"
          className="artp-icon-btn"
          onClick={onOpenLibrary}
          title="Artifact library"
          aria-label="Open artifact library"
        >
          <Package size={15} />
        </button>
        <button
          type="button"
          className="artp-icon-btn"
          onClick={onClose}
          title="Close panel"
          aria-label="Close artifacts panel"
        >
          <X size={15} />
        </button>
      </div>
    </header>
  );
}
