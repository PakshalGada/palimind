import type { ReactNode } from 'react';
import {
  BookOpen,
  Code2,
  Copy,
  Download,
  ExternalLink,
  Eye,
  FileDown,
  FolderPlus,
  History,
  MoreHorizontal,
  Pencil,
  Save,
  Share2,
} from 'lucide-react';
import { Popover } from '../../ui/primitives';
import {
  ARTIFACT_TYPE_LABEL,
  EXPORT_FORMAT_LABEL,
  isPreviewable,
  type ExportFormat,
} from '../../utils/artifacts';
import ArtifactIcon from './ArtifactIcon';
import type { ActiveArtifact, ViewMode } from './types';

function MenuItem({
  icon,
  label,
  hint,
  disabled,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  hint?: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      className="artp-menu-item"
      disabled={disabled}
      onClick={onClick}
    >
      <span className="artp-menu-icon">{icon}</span>
      <span className="artp-menu-label">{label}</span>
      {hint && <span className="artp-menu-hint">{hint}</span>}
    </button>
  );
}

export default function ArtifactToolbar({
  active,
  content,
  saved,
  versionCount,
  editing,
  viewMode,
  exporting,
  pinBusy,
  onToggleView,
  onToggleEdit,
  onSave,
  onExport,
  onCopy,
  onDownload,
  onShare,
  onOpenHistory,
  onOpenProject,
  onSaveKnowledge,
  onOpenInNewTab,
}: {
  active: ActiveArtifact;
  content: string;
  saved: boolean;
  versionCount: number;
  editing: boolean;
  viewMode: ViewMode;
  exporting: ExportFormat | null;
  pinBusy: boolean;
  onToggleView: (mode: ViewMode) => void;
  onToggleEdit: () => void;
  onSave: () => void;
  onExport: (format: ExportFormat) => void;
  onCopy: () => void;
  onDownload: () => void;
  onShare: () => void;
  onOpenHistory: () => void;
  onOpenProject: () => void;
  onSaveKnowledge: () => void;
  onOpenInNewTab: () => void;
}) {
  const lineCount = content ? content.split('\n').length : 0;
  const charCount = content.length;

  return (
    <>
      <div className="artp-meta">
        <div className="artp-meta-main">
          <span className={`artp-type type-${active.type}`}>
            <ArtifactIcon type={active.type} size={11} />
            {ARTIFACT_TYPE_LABEL[active.type]}
          </span>
          <span className="artp-title" title={active.title}>
            {active.title}
          </span>
          {active.closed === false && <span className="artp-tag">truncated</span>}
        </div>
        <div className="artp-sub">
          <span>{lineCount.toLocaleString()} lines</span>
          <span className="artp-sub-sep" aria-hidden="true" />
          <span>{charCount.toLocaleString()} chars</span>
          {versionCount > 0 && (
            <>
              <span className="artp-sub-sep" aria-hidden="true" />
              <span>
                {versionCount.toLocaleString()} version{versionCount === 1 ? '' : 's'}
              </span>
            </>
          )}
          {active.streaming && (
            <span className="artp-status is-live">
              <span className="artp-status-dot" aria-hidden="true" />
              Streaming
            </span>
          )}
          {saved && (
            <span className="artp-status is-saved" title="Current version saved to vault">
              <span className="artp-status-dot" aria-hidden="true" />
              Saved
            </span>
          )}
        </div>
      </div>

      <div className="artp-actions">
        <div className="artp-actions-left">
          {isPreviewable(active.type) && (
            <div className="artp-seg" role="group" aria-label="View mode">
              <button
                type="button"
                className={viewMode === 'preview' ? 'is-active' : ''}
                title="Preview"
                aria-label="Preview"
                aria-pressed={viewMode === 'preview'}
                onClick={() => onToggleView('preview')}
              >
                <Eye size={14} />
                <span className="artp-seg-label">Preview</span>
              </button>
              <button
                type="button"
                className={viewMode === 'code' ? 'is-active' : ''}
                title="Source"
                aria-label="Source"
                aria-pressed={viewMode === 'code'}
                onClick={() => onToggleView('code')}
              >
                <Code2 size={14} />
                <span className="artp-seg-label">Code</span>
              </button>
            </div>
          )}
          <button
            type="button"
            className={`artp-btn${editing ? ' is-active' : ''}`}
            title="Edit artifact (Ctrl/⌘ E)"
            aria-label="Edit artifact"
            aria-pressed={editing}
            onClick={onToggleEdit}
          >
            <Pencil size={14} />
            <span className="artp-btn-label">Edit</span>
          </button>
        </div>

        <div className="artp-actions-right">
          <button
            type="button"
            className={`artp-btn is-primary${saved ? ' is-saved' : ''}`}
            title="Save version (Ctrl/⌘ S)"
            aria-label="Save artifact version to vault"
            onClick={onSave}
          >
            <Save size={14} />
            <span className="artp-btn-label">Save</span>
          </button>

          <Popover
            ariaLabel="Export artifact"
            align="end"
            trigger={
              <button
                type="button"
                className="artp-btn artp-btn-icon"
                title="Export artifact"
                aria-label="Export artifact"
                disabled={exporting !== null}
              >
                <FileDown size={14} />
              </button>
            }
          >
            {close => (
              <div className="artp-menu" role="menu">
                {(Object.keys(EXPORT_FORMAT_LABEL) as ExportFormat[]).map(format => (
                  <button
                    key={format}
                    type="button"
                    role="menuitem"
                    className="artp-menu-item"
                    onClick={() => {
                      close();
                      onExport(format);
                    }}
                  >
                    <span className="artp-menu-label">{EXPORT_FORMAT_LABEL[format]}</span>
                    {exporting === format && <span className="artp-spinner" />}
                  </button>
                ))}
              </div>
            )}
          </Popover>

          <Popover
            ariaLabel="More artifact actions"
            align="end"
            trigger={
              <button
                type="button"
                className="artp-btn artp-btn-icon"
                title="More actions"
                aria-label="More actions"
              >
                <MoreHorizontal size={16} />
              </button>
            }
          >
            {close => (
              <div className="artp-menu" role="menu">
                <MenuItem
                  icon={<Copy size={14} />}
                  label="Copy content"
                  hint="Ctrl/⌘ ⇧ C"
                  onClick={() => {
                    close();
                    onCopy();
                  }}
                />
                <MenuItem
                  icon={<Download size={14} />}
                  label="Download source"
                  onClick={() => {
                    close();
                    onDownload();
                  }}
                />
                <MenuItem
                  icon={<Share2 size={14} />}
                  label="Share"
                  onClick={() => {
                    close();
                    onShare();
                  }}
                />
                <span className="artp-menu-sep" role="separator" />
                <MenuItem
                  icon={<History size={14} />}
                  label="Version history"
                  onClick={() => {
                    close();
                    onOpenHistory();
                  }}
                />
                <MenuItem
                  icon={<FolderPlus size={14} />}
                  label="Pin to project"
                  disabled={pinBusy}
                  onClick={() => {
                    close();
                    onOpenProject();
                  }}
                />
                <span className="artp-menu-sep" role="separator" />
                <MenuItem
                  icon={<BookOpen size={14} />}
                  label="Save to knowledge"
                  onClick={() => {
                    close();
                    onSaveKnowledge();
                  }}
                />
                <MenuItem
                  icon={<ExternalLink size={14} />}
                  label="Open in new tab"
                  onClick={() => {
                    close();
                    onOpenInNewTab();
                  }}
                />
              </div>
            )}
          </Popover>
        </div>
      </div>
    </>
  );
}
