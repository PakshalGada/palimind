import type { ReactNode } from 'react';
import MainPanel from './MainPanel';

/**
 * Top-level application shell: collapsible sidebar, main workspace and the
 * optional right rail. Keeps the flex contract that all workspace surfaces
 * (chat, agents, kanban) already rely on.
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
    <div className={`app-container app-layout ${className}`.trim()}>
      {sidebar}
      <MainPanel>{children}</MainPanel>
      {sidePanel}
    </div>
  );
}
