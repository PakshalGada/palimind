import { useEffect, useRef, useState } from 'react';
import {
  Check,
  ChevronDown,
  Copy,
  FileText,
  FlaskConical,
  Pencil,
  RefreshCw,
  Share2,
  Star,
  StarOff,
  Trash2,
} from 'lucide-react';
import { useConfirm } from './ConfirmDialog';
import './MessageActions.css';

export interface MessageActionsProps {
  content: string;
  isUser: boolean;
  bookmarked: boolean;
  /** Regenerate the reply (assistant messages only). */
  onRegenerate?: () => void;
  /** Enter inline edit mode (user messages only). */
  onEdit?: () => void;
  /** Send this message's content to the Canvas panel. */
  onOpenCanvas?: () => void;
  /** Save this message into a research project. */
  onSaveResearch?: () => void;
  onDelete: () => void;
  onShare: () => void;
  onToggleBookmark: () => void;
}

function toPlainText(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```[^\n]*\n?/g, '').replace(/```/g, ''))
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^>\s?/gm, '')
    .replace(/[*_~]/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function extractCode(md: string): string {
  const blocks = [...md.matchAll(/```[^\n]*\n?([\s\S]*?)```/g)].map((m) => m[1].trim());
  return blocks.length ? blocks.join('\n\n') : md;
}

export default function MessageActions({
  content,
  isUser,
  bookmarked,
  onRegenerate,
  onEdit,
  onOpenCanvas,
  onSaveResearch,
  onDelete,
  onShare,
  onToggleBookmark,
}: MessageActionsProps) {
  const confirm = useConfirm();
  const [copyMenuOpen, setCopyMenuOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!copyMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setCopyMenuOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [copyMenuOpen]);

  const flash = () => {
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };

  const copy = (text: string) => {
    navigator.clipboard
      .writeText(text)
      .then(flash)
      .catch(() => {});
    setCopyMenuOpen(false);
  };

  const handleDelete = async () => {
    const ok = await confirm('Delete this message? This cannot be undone.', {
      title: 'Delete Message',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (ok) onDelete();
  };

  return (
    <div className="msg-actions" role="toolbar" aria-label="Message actions">
      <div className="msg-actions-copy" ref={menuRef}>
        <button
          type="button"
          className="msg-action-btn"
          title="Copy"
          aria-label="Copy message"
          onClick={() => setCopyMenuOpen((v) => !v)}
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
          <ChevronDown size={11} className="msg-action-caret" />
        </button>
        {copyMenuOpen && (
          <div className="msg-actions-menu" role="menu">
            <button type="button" role="menuitem" onClick={() => copy(content)}>
              Copy as Markdown
            </button>
            <button type="button" role="menuitem" onClick={() => copy(toPlainText(content))}>
              Copy as plain text
            </button>
            <button type="button" role="menuitem" onClick={() => copy(extractCode(content))}>
              Copy code blocks
            </button>
          </div>
        )}
      </div>

      {!isUser && onRegenerate && (
        <button
          type="button"
          className="msg-action-btn"
          title="Regenerate response"
          aria-label="Regenerate response"
          onClick={onRegenerate}
        >
          <RefreshCw size={14} />
        </button>
      )}

      {isUser && onEdit && (
        <button
          type="button"
          className="msg-action-btn"
          title="Edit and resend"
          aria-label="Edit message"
          onClick={onEdit}
        >
          <Pencil size={14} />
        </button>
      )}

      {!isUser && onOpenCanvas && (
        <button
          type="button"
          className="msg-action-btn"
          title="Open in Canvas"
          aria-label="Open message in canvas"
          onClick={onOpenCanvas}
        >
          <FileText size={14} />
        </button>
      )}

      {!isUser && onSaveResearch && (
        <button
          type="button"
          className="msg-action-btn"
          title="Save to Research"
          aria-label="Save message to a research project"
          onClick={onSaveResearch}
        >
          <FlaskConical size={14} />
        </button>
      )}

      <button
        type="button"
        className={`msg-action-btn${bookmarked ? ' is-active' : ''}`}
        title={bookmarked ? 'Remove bookmark' : 'Bookmark'}
        aria-label={bookmarked ? 'Remove bookmark' : 'Bookmark message'}
        onClick={onToggleBookmark}
      >
        {bookmarked ? <Star size={14} fill="currentColor" /> : <StarOff size={14} />}
      </button>

      <button
        type="button"
        className="msg-action-btn"
        title="Share conversation"
        aria-label="Share conversation"
        onClick={onShare}
      >
        <Share2 size={14} />
      </button>

      <button
        type="button"
        className="msg-action-btn msg-action-danger"
        title="Delete message"
        aria-label="Delete message"
        onClick={handleDelete}
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}
