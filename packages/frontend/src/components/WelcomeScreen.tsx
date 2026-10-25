import { CloudOff, FileText, FolderPlus, Sparkles, Waypoints } from 'lucide-react';
import { Button, EmptyState } from '../ui/primitives';

export default function WelcomeScreen() {
  const openPicker = () => {
    const modal = document.getElementById('dir-picker-modal');
    if (modal) {
      modal.style.display = 'flex';
      window.dispatchEvent(new CustomEvent('palimind:open-dir-picker'));
    }
  };

  return (
    <main className="chat-area" id="main-area">
      <div id="welcome-screen" className="welcome-screen">
        <EmptyState
          className="welcome-empty"
          icon={
            <span className="welcome-badge">
              <Sparkles size={14} />
              Local-First Intelligence OS
            </span>
          }
          title="Welcome to Palimind"
          description="Index documents, chat with local LLMs, and explore knowledge graphs — 100% offline and private."
          action={
            <Button variant="primary" size="md" className="welcome-cta" onClick={openPicker}>
              <FolderPlus size={17} />
              Select Workspace Directory
            </Button>
          }
        >
          <div className="welcome-features">
            <button type="button" className="welcome-feature-card" onClick={openPicker}>
              <span className="welcome-feature-icon">
                <FileText size={19} />
              </span>
              <span className="welcome-feature-title">Multimodal RAG</span>
              <span className="welcome-feature-desc">
                Query PDFs, code, images and notes locally
              </span>
            </button>

            <button type="button" className="welcome-feature-card" onClick={openPicker}>
              <span className="welcome-feature-icon">
                <Waypoints size={19} />
              </span>
              <span className="welcome-feature-title">Mixture of Experts</span>
              <span className="welcome-feature-desc">
                Parallel local models for deeper answers
              </span>
            </button>

            <button type="button" className="welcome-feature-card" onClick={openPicker}>
              <span className="welcome-feature-icon">
                <CloudOff size={19} />
              </span>
              <span className="welcome-feature-title">Zero Cloud Leaks</span>
              <span className="welcome-feature-desc">
                Vectors and inference stay on your machine
              </span>
            </button>
          </div>
        </EmptyState>
      </div>
    </main>
  );
}
