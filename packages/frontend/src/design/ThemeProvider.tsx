import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { Theme } from '../types';

/**
 * Theme preference storage. `palimind:theme` is canonical; the older `theme`
 * key is still read so existing installs keep their choice.
 */
export const THEME_STORAGE_KEY = 'palimind:theme';
const LEGACY_THEME_KEY = 'theme';

function systemTheme(): Theme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'dark';
  }
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function readStoredTheme(): Theme | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY) ?? localStorage.getItem(LEGACY_THEME_KEY);
    return stored === 'light' || stored === 'dark' ? stored : null;
  } catch {
    return null;
  }
}

/** Apply the palette class + data attribute to <html>. Shared with index.html. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.toggle('light-mode', theme === 'light');
  root.classList.toggle('dark-mode', theme === 'dark');
  root.dataset.theme = theme;
}

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  /** True while no explicit preference is stored (system drives the theme). */
  followsSystem: boolean;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const stored = useRef<Theme | null>(readStoredTheme());
  const explicit = useRef(stored.current !== null);
  const [theme, setThemeState] = useState<Theme>(() => stored.current ?? systemTheme());
  const [followsSystem, setFollowsSystem] = useState(() => stored.current === null);

  const setTheme = useCallback((next: Theme) => {
    explicit.current = true;
    setFollowsSystem(false);
    setThemeState(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
      localStorage.setItem(LEGACY_THEME_KEY, next);
    } catch {
      // Storage may be unavailable (private mode); the in-memory theme still works.
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  }, [theme, setTheme]);

  // Keep <html> in sync with the resolved theme.
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Respect live OS changes until the user makes an explicit choice.
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia('(prefers-color-scheme: light)');
    const onChange = (e: MediaQueryListEvent) => {
      if (explicit.current) return;
      setThemeState(e.matches ? 'light' : 'dark');
    };
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  // Cross-tab sync: another window changed the preference.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== THEME_STORAGE_KEY && e.key !== LEGACY_THEME_KEY) return;
      if (e.key === LEGACY_THEME_KEY && localStorage.getItem(THEME_STORAGE_KEY)) return;
      if (e.newValue === 'light' || e.newValue === 'dark') {
        explicit.current = true;
        setFollowsSystem(false);
        setThemeState(e.newValue);
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const value = useMemo(
    () => ({ theme, setTheme, toggleTheme, followsSystem }),
    [theme, setTheme, toggleTheme, followsSystem],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
