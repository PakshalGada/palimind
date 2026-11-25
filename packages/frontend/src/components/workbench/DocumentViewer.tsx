import { useEffect, useState } from 'react';
import { Download, ExternalLink, FileText } from 'lucide-react';
import { api } from '../../api';
import { EmptyState } from '../../ui/primitives';
import type { ChatAttachment } from '../../types';

function formatSize(bytes?: number): string {
  if (!bytes || bytes < 1) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isImage(attachment: ChatAttachment): boolean {
  return attachment.kind === 'image' || Boolean(attachment.mime?.startsWith('image/'));
}

function isPdf(attachment: ChatAttachment): boolean {
  return attachment.kind === 'pdf' || attachment.mime === 'application/pdf';
}

function isText(attachment: ChatAttachment): boolean {
  return (
    attachment.kind === 'text' ||
    Boolean(attachment.mime?.startsWith('text/')) ||
    /\.(txt|md|markdown|csv|tsv|json|jsonl|yaml|yml|toml|ini|xml|html?|py|js|ts|tsx|jsx|sql|log|rst)$/i.test(
      attachment.name,
    )
  );
}

export default function DocumentViewer({ attachment }: { attachment: ChatAttachment }) {
  const url = api.uploads.fileUrl(attachment.id);
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setText(null);
    setError('');
    if (!isText(attachment)) return;
    let cancelled = false;
    setLoading(true);
    fetch(url, { credentials: 'include' })
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.text();
      })
      .then((body) => {
        if (!cancelled) setText(body);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not read the file.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attachment, url]);

  return (
    <div className="wb-doc">
      <div className="wb-doc__bar">
        <span className="wb-doc__icon" aria-hidden="true">
          <FileText size={15} />
        </span>
        <span className="wb-doc__name" title={attachment.name}>
          {attachment.name}
        </span>
        {formatSize(attachment.size) && (
          <span className="wb-doc__size">{formatSize(attachment.size)}</span>
        )}
        <a
          className="wb-doc__action"
          href={url}
          download={attachment.name}
          title="Download"
          aria-label={`Download ${attachment.name}`}
        >
          <Download size={14} />
        </a>
        <a
          className="wb-doc__action"
          href={url}
          target="_blank"
          rel="noreferrer"
          title="Open in a new tab"
          aria-label={`Open ${attachment.name} in a new tab`}
        >
          <ExternalLink size={14} />
        </a>
      </div>

      <div className="wb-doc__body">
        {isImage(attachment) ? (
          <img className="wb-doc__image" src={url} alt={attachment.name} />
        ) : isPdf(attachment) ? (
          <iframe className="wb-doc__frame" src={url} title={attachment.name} />
        ) : isText(attachment) ? (
          loading ? (
            <p className="wb-doc__status">Loading…</p>
          ) : error ? (
            <p className="wb-doc__status">{error}</p>
          ) : (
            <pre className="wb-doc__text">{text ?? ''}</pre>
          )
        ) : (
          <div className="wb-doc__empty">
            <EmptyState
              icon={<FileText size={22} />}
              title="No preview available"
              description="This file type cannot be shown here yet. Use Open or Download above to view it."
            />
          </div>
        )}
      </div>
    </div>
  );
}
