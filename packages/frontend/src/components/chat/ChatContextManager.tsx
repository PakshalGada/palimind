import { useMemo } from 'react';
import { Archive, Pin, Trash2 } from 'lucide-react';
import { useApp } from '../../AppContext';
import { summarizeContextBudget } from '../../utils/chatContext';
import { Dialog } from '../../ui/primitives';
import './ChatContextManager.css';

export default function ChatContextManager({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const {
    pinnedContext,
    unpinContext,
    clearPinnedContext,
    compactPinnedContext,
    chatMemory,
    sessions,
    activeSessionId,
  } = useApp();

  const session = sessions.find((item) => item.id === activeSessionId);
  const messageCount = session?.messages.length ?? 0;

  const budget = 8192;
  const { totalTokens, contextTokens, messageTokens, memoryTokens, pct } = useMemo(
    () =>
      summarizeContextBudget({
        pinnedContext,
        messages: session?.messages ?? [],
        memory: chatMemory,
        budget,
      }),
    [pinnedContext, session?.messages, chatMemory],
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Chat context"
      subtitle="Everything the assistant can use in this conversation. Pin only what matters."
      width={640}
    >
      <div className="chat-context-manager">
        <section className="chat-context-manager__budget">
          <div className="chat-context-manager__budget-head">
            <strong>Estimated context</strong>
            <span>{totalTokens.toLocaleString()} / {budget.toLocaleString()} tokens</span>
          </div>
          <div className="chat-context-manager__bar" aria-hidden="true">
            <span style={{ width: `${pct}%` }} />
          </div>
          <div className="chat-context-manager__legend">
            <span>Messages {messageTokens.toLocaleString()}</span>
            <span>Pinned {contextTokens.toLocaleString()}</span>
            <span>Memory {memoryTokens.toLocaleString()}</span>
            <span>{messageCount} messages</span>
          </div>
        </section>

        <section className="chat-context-manager__section">
          <div className="chat-context-manager__section-head">
            <h3><Pin size={13} /> Pinned context</h3>
            <div className="chat-context-manager__actions">
              <button
                type="button"
                disabled={pinnedContext.length < 2}
                onClick={compactPinnedContext}
                title="Condense pinned items into one summary"
              >
                <Archive size={12} />
                Compact
              </button>
              <button
                type="button"
                disabled={pinnedContext.length === 0}
                onClick={clearPinnedContext}
              >
                Clear
              </button>
            </div>
          </div>

          {pinnedContext.length === 0 ? (
            <p className="chat-context-manager__empty">
              Nothing pinned yet. Use <strong>Use as context</strong> on an artifact, or pin a
              message from its actions.
            </p>
          ) : (
            <ul className="chat-context-manager__list">
              {pinnedContext.map((item) => (
                <li key={item.id}>
                  <span className={`chat-context-manager__kind is-${item.kind}`}>
                    {item.kind === 'artifact' ? 'Artifact' : 'Message'}
                  </span>
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.content.replace(/\s+/g, ' ').slice(0, 220)}</p>
                  </div>
                  <button
                    type="button"
                    aria-label={`Remove ${item.title}`}
                    title="Remove from context"
                    onClick={() => unpinContext(item.id)}
                  >
                    <Trash2 size={13} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Dialog>
  );
}
