import { useEffect, useMemo, useState } from 'react';
import {
  Accessibility,
  Cpu,
  Database,
  Folder,
  Package,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { useApp } from '../../AppContext';
import { api } from '../../api';
import { useConfirm } from '../ConfirmDialog';
import { resolveScope } from '../../lib/scope';
import { Dialog } from '../../ui/primitives';
import { auditAccessibility, type A11yIssue } from '../../utils/a11y';
import { collectArtifacts } from '../../utils/artifacts';
import { memoryForScope } from '../../utils/chatMemory';
import { redactText } from '../../utils/redaction';
import { loadRetention, saveRetention as persistRetention, retentionKey, retentionLabel, type RetentionDays } from '../../utils/retention';
import './ChatTrustDialog.css';

function leaf(path: string | null): string {
  if (!path) return 'Local workspace';
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export default function ChatTrustDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const {
    currentModel,
    llmSubMode,
    activeField,
    activeProjectId,
    activeProjectName,
    activeView,
    selectedAgentId,
    sessions,
    activeSessionId,
    setSessions,
    setActiveSessionId,
    chatMemory,
    removeChatMemory,
    pinnedContext,
    clearPinnedContext,
    addToast,
  } = useApp();
  const confirm = useConfirm();
  const [showRedacted, setShowRedacted] = useState(true);
  const [retention, setRetention] = useState<RetentionDays>(0);
  const [auditEvents, setAuditEvents] = useState<
    { timestamp: number; event: string; detail: Record<string, unknown> }[]
  >([]);
  const [a11yIssues, setA11yIssues] = useState<A11yIssue[] | null>(null);

  const session = sessions.find((item) => item.id === activeSessionId);
  const artifacts = collectArtifacts(session?.messages).length;
  const activeMemory = memoryForScope(chatMemory, {
    sessionId: activeSessionId,
    projectId: activeProjectId,
  });
  const workspace = activeProjectId ? activeProjectName || 'Project' : leaf(activeField);
  const mode =
    llmSubMode === 'moe'
      ? 'Mixture of Experts'
      : llmSubMode === 'deep_research'
        ? 'Deep Research'
        : 'Default';
  const scope = resolveScope(activeView, {
    agentId: selectedAgentId,
    projectId: activeProjectId,
  });

  useEffect(() => {
    if (!open) return;
    setRetention(loadRetention(activeSessionId));
    let cancelled = false;
    api.chat
      .audit(activeSessionId ?? '', 40)
      .then((data) => {
        if (!cancelled) setAuditEvents(data.events || []);
      })
      .catch(() => {
        if (!cancelled) setAuditEvents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, retentionKey(activeSessionId), activeSessionId]);

  const contextText = useMemo(() => {
    const messages = (session?.messages ?? []).slice(-16).map((message) => {
      const role = message.role === 'user' ? 'You' : 'Assistant';
      return `${role}:\n${message.content}`;
    });
    const memory = activeMemory.map((item) => `- ${item.text}`);
    const pinned = pinnedContext.map((item) => `- ${item.kind}: ${item.title}`);
    return [
      `Workspace: ${workspace}`,
      `Model: ${currentModel || 'unknown'} · ${mode}`,
      messages.length ? `\nConversation:\n${messages.join('\n\n---\n\n')}` : '',
      memory.length ? `\nMemory:\n${memory.join('\n')}` : '',
      pinned.length ? `\nPinned context:\n${pinned.join('\n')}` : '',
    ]
      .filter(Boolean)
      .join('\n');
  }, [session?.messages, activeMemory, pinnedContext, workspace, currentModel, mode]);

  const redacted = useMemo(() => redactText(contextText), [contextText]);
  const preview = showRedacted ? redacted.text : contextText;

  const saveRetention = (days: RetentionDays) => {
    setRetention(days);
    persistRetention(activeSessionId, days);
    addToast(`Retention set to ${retentionLabel(days).toLowerCase()}`, { tone: 'success' });
  };

  const deleteChat = async () => {
    if (!activeSessionId) return;
    const ok = await confirm(
      'Delete this chat and its transcript permanently? This cannot be undone.',
      { title: 'Delete chat', confirmLabel: 'Delete', danger: true },
    );
    if (!ok) return;
    try {
      const data = await api.sessions.remove(activeSessionId, scope);
      if (data.error) {
        addToast(data.error, { tone: 'error' });
        return;
      }
      setSessions(data.sessions as typeof sessions);
      setActiveSessionId(data.active_session_id);
      addToast('Chat deleted', { tone: 'success' });
      onClose();
    } catch {
      addToast('Could not delete the chat.', { tone: 'error' });
    }
  };

  const copyContext = async () => {
    try {
      await navigator.clipboard.writeText(preview);
      addToast(
        showRedacted ? 'Redacted context copied' : 'Context copied',
        { tone: 'success' },
      );
    } catch {
      addToast('Could not access the clipboard.', { tone: 'error' });
    }
  };

  const runA11y = () => {
    setA11yIssues(auditAccessibility(document));
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Chat details"
      subtitle="What this chat is using, what it remembers and what leaves the machine."
      width={660}
    >
      <div className="chat-trust">
        <dl className="chat-trust__grid">
          <div>
            <dt><Cpu size={13} /> Model</dt>
            <dd>{currentModel || 'Not selected'}</dd>
          </div>
          <div>
            <dt>Mode</dt>
            <dd>{mode}</dd>
          </div>
          <div>
            <dt><Folder size={13} /> Workspace</dt>
            <dd>{workspace}</dd>
          </div>
          <div>
            <dt><Package size={13} /> Artifacts</dt>
            <dd>{artifacts}</dd>
          </div>
          <div>
            <dt><Database size={13} /> Memory</dt>
            <dd>{activeMemory.length} fact{activeMemory.length === 1 ? '' : 's'}</dd>
          </div>
          <div>
            <dt><ShieldCheck size={13} /> Processing</dt>
            <dd>Local-first</dd>
          </div>
        </dl>

        <details className="chat-trust__details" open>
          <summary>
            Context inspector
            {showRedacted && redacted.matches.length > 0 && (
              <span className="chat-trust__badge">{redacted.matches.length} redacted</span>
            )}
          </summary>
          <div className="chat-trust__inspector">
            <div className="chat-trust__inspector-head">
              <label className="chat-trust__toggle">
                <input
                  type="checkbox"
                  checked={showRedacted}
                  onChange={(event) => setShowRedacted(event.target.checked)}
                />
                Redact sensitive data
              </label>
              <button type="button" onClick={() => void copyContext()}>
                Copy {showRedacted ? 'redacted' : 'context'}
              </button>
            </div>
            <pre className="chat-trust__preview" aria-label="Context preview">
              {preview}
            </pre>
            {showRedacted && redacted.matches.length > 0 && (
              <p className="chat-trust__redaction-note" role="status">
                Redacted {redacted.matches.length} item(s):{' '}
                {[...new Set(redacted.matches.map((match) => match.kind))].join(', ')}
              </p>
            )}
          </div>
        </details>

        <section className="chat-trust__memory" aria-label="Chat memory">
          <h3>Chat memory</h3>
          {activeMemory.length === 0 ? (
            <p>Nothing remembered yet. Add facts from the Memory button or any answer’s save menu.</p>
          ) : (
            <ul>
              {activeMemory.map((item) => (
                <li key={item.id}>
                  <span>{item.text}</span>
                  <button
                    type="button"
                    onClick={() => removeChatMemory(item.id)}
                    aria-label={`Forget: ${item.text}`}
                    title="Forget this"
                  >
                    <Trash2 size={13} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {pinnedContext.length > 0 && (
          <section className="chat-trust__memory" aria-label="Pinned context">
            <div className="chat-trust__section-head">
              <h3>Pinned context ({pinnedContext.length})</h3>
              <button type="button" onClick={clearPinnedContext}>Clear</button>
            </div>
            <ul>
              {pinnedContext.map((item) => (
                <li key={item.id}>
                  <span>{item.kind === 'artifact' ? 'Artifact' : 'Message'} · {item.title}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="chat-trust__retention" aria-label="Retention controls">
          <div>
            <h3>Retention</h3>
            <p>Retention policy is stored locally; delete the chat now to remove the transcript.</p>
          </div>
          <select
            value={retention}
            onChange={(event) => saveRetention(Number(event.target.value) as RetentionDays)}
            aria-label="Chat retention"
          >
            <option value={0}>Keep until I delete</option>
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
          <button
            type="button"
            className="chat-trust__danger"
            onClick={() => void deleteChat()}
            disabled={!activeSessionId}
          >
            <Trash2 size={13} />
            Delete this chat
          </button>
        </section>

        <details className="chat-trust__details">
          <summary>Audit log <span className="chat-trust__badge">{auditEvents.length}</span></summary>
          <div className="chat-trust__audit" role="log" aria-live="polite">
            {auditEvents.length === 0 ? (
              <p>No audit events for this chat yet.</p>
            ) : (
              <ul>
                {auditEvents.map((event, index) => (
                  <li key={`${event.timestamp}-${index}`}>
                    <time dateTime={new Date(event.timestamp * 1000).toISOString()}>
                      {new Date(event.timestamp * 1000).toLocaleString()}
                    </time>
                    <strong>{event.event}</strong>
                    <span>{Object.keys(event.detail || {}).length > 0 ? JSON.stringify(event.detail) : ''}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </details>

        <section className="chat-trust__a11y" aria-label="Accessibility check">
          <div className="chat-trust__section-head">
            <h3><Accessibility size={14} /> Accessibility check</h3>
            <button type="button" onClick={runA11y}>
              <RefreshCw size={12} />
              Run check
            </button>
          </div>
          {a11yIssues === null ? (
            <p>Run a local check for missing names, image alt text, duplicate ids and tab-order issues.</p>
          ) : a11yIssues.length === 0 ? (
            <p className="chat-trust__ok" role="status">No accessibility issues found in the current view.</p>
          ) : (
            <ul className="chat-trust__issues" role="status">
              {a11yIssues.map((issue, index) => (
                <li key={`${issue.rule}-${index}`}>
                  <strong>{issue.rule}</strong>
                  <span>{issue.message} · <code>{issue.target}</code></span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Dialog>
  );
}
