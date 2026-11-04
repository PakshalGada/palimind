import type { ComponentType, SVGProps } from 'react';
import {
  AlignLeft,
  AppWindow,
  ArrowDownUp,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  BookOpenText,
  Brain,
  Camera,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  CloudSun,
  Compass,
  Copy,
  CornerDownLeft,
  Database,
  Download,
  ExternalLink,
  File,
  FilePen,
  FileText,
  Files,
  FolderOpen,
  FolderSearch,
  GitFork,
  Globe,
  GraduationCap,
  HeartPulse,
  Image,
  KeyRound,
  Keyboard,
  Landmark,
  Layers,
  LayoutPanelTop,
  Library,
  ListTree,
  Loader2,
  Lock,
  MapPin,
  Maximize2,
  Minus,
  Moon,
  MoreHorizontal,
  MousePointerClick,
  Newspaper,
  OctagonX,
  Pause,
  Play,
  Quote,
  Radio,
  RefreshCw,
  Replace,
  Rss,
  Scan,
  Scissors,
  Search,
  Share2,
  Square,
  Sun,
  Table,
  Terminal,
  TextSearch,
  TriangleAlert,
  Wrench,
  X,
} from 'lucide-react';
import {
  ArxivBrand,
  GitHubBrand,
  HackerNewsBrand,
  OpenAlexBrand,
  StackExchangeBrand,
  XBrand,
} from './brands';

type IconComponent = ComponentType<
  SVGProps<SVGSVGElement> & { size?: number | string }
>;

const iconRegistry = {
  'align-left': AlignLeft,
  'app-window': AppWindow,
  'arrow-down-up': ArrowDownUp,
  'arrow-left': ArrowLeft,
  'arrow-right': ArrowRight,
  'arrow-up-right': ArrowUpRight,
  arxiv: ArxivBrand,
  'book-open': BookOpen,
  'book-open-text': BookOpenText,
  brain: Brain,
  camera: Camera,
  check: Check,
  'chevron-down': ChevronDown,
  'chevron-right': ChevronRight,
  circle: Circle,
  'cloud-sun': CloudSun,
  compass: Compass,
  copy: Copy,
  'corner-down-left': CornerDownLeft,
  database: Database,
  download: Download,
  'external-link': ExternalLink,
  file: File,
  'file-pen': FilePen,
  'file-text': FileText,
  files: Files,
  'folder-open': FolderOpen,
  'folder-search': FolderSearch,
  'git-fork': GitFork,
  github: GitHubBrand,
  globe: Globe,
  'graduation-cap': GraduationCap,
  'heart-pulse': HeartPulse,
  'hacker-news': HackerNewsBrand,
  image: Image,
  key: KeyRound,
  keyboard: Keyboard,
  landmark: Landmark,
  layers: Layers,
  'layout-panel-top': LayoutPanelTop,
  library: Library,
  'list-tree': ListTree,
  'loader-2': Loader2,
  lock: Lock,
  'map-pin': MapPin,
  maximize: Maximize2,
  minus: Minus,
  moon: Moon,
  'more-horizontal': MoreHorizontal,
  'mouse-pointer-click': MousePointerClick,
  newspaper: Newspaper,
  'octagon-x': OctagonX,
  openalex: OpenAlexBrand,
  pause: Pause,
  play: Play,
  quote: Quote,
  radio: Radio,
  refresh: RefreshCw,
  replace: Replace,
  rss: Rss,
  scan: Scan,
  scissors: Scissors,
  search: Search,
  'share-2': Share2,
  'stack-exchange': StackExchangeBrand,
  square: Square,
  sun: Sun,
  table: Table,
  terminal: Terminal,
  'terminal-square': Terminal,
  'text-search': TextSearch,
  'triangle-alert': TriangleAlert,
  wrench: Wrench,
  x: X,
  'x-brand': XBrand,
} satisfies Record<string, IconComponent>;

export type IconName = keyof typeof iconRegistry;

const fallback: IconComponent = Wrench;

export function Icon({
  name,
  size = 16,
  className,
  strokeWidth = 1.5,
  label,
}: {
  name: IconName;
  size?: number;
  className?: string;
  strokeWidth?: number;
  /** Set only when the icon is the sole label for a control. */
  label?: string;
}) {
  const Component = iconRegistry[name] ?? fallback;
  return (
    <Component
      size={size}
      strokeWidth={strokeWidth}
      className={className}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    />
  );
}

export function isIconName(value: string): value is IconName {
  return value in iconRegistry;
}
