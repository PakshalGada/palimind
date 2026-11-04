import { useEffect, useLayoutEffect, useRef, useState } from 'react';

interface MenuItem {
  label: string;
  action: () => void;
  isDanger?: boolean;
}

interface ContextMenuProps {
  x: number;
  y: number;
  items: MenuItem[];
  onClose: () => void;
}

export default function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });

  // Keep the menu inside the viewport: opening near the right/bottom edge
  // would otherwise render items off-screen.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const margin = 8;
    const { width, height } = el.getBoundingClientRect();
    const left = Math.max(margin, Math.min(x, window.innerWidth - width - margin));
    const top = Math.max(margin, Math.min(y, window.innerHeight - height - margin));
    setPos({ left, top });
  }, [x, y, items.length]);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="context-menu"
      style={{ left: pos.left, top: pos.top }}
    >
      {items.map((item, i) => {
        const isDelete = item.isDanger || /delete|remove|trash/i.test(item.label);
        return (
          <button
            key={i}
            className={`context-menu-item ${isDelete ? 'danger' : ''}`}
            onClick={() => { item.action(); onClose(); }}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
