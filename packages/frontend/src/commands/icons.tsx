import type { ComponentType } from 'react';
import {
  Blocks,
  Bot,
  Brain,
  Command,
  Copy,
  Cpu,
  FileText,
  Folder,
  Keyboard,
  Layers,
  MessageSquare,
  Network,
  PanelLeft,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Square,
  Sun,
} from 'lucide-react';
import type { CommandIcon } from './catalog';

type IconComponent = ComponentType<{ size?: number | string; strokeWidth?: number | string; className?: string }>;

const ICONS: Record<CommandIcon, IconComponent> = {
  plus: Plus,
  message: MessageSquare,
  search: Search,
  command: Command,
  keyboard: Keyboard,
  settings: Settings,
  'panel-left': PanelLeft,
  copy: Copy,
  refresh: RefreshCw,
  square: Square,
  blocks: Blocks,
  canvas: FileText,
  brain: Brain,
  layers: Layers,
  bot: Bot,
  folder: Folder,
  network: Network,
  sun: Sun,
  sync: RefreshCw,
  model: Cpu,
};

export function CommandIconView({
  icon,
  size = 15,
  strokeWidth = 2,
  className,
}: {
  icon?: CommandIcon;
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  if (!icon) return null;
  const Icon = ICONS[icon];
  if (!Icon) return null;
  return <Icon size={size} strokeWidth={strokeWidth} className={className} />;
}
