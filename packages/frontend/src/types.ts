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
  citations?: CitationPayload;
}

export interface CitationSource {
  marker: number;
  title: string;
  kind: 'web' | 'document' | 'media' | 'agent' | string;
  url: string;
  file: string;
  section: string;
  snippet: string;
  content: string;
  score: number;
}

export interface CitationLink {
  marker: number;
  source_id: string;
  sentence: string;
  score: number;
}

export interface CitationPayload {
  text?: string;
  citations: CitationLink[];
  sources: CitationSource[];
  bibliography: string;
  accuracy: number;
  coverage: number;
  mean_score: number;
  cited_markers: number[];
}

export interface ResearchSubTopic {
  subtopic_id: number;
  title: string;
  research_question: string;
  search_queries: string[];
}

export interface ResearchFinding {
  id: string;
  title: string;
  content: string;
  created_at: number;
}

export interface ResearchTimelineEntry {
  at: number;
  type: string;
  text: string;
}

export interface ResearchReport {
  id: string;
  query: string;
  report: string;
  created_at: number;
}

export interface ResearchProject {
  id: string;
  title: string;
  query: string;
  created_at: number;
  updated_at: number;
  notes: string;
  findings: ResearchFinding[];
  sources: CitationSource[];
  timeline: ResearchTimelineEntry[];
  reports: ResearchReport[];
}

export interface ResearchProjectSummary {
  id: string;
  title: string;
  query: string;
  created_at: number;
  updated_at: number;
  source_count: number;
  finding_count: number;
}

export interface ComparisonConsensus {
  text: string;
  models: string[];
  support: number;
}

export interface ComparisonContradiction {
  claim_a: string;
  model_a: string;
  claim_b: string;
  model_b: string;
  explanation: string;
}

export interface ComparisonResult {
  models: string[];
  consensus: ComparisonConsensus[];
  unique: Record<string, string[]>;
  claim_counts: Record<string, number>;
  contradictions?: ComparisonContradiction[];
}

export interface SocialSentiment {
  label: string;
  score: number;
  positive: number;
  negative: number;
  distribution?: Record<string, number>;
}

export interface SocialPost {
  text: string;
  snippet: string;
  url: string;
  author: string;
  sentiment: SocialSentiment;
}

export interface SocialSignal {
  query: string;
  posts: SocialPost[];
  sentiment: SocialSentiment;
  trends: {
    hashtags: [string, number][];
    cashtags: [string, number][];
    keywords: string[];
  };
  count: number;
  error?: string;
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
  provider?: string;
}

export interface Recommendation {
  name: string;
  params_b: string;
  file_size_gb: number;
  fit: 'FITS_PERFECTLY' | 'FITS_TIGHT' | 'CPU_FALLBACK' | 'TOO_LARGE';
}

export type ChatMode = 'document' | 'llm';
export type LlmSubMode = 'default' | 'moe' | 'deep_research';
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
  // Phase 4 — adaptive reasoning, orchestration, planning & verification.
  reasoning_effort: ReasoningEffort;
  planning_mode: PlanningMode;
  orchestration: OrchestrationMode;
  orchestration_agents: number;
  verify_confidence_threshold: number;
  success_criteria: string;
}

export type ReasoningEffort = 'off' | 'auto' | 'minimal' | 'standard' | 'high' | 'max';
export type PlanningMode = 'off' | 'review' | 'auto';
export type OrchestrationMode = 'off' | 'fan_out' | 'arena';

export interface EffortLevel {
  level: Exclude<ReasoningEffort, 'off' | 'auto'>;
  label: string;
  description: string;
  iterations: number;
  context: number;
  tokens: number;
  verify: boolean;
  indicator: string;
}

export interface PlanStep {
  id: number;
  title: string;
  description: string;
  tool: string;
  args: Record<string, unknown>;
  status: string;
  result: string;
  approved: boolean;
}

export interface AgentPlan {
  id: string;
  agent_id: string;
  task: string;
  notes: string;
  created_at: number;
  updated_at: number;
  status: string;
  steps: PlanStep[];
  error?: string;
}

export interface PlanTemplate {
  id: string;
  name: string;
  description: string;
  steps: Partial<PlanStep>[];
}

export interface Goal {
  id: string;
  name: string;
  objective: string;
  success_criteria: string;
  agent_id: string;
  status: 'active' | 'paused' | 'completed' | 'failed';
  progress: number;
  created_at: number;
  updated_at: number;
  deadline: number | null;
  notes: { at: number; text: string }[];
  task_ids: string[];
}

export interface BackgroundTask {
  id: string;
  goal_id: string;
  agent_id: string;
  prompt: string;
  kind: 'once' | 'loop';
  interval_seconds: number;
  next_run: number;
  created_at: number;
  expires_at: number;
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled' | 'expired';
  run_count: number;
  last_run: number | null;
  last_status: string;
  last_output: string;
}

export interface GoalNotification {
  id: string;
  kind: string;
  text: string;
  meta: Record<string, unknown>;
  created_at: number;
  read: boolean;
}

export interface SkillCommand {
  command: string;
  skill_id: string;
  name: string;
  description: string;
  category: string;
}

export interface MarketplaceSkill {
  id: string;
  name: string;
  description: string;
  category: string;
  command: string;
  version: string;
  author: string;
  tools: string[];
  instructions: string;
  installed: boolean;
}

export interface VerificationReport {
  task_type: string;
  checklist: string[];
  passed: boolean;
  confidence: number;
  checks: Record<string, string>;
  issues: string[];
  suggestions: string[];
  reasoning: string;
  source: string;
}

export interface SkillMeta {
  id: string;
  name: string;
  description: string;
  category: string;
  tools: string[];
  instructions: string;
  builtin: boolean;
  command?: string;
  compose?: string[];
  version?: string;
  author?: string;
  source?: string;
  enabled?: boolean;
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
  verification?: VerificationReport;
  effort?: { level?: string; source?: string; score?: number | null; reasoning?: string };
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
  | {
      type: 'agent:effort';
      level: string;
      indicator?: string;
      source?: string;
      score?: number | null;
      reasoning?: string;
      max_iterations?: number;
    }
  | { type: 'agent:plan'; plan_id: string; mode: string; status: string; steps: PlanStep[] }
  | { type: 'agent:verification'; report: VerificationReport; attempt?: number }
  | { type: 'agent:needs_review'; report: VerificationReport }
  | {
      type: 'orchestrator:plan';
      mode: string;
      agents: { agent_id: number; label: string; task: string; tools?: string[] }[];
    }
  | { type: 'orchestrator:agent_start'; agent_id: number; label: string; task?: string }
  | { type: 'orchestrator:agent_step'; agent_id: number; text: string }
  | { type: 'orchestrator:blackboard'; agent_id: number; label: string; output: string }
  | { type: 'orchestrator:agent_complete'; agent_id: number; label: string }
  | { type: 'orchestrator:conflict'; conflicts: unknown[] }
  | { type: 'orchestrator:complete'; output: string; conflicts?: number; mode?: string }
  | { type: 'error'; text: string };

// ─── Phase 1: Workflow Builder Types ────────────────────────────────────────

export type WorkflowNodeType =
  | 'agent'
  | 'tool'
  | 'condition'
  | 'loop'
  | 'delay'
  | 'webhook'
  | 'cron'
  | 'code'
  | 'transform'
  | 'output';

export type WorkflowNodeStatus = 'idle' | 'pending' | 'running' | 'done' | 'error' | 'skipped';

export interface WorkflowNode {
  id: string;
  type: WorkflowNodeType;
  name: string;
  description?: string;
  config: Record<string, unknown>;
  position: { x: number; y: number };
  agent_id?: string;
  status: WorkflowNodeStatus;
  error?: string;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  source_handle?: string;
  target_handle?: string;
  condition?: string;
  label?: string;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  created_at: number;
  updated_at: number;
  status: 'draft' | 'active' | 'paused' | 'archived';
  version: number;
}

export interface WorkflowExecution {
  id: string;
  workflow_id: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  started_at: number;
  completed_at?: number;
  node_results: Record<string, { status: WorkflowNodeStatus; output?: unknown; error?: string; duration?: number }>;
  logs: WorkflowLogEntry[];
}

export interface WorkflowLogEntry {
  timestamp: number;
  node_id?: string;
  level: 'info' | 'warn' | 'error' | 'debug';
  message: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

// ─── Phase 1: Kanban Dashboard Types ────────────────────────────────────────

export type KanbanStatus = 'todo' | 'in_progress' | 'pending_approval' | 'completed' | 'failed';
export type KanbanPriority = 'low' | 'medium' | 'high' | 'critical';

export interface KanbanTask {
  id: string;
  agent_id: string;
  agent_name: string;
  title: string;
  description: string;
  prompt: string;
  status: KanbanStatus;
  priority: KanbanPriority;
  created_at: number;
  started_at?: number;
  completed_at?: number;
  duration?: number;
  parent_task_id?: string;
  workflow_id?: string;
  progress: number;
  output?: string;
  metadata: Record<string, unknown>;
  tags: string[];
  history?: KanbanTaskHistory[];
}

export interface KanbanTaskHistory {
  id: string;
  task_id: string;
  from_status: KanbanStatus;
  to_status: KanbanStatus;
  timestamp: number;
  actor: 'user' | 'agent' | 'system';
}

export interface KanbanColumn {
  id: KanbanStatus;
  title: string;
  color: string;
  limit?: number;
}


