import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import MessageContent from './MessageContent';
import type { CitationPayload } from '../types';
import './CollapsibleMessage.css';

/**
 * One agent answer, rendered once.
 *
 * Long answers stay one message: the whole block folds after a readable
 * height instead of being chopped into several fake chat bubbles.
 */
export default function CollapsibleMessage({
  content,
  citations,
  messageIndex,
  streaming = false,
  onOpenArtifact,
  className = '',
  collapseAt = 260,
  fold = true,
}: {
  content: string;
  citations?: CitationPayload;
  messageIndex?: number;
  streaming?: boolean;
  onOpenArtifact?: (artifactId: string) => void;
  className?: string;
  collapseAt?: number;
  /** Set false for short progress notes that should never be folded. */
  fold?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (streaming) setExpanded(false);
  }, [streaming]);

  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    if (!fold || streaming) {
      setOverflows(false);
      return;
    }
    setOverflows(el.scrollHeight > collapseAt + 4);
  }, [content, streaming, collapseAt, fold]);

  return (
    <div className={`message-fold${className ? ` ${className}` : ''}`}>
      <div
        ref={bodyRef}
        className={`message-fold__body${overflows && !expanded ? ' is-collapsed' : ''}`}
        style={overflows && !expanded ? { maxHeight: collapseAt } : undefined}
      >
        <MessageContent
          content={content}
          citations={citations}
          messageIndex={messageIndex}
          streaming={streaming}
          onOpenArtifact={onOpenArtifact}
        />
      </div>
      {overflows && (
        <button
          type="button"
          className="message-fold__more"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? 'Show less' : 'Show full answer'}
        </button>
      )}
    </div>
  );
}
