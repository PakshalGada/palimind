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

export type InspectorTab = 'definition' | 'tools' | 'memory' | 'history';

export const EMPTY_DEF: Partial<AgentDefinition> = {
  name: '',
  system_prompt: '',
  model: '',
  temperature: 0.2,
  context_budget: 8000,
  tools: [],
  tier_policy: 'tier1+2',
  memory_scope: 'field',
  context_fields: [],
  visibility: 'global',
  run_mode: 'on_demand',
  schedule: '',
  watcher_pattern: '',
  max_iterations: 15,
  human_in_loop_threshold: 0.0,
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
  memory_mode: 'shared',
  autonomy_level: 'semi',
  proactive_message_first: false,
  morning_brief: false,
  watch_sources: [],
  working_hours: '',
  max_concurrent_runs: 1,
  knowledge_access: 'personal',
  can_create_knowledge: false,
};

export function fmtTime(ts?: number | null): string {
  if (!ts) return 'never';
  return new Date(ts * 1000).toLocaleString();
}
