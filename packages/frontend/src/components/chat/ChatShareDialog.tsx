import { useMemo, useState } from 'react';
import { Download, FileText, Link2, Loader2, Package } from 'lucide-react';
import { useApp } from '../../AppContext';
import { api } from '../../api';
import { Dialog } from '../../ui/primitives';
import { collectArtifacts } from '../../utils/artifacts';
import './ChatShareDialog.css';

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function ChatShareDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { sessions, activeSessionId, addToast } = useApp();
  const [busy, setBusy] = useState(false);
  const [includeArtifacts, setIncludeArtifacts] = useState(true);

  const session = sessions.find((item) => item.id === activeSessionId);
  const messages = session?.messages ?? [];
  const artifacts = useMemo(() => collectArtifacts(messages), [messages]);
  const sources = useMemo(() => {
    const map = new Map<string, { title?: string; url?: string; file?: string; section?: string; kind?: string }>();
    for (const message of messages) {
      for (const source of message.citations?.sources ?? []) {
        const key = source.url || `${source.file}:${source.section || ''}`;
        if (!key) continue;
        map.set(key, {
          title: source.title,
          url: source.url,
          file: source.file,
          section: source.section,
          kind: source.kind,
        });
      }
      for (const url of message.sources ?? []) {
        if (!url) continue;
        map.set(url, { title: url, url });
      }
    }
    return [...map.values()];
  }, [messages]);

  const download = async () => {
    if (messages.length === 0) return;
    setBusy(true);
    try {
      const result = await api.chat.exportBundle({
        title: session?.name || 'Conversation',
        messages: messages.map((message) => ({
          role: message.role,
          content: message.content,
          timestamp: message.timestamp,
        })),
        artifacts: includeArtifacts
          ? artifacts.map((artifact) => ({
              title: artifact.title,
              type: artifact.type,
              content: artifact.content,
            }))
          : [],
        sources,
      });
      downloadBlob(result.blob, result.filename);
      addToast('Chat bundle downloaded', { tone: 'success' });
      onClose();
    } catch (error) {
      addToast(error instanceof Error ? error.message : 'Could not export the chat.', {
        tone: 'error',
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Share chat bundle"
      subtitle="Everything in one ZIP: transcript, artifacts and sources."
      width={560}
    >
      <div className="chat-share">
        <div className="chat-share__summary">
          <div>
            <FileText size={15} />
            <strong>{messages.length}</strong>
            <span>messages</span>
          </div>
          <div>
            <Package size={15} />
            <strong>{artifacts.length}</strong>
            <span>artifacts</span>
          </div>
          <div>
            <Link2 size={15} />
            <strong>{sources.length}</strong>
            <span>sources</span>
          </div>
        </div>

        <label className="chat-share__option">
          <input
            type="checkbox"
            checked={includeArtifacts}
            onChange={(event) => setIncludeArtifacts(event.target.checked)}
          />
          Include generated artifacts in the bundle
        </label>

        <div className="chat-share__files">
          <code>transcript.md</code>
          <code>sources.md</code>
          <code>sources.json</code>
          {includeArtifacts && <code>artifacts/</code>}
          <code>manifest.json</code>
        </div>

        <button
          type="button"
          className="chat-share__download"
          onClick={() => void download()}
          disabled={busy || messages.length === 0}
        >
          {busy ? <Loader2 size={15} className="spin" /> : <Download size={15} />}
          {busy ? 'Building bundle…' : 'Download bundle'}
        </button>
      </div>
    </Dialog>
  );
}
