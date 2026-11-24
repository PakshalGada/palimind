import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { useApp } from '../../AppContext';
import { Dialog } from '../../ui/primitives';
import './ChatSearchDialog.css';

export default function ChatSearchDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { sessions, activeSessionId } = useApp();
  const [query, setQuery] = useState('');
  const session = sessions.find((item) => item.id === activeSessionId);
  const messages = session?.messages ?? [];

  const results = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return messages.map((message, index) => ({ message, index })).slice(-30).reverse();
    return messages
      .map((message, index) => ({ message, index }))
      .filter(({ message }) => message.content.toLowerCase().includes(needle))
      .reverse()
      .slice(0, 30);
  }, [messages, query]);

  const jump = (index: number, messageId?: number) => {
    window.dispatchEvent(
      new CustomEvent('palimind:goto-message', {
        detail: { sessionId: activeSessionId, messageId, messageIndex: index },
      }),
    );
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Search this chat"
      subtitle={`${messages.length} messages in the current conversation.`}
      width={620}
    >
      <div className="chat-search">
        <label className="chat-search__input">
          <Search size={15} />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search messages…"
            aria-label="Search chat messages"
          />
        </label>

        {results.length === 0 ? (
          <p className="chat-search__empty">No messages match “{query.trim()}”.</p>
        ) : (
          <ul className="chat-search__list">
            {results.map(({ message, index }) => (
              <li key={`${index}-${message.id ?? 'i'}`}>
                <button type="button" onClick={() => jump(index, message.id)}>
                  <span className={`chat-search__role is-${message.role}`}>
                    {message.role === 'user' ? 'You' : 'Assistant'}
                  </span>
                  <span className="chat-search__snippet">{message.content.replace(/\s+/g, ' ').slice(0, 180)}</span>
                  <span className="chat-search__meta">#{index + 1}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Dialog>
  );
}
