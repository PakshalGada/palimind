import type { AgentDefinition, AgentReasoningEvent } from '../../types';

export interface ChatMessage {
  role: 'user' | 'agent';
  content: string;
  steps: AgentReasoningEvent[];
  pending: boolean;
  waiting: { tool: string; args: unknown } | null;
  error: string;
  timestamp: number;
}

export type InspectorSection =
  | 'identity'
  | 'instructions'
  | 'capabilities'
  | 'autonomy'
  | 'schedule'
  | 'knowledge'
  | 'runs'
  | 'danger';

export const EMPTY_DEF: Partial<AgentDefinition> = {
  name: '',
  display_name: '',
  system_prompt: '',
  model: '',
  temperature: 0.2,
  context_budget: 8000,
  tools: [],
  tier_policy: 'tier1+2',
  run_mode: 'on_demand',
  schedule: '',
  watcher_pattern: '',
  max_iterations: 15,
  write_access: false,
  shell_access: false,
  enabled: true,
  self_critique: false,
  skills: [],
  webhook_token: '',
  reasoning_effort: 'auto',
  planning_mode: 'off',
  orchestration: 'off',
  orchestration_agents: 0,
  verify_confidence_threshold: 0.0,
  success_criteria: '',
  title: '',
  description: '',
  avatar_type: 'bot',
  avatar_upload: '',
  avatar_config: {},
  personality_style: '',
  goal: '',
  custom_instructions: '',
  autonomy_level: 'semi',
  memory_mode: 'private',
  knowledge_scope: { mode: 'all', primary_field: '', extra_fields: [] },
  max_concurrent_runs: 1,
};

export function fmtTime(ts?: number | null): string {
  if (!ts) return 'never';
  return new Date(ts * 1000).toLocaleString();
}
