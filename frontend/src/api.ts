import type { AgentDefinition, AgentListItem, DirItem, GlanceSession, GraphData, HardwareData, MemoryEntry, ModelItem, Recommendation, RunRecord, ToolMeta, TreeNode } from './types';

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

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  return parse<T>(res, `GET ${path}`);
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
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
    list: () => get<{ sessions: { id: string; name: string; messages: { role: string; content: string; sources?: string[] }[] }[]; active_session_id: string | null; error?: string }>('/sessions'),
    new: (name: string) => post<{ error?: string; sessions: unknown[]; active_session_id: string }>('/sessions/new', { name }),
    setActive: (sessionId: string) => post<{ error?: string; sessions: unknown[]; active_session_id: string }>('/sessions/set_active', { session_id: sessionId }),
    remove: (sessionId: string) => post<{ error?: string; sessions: unknown[]; active_session_id: string }>('/sessions/remove', { session_id: sessionId }),
  },
  sync: () => post<{ status: string; indexed_files?: number; deleted_files?: number; error?: string }>('/update'),
  files: {
    tree: () => get<{ tree?: TreeNode[]; error?: string }>('/files/tree'),
    treeSub: (path: string) => get<{ children?: TreeNode[]; error?: string }>(`/files/tree/sub?path=${encodeURIComponent(path)}`),
  },
  config: {
    get: () => get<{ chat_model?: string; moe_orchestrator_model?: string; moe_worker_model?: string; moe_sub_mode?: string; persona_name?: string; persona_system_prompt?: string }>('/config'),
    setModel: (modelId: string) => patch<{ error?: string }>('/config/model', { model_id: modelId }),
    setMoe: (data: { moe_orchestrator_model?: string; moe_worker_model?: string; moe_sub_mode?: string }) => patch<{ error?: string }>('/config/moe', data),
    setPersona: (data: { persona_name?: string; persona_system_prompt?: string }) =>
      patch<{ error?: string; status?: string }>('/config/persona', data),
  },
  settings: {
    opencodeKey: {
      status: () => get<{ configured: boolean; masked?: string | null }>('/settings/opencode-key'),
      save: (key: string) => post<{ status?: string; error?: string }>('/settings/opencode-key', { key }),
      remove: () => del<{ status?: string; error?: string }>('/settings/opencode-key'),
    },
  },
  agents: {
    list: () => get<{ agents?: AgentListItem[]; error?: string }>('/agents'),
    create: (defn: Partial<AgentDefinition>) => post<AgentListItem & { error?: string }>('/agents/create', defn),
    update: (agentId: string, changes: Partial<AgentDefinition>) =>
      patch<AgentListItem & { error?: string }>(`/agents/${agentId}`, changes),
    remove: (agentId: string) => del<{ error?: string; status?: string }>(`/agents/${agentId}`),
    tools: () => get<{ tools: Record<string, ToolMeta> }>('/agents/tools'),
    memory: (agentId: string, page = 1, perPage = 20) =>
      get<{ entries: MemoryEntry[]; total: number; page: number; per_page: number }>(
        `/agents/${agentId}/memory?page=${page}&per_page=${perPage}`,
      ),
    deleteMemoryEntry: (agentId: string, index: number) =>
      del<{ error?: string; status?: string }>(`/agents/${agentId}/memory?index=${index}`),
    clearMemory: (agentId: string) => post<{ error?: string; status?: string }>(`/agents/${agentId}/memory/clear`),
    history: (agentId: string) => get<{ history: RunRecord[] }>(`/agents/${agentId}/history`),
    cancel: (agentId: string) => post<{ error?: string; status?: string }>(`/agents/${agentId}/cancel`),
    approve: (agentId: string, approved: boolean, correction = '') =>
      post<{ error?: string; status?: string }>(`/agents/${agentId}/approve`, { approved, correction }),
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
  },
  cookbook: {
    hardware: () => get<HardwareData & { error?: string }>('/cookbook/hardware'),
    recommendations: (top = 10) => get<{ recommendations?: Recommendation[] }>(`/cookbook/recommendations?top=${top}`),
  },
  graph: {
    get: () => get<GraphData & { error?: string }>('/document/graph'),
    rebuild: () => post<{ error?: string }>('/document/graph/rebuild'),
  },
  fs: {
    list: (path?: string) => get<{ current_path: string; parent_path?: string; items: DirItem[]; error?: string }>(`/fs/list${path ? `?path=${encodeURIComponent(path)}` : ''}`),
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
  palivision: {
    sessions: () => get<{ sessions: GlanceSession[] }>('/palivision/sessions'),
    analyze: (body: unknown) =>
      fetch(`${BASE}/palivision/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    saveSession: (body: unknown) => post<{ status?: string }>('/palivision/session/save', body),
    deleteSession: (id: string) => del<{ status?: string }>(`/palivision/session/${id}`),
    updateMemory: (body: unknown) => post<{ status?: string }>('/palivision/memory/update', body),
  },
};
