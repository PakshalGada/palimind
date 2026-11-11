import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useApp } from '../../AppContext';

const MOBILE_QUERY = '(max-width: 900px)';

/**
 * Wraps the sidebar with collapse behaviour.
 *
 * - Expanded: full navigation column.
 * - Collapsed on desktop: a slim icon rail. It only expands again through the
 *   toggle button (or the view.toggle-sidebar command), never on hover.
 * - Mobile: an off-canvas drawer with a scrim; closed by default.
 */
export default function ResponsiveSidebar({ children }: { children: ReactNode }) {
  const { sidebarCollapsed, setSidebarCollapsed } = useApp();
  const initialised = useRef(false);
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches,
  );

  // On a phone-sized viewport the drawer starts closed. This runs once so a
  // later resize never fights the user's choice.
  useEffect(() => {
    if (initialised.current) return;
    initialised.current = true;
    if (window.matchMedia(MOBILE_QUERY).matches) {
      setSidebarCollapsed(true);
    }
  }, [setSidebarCollapsed]);

  useEffect(() => {
    const query = window.matchMedia(MOBILE_QUERY);
    const onChange = (event: MediaQueryListEvent) => {
      setIsMobile(event.matches);
      if (event.matches) setSidebarCollapsed(true);
    };
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, [setSidebarCollapsed]);

  // Escape closes the mobile drawer.
  useEffect(() => {
    if (!isMobile || sidebarCollapsed) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSidebarCollapsed(true);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isMobile, sidebarCollapsed, setSidebarCollapsed]);

  const drawerOpen = isMobile && !sidebarCollapsed;

  return (
    <div
      className={[
        'app-sidebar-shell',
        sidebarCollapsed ? 'is-collapsed' : 'is-expanded',
        drawerOpen ? 'is-drawer-open' : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {children}
      {isMobile && (
        <button
          type="button"
          className="app-sidebar-scrim"
          aria-label="Close navigation"
          tabIndex={drawerOpen ? 0 : -1}
          onClick={() => setSidebarCollapsed(true)}
        />
      )}
    </div>
  );
}
