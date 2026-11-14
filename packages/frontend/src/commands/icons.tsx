import { PixelGlyph } from '../components/pixel/PixelGlyph';
import type { PixelSprite } from '../components/pixel/sprites';
import type { CommandIcon } from './catalog';

/**
 * Command icons use the same 8×8 pixel sprite set as navigation and status.
 * Keeping this map in one place means the command palette never falls back to
 * line art while the rest of the chrome is made of filled blocks.
 */
const SPRITES: Record<CommandIcon, PixelSprite> = {
  plus: 'plus',
  message: 'chat',
  search: 'search',
  command: 'grid',
  keyboard: 'grid',
  settings: 'settings',
  'panel-left': 'menu',
  copy: 'copy',
  refresh: 'refresh',
  square: 'stop',
  blocks: 'grid',
  brain: 'spark',
  layers: 'grid',
  bot: 'bot',
  folder: 'folder',
  network: 'graph',
  sun: 'sun',
  sync: 'refresh',
  model: 'desktop',
  home: 'home',
  monitor: 'desktop',
  package: 'package',
};

export function CommandIconView({
  icon,
  size = 15,
  className,
}: {
  icon?: CommandIcon;
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  if (!icon) return null;
  const sprite = SPRITES[icon];
  if (!sprite) return null;
  return <PixelGlyph sprite={sprite} cell={size / 8} className={className} />;
}
