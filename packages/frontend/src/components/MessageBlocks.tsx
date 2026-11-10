import { useState } from 'react';
import MessageContent from './MessageContent';
import {
  MAX_VISIBLE_BLOCKS,
  splitMessageBlocks,
  visibleMessageBlocks,
} from '../features/agents/messageBlocks';
import type { CitationPayload } from '../types';
import './MessageBlocks.css';

/**
 * One answer rendered as a short run of chat bubbles. The same component is
 * used for a live stream and for a saved message, so a reload does not change
 * the shape of the conversation.
 */
export default function MessageBlocks({
  content,
  streaming = false,
  citations,
  messageIndex,
  onOpenArtifact,
  className = '',
}: {
  content: string;
  streaming?: boolean;
  citations?: CitationPayload;
  messageIndex?: number;
  onOpenArtifact?: (artifactId: string) => void;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const blocks = splitMessageBlocks(content);
  const visible = visibleMessageBlocks(blocks, expanded);

  if (blocks.length === 0) return null;

  return (
    <div className={`message-blocks${className ? ` ${className}` : ''}`}>
      {visible.map((block, index) => {
        const last = index === visible.length - 1;
        return (
          <div
            key={`${index}-${block.slice(0, 24)}`}
            className={`message-block${last && streaming ? ' is-live' : ''}`}
          >
            <MessageContent
              content={block}
              citations={citations}
              messageIndex={messageIndex}
              streaming={streaming && last}
              onOpenArtifact={onOpenArtifact}
            />
          </div>
        );
      })}
      {blocks.length > MAX_VISIBLE_BLOCKS && (
        <button
          type="button"
          className="message-blocks__more"
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? 'Show less' : `Show full answer · ${blocks.length - MAX_VISIBLE_BLOCKS} more`}
        </button>
      )}
    </div>
  );
}
