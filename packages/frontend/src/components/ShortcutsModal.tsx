import { useEffect, useMemo, useState } from 'react';
import { RotateCcw, Search, X } from 'lucide-react';
import { useApp } from '../AppContext';
import { COMMAND_CATEGORIES, VISIBLE_COMMANDS, type CommandCategory } from '../commands/catalog';
import { CommandIconView } from '../commands/icons';
import { Modal } from '../ui/primitives';
import { setShortcutsSuspended } from '../hooks/useKeyboardShortcuts';
import {
  canonicalizeShortcut,
  eventToShortcut,
  formatShortcut,
  parseShortcut,
} from '../utils/shortcuts';
import './ShortcutsModal.css';

export default function ShortcutsModal() {
  const {
    shortcutsModalOpen,
    setShortcutsModalOpen,
    shortcutOverrides,
    setShortcutOverride,
    resetShortcut,
    resetAllShortcuts,
  } = useApp();

  const [query, setQuery] = useState('');
  const [recordingId, setRecordingId] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);

  // Effective binding per command (override wins over default).
  const effective = useMemo(() => {
    const map: Record<string, string> = {};
    for (const cmd of VISIBLE_COMMANDS) {
      const combo = shortcutOverrides[cmd.id] ?? cmd.defaultShortcut ?? '';
      if (combo) map[cmd.id] = combo;
    }
    return map;
  }, [shortcutOverrides]);

  // canonical binding -> command id, used for conflict detection.
  const bindingOwners = useMemo(() => {
    const map = new Map<string, string>();
    for (const [id, combo] of Object.entries(effective)) {
      const canonical = canonicalizeShortcut(combo);
      if (canonical && !map.has(canonical)) map.set(canonical, id);
    }
    return map;
  }, [effective]);

  // While recording, capture the next chord and suppress global shortcuts.
  useEffect(() => {
    if (!recordingId) return;
    setShortcutsSuspended(true);
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (e.key === 'Escape') {
        setRecordingId(null);
        setConflict(null);
        return;
      }
      if (e.key === 'Backspace' || e.key === 'Delete') {
        resetShortcut(recordingId);
        setRecordingId(null);
        setConflict(null);
        return;
      }
      const combo = eventToShortcut(e);
      if (!combo) return; // modifier-only keypress; keep waiting
      const parsed = parseShortcut(combo);
      // Require a modifier (or a function key) so plain letters are not bound.
      const isFunctionKey = /^f\d{1,2}$/.test(parsed?.key ?? '');
      if (parsed && !parsed.mod && !parsed.alt && !isFunctionKey) {
        setConflict('Add a modifier (Ctrl/Cmd, Alt) to this shortcut.');
        return;
      }
      const canonical = canonicalizeShortcut(combo);
      const owner = bindingOwners.get(canonical);
      if (owner && owner !== recordingId) {
        const ownerTitle = VISIBLE_COMMANDS.find((c) => c.id === owner)?.title ?? owner;
        setConflict(`Already used by “${ownerTitle}”.`);
        return;
      }
      setShortcutOverride(recordingId, canonical);
      setRecordingId(null);
      setConflict(null);
    };
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      setShortcutsSuspended(false);
    };
  }, [recordingId, bindingOwners, resetShortcut, setShortcutOverride]);

  const close = () => {
    setRecordingId(null);
    setConflict(null);
    setShortcutsModalOpen(false);
  };

  const normalizedQuery = query.trim().toLowerCase();
  const filtered = normalizedQuery
    ? VISIBLE_COMMANDS.filter((c) =>
        [c.title, c.description ?? '', c.category, ...(c.keywords ?? [])]
          .join(' ')
          .toLowerCase()
          .includes(normalizedQuery),
      )
    : VISIBLE_COMMANDS;

  const hasOverrides = Object.keys(shortcutOverrides).length > 0;

  return (
    <Modal
      open={shortcutsModalOpen}
      onClose={close}
      title="Keyboard Shortcuts"
      subtitle="Click a binding to record a new combination. Backspace clears it."
      width={720}
      footer={
        <div className="shortcuts-footer">
          <span className="shortcuts-footer-hint">
            {conflict ? <span className="shortcuts-conflict">{conflict}</span> : 'Bindings are saved automatically.'}
          </span>
          <button
            type="button"
            className="ui-btn ui-btn--ghost ui-btn--sm"
            onClick={resetAllShortcuts}
            disabled={!hasOverrides}
          >
            <RotateCcw size={13} strokeWidth={2} /> Reset all
          </button>
        </div>
      }
    >
      <div className="shortcuts-search">
        <Search size={15} strokeWidth={2} className="shortcuts-search-icon" />
        <input
          type="text"
          className="shortcuts-search-input"
          placeholder="Filter shortcuts…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
        />
        {query && (
          <button type="button" className="shortcuts-search-clear" onClick={() => setQuery('')} aria-label="Clear search">
            <X size={14} />
          </button>
        )}
      </div>

      <div className="shortcuts-list">
        {COMMAND_CATEGORIES.map((category: CommandCategory) => {
          const items = filtered.filter((c) => c.category === category);
          if (items.length === 0) return null;
          return (
            <section key={category} className="shortcuts-group">
              <h4 className="shortcuts-group-title">{category}</h4>
              {items.map((cmd) => {
                const combo = effective[cmd.id] ?? '';
                const overridden = cmd.id in shortcutOverrides;
                const isRecording = recordingId === cmd.id;
                return (
                  <div key={cmd.id} className="shortcuts-row">
                    <span className="shortcuts-row-icon">
                      <CommandIconView icon={cmd.icon} size={15} />
                    </span>
                    <span className="shortcuts-row-text">
                      <span className="shortcuts-row-title">{cmd.title}</span>
                      {cmd.description && <span className="shortcuts-row-desc">{cmd.description}</span>}
                    </span>
                    {overridden && (
                      <button
                        type="button"
                        className="shortcuts-reset"
                        title="Reset to default"
                        aria-label={`Reset ${cmd.title} to default`}
                        onClick={() => resetShortcut(cmd.id)}
                      >
                        <RotateCcw size={13} />
                      </button>
                    )}
                    <button
                      type="button"
                      className={`shortcuts-kbd${isRecording ? ' is-recording' : ''}`}
                      onClick={() => {
                        setConflict(null);
                        setRecordingId(isRecording ? null : cmd.id);
                      }}
                      aria-label={`Change shortcut for ${cmd.title}`}
                    >
                      {isRecording ? 'Press keys…' : combo ? formatShortcut(combo) : 'Unassigned'}
                    </button>
                  </div>
                );
              })}
            </section>
          );
        })}
        {filtered.length === 0 && <div className="shortcuts-empty">No shortcuts match “{query}”.</div>}
      </div>
    </Modal>
  );
}
