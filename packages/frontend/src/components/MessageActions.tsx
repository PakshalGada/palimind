import { useEffect, useRef, useState } from 'react';
import {
  BookOpen,
  Check,
  ChevronDown,
  Copy,
  GitFork,
  Loader2,
  Pencil,
  RefreshCw,
  Share2,
  Square,
  Star,
  StarOff,
  Trash2,
  Volume2,
} from 'lucide-react';
import { useConfirm } from './ConfirmDialog';
import { api } from '../api';
import { saveToVault } from '../utils/artifactVault';
import './MessageActions.css';

export interface MessageActionsProps {
  content: string;
  isUser: boolean;
  bookmarked: boolean;
  /** Regenerate the reply (assistant messages only). */
  onRegenerate?: () => void;
  /** Enter inline edit mode (user messages only). */
  onEdit?: () => void;
  /** Speak / stop the message (assistant messages only). */
  onSpeak?: () => void;
  /** True while this message is being synthesized or played back. */
  speaking?: boolean;
  /** True while the WAV chunks are still being synthesized. */
  speakLoading?: boolean;
  /** Start a new conversation branch from this message. */
  onFork?: () => void;
  onDelete: () => void;
  /** Share the conversation: 'copy' (transcript) or a file export format. */
  onShare: (format?: 'copy' | 'md' | 'pdf' | 'docx') => void;
  onToggleBookmark: () => void;
  /** Add the answer to local chat memory. */
  onRemember?: () => void;
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

function messageUrls(md: string): string[] {
  const urls = new Set<string>();
  for (const match of md.matchAll(/https?:\/\/[^\s)\]"'<>]+/g)) {
    urls.add(match[0].replace(/[.,;:]+$/, ''));
  }
  return [...urls];
}

function answerTitle(md: string): string {
  const line = md
    .split('\n')
    .map((item) => item.replace(/^#+\s*/, '').trim())
    .find(Boolean);
  return (line || 'Saved answer').slice(0, 100);
}

async function saveAnswer(md: string): Promise<void> {
  if (!md.trim()) return;
  await api.capture.note({
    text: md,
    title: answerTitle(md),
    tags: ['chat-answer'],
  });
  window.dispatchEvent(new CustomEvent('palimind:sources-changed'));
}

async function saveLinks(md: string): Promise<number> {
  const urls = messageUrls(md);
  if (!urls.length) return 0;
  const data = await api.capture.sources({ urls, tags: ['chat-links'] });
  if (!data.error) window.dispatchEvent(new CustomEvent('palimind:sources-changed'));
  return data.sources?.length ?? 0;
}

export default function MessageActions({
  content,
  isUser,
  bookmarked,
  onRegenerate,
  onEdit,
  onSpeak,
  speaking,
  speakLoading,
  onFork,
  onDelete,
  onShare,
  onToggleBookmark,
  onRemember,
}: MessageActionsProps) {
  const confirm = useConfirm();
  const [copyMenuOpen, setCopyMenuOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [shareMenuOpen, setShareMenuOpen] = useState(false);
  const [saveMenuOpen, setSaveMenuOpen] = useState(false);
  const [savedAnswer, setSavedAnswer] = useState(false);
  const [savedLinks, setSavedLinks] = useState(false);
  const [savedArtifact, setSavedArtifact] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const shareRef = useRef<HTMLDivElement>(null);
  const saveRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!copyMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setCopyMenuOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [copyMenuOpen]);

  useEffect(() => {
    if (!shareMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (shareRef.current && !shareRef.current.contains(e.target as Node)) setShareMenuOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [shareMenuOpen]);

  useEffect(() => {
    if (!saveMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (saveRef.current && !saveRef.current.contains(e.target as Node)) setSaveMenuOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [saveMenuOpen]);

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

      {!isUser && onSpeak && (
        <button
          type="button"
          className={`msg-action-btn${speaking ? ' is-active' : ''}`}
          title={speaking ? 'Stop playback' : 'Read aloud'}
          aria-label={speaking ? 'Stop playback' : 'Read aloud'}
          onClick={onSpeak}
        >
          {speakLoading ? (
            <Loader2 size={14} className="msg-action-spin" />
          ) : speaking ? (
            <Square size={14} />
          ) : (
            <Volume2 size={14} />
          )}
        </button>
      )}

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

      {onFork && (
        <button
          type="button"
          className="msg-action-btn"
          title="Fork from here — try a different direction"
          aria-label="Fork conversation from this message"
          onClick={onFork}
        >
          <GitFork size={14} />
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

      {!isUser && (
        <div className="msg-actions-copy" ref={saveRef}>
          <button
            type="button"
            className="msg-action-btn"
            title="Save to knowledge"
            aria-label="Save message to knowledge"
            aria-haspopup="menu"
            aria-expanded={saveMenuOpen}
            onClick={() => setSaveMenuOpen((v) => !v)}
          >
            <BookOpen size={14} />
            <ChevronDown size={11} className="msg-action-caret" />
          </button>
          {saveMenuOpen && (
            <div className="msg-actions-menu" role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setSaveMenuOpen(false);
                  void saveAnswer(content).then(() => setSavedAnswer(true));
                }}
              >
                {savedAnswer ? 'Answer saved' : 'Save answer as note'}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setSaveMenuOpen(false);
                  onRemember?.();
                }}
              >
                Remember this answer
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setSaveMenuOpen(false);
                  const title = answerTitle(content);
                  void saveToVault(
                    {
                      id: `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
                      type: 'markdown',
                      language: 'markdown',
                      title,
                      content,
                    },
                    'Saved from chat',
                  ).then(() => setSavedArtifact(true));
                }}
              >
                {savedArtifact ? 'Saved as artifact' : 'Save as artifact'}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setSaveMenuOpen(false);
                  void saveLinks(content).then((count) => setSavedLinks(count > 0));
                }}
              >
                {savedLinks ? 'Links saved' : 'Save links in this answer'}
              </button>
            </div>
          )}
        </div>
      )}

      <div className="msg-actions-copy" ref={shareRef}>
        <button
          type="button"
          className="msg-action-btn"
          title="Share / export conversation"
          aria-label="Share or export conversation"
          aria-haspopup="menu"
          aria-expanded={shareMenuOpen}
          onClick={() => setShareMenuOpen((v) => !v)}
        >
          <Share2 size={14} />
          <ChevronDown size={11} className="msg-action-caret" />
        </button>
        {shareMenuOpen && (
          <div className="msg-actions-menu" role="menu">
            <button type="button" role="menuitem" onClick={() => { setShareMenuOpen(false); onShare('copy'); }}>
              Copy transcript
            </button>
            <button type="button" role="menuitem" onClick={() => { setShareMenuOpen(false); onShare('md'); }}>
              Export as Markdown
            </button>
            <button type="button" role="menuitem" onClick={() => { setShareMenuOpen(false); onShare('pdf'); }}>
              Export as PDF
            </button>
            <button type="button" role="menuitem" onClick={() => { setShareMenuOpen(false); onShare('docx'); }}>
              Export as Word
            </button>
          </div>
        )}
      </div>

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
