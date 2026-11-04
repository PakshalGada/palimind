import type { ReactNode } from 'react';
import './PageTitle.css';

/**
 * Content-level page title. Not chrome: it scrolls with the page, has no
 * background and no rule. The single chrome band is CommandBar.
 */
export default function PageTitle({
  eyebrow,
  title,
  subtitle,
  actions,
  className = '',
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={`page-title ${className}`.trim()}>
      <div className="page-title__text">
        {eyebrow != null && <div className="page-title__eyebrow">{eyebrow}</div>}
        <h1 className="page-title__title">{title}</h1>
        {subtitle != null && <p className="page-title__subtitle">{subtitle}</p>}
      </div>
      {actions != null && <div className="page-title__actions">{actions}</div>}
    </header>
  );
}
