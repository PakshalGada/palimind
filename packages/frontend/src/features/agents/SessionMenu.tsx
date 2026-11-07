import { useEffect, useRef, useState } from 'react';
import { Check, History, Plus, Trash2 } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import './SessionMenu.css';

/** Compact session switcher for an agent's private conversation store. */
export default function SessionMenu({ agentId }: { agentId: string }) {
  const { sessions, activeSessionId, setSessions, setActiveSessionId, addToast } = useApp();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const scope = `agent:${agentId}`;

  const apply = (data: { sessions?: unknown[]; active_session_id?: string; error?: string }) => {
    if (data.error) {
      addToast(data.error, { tone: 'error' });
      return;
    }
    if (data.sessions) setSessions(data.sessions as typeof sessions);
    if (data.active_session_id) setActiveSessionId(data.active_session_id);
  };

  const newChat = async () => {
    setBusy(true);
    try {
      const data = await api.sessions.new(`Session ${sessions.length + 1}`, scope);
      apply(data);
      setOpen(false);
    } catch {
      addToast('Could not create a new chat.', { tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const switchTo = async (id: string) => {
    setBusy(true);
    try {
      apply(await api.sessions.setActive(id, scope));
      setOpen(false);
    } catch {
      addToast('Could not open that chat.', { tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    setBusy(true);
    try {
      apply(await api.sessions.remove(id, scope));
    } catch {
      addToast('Could not delete that chat.', { tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ag-sessions" ref={ref}>
      <button
        type="button"
        className="ag-icon-btn"
        title="Conversation history"
        aria-label="Conversation history"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <History size={15} />
      </button>
      {open && (
        <div className="ag-sessions__menu" role="menu">
          <div className="ag-sessions__head">
            <span>Conversations</span>
            <button type="button" onClick={() => void newChat()} disabled={busy}>
              <Plus size={12} /> New
            </button>
          </div>
          <div className="ag-sessions__list">
            {sessions.length === 0 && <p className="ag-sessions__empty">No conversations yet.</p>}
            {sessions.map((session) => (
              <div
                key={session.id}
                className={`ag-sessions__item${session.id === activeSessionId ? ' is-active' : ''}`}
              >
                <button
                  type="button"
                  className="ag-sessions__pick"
                  onClick={() => void switchTo(session.id)}
                  disabled={busy}
                >
                  <span>{session.name || 'Untitled'}</span>
                  {session.id === activeSessionId && <Check size={13} />}
                </button>
                <button
                  type="button"
                  className="ag-sessions__delete"
                  onClick={() => void remove(session.id)}
                  aria-label="Delete conversation"
                  title="Delete conversation"
                  disabled={busy}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
