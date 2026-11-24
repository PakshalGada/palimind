import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, Command, X } from 'lucide-react';
import { useApp } from '../AppContext';
import './QuickAsk.css';

/**
 * Small global quick-ask surface. The desktop shell shows the window and emits
 * `palimind:quick-ask`; the browser fallback listens to the same window event.
 */
export default function QuickAsk() {
  const { setActiveView, activeView } = useApp();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    setText('');
  }, []);

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener('palimind:quick-ask', onOpen);
    let unlisten: (() => void) | undefined;
    void import('@tauri-apps/api/event')
      .then(({ listen }) => listen('palimind:quick-ask', () => setOpen(true)))
      .then((stop) => {
        unlisten = stop;
      })
      .catch(() => undefined);
    return () => {
      window.removeEventListener('palimind:quick-ask', onOpen);
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        close();
      }
    };
    window.addEventListener('keydown', onKey, true);
    requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.removeEventListener('keydown', onKey, true);
  }, [open, close]);

  const submit = () => {
    const value = text.trim();
    if (!value) return;
    if (activeView !== 'chat') setActiveView('chat');
    window.dispatchEvent(
      new CustomEvent('palimind:prefill-composer', { detail: { text: value } }),
    );
    close();
  };

  if (!open) return null;

  return (
    <div
      className="quick-ask__backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        className="quick-ask"
        role="dialog"
        aria-modal="true"
        aria-label="Quick ask"
      >
        <div className="quick-ask__head">
          <span className="quick-ask__icon"><Command size={14} /></span>
          <span>Quick ask</span>
          <button type="button" onClick={close} aria-label="Close quick ask" title="Close">
            <X size={14} />
          </button>
        </div>
        <textarea
          ref={inputRef}
          rows={3}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder="Ask anything without leaving what you're doing…"
          aria-label="Quick ask message"
        />
        <div className="quick-ask__foot">
          <span>Enter to ask · Shift+Enter for a new line</span>
          <button type="button" onClick={submit} disabled={!text.trim()} aria-label="Ask">
            <ArrowUp size={14} />
            Ask
          </button>
        </div>
      </div>
    </div>
  );
}
