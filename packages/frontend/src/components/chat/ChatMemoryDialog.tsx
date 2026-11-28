import { useMemo, useState } from 'react';
import { Brain, Plus, Search, Trash2 } from 'lucide-react';
import { useApp } from '../../AppContext';
import { Dialog } from '../../ui/primitives';
import {
  memoryForScope,
  searchMemory,
  type ChatMemoryScope,
} from '../../utils/chatMemory';
import './ChatMemoryDialog.css';

type ScopeFilter = 'all' | ChatMemoryScope;

const FILTERS: { id: ScopeFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'chat', label: 'Chat' },
  { id: 'project', label: 'Project' },
  { id: 'global', label: 'Global' },
];

export default function ChatMemoryDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const {
    chatMemory,
    addChatMemory,
    removeChatMemory,
    activeSessionId,
    activeProjectId,
    activeProjectName,
  } = useApp();
  const [draft, setDraft] = useState('');
  const [scope, setScope] = useState<ChatMemoryScope>('chat');
  const [filter, setFilter] = useState<ScopeFilter>('all');
  const [query, setQuery] = useState('');

  const scoped = useMemo(
    () => memoryForScope(chatMemory, { sessionId: activeSessionId, projectId: activeProjectId }),
    [chatMemory, activeSessionId, activeProjectId],
  );
  const visible = useMemo(() => {
    const filtered = filter === 'all' ? scoped : scoped.filter((item) => item.scope === filter);
    return searchMemory(filtered, query);
  }, [scoped, filter, query]);

  const add = () => {
    const text = draft.trim();
    if (!text) return;
    addChatMemory(text, scope);
    setDraft('');
  };

  const scopeLabel = (value: ChatMemoryScope) => {
    if (value === 'chat') return 'Chat';
    if (value === 'project') return activeProjectName || 'Project';
    return 'Global';
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Chat memory"
      subtitle="Facts kept in chat prompts. Stored locally."
      width={620}
    >
      <div className="chat-memory">
        <form
          className="chat-memory__form"
          onSubmit={(event) => {
            event.preventDefault();
            add();
          }}
        >
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value as ChatMemoryScope)}
            aria-label="Memory scope"
          >
            <option value="chat">This chat</option>
            <option value="project" disabled={!activeProjectId}>This project</option>
            <option value="global">All chats</option>
          </select>
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

        <div className="chat-memory__toolbar">
          <div className="chat-memory__filters" role="group" aria-label="Memory scope filter">
            {FILTERS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`chat-memory__filter${filter === item.id ? ' is-active' : ''}`}
                onClick={() => setFilter(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <label className="chat-memory__search">
            <Search size={13} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search memory"
              aria-label="Search memory"
            />
          </label>
        </div>

        {visible.length === 0 ? (
          <div className="chat-memory__empty">
            <Brain size={22} />
            <strong>{scoped.length === 0 ? 'No memory yet' : 'No matching memory'}</strong>
            <span>
              {scoped.length === 0
                ? 'Add preferences, project facts or recurring context.'
                : 'Try a different search or scope.'}
            </span>
          </div>
        ) : (
          <ul className="chat-memory__list">
            {visible.map((item) => (
              <li key={item.id}>
                <span className={`chat-memory__scope is-${item.scope}`}>{scopeLabel(item.scope)}</span>
                <span>{item.text}</span>
                <button
                  type="button"
                  aria-label={`Remove memory: ${item.text}`}
                  title="Remove"
                  onClick={() => removeChatMemory(item.id)}
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
