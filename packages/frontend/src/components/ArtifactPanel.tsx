import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Code2,
  Copy,
  Download,
  ExternalLink,
  Eye,
  Package,
  Pencil,
  Save,
  Share2,
  X,
} from 'lucide-react';
import { useApp } from '../AppContext';
import { formatMarkdown } from '../utils/markdown';
import {
  ARTIFACT_TYPE_LABEL,
  collectArtifacts,
  downloadArtifact,
  type Artifact,
} from '../utils/artifacts';
import { loadVault, saveToVault, type SavedArtifact } from '../utils/artifactVault';
import MermaidPreview from './MermaidPreview';
import HighlightedCode from './HighlightedCode';
import ArtifactVault from './ArtifactVault';
import './ArtifactPanel.css';

type ActiveArtifact = Artifact | SavedArtifact;

export default function ArtifactPanel() {
  const {
    artifactPanelOpen,
    setArtifactPanelOpen,
    sessions,
    activeSessionId,
    addToast,
  } = useApp();

  const currentSess = sessions.find((s) => s.id === activeSessionId);
  const sessionArtifacts = useMemo(
    () => collectArtifacts(currentSess?.messages),
    [currentSess?.messages],
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [vaultArtifact, setVaultArtifact] = useState<SavedArtifact | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [viewMode, setViewMode] = useState<'preview' | 'code'>('preview');
  const [vaultOpen, setVaultOpen] = useState(false);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());

  // Keep the selection valid as the conversation changes.
  useEffect(() => {
    if (vaultArtifact) return;
    if (sessionArtifacts.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !sessionArtifacts.some((a) => a.id === selectedId)) {
      setSelectedId(sessionArtifacts[0].id);
    }
  }, [sessionArtifacts, selectedId, vaultArtifact]);

  const active: ActiveArtifact | null =
    vaultArtifact ?? sessionArtifacts.find((a) => a.id === selectedId) ?? sessionArtifacts[0] ?? null;

  // Reset the editor whenever the shown artifact changes. Content is read
  // from a ref so the effect can key on the id alone.
  const activeId = active?.id;
  const activeContentRef = useRef(active?.content ?? '');
  activeContentRef.current = active?.content ?? '';
  useEffect(() => {
    setEditing(false);
    setViewMode('preview');
    setDraft(activeContentRef.current);
  }, [activeId]);

  useEffect(() => {
    if (artifactPanelOpen) setSavedIds(new Set(loadVault().map((a) => a.id)));
  }, [artifactPanelOpen]);

  if (!artifactPanelOpen) return null;

  const previewContent = editing ? draft : active?.content ?? '';

  const selectSessionArtifact = (id: string) => {
    setVaultArtifact(null);
    setSelectedId(id);
  };

  const copy = () => {
    if (!active) return;
    navigator.clipboard
      .writeText(previewContent)
      .then(() => addToast('Artifact copied to clipboard'))
      .catch(() => addToast('Could not access the clipboard'));
  };

  const save = () => {
    if (!active) return;
    const next = saveToVault({ ...active, content: previewContent });
    setSavedIds(new Set(next.map((a) => a.id)));
    addToast('Saved to Artifact Vault');
  };

  const share = async () => {
    if (!active) return;
    if (navigator.share) {
      try {
        await navigator.share({ title: active.title, text: previewContent });
        return;
      } catch {
        // fall through to clipboard
      }
    }
    copy();
  };

  const openInNewTab = () => {
    if (!active) return;
    const mime = active.type === 'svg' ? 'image/svg+xml' : 'text/html';
    const body =
      active.type === 'svg'
        ? `<!doctype html><html><body style="margin:0;padding:24px;background:#fff">${previewContent}</body></html>`
        : previewContent;
    const url = URL.createObjectURL(new Blob([body], { type: `${mime};charset=utf-8` }));
    window.open(url, '_blank');
    window.setTimeout(() => URL.revokeObjectURL(url), 15000);
  };

  const supportsPreview =
    active?.type === 'html' ||
    active?.type === 'svg' ||
    active?.type === 'mermaid' ||
    active?.type === 'markdown';

  const renderPreview = () => {
    if (!active) return null;

    // Code view (either the artifact has no preview, or the user toggled it).
    if (!supportsPreview || viewMode === 'code') {
      const language = active.type === 'react' ? 'jsx' : active.language || 'text';
      return <HighlightedCode code={previewContent} language={language} />;
    }

    switch (active.type) {
      case 'html':
        return (
          <iframe
            className="artifact-frame"
            title={active.title}
            sandbox="allow-scripts allow-forms allow-modals allow-popups"
            srcDoc={previewContent}
          />
        );
      case 'svg':
        return (
          <iframe
            className="artifact-frame"
            title={active.title}
            sandbox=""
            srcDoc={`<!doctype html><html><body style="margin:0;padding:12px;display:flex;align-items:center;justify-content:center;min-height:100%">${previewContent}</body></html>`}
          />
        );
      case 'mermaid':
        return <MermaidPreview code={previewContent} />;
      case 'markdown':
        return (
          <div
            className="artifact-markdown"
            dangerouslySetInnerHTML={{ __html: formatMarkdown(previewContent) }}
          />
        );
      default:
        return <HighlightedCode code={previewContent} language={active.language || 'text'} />;
    }
  };

  return (
    <aside className="artifact-panel" aria-label="Artifacts panel">
      <header className="artifact-panel-head">
        <div className="artifact-panel-heading">
          <Code2 size={15} />
          <span>Artifacts</span>
        </div>
        <div className="artifact-panel-head-actions">
          <button
            type="button"
            className="ui-icon-btn"
            title="Artifact Vault"
            aria-label="Open artifact vault"
            onClick={() => setVaultOpen(true)}
          >
            <Package size={15} />
          </button>
          <button
            type="button"
            className="ui-icon-btn"
            title="Close panel"
            aria-label="Close artifacts panel"
            onClick={() => setArtifactPanelOpen(false)}
          >
            <X size={15} />
          </button>
        </div>
      </header>

      {!active ? (
        <div className="artifact-empty">
          <Code2 size={26} />
          <p>No artifacts in this conversation yet.</p>
          <span>
            Ask for HTML, an SVG, a Mermaid diagram, or a React component and it will appear here.
          </span>
        </div>
      ) : (
        <>
          {sessionArtifacts.length > 1 && !vaultArtifact && (
            <div className="artifact-tabs" role="tablist">
              {sessionArtifacts.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  role="tab"
                  aria-selected={a.id === active.id}
                  className={`artifact-tab${a.id === active.id ? ' is-active' : ''}`}
                  onClick={() => selectSessionArtifact(a.id)}
                  title={a.title}
                >
                  {ARTIFACT_TYPE_LABEL[a.type]}
                </button>
              ))}
            </div>
          )}

          <div className="artifact-toolbar">
            <div className="artifact-toolbar-info">
              <span className="artifact-type-badge">{ARTIFACT_TYPE_LABEL[active.type]}</span>
              <span className="artifact-title" title={active.title}>
                {active.title}
              </span>
            </div>
            <div className="artifact-toolbar-actions">
              {supportsPreview && (
                <div className="artifact-view-toggle" role="group" aria-label="View mode">
                  <button
                    type="button"
                    className={viewMode === 'preview' ? 'is-active' : ''}
                    title="Preview"
                    aria-label="Preview"
                    onClick={() => setViewMode('preview')}
                  >
                    <Eye size={14} />
                  </button>
                  <button
                    type="button"
                    className={viewMode === 'code' ? 'is-active' : ''}
                    title="Code"
                    aria-label="Code"
                    onClick={() => setViewMode('code')}
                  >
                    <Code2 size={14} />
                  </button>
                </div>
              )}
              {(active.type === 'html' || active.type === 'svg') && (
                <button
                  type="button"
                  className="ui-icon-btn"
                  title="Open preview in a new tab"
                  aria-label="Open preview in a new tab"
                  onClick={openInNewTab}
                >
                  <ExternalLink size={15} />
                </button>
              )}
              <button
                type="button"
                className={`ui-icon-btn${editing ? ' is-active' : ''}`}
                title={editing ? 'Close editor' : 'Open in Editor'}
                aria-label={editing ? 'Close editor' : 'Open in editor'}
                onClick={() => {
                  setEditing((v) => !v);
                  setDraft(active.content);
                }}
              >
                <Pencil size={15} />
              </button>
              <button
                type="button"
                className={`ui-icon-btn${savedIds.has(active.id) ? ' is-active' : ''}`}
                title="Save to Vault"
                aria-label="Save artifact to vault"
                onClick={save}
              >
                <Save size={15} />
              </button>
              <button type="button" className="ui-icon-btn" title="Copy" aria-label="Copy artifact" onClick={copy}>
                <Copy size={15} />
              </button>
              <button
                type="button"
                className="ui-icon-btn"
                title="Download"
                aria-label="Download artifact"
                onClick={() => downloadArtifact(active)}
              >
                <Download size={15} />
              </button>
              <button type="button" className="ui-icon-btn" title="Share" aria-label="Share artifact" onClick={share}>
                <Share2 size={15} />
              </button>
            </div>
          </div>

          <div className={`artifact-preview artifact-preview--${active.type}`}>{renderPreview()}</div>

          {editing && (
            <textarea
              className="artifact-editor"
              value={draft}
              spellCheck={false}
              onChange={(e) => setDraft(e.target.value)}
              aria-label="Artifact editor"
            />
          )}
        </>
      )}

      <ArtifactVault
        open={vaultOpen}
        onClose={() => setVaultOpen(false)}
        onOpen={(artifact) => {
          setVaultArtifact(artifact);
          setSelectedId(null);
        }}
      />
    </aside>
  );
}
