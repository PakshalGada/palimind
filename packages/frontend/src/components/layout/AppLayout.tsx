import type { ReactNode } from 'react';
import CommandBar from './CommandBar';
import MainPanel from './MainPanel';

/**
 * Top-level application shell:
 *
 *   ┌──────────────────────────────────────────────┐
 *   │ top bar — brand, breadcrumb, status, palette  │
 *   ├──────────┬───────────────────────┬───────────┤
 *   │ sidebar  │ main                  │ inspector │
 *   └──────────┴───────────────────────┴───────────┘
 *
 * The body keeps the flex contract every workspace surface already relies on.
 */
export default function AppLayout({
  sidebar,
  sidePanel,
  children,
  className = '',
}: {
  sidebar: ReactNode;
  sidePanel?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`app-container app-shell ${className}`.trim()}>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <CommandBar />
      <div className="app-layout app-body">
        {sidebar}
        <MainPanel>{children}</MainPanel>
        {sidePanel}
      </div>
    </div>
  );
}
