import type { AgentActivitySnapshot, AgentChatMessage, AgentDefinition, AgentListItem, AgentPlan, AgentQuestion, Approval, BackgroundTask, DirItem, EffortLevel, Goal, GoalNotification, GraphData, HardwareData, LibraryArtifact, MarketplaceSkill, MemoryEntry, ModelItem, Overview, PlanTemplate, Project, ProjectArtifact, ProjectKbStatus, ProjectScope, QueueItem, RecentRun, Recommendation, Routine, RunRecord, SetupTask, SkillCommand, SkillMeta, Team, TeamMessage, TeamNote, TeamRun, ToolMeta, TreeNode, VerificationReport, WorkspaceFile } from './types';

const BASE = '/api';

function reportConnection(ok: boolean, message?: string) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(
    new CustomEvent('palimind:connection', { detail: { ok, message } }),
  );
}

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
    const connectionIssue =
      res.status === 401 || res.status === 403 || res.status >= 500;
    if (connectionIssue) {
      reportConnection(
        false,
        res.status === 401 || res.status === 403
          ? 'The local engine needs authentication. Restart PaliMind to refresh its token.'
          : detail,
      );
    }
    throw new Error(`${label} failed: ${detail}`);
  }
  reportConnection(true);
  return (data ?? {}) as T;
}

async function get<T>(path: string, headers?: Record<string, string>): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers, credentials: 'include' });
  return parse<T>(res, `GET ${path}`);
}

async function post<T>(path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    credentials: 'include',
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
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return parse<T>(res, `PATCH ${path}`);
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE', credentials: 'include' });
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
  uploads: {
    create: (name: string, mime: string, data: string) =>
      post<{ upload?: { id: string; name: string; kind: string }; error?: string }>('/uploads', { name, mime, data }),
    list: () => get<{ uploads?: { id: string; name: string; kind: string }[] }>('/uploads'),
    remove: (id: string) => del<{ status?: string }>(`/uploads/${encodeURIComponent(id)}`),
  },
  config: {
    get: (scope = 'field') => get<{ chat_model?: string; embed_model?: string; moe_orchestrator_model?: string; moe_worker_model?: string; moe_sub_mode?: string; persona_name?: string; persona_system_prompt?: string }>(`/config?scope=${scope}`),
    setModel: (modelId: string, scope = 'field') => patch<{ error?: string }>(`/config/model?scope=${scope}`, { model_id: modelId }),
    setEmbedModel: (modelId: string, scope = 'field') => patch<{ error?: string; embed_dim?: number; index_dim?: number; reindex_required?: boolean; message?: string }>(`/config/embed-model?scope=${scope}`, { embed_model: modelId }),
    setMoe: (data: { moe_orchestrator_model?: string; moe_worker_model?: string; moe_sub_mode?: string }, scope = 'field') => patch<{ error?: string }>(`/config/moe?scope=${scope}`, data),
    setPersona: (data: { persona_name?: string; persona_system_prompt?: string }) =>
      patch<{ error?: string; status?: string }>('/config/persona', data),
  },
  desktop: {
    apps: (kind: 'apps' | 'windows' | 'displays' = 'windows') =>
      get<{
        ok: boolean;
        kind?: string;
        items?: Record<string, unknown>[];
        error?: unknown;
      }>(`/desktop/apps?kind=${kind}`),
    health: () =>
      get<{
        ok: boolean;
        ready: boolean;
        enabled: boolean;
        stopped: boolean;
        session_type?: string;
        accessibility?: { state?: string };
        default_allow?: boolean;
      }>('/desktop/health'),
    status: () =>
      get<{
        ok: boolean;
        enabled: boolean;
        error?: unknown;
        status?: Record<string, unknown>;
        summary?: string;
      }>('/desktop/status'),
    session: () =>
      post<{ ok: boolean; session_id?: string | null; status?: Record<string, unknown>; error?: unknown }>(
        '/desktop/session',
        {},
      ),
    stop: () => post<{ ok?: boolean; data?: Record<string, unknown>; error?: unknown }>('/desktop/stop', {}),
    resume: () => post<{ ok?: boolean }>('/desktop/resume', {}),
    audit: (limit = 20) =>
      get<{ ok?: boolean; data?: { entries?: Record<string, unknown>[] } }>(`/desktop/audit?limit=${limit}`),
    screenshot: (body: Record<string, unknown>) =>
      post<{
        ok?: boolean;
        data?: {
          path?: string;
          image?: string;
          width?: number;
          height?: number;
          screenshot_id?: string;
        };
        error?: { code?: string; message?: string; hint?: string };
      }>('/desktop/screenshot', body),
    ask: (body: Record<string, unknown>) =>
      fetch(`${BASE}/desktop/ask`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
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
    removeAll: () => del<{ error?: string; status?: string; deleted?: number }>('/agents/all'),
    tools: () => get<{ tools: Record<string, ToolMeta> }>('/agents/tools'),
    invokeTool: (agentId: string, tool: string, args: Record<string, unknown>) =>
      post<{ tool?: string; output?: string; error?: string }>(
        `/agents/${agentId}/tools/${encodeURIComponent(tool)}/invoke`,
        { args },
      ),
    skills: () => get<{ skills: SkillMeta[] }>('/agents/skills'),
    sections: {
      list: () => get<{ sections: { id: string; name: string; sort_order: number }[] }>('/agents/sections/all'),
      create: (name: string, sortOrder = 0) =>
        post<{ section?: { id: string; name: string }; error?: string }>('/agents/sections/create', {
          name,
          sort_order: sortOrder,
        }),
      rename: (sectionId: string, name: string) =>
        patch<{ section?: { id: string; name: string }; error?: string }>(
          `/agents/sections/${sectionId}`,
          { name },
        ),
      remove: (sectionId: string) => del<{ status?: string }>(`/agents/sections/${sectionId}`),
      assign: (sectionId: string, agentId: string) =>
        post<{ status?: string; error?: string }>(
          sectionId
            ? `/agents/sections/${sectionId}/assign`
            : '/agents/sections/unassign',
          { agent_id: agentId },
        ),
    },
    activity: () => get<AgentActivitySnapshot>('/agents/activity'),
    approvals: () => get<{ approvals: Approval[] }>('/agents/approvals'),
    questions: (agentId = '') =>
      get<{ questions: AgentQuestion[] }>(
        `/agents/questions${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''}`,
      ),
    answer: (agentId: string, questionId: string, answer = '', choice = '') =>
      post<{ status?: string; error?: string }>(`/agents/${agentId}/answer`, {
        question_id: questionId,
        answer,
        choice,
      }),
    setPlan: (agentId: string, runId: string, items: { label: string; status?: string }[]) =>
      post<{ status?: string; error?: string }>(
        `/agents/${agentId}/runs/${encodeURIComponent(runId)}/plan`,
        { items },
      ),
    starters: (agentId: string) =>
      get<{ prompts: string[]; error?: string }>(`/agents/${agentId}/starters`),
    recentRuns: (limit = 30) => get<{ runs: RecentRun[] }>(`/agents/runs/recent?limit=${limit}`),
    recallPreview: (agentId: string, query: string, k = 8) =>
      post<{ entries: MemoryEntry[] }>(`/agents/${agentId}/recall-preview`, { query, k }),
    run: (agentId: string, runId: string) =>
      get<RunRecord & { error?: string }>(`/agents/${agentId}/runs/${encodeURIComponent(runId)}`),
    resumeRun: async (agentId: string, runId: string, input?: string) => {
      const res = await fetch(
        `${BASE}/agents/${agentId}/runs/${encodeURIComponent(runId)}/resume`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(input ? { input } : {}),
        },
      );
      const text = await res.text();
      if (!res.ok) throw new Error(`Resume failed: ${res.status}`);
      return { text };
    },
    validateCron: (schedule: string) => post<{ valid: boolean; error?: string | null }>('/agents/validate-cron', { schedule }),
    memory: (agentId: string, page = 1, perPage = 20) =>
      get<{ entries: MemoryEntry[]; total: number; page: number; per_page: number }>(
        `/agents/${agentId}/memory?page=${page}&per_page=${perPage}`,
      ),
    chat: (agentId: string) => get<{ messages?: AgentChatMessage[] }>(`/agents/${agentId}/chat`),
    clearChat: (agentId: string) => del<{ error?: string; status?: string }>(`/agents/${agentId}/chat`),
    clearSessions: (agentId: string) =>
      del<{ error?: string; status?: string }>(`/agents/${agentId}/sessions`),
    deleteMemoryEntry: (agentId: string, index: number) =>
      del<{ error?: string; status?: string }>(`/agents/${agentId}/memory?index=${index}`),
    clearMemory: (agentId: string) => post<{ error?: string; status?: string }>(`/agents/${agentId}/memory/clear`),
    history: (agentId: string) => get<{ history: RunRecord[] }>(`/agents/${agentId}/history`),
    clearHistory: (agentId: string) =>
      del<{ error?: string; status?: string }>(`/agents/${agentId}/runs`),
    cancel: (agentId: string, runId = '') =>
      post<{ error?: string; status?: string; cancelled?: number }>(
        `/agents/${agentId}/cancel`,
        runId ? { run_id: runId } : undefined,
      ),
    approve: (
      agentId: string,
      approved: boolean,
      correction = '',
      runId = '',
      args?: Record<string, unknown>,
    ) =>
      post<{ error?: string; status?: string }>(`/agents/${agentId}/approve`, {
        approved,
        correction,
        run_id: runId,
        ...(args ? { args } : {}),
      }),
    runNow: (agentId: string, input = 'Run your task.') =>
      post<{ status?: string; error?: string }>(`/agents/${agentId}/run-now`, { input }),
    duplicate: async (agent: AgentListItem) => {
      const payload: Record<string, unknown> = { ...agent };
      for (const key of [
        'id',
        'created_at',
        'running',
        'active_runs',
        'last_run_status',
        'last_run_at',
      ]) {
        delete payload[key];
      }
      payload.name = `${agent.name}-copy`.slice(0, 64);
      payload.display_name = `${agent.display_name || agent.name} copy`;
      payload.webhook_token = '';
      return post<AgentListItem & { error?: string }>('/agents/create', payload);
    },
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
    overview: () => get<Overview>('/agents/overview'),
    inbox: () => get<{ approvals: Approval[]; groups: Record<string, Approval[]> }>('/agents/inbox'),
    alwaysAllow: (agentId: string, tool: string) =>
      post<{ agent?: AgentDefinition; error?: string }>(`/agents/${agentId}/approvals/always-allow`, { tool }),
    revokeAlwaysAllow: (agentId: string, tool: string) =>
      del<{ agent?: AgentDefinition; error?: string }>(
        `/agents/${agentId}/approvals/always-allow/${encodeURIComponent(tool)}`,
      ),
    steer: (agentId: string, text: string, runId = '') =>
      post<{ status?: string; error?: string }>(`/agents/${agentId}/steer`, { text, run_id: runId }),
    pause: (agentId: string) => post<{ status?: string }>(`/agents/${agentId}/pause`),
    resume: (agentId: string) => post<{ status?: string }>(`/agents/${agentId}/resume`),
    workspace: {
      list: (agentId: string, path = '') =>
        get<{ files?: WorkspaceFile[]; path?: string; root?: string; error?: string }>(
          `/agents/${agentId}/workspace${path ? `?path=${encodeURIComponent(path)}` : ''}`,
        ),
      read: (agentId: string, path: string) =>
        get<{ content?: string; binary?: boolean; size?: number; error?: string }>(
          `/agents/${agentId}/workspace/file?path=${encodeURIComponent(path)}`,
        ),
      remove: (agentId: string, path: string) =>
        del<{ deleted?: boolean; error?: string }>(
          `/agents/${agentId}/workspace/file?path=${encodeURIComponent(path)}`,
        ),
    },
  },
  teams: {
    list: () => get<{ teams: Team[]; error?: string }>('/agents/teams'),
    create: (data: Partial<Team>) => post<{ team?: Team; error?: string }>('/agents/teams', data),
    get: (teamId: string) => get<{ team?: Team; error?: string }>(`/agents/teams/${teamId}`),
    update: (teamId: string, changes: Partial<Team>) =>
      patch<{ team?: Team; error?: string }>(`/agents/teams/${teamId}`, changes),
    remove: (teamId: string) => del<{ status?: string; error?: string }>(`/agents/teams/${teamId}`),
    addMember: (teamId: string, agentId: string, role = '', manager = false) =>
      post<{ team?: Team; error?: string }>(`/agents/teams/${teamId}/members`, {
        agent_id: agentId,
        role,
        manager,
      }),
    removeMember: (teamId: string, agentId: string) =>
      del<{ team?: Team; error?: string }>(`/agents/teams/${teamId}/members/${agentId}`),
    setManager: (teamId: string, agentId: string) =>
      post<{ team?: Team; error?: string }>(`/agents/teams/${teamId}/manager`, { agent_id: agentId }),
    messages: (teamId: string, limit = 100, beforeSeq?: number) =>
      get<{ messages: TeamMessage[]; error?: string }>(
        `/agents/teams/${teamId}/messages?limit=${limit}${beforeSeq ? `&before_seq=${beforeSeq}` : ''}`,
      ),
    sendMessage: (teamId: string, content: string) =>
      post<{ message?: TeamMessage; error?: string }>(`/agents/teams/${teamId}/messages`, { content }),
    clearMessages: (teamId: string) =>
      del<{ status?: string; error?: string }>(`/agents/teams/${teamId}/messages`),
    runStream: async (
      teamId: string,
      input: string,
      onEvent: (ev: { type: string; [k: string]: unknown }) => void,
      opts: { mode?: string; interactive?: boolean } = {},
    ): Promise<void> => {
      const res = await fetch(`${BASE}/agents/teams/${teamId}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input, ...opts }),
      });
      if (!res.ok || !res.body) throw new Error(`run team failed: ${res.status}`);
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
    cancel: (teamId: string) => post<{ status?: string; cancelled?: number }>(`/agents/teams/${teamId}/cancel`),
    pause: (teamId: string) => post<{ status?: string }>(`/agents/teams/${teamId}/pause`),
    resume: (teamId: string) => post<{ status?: string }>(`/agents/teams/${teamId}/resume`),
    steer: (teamId: string, text: string, agentId = '') =>
      post<{ status?: string }>(`/agents/teams/${teamId}/steer`, { text, agent_id: agentId }),
    runs: (teamId: string, limit = 30) =>
      get<{ runs: TeamRun[]; error?: string }>(`/agents/teams/${teamId}/runs?limit=${limit}`),
    runDetail: (teamId: string, runId: string) =>
      get<TeamRun & { error?: string }>(`/agents/teams/${teamId}/runs/${runId}`),
    notes: (teamId: string) => get<{ notes: TeamNote[]; error?: string }>(`/agents/teams/${teamId}/notes`),
    addNote: (teamId: string, content: string, label = 'Note') =>
      post<{ entry?: TeamNote; error?: string }>(`/agents/teams/${teamId}/notes`, { content, label }),
    clearNotes: (teamId: string) => del<{ status?: string }>(`/agents/teams/${teamId}/notes`),
  },
  routines: {
    list: () => get<{ routines: Routine[]; error?: string }>('/agents/routines'),
    create: (data: Partial<Routine>) => post<{ routine?: Routine; error?: string }>('/agents/routines', data),
    update: (routineId: string, changes: Partial<Routine>) =>
      patch<{ routine?: Routine; error?: string }>(`/agents/routines/${routineId}`, changes),
    remove: (routineId: string) => del<{ status?: string; error?: string }>(`/agents/routines/${routineId}`),
    run: (routineId: string) =>
      post<{ status?: string; run_id?: string; error?: string }>(`/agents/routines/${routineId}/run`),
    saveFromRun: (runId: string, data: { target_type: string; target_id: string; name: string; schedule?: string | null; run_mode?: string; tool_pack?: string; working_root?: string }) =>
      post<{ routine?: Routine; error?: string }>(`/agents/runs/${runId}/save-as-routine`, data),
  },
  queue: {
    list: (targetType?: string, targetId?: string) =>
      get<{ items: QueueItem[]; error?: string }>(
        `/agents/queue${targetType ? `?target_type=${targetType}&target_id=${encodeURIComponent(targetId || '')}` : ''}`,
      ),
    enqueue: (data: { target_type: string; target_id: string; input: string; priority?: number }) =>
      post<{ item?: QueueItem; error?: string }>('/agents/queue', data),
    update: (itemId: string, status: string) =>
      patch<{ item?: QueueItem; error?: string }>(`/agents/queue/${itemId}`, { status }),
    cancel: (itemId: string) => post<{ item?: QueueItem; error?: string }>(`/agents/queue/${itemId}/cancel`),
  },
  chat: {
    /**
     * Stop a chat stream. The server persists the partial answer before it
     * responds, so a sessions refresh afterwards already contains it.
     */
    stop: (streamId: string) => post<{ status: 'stopped' | 'finished' | 'not_found'; persisted: boolean; session_id: string | null }>(`/chat/stop?stream_id=${encodeURIComponent(streamId)}`),
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
  projects: {
    scope: (projectId: string): ProjectScope => `project:${projectId}`,
    list: (query = '') =>
      get<{ projects: Project[] }>(`/projects${query ? `?q=${encodeURIComponent(query)}` : ''}`),
    create: (data: { name: string; description?: string; workspace_path?: string }) =>
      post<Project>('/projects', data),
    get: (projectId: string) =>
      get<Project & { error?: string }>(`/projects/${encodeURIComponent(projectId)}`),
    update: (
      projectId: string,
      changes: { name?: string; description?: string; workspace_path?: string },
    ) =>
      patch<Project & { error?: string }>(
        `/projects/${encodeURIComponent(projectId)}`,
        changes,
      ),
    remove: (projectId: string) =>
      del<{ status?: string; deleted?: boolean; error?: string }>(
        `/projects/${encodeURIComponent(projectId)}`,
      ),
    open: (projectId: string) =>
      post<{
        project: Project;
        scope: ProjectScope;
        sessions: {
          sessions: { id: string; name: string; messages: { role: string; content: string }[] }[];
          active_session_id: string | null;
        };
      }>(`/projects/${encodeURIComponent(projectId)}/open`),
    sessions: {
      list: (projectId: string) =>
        get<{
          sessions: { id: string; name: string; messages: { role: string; content: string }[] }[];
          active_session_id: string | null;
          error?: string;
        }>(`/projects/${encodeURIComponent(projectId)}/sessions`),
      create: (projectId: string, name = 'New Session') =>
        post<{
          sessions: { id: string; name: string; messages: { role: string; content: string }[] }[];
          active_session_id: string | null;
          error?: string;
        }>(`/projects/${encodeURIComponent(projectId)}/sessions`, { name }),
    },
    kb: {
      status: (projectId: string) =>
        get<ProjectKbStatus & { error?: string }>(
          `/projects/${encodeURIComponent(projectId)}/kb/status`,
        ),
      sync: (projectId: string) =>
        post<{
          status?: string;
          project_id?: string;
          workspace_path?: string;
          indexed_files?: number;
          deleted_files?: number;
          unchanged_files?: number;
          chunks_indexed?: number;
          file_errors?: number;
          errors?: { path: string; error: string }[];
          error?: string;
        }>(`/projects/${encodeURIComponent(projectId)}/kb/sync`),
    },
    artifacts: {
      /** Project artifact library, newest first. */
      library: (projectId: string, includeContent = false) =>
        get<{ artifacts: ProjectArtifact[]; error?: string }>(
          `/projects/${encodeURIComponent(projectId)}/artifacts${
            includeContent ? '?include_content=true' : ''
          }`,
        ),
      list: (projectId: string, includeContent = false) =>
        get<{ artifacts: ProjectArtifact[]; error?: string }>(
          `/projects/${encodeURIComponent(projectId)}/artifacts${
            includeContent ? '?include_content=true' : ''
          }`,
        ),
      get: (projectId: string, artifactId: string, version?: number) =>
        get<ProjectArtifact & { error?: string }>(
          `/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}${
            version != null ? `?version=${version}` : ''
          }`,
        ),
      save: (
        projectId: string,
        data: {
          title?: string;
          type?: string;
          language?: string;
          description?: string;
          content?: string;
          source_path?: string;
          filename?: string;
          session_id?: string;
          message_id?: string;
          source?: string;
          metadata?: Record<string, unknown>;
        },
      ) =>
        post<ProjectArtifact & { error?: string }>(
          `/projects/${encodeURIComponent(projectId)}/artifacts`,
          data,
        ),
      addVersion: (
        projectId: string,
        artifactId: string,
        data: {
          content?: string;
          source_path?: string;
          filename?: string;
          title?: string;
          description?: string;
          metadata?: Record<string, unknown>;
        },
      ) =>
        post<ProjectArtifact & { error?: string }>(
          `/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}/versions`,
          data,
        ),
      remove: (projectId: string, artifactId: string) =>
        del<{ status?: string; deleted?: boolean; error?: string }>(
          `/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}`,
        ),
      /** Download URL for the artifact (defaults to the latest version). */
      exportUrl: (projectId: string, artifactId: string, version?: number) =>
        `${BASE}/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}/export${
          version != null ? `?version=${version}` : ''
        }`,
      exportAs: async (
        projectId: string,
        artifactId: string,
        format: string,
        version?: number,
      ) => {
        const res = await fetch(
          `${BASE}/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}/export`,
          {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ format, version }),
          },
        );
        if (!res.ok) throw new Error(`Export failed: ${res.status}`);
        const blob = await res.blob();
        const disposition = res.headers.get('content-disposition') || '';
        const match = /filename="?([^"]+)"?/.exec(disposition);
        return { blob, filename: match?.[1] || `artifact.${format}` };
      },
    },
  },
  research: {
    approve: (planId: string, plan?: import('./types').ResearchSubTopic[]) =>
      post<{ status?: string; error?: string }>('/research/approve', {
        plan_id: planId,
        plan,
      }),
    cancel: (planId: string) =>
      post<{ status?: string; error?: string }>('/research/cancel', { plan_id: planId }),
  },
  artifacts: {
    list: (q = '', projectId = '', includeContent = false) => {
      const params = new URLSearchParams();
      if (q) params.set('q', q);
      if (projectId) params.set('project_id', projectId);
      if (includeContent) params.set('include_content', 'true');
      const suffix = params.toString();
      return get<{ artifacts: LibraryArtifact[] }>(`/artifacts${suffix ? `?${suffix}` : ''}`);
    },
    get: (artifactId: string) =>
      get<LibraryArtifact & { error?: string }>(
        `/artifacts/${encodeURIComponent(artifactId)}`,
      ),
    save: (data: {
      id?: string;
      title: string;
      type: string;
      language?: string;
      description?: string;
      content: string;
      project_id?: string;
      source?: string;
      session_id?: string;
      message_id?: string;
    }) => post<LibraryArtifact & { error?: string }>('/artifacts', data),
    remove: (artifactId: string) =>
      del<{ status?: string; deleted?: boolean; error?: string }>(
        `/artifacts/${encodeURIComponent(artifactId)}`,
      ),
    saveToKnowledge: (data: {
      title: string;
      content: string;
      project_id?: string;
    }) =>
      post<{
        status?: string;
        path?: string;
        indexed_files?: number | null;
        message?: string;
        error?: string;
      }>('/artifacts/save-to-knowledge', data),
    export: async (artifactId: string, format: string) => {
      const res = await fetch(`${BASE}/artifacts/${encodeURIComponent(artifactId)}/export`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ format }),
      });
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const blob = await res.blob();
      const disposition = res.headers.get('content-disposition') || '';
      const match = /filename="?([^"]+)"?/.exec(disposition);
      return { blob, filename: match?.[1] || `artifact.${format}` };
    },
    exportUrl: (artifactId: string) =>
      `${BASE}/artifacts/${encodeURIComponent(artifactId)}/export`,
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
  agentTasks: {
    deliveries: (status = '', limit = 50) =>
      get<{ deliveries?: Record<string, unknown>[]; error?: string }>(
        `/agents/deliveries?status=${encodeURIComponent(status)}&limit=${limit}`,
      ),
    list: (agentId: string, includeClosed = false) =>
      get<{ tasks?: Record<string, unknown>[]; error?: string }>(
        `/agents/${agentId}/tasks?include_closed=${includeClosed}`,
      ),
    create: (agentId: string, data: { title?: string; input?: string; parent_task_id?: string; priority?: number }) =>
      post<{ task?: Record<string, unknown>; queued?: Record<string, unknown>; error?: string }>(
        `/agents/${agentId}/tasks`,
        data,
      ),
    get: (agentId: string, taskId: string) =>
      get<{ task?: Record<string, unknown>; error?: string }>(`/agents/${agentId}/tasks/${taskId}`),
    update: (agentId: string, taskId: string, changes: Record<string, unknown>) =>
      patch<{ task?: Record<string, unknown>; error?: string }>(`/agents/${agentId}/tasks/${taskId}`, changes),
    remove: (agentId: string, taskId: string) =>
      del<{ deleted?: boolean; error?: string }>(`/agents/${agentId}/tasks/${taskId}`),
    send: (agentId: string, taskId: string, text: string) =>
      post<{ delivery?: Record<string, unknown>; error?: string }>(
        `/agents/${agentId}/tasks/${taskId}/send`,
        { text },
      ),
    stop: (agentId: string, taskId: string) =>
      post<{ task?: Record<string, unknown>; error?: string }>(`/agents/${agentId}/tasks/${taskId}/stop`),
    close: (agentId: string, taskId: string) =>
      post<{ task?: Record<string, unknown>; error?: string }>(`/agents/${agentId}/tasks/${taskId}/close`),
    reopen: (agentId: string, taskId: string) =>
      post<{ task?: Record<string, unknown>; error?: string }>(`/agents/${agentId}/tasks/${taskId}/reopen`),
  },
  channels: {
    list: (includeArchived = true) =>
      get<{ channels?: Record<string, unknown>[]; error?: string }>(`/channels?include_archived=${includeArchived}`),
    create: (data: Record<string, unknown>) =>
      post<{ channel?: Record<string, unknown>; error?: string }>('/channels', data),
    get: (channelId: string) =>
      get<{ channel?: Record<string, unknown>; error?: string }>(`/channels/${channelId}`),
    update: (channelId: string, changes: Record<string, unknown>) =>
      patch<{ channel?: Record<string, unknown>; error?: string }>(`/channels/${channelId}`, changes),
    remove: (channelId: string) => del<{ deleted?: boolean; error?: string }>(`/channels/${channelId}`),
    archive: (channelId: string) => post<{ channel?: Record<string, unknown> }>(`/channels/${channelId}/archive`),
    restore: (channelId: string) => post<{ channel?: Record<string, unknown> }>(`/channels/${channelId}/restore`),
    messages: (channelId: string, limit = 100) =>
      get<{ messages?: Record<string, unknown>[]; error?: string }>(`/channels/${channelId}/messages?limit=${limit}`),
    send: (channelId: string, text: string, opts: { agent_id?: string; reply_to_task_id?: string; operation_id?: string } = {}) =>
      post<{ message?: Record<string, unknown>; task?: Record<string, unknown>; error?: string }>(
        `/channels/${channelId}/messages`,
        { text, ...opts },
      ),
    tasks: (channelId: string) =>
      get<{ tasks?: Record<string, unknown>[]; error?: string }>(`/channels/${channelId}/tasks`),
    stop: (channelId: string, taskId: string) =>
      post<{ task?: Record<string, unknown> }>(`/channels/${channelId}/tasks/${taskId}/stop`),
    reassign: (channelId: string, taskId: string, agentId: string) =>
      post<{ task?: Record<string, unknown> }>(`/channels/${channelId}/tasks/${taskId}/reassign`, { agent_id: agentId }),
    addMember: (channelId: string, agentId: string, role = '') =>
      post<{ member?: Record<string, unknown>; error?: string }>(`/channels/${channelId}/members`, { agent_id: agentId, role }),
    removeMember: (channelId: string, agentId: string) =>
      del<{ removed?: boolean }>(`/channels/${channelId}/members/${agentId}`),
    setLead: (channelId: string, agentId: string) =>
      post<{ channel?: Record<string, unknown> }>(`/channels/${channelId}/lead`, { agent_id: agentId }),
    memories: (channelId: string) =>
      get<{ memories?: Record<string, unknown>[] }>(`/channels/${channelId}/memories`),
    setMemory: (channelId: string, key: string, value: string) =>
      post<{ channel_id?: string; key?: string; value?: string }>(`/channels/${channelId}/memories`, { key, value }),
  },
  providers: {
    list: () => get<{ providers?: Record<string, unknown>[]; models?: Record<string, unknown>[] }>('/providers'),
    models: () => get<{ providers?: Record<string, unknown>[]; models?: Record<string, unknown>[] }>('/providers/models'),
  },
  usage: {
    get: (agentId = '', start = '', end = '') =>
      get<Record<string, unknown>>(
        `/usage?agent_id=${encodeURIComponent(agentId)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
      ),
  },
  visuals: {
    list: (agentId = '') =>
      get<{ visuals: import('./types').VisualReply[] }>(
        `/visuals${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''}`,
      ),
  },
  mcp: {
    servers: () => get<{ servers: Record<string, unknown>[] }>('/mcp/servers'),
    reload: () => post<{ servers?: Record<string, unknown>[]; error?: string }>('/mcp/reload'),
  },
  plugins: {
    list: () => get<{ plugins: Record<string, unknown>[] }>('/plugins'),
    install: (pluginId: string, overwrite = false) =>
      post<{ plugin?: Record<string, unknown>; error?: string }>('/plugins/install', {
        plugin_id: pluginId,
        overwrite,
      }),
    uninstall: (pluginId: string) =>
      del<{ deleted?: boolean; error?: string }>(`/plugins/${pluginId}`),
  },
  office: {
    /** Turn a settled chat artifact into a real DOCX/PPTX download. */
    generate: async (payload: {
      format: 'docx' | 'pptx';
      title: string;
      content?: string;
      slides?: { title: string; bullets: string[] }[];
    }): Promise<{ blob: Blob; filename: string; path: string }> => {
      const res = await fetch(`${BASE}/office/generate`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try {
          const data = (await res.json()) as { detail?: string; error?: string };
          detail = data.detail || data.error || detail;
        } catch {
          // keep the status text
        }
        throw new Error(`Could not create ${payload.format.toUpperCase()}: ${detail}`);
      }
      const disposition = res.headers.get('content-disposition') || '';
      const match = /filename="?([^";]+)"?/i.exec(disposition);
      return {
        blob: await res.blob(),
        filename: match?.[1] || res.headers.get('x-palimind-filename') || `${payload.title}.${payload.format}`,
        path: res.headers.get('x-palimind-path') || '',
      };
    },
  },
  browser: {
    profiles: () => get<{ profiles?: Record<string, unknown>[]; error?: string }>('/browser/profiles'),
    createProfile: (name: string, color = '') =>
      post<{ profile?: Record<string, unknown>; error?: string }>('/browser/profiles', { name, color }),
    removeProfile: (profileId: string) => del<{ deleted?: boolean }>(`/browser/profiles/${profileId}`),
    tabs: (profileId = '', agentId = '') =>
      get<{ tabs?: Record<string, unknown>[]; error?: string }>(`/browser/tabs?profile_id=${encodeURIComponent(profileId)}&agent_id=${encodeURIComponent(agentId)}`),
    state: (agentId = '') =>
      get<import('./types').BrowserState>(`/browser/state${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''}`),
    action: (action: string, payload: Record<string, unknown> = {}) =>
      post<import('./types').BrowserState & { error?: string }>('/browser/action', { action, ...payload }),
    claimControl: (agentId = '', takeoverId = '') =>
      post<{ control?: Record<string, string>; error?: string }>('/browser/control/claim', {
        agent_id: agentId,
        takeover_id: takeoverId,
      }),
    releaseControl: () =>
      post<{ control?: Record<string, string>; error?: string }>('/browser/control/release'),
    frameUrl: (nonce = Date.now(), quality = 70) =>
      `${BASE}/browser/frame?quality=${quality}&t=${nonce}`,
    takeovers: (agentId = '', status = '') =>
      get<{ takeovers?: Record<string, unknown>[]; error?: string }>(`/browser/takeovers?agent_id=${encodeURIComponent(agentId)}&status=${encodeURIComponent(status)}`),
    requestTakeover: (agentId: string, reason: string, tabId = '') =>
      post<{ takeover?: Record<string, unknown>; error?: string }>('/browser/takeovers', { agent_id: agentId, reason, tab_id: tabId }),
    acceptTakeover: (takeoverId: string) =>
      post<{ takeover?: Record<string, unknown>; error?: string }>(`/browser/takeovers/${takeoverId}/accept`, {}),
    resolveTakeover: (takeoverId: string, status = 'completed') =>
      post<{ takeover?: Record<string, unknown>; error?: string }>(`/browser/takeovers/${takeoverId}/resolve`, { status }),
  },
  tasks: {
    list: () => get<{ tasks: import('./types').KanbanTask[] }>('/tasks'),
    create: (task: Partial<import('./types').KanbanTask>) =>
      post<{ task?: import('./types').KanbanTask; error?: string }>('/tasks', task),
    update: (id: string, changes: Partial<import('./types').KanbanTask>) =>
      patch<{ task?: import('./types').KanbanTask; error?: string }>(`/tasks/${encodeURIComponent(id)}`, changes),
    delete: (id: string) => del<{ status?: string }>(`/tasks/${encodeURIComponent(id)}`),
    run: (id: string) =>
      post<{ task?: import('./types').KanbanTask; output?: string; error?: string }>(
        `/tasks/${encodeURIComponent(id)}/run`,
      ),
  },
};
