import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../api';
import type { BrowserState } from '../../../types';

const EMPTY: BrowserState = {
  open: false,
  owner: 'agent',
  agent_id: '',
  url: '',
  title: '',
  tabs: [],
  takeover: null,
  error: null,
};

/**
 * Live state for the shared browser dock. Frames are pulled as images; state
 * (owner, url, tabs) is polled slowly. Nothing here starts a browser — only an
 * explicit navigation or an agent tool call does.
 */
export function useBrowserSession(active: boolean, agentId = '') {
  const [state, setState] = useState<BrowserState>(EMPTY);
  const [nonce, setNonce] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [frameFailed, setFrameFailed] = useState(false);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const next = await api.browser.state(agentId);
      if (mounted.current) {
        setState((previous) => ({ ...previous, ...next }));
        setFrameFailed(false);
      }
    } catch (error) {
      // Keep the last known page on screen, but say why it stopped updating.
      if (mounted.current) {
        setState((previous) => ({
          ...previous,
          error:
            error instanceof Error
              ? error.message
              : 'Could not reach the browser service.',
        }));
      }
    }
  }, [agentId]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!active) return;
    void refresh();
    const stateTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refresh();
    }, 2200);
    const frameTimer = window.setInterval(() => {
      if (document.visibilityState === 'visible') setNonce(Date.now());
    }, 950);
    return () => {
      window.clearInterval(stateTimer);
      window.clearInterval(frameTimer);
    };
  }, [active, refresh]);

  const act = useCallback(
    async (action: string, payload: Record<string, unknown> = {}) => {
      setBusy(true);
      try {
        const next = await api.browser.action(action, payload);
        if (!mounted.current) return next;
        if (next && typeof next === 'object' && 'owner' in next) {
          setState((previous) => ({ ...previous, ...next }));
        } else if (next && typeof next === 'object' && 'error' in next) {
          setState((previous) => ({ ...previous, error: String((next as { error?: string }).error || '') }));
        }
        setNonce(Date.now());
        return next;
      } catch (error) {
        if (mounted.current) {
          setState((previous) => ({
            ...previous,
            error:
              error instanceof Error
                ? error.message
                : 'The browser action failed.',
          }));
        }
        return { error: error instanceof Error ? error.message : 'Browser action failed' };
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const claim = useCallback(async (agentId = '', takeoverId = '') => {
    await api.browser.claimControl(agentId, takeoverId);
    await refresh();
    setNonce(Date.now());
  }, [refresh]);

  const release = useCallback(async () => {
    await api.browser.releaseControl();
    await refresh();
    setNonce(Date.now());
  }, [refresh]);

  return {
    state,
    nonce,
    busy,
    frameFailed,
    setFrameFailed,
    refresh,
    act,
    claim,
    release,
    frameUrl: api.browser.frameUrl(nonce),
  };
}
