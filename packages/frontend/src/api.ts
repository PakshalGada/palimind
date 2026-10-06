import type { AgentActivitySnapshot, AgentChatMessage, AgentDefinition, AgentListItem, AgentPlan, Approval, BackgroundTask, DirItem, EffortLevel, Goal, GoalNotification, GraphData, HardwareData, MarketplaceSkill, MemoryEntry, ModelItem, PlanTemplate, RecentRun, Recommendation, ResearchFinding, ResearchProject, ResearchProjectSummary, RunRecord, SetupTask, SkillCommand, SkillMeta, SocialSignal, ToolMeta, TreeNode, VerificationReport } from './types';

const BASE = '/api';

async function parse<T>(res: Response, label: string): Promise<T> {
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {}
  if (!res.ok) {
    const detail =
      (data as { detail?: string; error?: string } | null)?.detail ||
      (data as { error?: string } | null)?.error ||
      `${res.status} ${res.statusText}`;
    throw new Error(`${label} failed: ${detail}`);
  }
  return (data ?? {}) as T;
}

async function get<T>(path: string, headers?: Record<string, string>): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers });
  return parse<T>(res, `GET ${path}`);
}

async function post<T>(path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return parse<T>(res, `POST ${path}`);
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return parse<T>(res, `PATCH ${path}`);
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return parse<T>(res, `PUT ${path}`);
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE' });
  return parse<T>(res, `DELETE ${path}`);
}

export const api = {
  fields: {
    list: () => get<{ fields: string[]; active_field: string | null; is_indexing: boolean; indexing_status?: string }>('/fields'),
    setActive: (path: string) => post<{ error?: string }>('/fields/set_active', { path }),
    add: (path: string) => post<{ error?: string }>('/fields/add', { path }),
    remove: (path: string) => post<{ status?: string }>('/fields/remove', { path }),
  },
  sessions: {
    list: (scope = 'field') => get<{ sessions: { id: string; name: string; messages: { role: string; content: string; sources?: string[]; citations?: import('./types').CitationPayload }[] }[]; active_session_id: string | null; error?: string }>(`/sessions?scope=${scope}`),
    new: (name: string, scope = 'field') => post<{ error?: string; sessions: unknown[]; active_session_id: string }>(`/sessions/new?scope=${scope}`, { name }),
    setActive: (sessionId: string, scope = 'field') => post<{ error?: string; sessions: unknown[]; active_session_id: string }>(`/sessions/set_active?scope=${scope}`, { session_id: sessionId }),
    remove: (sessionId: string, scope = 'field') => post<{ error?: string; sessions: unknown[]; active_session_id: string }>(`/sessions/remove?scope=${scope}`, { session_id: sessionId }),
    truncate: (sessionId: string, keepCount: number, scope = 'field') => post<{ error?: string; sessions: unknown[]; active_session_id: string }>(`/sessions/truncate?scope=${scope}`, { session_id: sessionId, keep_count: keepCount }),
    deleteMessage: (sessionId: string, index: number, scope = 'field') => post<{ error?: string; sessions: unknown[]; active_session_id: string }>(`/sessions/delete_message?scope=${scope}`, { session_id: sessionId, index }),
  },
  sync: () => post<{ status: string; indexed_files?: number; deleted_files?: number; error?: string }>('/update'),
  files: {
    tree: () => get<{ tree?: TreeNode[]; error?: string }>('/files/tree'),
    treeSub: (path: string) => get<{ children?: TreeNode[]; error?: string }>(`/files/tree/sub?path=${encodeURIComponent(path)}`),
  },
  config: {
    get: (scope = 'field') => get<{ chat_model?: string; embed_model?: string; moe_orchestrator_model?: string; moe_worker_model?: string; moe_sub_mode?: string; deep_research_model?: string; persona_name?: string; persona_system_prompt?: string }>(`/config?scope=${scope}`),
    setModel: (modelId: string, scope = 'field') => patch<{ error?: string }>(`/config/model?scope=${scope}`, { model_id: modelId }),
    setEmbedModel: (modelId: string, scope = 'field') => patch<{ error?: string }>(`/config/embed-model?scope=${scope}`, { embed_model: modelId }),
    setMoe: (data: { moe_orchestrator_model?: string; moe_worker_model?: string; moe_sub_mode?: string }, scope = 'field') => patch<{ error?: string }>(`/config/moe?scope=${scope}`, data),
    setPersona: (data: { persona_name?: string; persona_system_prompt?: string }) =>
      patch<{ error?: string; status?: string }>('/config/persona', data),
  },
  settings: {
    opencodeKey: {
      status: () => get<{ configured: boolean; masked?: string | null }>('/settings/opencode-key'),
      save: (key: string) => post<{ status?: string; error?: string }>('/settings/opencode-key', { key }),
      remove: () => del<{ status?: string; error?: string }>('/settings/opencode-key'),
    },
    voice: {
      status: () =>
        get<{
          stt_whisper_model: string;
          options: { id: string; label: string; size_mb: number; note: string }[];
        }>('/settings/voice'),
      save: (data: { stt_whisper_model: string }) =>
        patch<{ status?: string; error?: string }>('/settings/voice', data),
    },
  },
  agents: {
    list: () => get<{ agents?: AgentListItem[]; error?: string }>('/agents'),
    create: (defn: Partial<AgentDefinition>) => post<AgentListItem & { error?: string }>('/agents/create', defn),
    update: (agentId: string, changes: Partial<AgentDefinition>) =>
      patch<AgentListItem & { error?: string }>(`/agents/${agentId}`, changes),
    remove: (agentId: string) => del<{ error?: string; status?: string }>(`/agents/${agentId}`),
    tools: () => get<{ tools: Record<string, ToolMeta> }>('/agents/tools'),
    skills: () => get<{ skills: SkillMeta[] }>('/agents/skills'),
    activity: () => get<AgentActivitySnapshot>('/agents/activity'),
    approvals: () => get<{ approvals: Approval[] }>('/agents/approvals'),
    recentRuns: (limit = 30) => get<{ runs: RecentRun[] }>(`/agents/runs/recent?limit=${limit}`),
    recallPreview: (agentId: string, query: string, k = 8) =>
      post<{ entries: MemoryEntry[] }>(`/agents/${agentId}/recall-preview`, { query, k }),
    run: (agentId: string, runId: string) =>
      get<RunRecord & { error?: string }>(`/agents/${agentId}/runs/${encodeURIComponent(runId)}`),
    validateCron: (schedule: string) => post<{ valid: boolean; error?: string | null }>('/agents/validate-cron', { schedule }),
    memory: (agentId: string, page = 1, perPage = 20) =>
      get<{ entries: MemoryEntry[]; total: number; page: number; per_page: number }>(
        `/agents/${agentId}/memory?page=${page}&per_page=${perPage}`,
      ),
    chat: (agentId: string) => get<{ messages?: AgentChatMessage[] }>(`/agents/${agentId}/chat`),
    clearChat: (agentId: string) => del<{ error?: string; status?: string }>(`/agents/${agentId}/chat`),
    deleteMemoryEntry: (agentId: string, index: number) =>
      del<{ error?: string; status?: string }>(`/agents/${agentId}/memory?index=${index}`),
    clearMemory: (agentId: string) => post<{ error?: string; status?: string }>(`/agents/${agentId}/memory/clear`),
    history: (agentId: string) => get<{ history: RunRecord[] }>(`/agents/${agentId}/history`),
    cancel: (agentId: string) => post<{ error?: string; status?: string }>(`/agents/${agentId}/cancel`),
    approve: (agentId: string, approved: boolean, correction = '') =>
      post<{ error?: string; status?: string }>(`/agents/${agentId}/approve`, { approved, correction }),
    effortLevels: () => get<{ levels: EffortLevel[] }>('/agents/effort-levels'),
    classifyEffort: (task: string, model = '') =>
      post<{ level: string; score: number; indicator: string; reasoning?: string; source: string }>(
        '/agents/classify-effort',
        { task, model },
      ),
    verificationChecklists: () =>
      get<{ checklists: Record<string, string[]> }>('/agents/verification/checklists'),
    verify: (task: string, output: string, model = '', taskType?: string) =>
      post<{ report: VerificationReport }>('/agents/verify', {
        task,
        output,
        model,
        task_type: taskType,
      }),
    skillsAdmin: {
      validate: (skill: Partial<SkillMeta>) =>
        post<{ valid: boolean; error?: string | null }>('/agents/skills/validate', { skill }),
      install: (skill: Partial<SkillMeta>, overwrite = false) =>
        post<{ status?: string; skill?: SkillMeta; error?: string }>('/agents/skills/install', {
          skill,
          overwrite,
        }),
      uninstall: (id: string) =>
        post<{ status?: string }>('/agents/skills/uninstall', { id }),
      export: (id: string) =>
        get<{ skill?: SkillMeta; error?: string }>(`/agents/skills/export?id=${encodeURIComponent(id)}`),
      marketplace: () => get<{ skills: MarketplaceSkill[] }>('/agents/skills/marketplace'),
      marketplaceInstall: (id: string, overwrite = false) =>
        post<{ status?: string; skill?: SkillMeta; error?: string }>(
          '/agents/skills/marketplace/install',
          { id, overwrite },
        ),
      commands: () => get<{ commands: SkillCommand[] }>('/agents/skills/commands'),
      resolve: (text: string) =>
        post<{ resolved: boolean; command?: string; skill?: SkillMeta; input?: string }>(
          '/agents/skills/resolve',
          { text },
        ),
    },
    plans: {
      templates: () => get<{ templates: PlanTemplate[] }>('/agents/plan-templates'),
      create: (task: string, opts: { template?: string; agent_id?: string; model?: string } = {}) =>
        post<{ plan: AgentPlan }>('/agents/plan', { task, ...opts }),
      list: (limit = 50) => get<{ plans: AgentPlan[] }>(`/agents/plans?limit=${limit}`),
      get: (planId: string) => get<AgentPlan & { error?: string }>(`/agents/plans/${planId}`),
      update: (planId: string, changes: { steps?: unknown[]; status?: string; notes?: string }) =>
        patch<AgentPlan & { error?: string }>(`/agents/plans/${planId}`, changes),
      remove: (planId: string) => del<{ status?: string }>(`/agents/plans/${planId}`),
      approve: (planId: string, approved: boolean, steps?: unknown[]) =>
        post<{ status?: string }>(`/agents/plans/${planId}/approve`, { approved, steps }),
      execute: (planId: string, autoApprove = true) =>
        post<{ plan?: AgentPlan; error?: string }>(`/agents/plans/${planId}/execute`, {
          auto_approve: autoApprove,
        }),
    },
    goals: {
      list: () => get<{ goals: Goal[] }>('/agents/goals'),
      create: (data: { name: string; objective?: string; success_criteria?: string; agent_id?: string }) =>
        post<{ goal?: Goal; error?: string }>('/agents/goals', data),
      get: (goalId: string) => get<Goal & { error?: string }>(`/agents/goals/${goalId}`),
      update: (goalId: string, changes: Partial<Goal>) =>
        patch<Goal & { error?: string }>(`/agents/goals/${goalId}`, changes),
      remove: (goalId: string) => del<{ status?: string }>(`/agents/goals/${goalId}`),
      setProgress: (goalId: string, progress: number, note = '') =>
        post<Goal & { error?: string }>(`/agents/goals/${goalId}/progress`, { progress, note }),
    },
    tasks: {
      list: (goalId?: string) =>
        get<{ tasks: BackgroundTask[] }>(`/agents/tasks${goalId ? `?goal_id=${encodeURIComponent(goalId)}` : ''}`),
      create: (data: {
        agent_id: string;
        prompt?: string;
        command?: string;
        goal_id?: string;
        interval_seconds?: number;
      }) => post<{ task?: BackgroundTask; error?: string }>('/agents/tasks', data),
      cancel: (taskId: string) =>
        post<{ task?: BackgroundTask; error?: string }>(`/agents/tasks/${taskId}/cancel`),
      remove: (taskId: string) => del<{ status?: string }>(`/agents/tasks/${taskId}`),
    },
    notifications: {
      list: (unreadOnly = false) =>
        get<{ notifications: GoalNotification[] }>(`/agents/notifications?unread_only=${unreadOnly}`),
      markRead: (ids?: string[]) =>
        post<{ status?: string; updated: number }>('/agents/notifications/read', { ids }),
      clear: () => del<{ status?: string }>('/agents/notifications'),
    },
    orchestrateStream: async (
      agentId: string,
      task: string,
      onEvent: (ev: { type: string; [k: string]: unknown }) => void,
      opts: { mode?: string; num_agents?: number; session_id?: string } = {},
    ): Promise<void> => {
      const res = await fetch(`${BASE}/agents/${agentId}/orchestrate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task, ...opts }),
      });
      if (!res.ok || !res.body) throw new Error(`orchestrate failed: ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          for (const line of frame.split('\n')) {
            if (!line.startsWith('data:')) continue;
            try {
              onEvent(JSON.parse(line.slice(5).trim()));
            } catch {}
          }
        }
      }
    },
    runStream: async (
      agentId: string,
      input: string,
      sessionId: string | undefined,
      onEvent: (ev: { type: string; [k: string]: unknown }) => void,
    ): Promise<void> => {
      const res = await fetch(`${BASE}/agents/${agentId}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input, session_id: sessionId || '' }),
      });
      if (!res.ok || !res.body) throw new Error(`run agent failed: ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          for (const line of frame.split('\n')) {
            if (!line.startsWith('data:')) continue;
            try {
              onEvent(JSON.parse(line.slice(5).trim()));
            } catch {}
          }
        }
      }
    },
  },
  moe: {
    hardwareCheck: () => get<{ fits_gpu?: boolean; fits_ram?: boolean; vram_per_worker_mb?: number; vram_orchestrator_mb?: number; total_vram_needed_mb?: number; total_ram_needed_mb?: number; suggested_worker?: string; suggested_orchestrator?: string; gpu_vram_mb?: number; system_ram_mb?: number; error?: string }>('/moe/hardware-check'),
  },
  models: {
    list: () => get<{ models?: ModelItem[]; current_model?: string; status?: string }>('/models'),
    pullUrl: (model: string) => `${BASE}/models/pull?model=${encodeURIComponent(model)}`,
  },
  setup: {
    status: () => get<{ tasks: SetupTask[] }>('/setup/status'),
  },
  cookbook: {
    hardware: () => get<HardwareData & { error?: string }>('/cookbook/hardware'),
    recommendations: (top = 10) => get<{ recommendations?: Recommendation[] }>(`/cookbook/recommendations?top=${top}`),
  },
  graph: {
    get: () => get<GraphData & { error?: string; needs_rebuild?: boolean }>('/document/graph'),
    rebuild: () => post<{ error?: string }>('/document/graph/rebuild'),
  },
  fs: {
    list: (path?: string) => get<{ current_path: string; parent_path?: string; items: DirItem[]; error?: string }>(`/fs/list${path ? `?path=${encodeURIComponent(path)}` : ''}`),
  },
  canvas: {
    list: () => get<{ canvases: { id: string; title: string; updated_at: number; created_at: number }[] }>('/canvas'),
    get: (canvasId: string) => get<{ id: string; title: string; content: string; created_at?: number; updated_at?: number; error?: string }>(`/canvas/${encodeURIComponent(canvasId)}`),
    save: (canvasId: string, title: string, content: string) =>
      put<{ id: string; title: string; content: string; updated_at: number; error?: string }>(`/canvas/${encodeURIComponent(canvasId)}`, { title, content }),
    remove: (canvasId: string) => del<{ status?: string; error?: string }>(`/canvas/${encodeURIComponent(canvasId)}`),
  },
  research: {
    approve: (planId: string, plan: unknown[]) =>
      post<{ status?: string; error?: string }>('/research/approve', { plan_id: planId, plan }),
    cancel: (planId: string) =>
      post<{ status?: string; error?: string }>('/research/cancel', { plan_id: planId }),
    social: (q: string, maxResults = 8) =>
      get<SocialSignal>(`/research/x?q=${encodeURIComponent(q)}&max_results=${maxResults}`),
    projects: {
      list: () => get<{ projects: ResearchProjectSummary[] }>('/research/projects'),
      create: (title: string, query = '') => post<ResearchProject>('/research/projects', { title, query }),
      get: (id: string) => get<ResearchProject & { error?: string }>(`/research/projects/${encodeURIComponent(id)}`),
      update: (id: string, changes: { title?: string; query?: string; notes?: string }) =>
        put<ResearchProject & { error?: string }>(`/research/projects/${encodeURIComponent(id)}`, changes),
      remove: (id: string) => del<{ status?: string; error?: string }>(`/research/projects/${encodeURIComponent(id)}`),
      addFinding: (id: string, title: string, content: string) =>
        post<{ finding?: ResearchFinding; error?: string }>(`/research/projects/${encodeURIComponent(id)}/findings`, { title, content }),
      addSources: (id: string, sources: unknown[]) =>
        post<ResearchProject & { error?: string }>(`/research/projects/${encodeURIComponent(id)}/sources`, { sources }),
      addReport: (id: string, query: string, report: string) =>
        post<ResearchProject & { error?: string }>(`/research/projects/${encodeURIComponent(id)}/reports`, { query, report }),
    },
  },
  voice: {
    synthesize: (text: string, voice = 'af_bella') =>
      fetch(`${BASE}/voice/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice }),
      }).then(res => {
        if (!res.ok) throw new Error('TTS HTTP ' + res.status);
        return res.blob();
      }),
    transcribe: (wavBlob: Blob) =>
      fetch(`${BASE}/voice/transcribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: wavBlob,
      }).then(res => res.json() as Promise<{ text?: string; error?: string }>),
  },
};
