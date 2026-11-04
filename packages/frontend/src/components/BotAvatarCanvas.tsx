import { useEffect, useRef } from 'react';
import { createBot, DEFAULTS } from '../vendor/bots/index.js';
import type { BotAvatarConfig, BotState } from '../bots/config';

/**
 * Thin React host for the vendored "bots" canvas renderer. Creates one
 * controller per mount and feeds option changes through `set()`.
 */
export default function BotAvatarCanvas({
  config,
  size,
  state,
  interactive = true,
  paused = false,
}: {
  config: BotAvatarConfig;
  size: number;
  state: BotState;
  interactive?: boolean;
  paused?: boolean;
}) {
  const hostRef = useRef<HTMLSpanElement>(null);
  const botRef = useRef<ReturnType<typeof createBot> | null>(null);
  const prevConfigRef = useRef<BotAvatarConfig>(config);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const bot = createBot(host, { ...config, size, state, interactive, paused });
    botRef.current = bot;
    return () => {
      bot.destroy();
      botRef.current = null;
    };
    // Create once; option changes are applied by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // `set()` merges into the previous options, so keys dropped from the new
    // config (e.g. a preset without a hat) must be reset explicitly.
    const cleared: Record<string, unknown> = {};
    for (const key of Object.keys(prevConfigRef.current)) {
      if (!(key in config)) cleared[key] = (DEFAULTS as Record<string, unknown>)[key];
    }
    prevConfigRef.current = config;
    botRef.current?.set({ ...cleared, ...config, size, state, interactive, paused });
  }, [config, size, state, interactive, paused]);

  return (
    <span
      ref={hostRef}
      className="bot-canvas-host"
      style={{ display: 'inline-block', width: size, height: size, lineHeight: 0 }}
    />
  );
}
