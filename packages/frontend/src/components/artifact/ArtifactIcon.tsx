import {
  BookOpen,
  Code2,
  FileCode2,
  FileText,
  FolderTree,
  GitBranch,
  Globe,
  Image,
  Presentation,
  Table2,
} from 'lucide-react';
import type { ArtifactType } from '../../utils/artifacts';

const ICONS: Record<ArtifactType, typeof Code2> = {
  html: Globe,
  svg: Image,
  mermaid: GitBranch,
  react: Code2,
  markdown: FileText,
  code: Code2,
  document: BookOpen,
  'slide-outline': Presentation,
  table: Table2,
  'code-file': FileCode2,
  'multi-file': FolderTree,
};

/** Type-specific icon shared by tabs, the toolbar and menus. */
export default function ArtifactIcon({
  type,
  size = 14,
}: {
  type: ArtifactType;
  size?: number;
}) {
  const Icon = ICONS[type] || Code2;
  return <Icon size={size} aria-hidden="true" />;
}
