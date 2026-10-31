import { useEffect, useMemo, useRef, useState } from 'react';
import { History, Loader2 } from 'lucide-react';
import { Dialog, EmptyState } from '../../ui/primitives';
import { useConfirm } from '../ConfirmDialog';
import type { ProjectArtifact } from '../../types';
import type { SavedArtifact } from '../../utils/artifactVault';
import { diffLines } from '../../utils/lineDiff';

interface CompareSelection {
  source: 'local' | 'project';
  id: string;
  label: string;
}

function formatTimestamp(value: number): string {
  if (!value) return 'Unknown time';
  const ms = value < 10_000_000_000 ? value * 1000 : value;
  return new Date(ms).toLocaleString();
}

function formatSize(size: number): string {
  if (!size) return '0 chars';
  if (size < 1024) return `${size.toLocaleString()} chars`;
  return `${(size / 1024).toFixed(1)} KB`;
}

function isServerCurrent(artifact: ProjectArtifact | null, version: number): boolean {
  return Boolean(artifact && artifact.current_version === version);
}

export default function ArtifactVersionDialog({
  open,
  onClose,
  title,
  currentContent,
  dirty,
  saved,
  projectArtifact,
  projectLoading,
  onRestoreLocal,
  onRestoreProject,
  onLoadLocalVersion,
  onLoadProjectVersion,
}: {
  open: boolean;
  onClose: () => void;
  title?: string;
  currentContent: string;
  dirty: boolean;
  saved: SavedArtifact | null;
  projectArtifact: ProjectArtifact | null;
  projectLoading: boolean;
  onRestoreLocal: (versionId: string) => Promise<void>;
  onRestoreProject: (version: number) => Promise<void>;
  onLoadLocalVersion: (versionId: string) => Promise<string>;
  onLoadProjectVersion: (version: number) => Promise<string>;
}) {
  const confirm = useConfirm();
  const [compare, setCompare] = useState<CompareSelection | null>(null);
  const [compareContent, setCompareContent] = useState('');
  const [compareLoading, setCompareLoading] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);
  const compareToken = useRef(0);

  const localVersions = saved ? [...saved.versions].reverse() : [];
  const projectVersions = projectArtifact
    ? [...projectArtifact.versions].reverse()
    : [];

  useEffect(() => {
    if (!open) {
      setCompare(null);
      setCompareContent('');
      setCompareLoading(false);
      setRestoring(null);
    }
  }, [open]);

  const diff = useMemo(
    () => (compare ? diffLines(compareContent, currentContent) : null),
    [compare, compareContent, currentContent],
  );

  const openCompare = async (selection: CompareSelection) => {
    const token = compareToken.current + 1;
    compareToken.current = token;
    setCompare(selection);
    setCompareContent('');
    setCompareLoading(true);
    try {
      const content =
        selection.source === 'local'
          ? await onLoadLocalVersion(selection.id)
          : await onLoadProjectVersion(Number(selection.id));
      if (compareToken.current === token) setCompareContent(content);
    } catch {
      if (compareToken.current === token) setCompareContent('');
    } finally {
      if (compareToken.current === token) setCompareLoading(false);
    }
  };

  const requestRestore = async (
    source: 'local' | 'project',
    id: string,
    label: string,
  ) => {
    const ok = await confirm(
      `Restore ${label}? Your current content will be autosaved as a draft first.`,
      { title: 'Restore Version', confirmLabel: 'Restore' },
    );
    if (!ok) return;
    setRestoring(`${source}:${id}`);
    try {
      if (source === 'local') await onRestoreLocal(id);
      else await onRestoreProject(Number(id));
    } finally {
      setRestoring(null);
    }
  };

  const hasVersions = localVersions.length > 0 || projectVersions.length > 0;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Version History"
      subtitle={title}
      width={860}
    >
      {!hasVersions ? (
        projectLoading ? (
          <div className="artifact-version-loading">
            <Loader2 size={18} className="artifact-version-spinner" />
            <span>Loading version history…</span>
          </div>
        ) : (
          <EmptyState
            icon={<History size={22} />}
            title="No versions yet"
            description="Save this artifact to the vault to start a version history."
          />
        )
      ) : (
        <div className="artifact-version-dialog">
          {dirty && (
            <div className="artifact-version-dirty">
              Unsaved edits are autosaved as a draft before restoring.
            </div>
          )}

          {localVersions.length > 0 && (
            <section className="artifact-timeline">
              <h4 className="artifact-timeline-title">Local vault</h4>
              <div className="artifact-timeline-list">
                {localVersions.map(version => {
                  const isCurrent = saved?.currentVersionId === version.id;
                  const isRestoring = restoring === `local:${version.id}`;
                  return (
                    <div
                      className={`artifact-version-row${isCurrent ? ' is-current' : ''}`}
                      key={version.id}
                    >
                      <span className="artifact-timeline-dot" aria-hidden="true" />
                      <div className="artifact-version-main">
                        <div className="artifact-version-line">
                          <span className="artifact-version-time">
                            {formatTimestamp(version.savedAt)}
                          </span>
                          {isCurrent && (
                            <span className="artifact-version-current">Current</span>
                          )}
                          {version.autosaved && (
                            <span className="artifact-version-auto">Auto</span>
                          )}
                        </div>
                        <span className="artifact-version-note">
                          {version.note || 'Saved version'} ·{' '}
                          {formatSize(version.size)}
                        </span>
                      </div>
                      <div className="artifact-version-actions">
                        <button
                          type="button"
                          className="artifact-version-action"
                          onClick={() =>
                            void openCompare({
                              source: 'local',
                              id: version.id,
                              label: formatTimestamp(version.savedAt),
                            })
                          }
                        >
                          Compare
                        </button>
                        {!isCurrent && (
                          <button
                            type="button"
                            className="artifact-version-action is-primary"
                            disabled={restoring !== null}
                            onClick={() =>
                              void requestRestore(
                                'local',
                                version.id,
                                `the version from ${formatTimestamp(version.savedAt)}`,
                              )
                            }
                          >
                            {isRestoring ? 'Restoring…' : 'Restore'}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {(projectVersions.length > 0 || projectLoading) && (
            <section className="artifact-timeline">
              <h4 className="artifact-timeline-title">
                Project versions
                {projectLoading && (
                  <Loader2 size={12} className="artifact-version-spinner" />
                )}
              </h4>
              {projectVersions.length > 0 && (
                <div className="artifact-timeline-list">
                  {projectVersions.map(version => {
                    const isCurrent = isServerCurrent(
                      projectArtifact,
                      version.version,
                    );
                    const isRestoring =
                      restoring === `project:${version.version}`;
                    return (
                      <div
                        className={`artifact-version-row${isCurrent ? ' is-current' : ''}`}
                        key={version.version}
                      >
                        <span className="artifact-timeline-dot" aria-hidden="true" />
                        <div className="artifact-version-main">
                          <div className="artifact-version-line">
                            <span className="artifact-version-time">
                              Version {version.version}
                            </span>
                            {isCurrent && (
                              <span className="artifact-version-current">
                                Current
                              </span>
                            )}
                          </div>
                          <span className="artifact-version-note">
                            {formatTimestamp(version.created_at)} ·{' '}
                            {formatSize(version.size)}
                          </span>
                        </div>
                        <div className="artifact-version-actions">
                          <button
                            type="button"
                            className="artifact-version-action"
                            onClick={() =>
                              void openCompare({
                                source: 'project',
                                id: String(version.version),
                                label: `server version ${version.version}`,
                              })
                            }
                          >
                            Compare
                          </button>
                          {!isCurrent && (
                            <button
                              type="button"
                              className="artifact-version-action is-primary"
                              disabled={restoring !== null}
                              onClick={() =>
                                void requestRestore(
                                  'project',
                                  String(version.version),
                                  `server version ${version.version}`,
                                )
                              }
                            >
                              {isRestoring ? 'Restoring…' : 'Restore'}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          )}

          {compare && (
            <section className="artifact-diff" aria-label="Version comparison">
              <header className="artifact-diff-head">
                <div className="artifact-diff-heading">
                  <strong>Version</strong>
                  <span>{compare.label}</span>
                </div>
                <div className="artifact-diff-heading">
                  <strong>Current</strong>
                  <span>{dirty ? 'unsaved edits' : 'saved content'}</span>
                </div>
                <button
                  type="button"
                  className="artifact-version-action"
                  onClick={() => setCompare(null)}
                >
                  Close
                </button>
              </header>
              {compareLoading ? (
                <div className="artifact-version-loading">
                  <Loader2 size={16} className="artifact-version-spinner" />
                  <span>Loading version…</span>
                </div>
              ) : (
                <>
                  <div className="artifact-diff-summary">
                    +{diff?.added ?? 0} added · −{diff?.removed ?? 0} removed
                  </div>
                  <div className="artifact-diff-body">
                    {diff?.rows.map((row, index) => (
                      <div className="artifact-diff-row" key={index}>
                        <span
                          className={`artifact-diff-no${row.left ? ` is-${row.left.kind}` : ''}`}
                        >
                          {row.left?.number ?? ''}
                        </span>
                        <code
                          className={`artifact-diff-code${row.left ? ` is-${row.left.kind}` : ''}`}
                        >
                          {row.left?.text ?? ''}
                        </code>
                        <span
                          className={`artifact-diff-no${row.right ? ` is-${row.right.kind}` : ''}`}
                        >
                          {row.right?.number ?? ''}
                        </span>
                        <code
                          className={`artifact-diff-code${row.right ? ` is-${row.right.kind}` : ''}`}
                        >
                          {row.right?.text ?? ''}
                        </code>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </section>
          )}
        </div>
      )}
    </Dialog>
  );
}
