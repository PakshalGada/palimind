import { File, FileText, Image as ImageIcon, Music, Video } from 'lucide-react';
import { useApp } from '../../AppContext';
import type { ChatAttachment } from '../../types';

function formatSize(bytes?: number): string {
  if (!bytes || bytes < 1) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function kindLabel(attachment: ChatAttachment): string {
  const kind = attachment.kind ?? 'file';
  if (kind === 'image') return 'Image';
  if (kind === 'pdf') return 'PDF';
  if (kind === 'text') return 'Text';
  if (kind === 'audio') return 'Audio';
  if (kind === 'video') return 'Video';
  const ext = attachment.name.split('.').pop();
  return ext ? ext.toUpperCase() : 'File';
}

function AttachmentIcon({ attachment }: { attachment: ChatAttachment }) {
  const kind = attachment.kind ?? 'file';
  if (kind === 'image') return <ImageIcon size={14} />;
  if (kind === 'pdf' || kind === 'text') return <FileText size={14} />;
  if (kind === 'audio') return <Music size={14} />;
  if (kind === 'video') return <Video size={14} />;
  return <File size={14} />;
}

export default function MessageAttachments({
  attachments,
}: {
  attachments: ChatAttachment[];
}) {
  const { openWorkbenchDocument } = useApp();
  if (attachments.length === 0) return null;

  return (
    <div className="message-attachments" aria-label="Attached files">
      {attachments.map((attachment) => {
        const size = formatSize(attachment.size);
        return (
          <button
            key={attachment.id}
            type="button"
            className="message-attachment"
            title={`Open ${attachment.name}`}
            onClick={() => openWorkbenchDocument(attachment)}
          >
            <span className="message-attachment__icon" aria-hidden="true">
              <AttachmentIcon attachment={attachment} />
            </span>
            <span className="message-attachment__text">
              <span className="message-attachment__name">{attachment.name}</span>
              <span className="message-attachment__meta">
                {kindLabel(attachment)}
                {size ? ` · ${size}` : ''}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
