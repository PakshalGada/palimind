import type { ReactNode } from 'react';
import './SurfaceHeader.css';

/**
 * Compact content header for a surface. It is deliberately *not* chrome: no
 * background, no second rule. The single global CommandBar owns the app
 * identity; this row only names the content and exposes its actions.
 */
export default function SurfaceHeader({
  title,
  meta,
  actions,
  className = '',
}: {
  title: ReactNode;
  /** Inline status, count or path shown next to the title. */
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={`surface-header ${className}`.trim()}>
      <div className="surface-header__text">
        <h1 className="surface-header__title">{title}</h1>
        {meta != null && <span className="surface-header__meta">{meta}</span>}
      </div>
      {actions != null && <div className="surface-header__actions">{actions}</div>}
    </header>
  );
}
