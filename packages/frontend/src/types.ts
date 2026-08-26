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

export type AppView = 'fields' | 'palivision' | 'agents';

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
  run_mode: 'on_demand' | 'scheduled' | 'watcher';
  schedule: string | null;
  watcher_pattern: string | null;
  max_iterations: number;
  human_in_loop_threshold: number;
  write_access: boolean;
  shell_access: boolean;
  enabled: boolean;
  context_fields?: string[];
  color_seed?: string;
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
}

export interface ToolMeta {
  id: string;
  description: string;
  tier: number;
  requires_approval: boolean;
  parameters?: Record<string, string>;
}

export interface GlanceMessage {
  role: 'user' | 'assistant';
  content: string;
  ts?: number;
}

export interface GlanceSession {
  id: string;
  title: string;
  messages: GlanceMessage[];
  screen_summary?: string;
  screenshot_b64?: string;
  ocr_text?: string;
  chat_model?: string;
  created_at?: number;
  updated_at?: number;
}
