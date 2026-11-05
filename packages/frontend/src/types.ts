import type { BotAvatarConfig } from './bots/config';

export interface Field {
  path: string;
}

export interface Session {
  id: string;
  name: string;
  created_at?: number;
  messages: Message[];
}

export interface Message {
  role: 'user' | 'system';
  content: string;
  timestamp?: number;
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

// ── First-class projects (isolated sessions, KB and artifacts) ───────────

export type ProjectScope = `project:${string}`;

export interface ProjectArtifactVersion {
  version: number;
  created_at: number;
  size: number;
  checksum: string;
  filename: string;
  mime_type: string;
}

/** Local vault version metadata (content bodies live in IndexedDB). */
export interface ArtifactVersion {
  id: string;
  artifactId: string;
  savedAt: number;
  note?: string;
  size?: number;
  autosaved?: boolean;
}

export interface ProjectArtifact {
  id: string;
  project_id: string;
  title: string;
  type: string;
  language: string;
  description: string;
  size: number;
  current_version: number;
  created_at: number;
  updated_at: number;
  versions: ProjectArtifactVersion[];
  metadata: Record<string, unknown>;
  source?: string;
  session_id?: string;
  message_id?: string;
  /** Present when fetching a single artifact. */
  content?: string;
  /** Version returned with `content` (defaults to the current version). */
  version?: number;
}

/** Summary returned by the global artifact library. */
export interface LibraryArtifact {
  id: string;
  title: string;
  type: string;
  language: string;
  description: string;
  project_id: string;
  source: string;
  size: number;
  created_at: number;
  updated_at: number;
  content?: string;
}

export interface ProjectKbMeta {
  last_synced_at?: number;
  indexed_files?: number;
  deleted_files?: number;
  unchanged_files?: number;
  chunks_indexed?: number;
  file_errors?: number;
  status?: 'idle' | 'syncing' | 'error' | string;
  error?: string;
}

export interface ProjectKbStatus {
  project_id: string;
  workspace_path: string;
  has_index: boolean;
  indexed_files: number;
  chunks: number;
  last_indexed_at: number | null;
  status: string;
  error: string;
  file_errors: number;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  workspace_path: string;
  created_at: number;
  updated_at: number;
  last_opened_at: number | null;
  scope: ProjectScope;
  kb: ProjectKbMeta;
  kb_status?: ProjectKbStatus;
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
export type LlmSubMode = 'default' | 'moe';
export type Theme = 'dark' | 'light';

export type AppView =
  | 'home'
  | 'chat'
  | 'agents'
  | 'knowledge'
  | 'projects'
  | 'artifacts';

/** Sub-views inside the Agents workspace. */
export type AgentsView = 'home' | 'chat' | 'teams' | 'kanban' | 'runs';

export type AutonomyLevel = 'off' | 'supervised' | 'semi' | 'high';
export type MemoryMode = 'off' | 'private' | 'shared' | 'project';
export type KnowledgeMode = 'all' | 'personal' | 'project';

export interface KnowledgeScope {
  mode: KnowledgeMode;
  primary_field: string;
  extra_fields: string[];
}

export interface AgentDefinition {
  id: string;
  name: string;
  display_name: string;
  created_at: string;
  system_prompt: string;
  model: string;
  temperature: number;
  context_budget: number;
  tools: string[];
  tier_policy: 'tier1' | 'tier1+2' | 'all';
  run_mode: 'on_demand' | 'scheduled' | 'watcher' | 'webhook';
  schedule: string | null;
  watcher_pattern: string | null;
  max_iterations: number;
  write_access: boolean;
  shell_access: boolean;
  enabled: boolean;
  self_critique: boolean;
  skills: string[];
  webhook_token: string;
  // Phase 4 — adaptive reasoning, orchestration, planning & verification.
  reasoning_effort: ReasoningEffort;
  planning_mode: PlanningMode;
  orchestration: OrchestrationMode;
  orchestration_agents: number;
  verify_confidence_threshold: number;
  success_criteria: string;
  // ── Identity / onboarding ───────────────────────────────────────────
  title: string;
  description: string;
  avatar_type?: 'bot' | 'upload';
  avatar_upload?: string;
  avatar_config?: BotAvatarConfig;
  goal: string;
  custom_instructions: string;
  personality_style: string;
  // ── Autonomy / memory / scope ───────────────────────────────────────
  autonomy_level: AutonomyLevel;
  memory_mode: MemoryMode;
  knowledge_scope: KnowledgeScope;
  max_concurrent_runs: number;
  // Legacy field kept for older definitions.
  human_in_loop_threshold?: number;
  schema_version?: number;
  // ── Teams / workspace / reliability ─────────────────────────────────
  always_allow_tools?: string[];
  workspace_dir?: string;
  team_ids?: string[];
  tool_pack?: ToolPack;
}

export type ToolPack = 'auto' | 'research' | 'code' | 'data' | 'web' | 'custom';

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
  agent_label?: string;
  agent_name?: string;
  agent_avatar?: { type?: string; upload?: string; config?: BotAvatarConfig };
  team_id?: string;
  summary?: string;
  tier?: number;
  risk?: string;
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
  active_runs?: number;
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



// ─── Teams / routines / queue / overview ───────────────────────────────────

export type TeamMode = 'manager' | 'roundtable' | 'chain';

export interface TeamMember {
  agent_id: string;
  role: string;
  manager: boolean;
  agent?: AgentDefinition | null;
  name?: string;
  enabled?: boolean;
}

export interface TeamAvatar {
  type?: string;
  color?: string;
}

export interface Team {
  id: string;
  name: string;
  display_name: string;
  description: string;
  avatar: TeamAvatar;
  mode: TeamMode;
  manager_agent_id: string | null;
  manager_model: string;
  members: TeamMember[];
  charter: string;
  shared_memory: boolean;
  working_root: string;
  max_concurrency: number;
  created_at: string;
  updated_at: string;
  running?: boolean;
  pending_approvals?: number;
}

export interface TeamMessage {
  id: string;
  team_id: string;
  seq: number;
  author: string;
  role: 'user' | 'manager' | 'handoff' | 'result' | 'approval' | 'system' | 'synthesis' | string;
  content: string;
  run_id: string | null;
  meta: Record<string, unknown>;
  created_at: number;
}

export interface TeamRun {
  run_id: string;
  timestamp?: number;
  input: string;
  output: string;
  status: string;
  duration?: number;
  usage?: { prompt_tokens: number; completion_tokens: number };
  trace?: AgentReasoningEvent[];
}

export interface TeamNote {
  id: string;
  team_id: string;
  author: string;
  label: string;
  content: string;
  kind: string;
  created_at: number;
}

export interface Routine {
  id: string;
  name: string;
  target_type: 'agent' | 'team';
  target_id: string;
  input: string;
  run_mode: 'manual' | 'scheduled' | 'watcher';
  schedule: string | null;
  watcher_pattern: string | null;
  working_root: string;
  tool_pack: ToolPack;
  source_run_id: string | null;
  enabled: boolean;
  created_at: string;
  last_run_at: number | null;
  last_status: string | null;
  runs?: { run_id: string; status: string; at: number }[];
}

export interface QueueItem {
  id: string;
  target_type: 'agent' | 'team';
  target_id: string;
  input: string;
  priority: number;
  status: 'queued' | 'running' | 'paused' | 'done' | 'failed' | 'cancelled';
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  run_id: string | null;
  error: string | null;
}

export type TargetStatus = 'idle' | 'working' | 'waiting' | 'paused' | 'scheduled' | 'error';

export interface OverviewTarget {
  id: string;
  target_type: 'agent' | 'team';
  name: string;
  display_name: string;
  title?: string;
  description?: string;
  avatar_type?: string;
  avatar_upload?: string;
  avatar_config?: BotAvatarConfig;
  status: TargetStatus;
  running: boolean;
  active_runs: number;
  current_step?: string;
  last_run_status?: string | null;
  last_run_at?: number | null;
  pending_approvals: number;
  next_run?: number | null;
  member_count?: number;
  members?: TeamMember[];
  enabled?: boolean;
}

export interface OverviewCounts {
  agents: number;
  teams: number;
  working: number;
  waiting: number;
  scheduled: number;
}

export interface OverviewRun {
  target_type: 'agent' | 'team';
  target_id: string;
  target_name: string;
  run_id: string;
  status: string;
  timestamp: number;
  input: string;
  output: string;
}

export interface Overview {
  agents: (OverviewTarget & AgentDefinition)[];
  teams: (OverviewTarget & Team)[];
  inbox: Approval[];
  recent: OverviewRun[];
  upcoming: Routine[];
  routines: Routine[];
  counts: OverviewCounts;
}

export interface WorkspaceFile {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size: number;
  modified: number;
  ext: string;
}

export interface TeamEvent {
  type: string;
  [key: string]: unknown;
}
