import { useState } from 'react';
import { Brain, Plus, Trash2 } from 'lucide-react';
import { useApp } from '../../AppContext';
import { Dialog } from '../../ui/primitives';
import './ChatMemoryDialog.css';

export default function ChatMemoryDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { chatMemory, addChatMemory, removeChatMemory } = useApp();
  const [draft, setDraft] = useState('');

  const add = () => {
    const text = draft.trim();
    if (!text) return;
    addChatMemory(text);
    setDraft('');
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Chat memory"
      subtitle="Facts the assistant should keep in mind. Stored locally and added to chat prompts."
      width={560}
    >
      <div className="chat-memory">
        <form
          className="chat-memory__form"
          onSubmit={(event) => {
            event.preventDefault();
            add();
          }}
        >
          <input
            value={draft}
            maxLength={500}
            placeholder="e.g. Prefers concise answers with concrete numbers"
            onChange={(event) => setDraft(event.target.value)}
            aria-label="New memory"
          />
          <button type="submit" disabled={!draft.trim()}>
            <Plus size={14} />
            Add
          </button>
        </form>

        {chatMemory.length === 0 ? (
          <div className="chat-memory__empty">
            <Brain size={22} />
            <strong>No memory yet</strong>
            <span>Add preferences, project facts or recurring context.</span>
          </div>
        ) : (
          <ul className="chat-memory__list">
            {chatMemory.map((item, index) => (
              <li key={`${index}-${item}`}>
                <span>{item}</span>
                <button
                  type="button"
                  aria-label={`Remove memory: ${item}`}
                  title="Remove"
                  onClick={() => removeChatMemory(index)}
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Dialog>
  );
}
