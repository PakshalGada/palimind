/* ==========================================================================
   bots/config.ts — Palimind-side configuration for the vendored "bots"
   library (src/vendor/bots). Persists a JSON-safe subset of BotOptions.
   ========================================================================== */

import {
  GLASSES,
  HATS,
  SHADINGS,
  palette,
  presets,
  types,
} from '../vendor/bots/index.js';
import type {
  BotGlasses,
  BotHat,
  BotShading,
  BotState,
  BotType,
} from '../vendor/bots/index';

export type { BotGlasses, BotHat, BotShading, BotState, BotType };

/** The persisted slice of the library's BotOptions. */
export interface BotAvatarConfig {
  type?: BotType;
  face?: 'eyes' | 'mouth';
  color?: string;
  ink?: string;
  brightness?: number;
  saturation?: number;
  shading?: BotShading;
  light?: number;
  shadow?: number;
  highlight?: number;
  rim?: number;
  spread?: number;
  depth?: number;
  furLength?: number;
  furDensity?: number;
  furFuzz?: number;
  furCurl?: number;
  furGravity?: number;
  hat?: BotHat;
  glasses?: BotGlasses;
  headphones?: boolean;
  bowTie?: boolean;
  accessoryColor?: string;
  blush?: boolean;
  blushColor?: string;
  eyeShine?: boolean;
  eyeSize?: number;
  eyeGap?: number;
  faceScale?: number;
  speed?: number;
  turn?: number;
  jumpEvery?: number;
  jumpHeight?: number;
  jumpTime?: number;
  jumpSpin?: number;
}

export const BOT_TYPES = types as BotType[];
export const BOT_SHADINGS = SHADINGS as BotShading[];
export const BOT_HATS = HATS as BotHat[];
export const BOT_GLASSES = GLASSES as BotGlasses[];
export const BOT_PALETTE = palette as Record<BotType, string>;
export const BOT_LABELS = Object.fromEntries(
  types.map((t) => [t, presets[t].label]),
) as Record<BotType, string>;

/** A friendly set of colours for the swatch picker. */
export const BOT_COLORS = [
  '#c5c5c5',
  '#8c8c8c',
  '#a2a2a2',
  '#b5b5b5',
  '#727272',
  '#535353',
  '#d4d4d4',
  '#9b9b9b',
  '#d0d0d0',
  '#b9b9b9',
  '#e4e4e4',
  '#d7d7d7',
  '#aaaaaa',
  '#dadada',
  '#e1e1e1',
  '#7e7e7e',
  '#f4f4f4',
  '#ededed',
  '#ececec',
  '#e6e6e6',
];

export interface BotPreset {
  id: string;
  name: string;
  config: BotAvatarConfig;
}

/** Ready-made characters inspired by the library's own lineup. */
export const BOT_PRESETS: BotPreset[] = [
  {
    id: 'mochi',
    name: 'Mochi',
    config: { type: 'cat', color: '#b9b9b9', shading: 'fabric', hat: 'party', bowTie: true, blush: true },
  },
  {
    id: 'pixel',
    name: 'Pixel',
    config: { type: 'droid', color: '#e1e1e1', shading: 'plastic', glasses: 'round', headphones: true },
  },
  {
    id: 'nova',
    name: 'Nova',
    config: { type: 'star', color: '#d4d4d4', shading: 'fabric', hat: 'crown', blush: true },
  },
  {
    id: 'pip',
    name: 'Pip',
    config: { type: 'clover', color: '#c5c5c5', shading: 'smooth', bowTie: true, blush: true },
  },
  {
    id: 'boo',
    name: 'Boo',
    config: { type: 'ghost', color: '#f4f4f4', shading: 'fabric', blush: true },
  },
  {
    id: 'zeke',
    name: 'Zeke',
    config: { type: 'alien', color: '#9b9b9b', shading: 'plastic', glasses: 'shades' },
  },
  {
    id: 'milo',
    name: 'Milo',
    config: { type: 'mech', color: '#7e7e7e', shading: 'crisp', hat: 'beanie', headphones: true },
  },
  {
    id: 'luna',
    name: 'Luna',
    config: { type: 'drop', color: '#535353', shading: 'plastic', hat: 'beret', bowTie: true, blush: true },
  },
];

function pick<T>(arr: readonly T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function hashSeed(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(a: number) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Deterministic look for a seed string (used for transient activity avatars). */
export function configFromSeed(seed: string): BotAvatarConfig {
  const rand = mulberry32(hashSeed(seed || 'palimind'));
  const choose = <T,>(arr: readonly T[]): T => arr[Math.floor(rand() * arr.length) % arr.length];
  const type = choose(BOT_TYPES);
  return {
    type,
    color: BOT_PALETTE[type],
    shading: choose(BOT_SHADINGS),
    hat: choose(BOT_HATS),
    glasses: choose(BOT_GLASSES),
    blush: rand() < 0.5,
  };
}

/** A fresh random look for "Shuffle". */
export function randomBotConfig(): BotAvatarConfig {
  const type = pick(BOT_TYPES);
  return {
    type,
    color: BOT_PALETTE[type],
    shading: pick(BOT_SHADINGS),
    hat: pick(BOT_HATS),
    glasses: pick(BOT_GLASSES),
    headphones: Math.random() < 0.2,
    bowTie: Math.random() < 0.45,
    blush: Math.random() < 0.55,
    eyeShine: true,
  };
}

/** Map an agent's runtime status to a bot state. */
export function botStateFor(agent: { running?: boolean; enabled?: boolean }): BotState {
  if (agent.running) return 'working';
  if (agent.enabled === false) return 'sleeping';
  return 'default';
}

/**
 * Map a run's status to a bot state for the chat assistant avatar.
 * reasoning → thinking · awaiting approval → waiting · steps running → working · done → default.
 */
export function botStateForRun(run: {
  status: 'idle' | 'thinking' | 'working' | 'awaiting_approval' | 'done' | 'stopped' | 'error';
}): BotState {
  switch (run.status) {
    case 'thinking':
      return 'thinking';
    case 'working':
      return 'working';
    case 'awaiting_approval':
      return 'waiting';
    case 'error':
      return 'default';
    default:
      return 'default';
  }
}
