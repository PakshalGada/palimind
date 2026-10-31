import { useEffect, useState } from 'react';

/**
 * Return a value that only updates after `delay` ms of quiet. Used to keep
 * iframe/Mermaid redraws off the keystroke path while editing.
 */
export function useDebouncedValue<T>(value: T, delay = 180): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);

  return debounced;
}
