import { useCallback, useRef, useState } from 'react';

/**
 * Replayable one-shot trigger. CSS animations do not restart when a boolean
 * flips, so components key off a monotonically increasing nonce instead.
 */
export function useOneShot(): [number, () => void] {
  const [nonce, setNonce] = useState(0);
  const ref = useRef(0);
  const fire = useCallback(() => {
    ref.current += 1;
    setNonce(ref.current);
  }, []);
  return [nonce, fire];
}
