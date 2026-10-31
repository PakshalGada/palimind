import { useEffect, useRef, useState } from 'react';

/**
 * Return `value`, but commit changes at most once every `interval` ms.
 *
 * Unlike a debounce this keeps updating while the input keeps changing; it
 * just drops the intermediate frames. Used to keep expensive artifact parsing
 * off the token-flush path.
 */
export function useThrottledValue<T>(value: T, interval: number): T {
  const [throttled, setThrottled] = useState(value);
  const latest = useRef(value);
  const lastCommit = useRef(0);
  const timer = useRef<number | null>(null);
  latest.current = value;

  useEffect(() => {
    if (interval <= 0) {
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
        timer.current = null;
      }
      return;
    }
    const elapsed = performance.now() - lastCommit.current;
    if (elapsed >= interval) {
      lastCommit.current = performance.now();
      setThrottled(value);
      return;
    }
    if (timer.current === null) {
      timer.current = window.setTimeout(() => {
        timer.current = null;
        lastCommit.current = performance.now();
        setThrottled(latest.current);
      }, interval - elapsed);
    }
  }, [value, interval]);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  // With throttling disabled, return the live value directly so callers don't
  // pay for an extra state update per change.
  return interval <= 0 ? value : throttled;
}
