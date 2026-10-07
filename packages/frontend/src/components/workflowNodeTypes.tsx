import type { ComponentType } from 'react';
import {
  Bot,
  Wrench,
  GitBranch,
  Repeat,
  Timer,
  Webhook,
  CalendarClock,
  Code2,
  Shuffle,
  Upload,
} from 'lucide-react';
import type { WorkflowNodeType } from '../types';

export type NodeIconComponent = ComponentType<{ size?: number | string; className?: string; strokeWidth?: number }>;

export interface WorkflowNodeTypeMeta {
  type: WorkflowNodeType;
  label: string;
  description: string;
  icon: NodeIconComponent;
}

export interface WorkflowNodeTypeCategory {
  category: string;
  types: WorkflowNodeTypeMeta[];
}

export const NODE_TYPE_ICONS: Record<WorkflowNodeType, NodeIconComponent> = {
  agent: Bot,
  tool: Wrench,
  condition: GitBranch,
  loop: Repeat,
  delay: Timer,
  webhook: Webhook,
  cron: CalendarClock,
  code: Code2,
  transform: Shuffle,
  output: Upload,
};

export const NODE_TYPE_CATEGORIES: WorkflowNodeTypeCategory[] = [
  {
    category: 'Agents & Triggers',
    types: [
      { type: 'agent', label: 'Agent', description: 'Run an AI agent', icon: Bot },
      { type: 'webhook', label: 'Webhook', description: 'Trigger on HTTP request', icon: Webhook },
      { type: 'cron', label: 'Cron', description: 'Trigger on schedule', icon: CalendarClock },
    ],
  },
  {
    category: 'Logic & Flow',
    types: [
      { type: 'condition', label: 'Condition', description: 'If/else branching', icon: GitBranch },
      { type: 'loop', label: 'Loop', description: 'For each / while', icon: Repeat },
      { type: 'delay', label: 'Delay', description: 'Wait N seconds', icon: Timer },
    ],
  },
  {
    category: 'Data & Tools',
    types: [
      { type: 'tool', label: 'Tool', description: 'Call a tool', icon: Wrench },
      { type: 'code', label: 'Code', description: 'Custom Python/JS', icon: Code2 },
      { type: 'transform', label: 'Transform', description: 'JSON/text transform', icon: Shuffle },
    ],
  },
  {
    category: 'Output',
    types: [{ type: 'output', label: 'Output', description: 'File/email/notify', icon: Upload }],
  },
];

export const NODE_TYPE_MAP: Record<string, WorkflowNodeTypeMeta> = {};
for (const cat of NODE_TYPE_CATEGORIES) {
  for (const t of cat.types) {
    NODE_TYPE_MAP[t.type] = t;
  }
}
