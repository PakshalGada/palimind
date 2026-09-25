export interface Field {
  path: string;
}

export interface Session {
  id: string;
  name: string;
  messages: Message[];
}

export interface Message {
  role: 'user' | 'system';
  content: string;
  sources?: string[];
}

export interface TreeNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  children?: TreeNode[];
}

export interface DirItem {
  name: string;
  path: string;
  type: 'file' | 'directory';
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  file_path?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface HardwareData {
  gpus?: { name: string; vram_mb: number }[];
  total_ram_mb?: number;
  os_platform?: string;
  serve_engines_available?: string[];
}

export interface ModelItem {
  model_id: string;
  display_name?: string;
  family?: string;
  parameter_size?: string;
  size_gb?: number;
}

export interface Recommendation {
  name: string;
  params_b: string;
  file_size_gb: number;
  fit: 'FITS_PERFECTLY' | 'FITS_TIGHT' | 'CPU_FALLBACK' | 'TOO_LARGE';
}

export type ChatMode = 'document' | 'llm';
export type LlmSubMode = 'default' | 'moe';
export type Theme = 'dark' | 'light';

export type AppView = 'chat' | 'fields' | 'agents';

export interface AgentDefinition {
  id: string;
  name: string;
  created_at: string;
  system_prompt: string;
  model: string;
  temperature: number;
  context_budget: number;
  tools: string[];
  tier_policy: 'tier1' | 'tier1+2' | 'all';
  memory_scope: 'none' | 'session' | 'field';
  memory_file: string;
  visibility: 'field' | 'global';
  run_mode: 'on_demand' | 'scheduled' | 'watcher' | 'webhook';
  schedule: string | null;
  watcher_pattern: string | null;
  max_iterations: number;
  human_in_loop_threshold: number;
  write_access: boolean;
  shell_access: boolean;
  enabled: boolean;
  self_critique: boolean;
  skills: string[];
  webhook_token: string;
  context_fields?: string[];
  color_seed?: string;
}

export interface SkillMeta {
  id: string;
  name: string;
  description: string;
  category: string;
  tools: string[];
  instructions: string;
  builtin: boolean;
}

export interface AgentActivity {
  agent_id: string;
  name: string;
  run_id: string;
  source: string;
  step: string;
  status: string;
  started_at: number;
  updated_at: number;
}

export interface AgentActivityEvent {
  type: 'start' | 'step' | 'finish';
  kind?: string;
  agent_id: string;
  name: string;
  run_id?: string;
  source?: string;
  status?: string;
  text: string;
  ts: number;
}

export interface AgentActivitySnapshot {
  running: AgentActivity[];
  recent: AgentActivityEvent[];
}

export interface Approval {
  agent_id: string;
  run_id: string;
  tool: string;
  args: unknown;
  confidence: number;
  reasoning: string;
  created_at: number;
}

export interface RecentRun extends RunRecord {
  agent_id: string;
  agent_name: string;
}

export interface SetupTask {
  key: string;
  label: string;
  status: string;
  progress: number | null;
  message: string;
}

export interface AgentChatMessage {
  role: 'user' | 'agent';
  content: string;
  timestamp: number;
}

export interface AgentListItem extends AgentDefinition {
  running: boolean;
  last_run_status: string | null;
  last_run_at?: number | null;
}

export interface MemoryEntry {
  timestamp: string;
  type: string;
  content: string;
}

export interface RunRecord {
  run_id: string;
  timestamp: number;
  input: string;
  output: string;
  status: string;
  duration: number;
  usage?: { prompt_tokens: number; completion_tokens: number };
  trace?: AgentReasoningEvent[];
}

export interface ToolMeta {
  id: string;
  description: string;
  tier: number;
  requires_approval: boolean;
  parameters?: Record<string, string>;
}

/**
 * Frozen SSE contract for an agent run (POST /api/agents/{id}/run and the
 * global chat @agent path). `agent:token` frames stream the final answer in
 * chunks; `agent:completed` carries the full output once the run ends.
 */
export type AgentReasoningEvent =
  | { type: 'agent:thought'; text: string; iteration?: number }
  | { type: 'agent:tool_call'; tool: string; args?: unknown }
  | { type: 'agent:tool_result'; tool: string; result?: string }
  | { type: 'agent:token'; text?: string; reset?: boolean; stream?: boolean }
  | {
      type: 'agent:waiting_for_human';
      tool: string;
      args?: unknown;
      confidence?: number;
      threshold?: number;
      reasoning?: string;
    }
  | { type: 'agent:completed'; output: string; status?: string }
  | { type: 'error'; text: string };
