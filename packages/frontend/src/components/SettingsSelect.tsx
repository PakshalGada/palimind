import { useState, useEffect, useRef } from 'react';
import { PixelGlyph } from './pixel/PixelGlyph';

interface Option {
  value: string;
  label: string;
  description?: string;
}

interface SettingsSelectProps {
  id: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
}

export default function SettingsSelect({ id, value, options, onChange }: SettingsSelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const selected = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    // Escape closes just the dropdown; capture + stopPropagation keeps it from
    // also closing the Settings dialog.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    window.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('mousedown', handler);
      window.removeEventListener('keydown', onKey, true);
    };
  }, [open]);

  return (
    <div
      ref={ref}
      className="settings-select-wrap"
    >
      <button
        type="button"
        id={id}
        className="settings-select-trigger"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="settings-select-value">
          {selected?.label || value}
        </span>
        <PixelGlyph sprite="chevron-down" cell={1.5} style={{ marginLeft: 'auto', flexShrink: 0 }} />
      </button>
      {open && (
        <div className="settings-select-dropdown" role="listbox">
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              role="option"
              aria-selected={opt.value === value}
              className={`settings-select-option${opt.value === value ? ' selected' : ''}`}
              onClick={() => {
                onChange(opt.value);
                setOpen(false);
              }}
            >
              <span className="settings-select-option-label">{opt.label}</span>
              {opt.description && (
                <span className="settings-select-option-desc">{opt.description}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
