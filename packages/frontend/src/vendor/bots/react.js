// React wrapper: <BotAvatar type="clover" state="working" />
// Kept dependency-free at the library level: React is a peer import here only.

import { createElement, useEffect, useRef } from 'react';
import { BotAvatar as Controller } from './bot.js';

export function BotAvatar({ className, style, onPoke, ...options }) {
  const host = useRef(null);
  const bot = useRef(null);
  useEffect(() => {
    bot.current = new Controller(host.current, options);
    return () => { bot.current.destroy(); bot.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { bot.current?.set(options); });
  useEffect(() => {
    const el = host.current;
    if (!onPoke || !el) return undefined;
    el.addEventListener('bot-poke', onPoke);
    return () => el.removeEventListener('bot-poke', onPoke);
  }, [onPoke]);
  const size = options.size ?? 64;
  return createElement('span', { ref: host, className, style: { display: 'inline-block', width: size, height: size, lineHeight: 0, ...style } });
}

export default BotAvatar;
