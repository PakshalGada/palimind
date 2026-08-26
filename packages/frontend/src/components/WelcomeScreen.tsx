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
        <div className="welcome-content">
          <div className="welcome-badge">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
            </svg>
            Local-First Intelligence OS
          </div>
          <h1>Welcome to Palimind</h1>
          <p>Index documents, chat with local LLMs, and explore knowledge graphs — 100% offline and private.</p>
          
          <button className="primary-btn welcome-cta" onClick={openPicker}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              <line x1="12" y1="11" x2="12" y2="17" /><line x1="9" y1="14" x2="15" y2="14" />
            </svg>
            Select Workspace Directory
          </button>

          <div className="welcome-features">
            <div className="welcome-feature-card" onClick={openPicker}>
              <div className="welcome-feature-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                </svg>
              </div>
              <div className="welcome-feature-title">Multimodal RAG</div>
              <div className="welcome-feature-desc">Query PDFs, Code, Images, & Notes locally</div>
            </div>

            <div className="welcome-feature-card">
              <div className="welcome-feature-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z" />
                </svg>
              </div>
              <div className="welcome-feature-title">Mixture of Experts</div>
              <div className="welcome-feature-desc">4 parallel agents running local Ollama models</div>
            </div>

            <div className="welcome-feature-card">
              <div className="welcome-feature-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
              </div>
              <div className="welcome-feature-title">Zero Cloud Leaks</div>
              <div className="welcome-feature-desc">All vectors & inference remain on host system</div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
