import { Menu } from 'lucide-react';
import type { ReactNode } from 'react';
import { useApp } from '../../AppContext';

/**
 * The main content column. Owns the mobile navigation trigger so the drawer
 * can be reopened when the sidebar is off-canvas.
 */
export default function MainPanel({ children }: { children: ReactNode }) {
  const { sidebarCollapsed, toggleSidebar } = useApp();

  return (
    <div className="app-main-panel">
      <button
        type="button"
        className="app-mobile-menu"
        data-visible={sidebarCollapsed ? 'true' : 'false'}
        onClick={toggleSidebar}
        aria-label="Open navigation"
        title="Open navigation"
      >
        <Menu size={17} />
      </button>
      {children}
    </div>
  );
}
