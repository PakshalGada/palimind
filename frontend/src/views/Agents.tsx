import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';
import { formatMarkdown } from '../utils/markdown';
import AgentAvatar from '../components/AgentAvatar';
import { useApp } from '../AppContext';
import type { AgentDefinition, AgentListItem, MemoryEntry, ModelItem, RunRecord, ToolMeta } from '../types';

interface StepEvent {
  type: string;
  [k: string]: unknown;
}

interface ChatMessage {
  role: 'user' | 'agent';
  content: string;
  steps: StepEvent[];
  pending: boolean;
  waiting: { tool: string; args: unknown } | null;
  error: string;
  timestamp: number;
}

type Tab = 'definition' | 'tools' | 'memory' | 'history';

const EMPTY_DEF: Partial<AgentDefinition> = {
  name: '',
  system_prompt: '',
  model: '',
  temperature: 0.2,
  context_budget: 8000,
  tools: [],
  tier_policy: 'tier1+2',
  memory_scope: 'field',
  context_fields: [],
  visibility: 'field',
  run_mode: 'on_demand',
  schedule: '',
  watcher_pattern: '',
  max_iterations: 8,
  human_in_loop_threshold: 0.0,
  write_access: false,
  shell_access: false,
  enabled: true,
};

function fmtTime(ts?: number): string {
  if (!ts) return 'never';
  return new Date(ts * 1000).toLocaleString();
}

function fmtClock(ts?: number): string {
  if (!ts) return '';
  const ms = ts < 1e12 ? ts * 1000 : ts;
  return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function Agents() {
  const { selectedAgentId, setSelectedAgentId } = useApp();
  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [messagesByAgent, setMessagesByAgent] = useState<Record<string, ChatMessage[]>>({});
  const [showConfig, setShowConfig] = useState(false);
  const [creating, setCreating] = useState(false);
  const [listError, setListError] = useState('');

  const notifyChanged = useCallback(() => {
    window.dispatchEvent(new CustomEvent('palimind:agents-changed'));
  }, []);

  useEffect(() => {
    const onNew = () => setCreating(true);
    window.addEventListener('palimind:new-agent', onNew);
    return () => window.removeEventListener('palimind:new-agent', onNew);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await api.agents.list();
      if (data.agents) {
        setAgents(data.agents);
        if (!selectedAgentId && data.agents.length > 0) {
          setSelectedAgentId(data.agents[0].id);
        }
      }
      setListError('');
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedAgentId]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { notifyChanged(); }, [notifyChanged]); // sync sidebar once mounted

  // Load the persisted conversation for the selected agent so chats that
  // happened in PaliSpace (@mention) or in earlier sessions stay visible.
  useEffect(() => {
    if (!selectedAgentId) return;
    let cancelled = false;
    api.agents.chat(selectedAgentId).then(d => {
      if (cancelled || !d.messages) return;
      setMessagesByAgent(prev => {
        if (prev[selectedAgentId] && prev[selectedAgentId].some(m => m.pending)) return prev;
        return {
          ...prev,
          [selectedAgentId]: d.messages!.map(m => ({
            role: m.role as 'user' | 'agent',
            content: m.content,
            steps: [],
            pending: false,
            waiting: null,
            error: '',
            timestamp: m.timestamp * 1000,
          })),
        };
      });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [selectedAgentId]);

  const selected = agents.find(a => a.id === selectedAgentId) || null;
  const messages = selectedAgentId ? (messagesByAgent[selectedAgentId] || []) : [];
  const agentWorking = messages.length > 0 && messages[messages.length - 1].role === 'agent' && messages[messages.length - 1].pending;
  const agentSeed = selected ? (selected.color_seed || selected.id + selected.name) : '';

  const sendMessage = useCallback(async (agentId: string, text: string) => {
    const now = Date.now();
    const userMsg: ChatMessage = { role: 'user', content: text, steps: [], pending: false, waiting: null, error: '', timestamp: now };
    const agentMsg: ChatMessage = { role: 'agent', content: '', steps: [], pending: true, waiting: null, error: '', timestamp: now + 1 };

    setMessagesByAgent(prev => ({
      ...prev,
      [agentId]: [...(prev[agentId] || []), userMsg, agentMsg],
    }));

    await api.agents.runStream(agentId, text, undefined, (ev: StepEvent) => {
      setMessagesByAgent(prev => {
        const msgs = [...(prev[agentId] || [])];
        if (msgs.length === 0) return prev;
        const lastIdx = msgs.length - 1;
        const last = msgs[lastIdx];
        if (last.role !== 'agent') return prev;

        const updated = { ...last, waiting: null as ChatMessage['waiting'] };
        switch (ev.type) {
          case 'agent:waiting_for_human':
            updated.waiting = { tool: String(ev.tool || ''), args: ev.args };
            updated.steps = [...updated.steps, ev];
            break;
          case 'agent:thought':
          case 'agent:tool_call':
          case 'agent:tool_result':
            updated.steps = [...updated.steps, ev];
            break;
          case 'agent:completed':
            updated.content = String(ev.output || '');
            updated.pending = false;
            break;
          case 'error':
            updated.error = String(ev.text || 'Unknown error');
            updated.pending = false;
            break;
        }
        msgs[lastIdx] = updated;
        return { ...prev, [agentId]: msgs };
      });
    });

    setMessagesByAgent(prev => {
      const msgs = [...(prev[agentId] || [])];
      const last = msgs[msgs.length - 1];
      if (last && last.role === 'agent' && last.pending) {
        msgs[msgs.length - 1] = { ...last, pending: false, error: last.error || 'Run ended' };
      }
      return { ...prev, [agentId]: msgs };
    });
  }, []);

  const stopAgent = useCallback(async (agentId: string) => {
    await api.agents.cancel(agentId);
  }, []);

  const clearConversation = useCallback(async (agentId: string) => {
    if (!window.confirm('Clear this conversation? The chat log on disk will be deleted.')) return;
    try { await api.agents.clearChat(agentId); } catch {}
    setMessagesByAgent(prev => ({ ...prev, [agentId]: [] }));
  }, []);

  return (
    <div className="agents-view">
      {listError && (
        <div className="agents-error-banner" title={listError}>
          Agents API unreachable — restart the app so the backend picks up the new endpoints.
          <span className="agents-error-detail">{listError}</span>
        </div>
      )}

      {creating ? (
        <AgentConfigModal
          mode="create"
          initial={EMPTY_DEF}
          onDone={() => { setCreating(false); refresh(); notifyChanged(); }}
          onCancel={() => setCreating(false)}
        />
      ) : showConfig && selected ? (
        <AgentConfigModal
          mode="edit"
          agent={selected}
          onDone={() => { setShowConfig(false); refresh(); notifyChanged(); }}
          onCancel={() => setShowConfig(false)}
        />
      ) : selected ? (
        <div className="agent-chat-pane">
          <div className="agent-chat-header">
            <AgentAvatar seed={agentSeed} thinking={agentWorking} size={38} />
            <div className="agent-chat-header-info">
              <h2>{selected.name}</h2>
              <span className={`agent-chat-status${agentWorking ? ' working' : ''}`}>
                <span className="agent-chat-status-dot" />
                {agentWorking ? 'active now' : 'online'}
              </span>
            </div>
            <span className="agent-chat-sub">{selected.model || 'default model'} · {selected.tools.length} tools</span>
            <button className="icon-btn" data-tooltip="Clear conversation" onClick={() => clearConversation(selected.id)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
              </svg>
            </button>
            <button className="icon-btn" data-tooltip="Configure" onClick={() => setShowConfig(true)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
            </button>
          </div>

          <AgentChatThread messages={messages} agentSeed={agentSeed} agentId={selected.id} />

          <AgentChatInput
            agentId={selected.id}
            agentName={selected.name}
            onSend={sendMessage}
            onStop={stopAgent}
            disabled={agentWorking}
          />
        </div>
      ) : (
        <div className="agents-detail-empty">Select an agent to start chatting, or create a new one.</div>
      )}
    </div>
  );
}

/* ── Model Picker ────────────────────────────────────────────────── */

function ModelPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  const fetchModels = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.models.list();
      if (data.models) setModels(data.models);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => {
    if (open && models.length === 0) fetchModels();
  }, [open, models.length, fetchModels]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const filtered = query.trim()
    ? models.filter(m => {
        const q = query.toLowerCase();
        return m.model_id?.toLowerCase().includes(q) ||
               m.display_name?.toLowerCase().includes(q) ||
               m.family?.toLowerCase().includes(q);
      })
    : models;

  return (
    <div className="model-picker" ref={ref}>
      <button type="button" className="model-picker-btn" onClick={() => setOpen(!open)}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M9 9h6M9 13h6M9 17h3" />
        </svg>
        <span className="model-picker-label">{value || 'Default (global model)'}</span>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div className="model-picker-dropdown">
          <input
            type="text"
            className="model-picker-search"
            placeholder="Search models..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            autoFocus
          />
          <div className="model-picker-list">
            <div
              className={`model-picker-item${!value ? ' selected' : ''}`}
              onClick={() => { onChange(''); setOpen(false); }}
            >
              <span>Default (use global model)</span>
            </div>
            {loading && <div className="model-picker-loading">Loading models...</div>}
            {!loading && filtered.map(m => (
              <div
                key={m.model_id}
                className={`model-picker-item${value === m.model_id ? ' selected' : ''}`}
                onClick={() => { onChange(m.model_id); setOpen(false); }}
              >
                <span className="model-picker-name">{m.display_name || m.model_id}</span>
                <span className="model-picker-meta">{m.parameter_size || ''} {m.size_gb ? `${m.size_gb}GB` : ''}</span>
              </div>
            ))}
            {!loading && filtered.length === 0 && models.length > 0 && (
              <div className="model-picker-loading">No models found</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Config Modal (create + edit) ────────────────────────────────── */

function AgentConfigModal({
  mode, initial, agent, onDone, onCancel,
}: {
  mode: 'create' | 'edit';
  initial?: Partial<AgentDefinition>;
  agent?: AgentListItem;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<Partial<AgentDefinition>>(initial || agent || EMPTY_DEF);
  const [tab, setTab] = useState<Tab>('definition');
  const [tools, setTools] = useState<Record<string, ToolMeta>>({});
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [memTotal, setMemTotal] = useState(0);
  const [memPage, setMemPage] = useState(1);
  const [history, setHistory] = useState<RunRecord[]>([]);
  const [fields, setFields] = useState<string[]>([]);

  useEffect(() => {
    api.fields.list().then(d => setFields(d.fields || [])).catch(() => {});
  }, []);

  useEffect(() => {
    api.agents.tools().then(d => setTools(d.tools || {})).catch(() => {});
  }, []);

  const agentId = agent?.id;

  useEffect(() => {
    if (mode === 'edit' && agentId && tab === 'memory') {
      api.agents.memory(agentId, 1, 20).then(d => { setMemory(d.entries); setMemTotal(d.total); setMemPage(d.page); });
    }
  }, [mode, agentId, tab]);

  useEffect(() => {
    if (mode === 'edit' && agentId && tab === 'history') {
      api.agents.history(agentId).then(d => setHistory(d.history || []));
    }
  }, [mode, agentId, tab]);

  const save = async () => {
    setSaving(true);
    setError('');
    setMessage('');
    const payload = { ...draft, schedule: draft.schedule || null, watcher_pattern: draft.watcher_pattern || null };
    try {
      if (mode === 'create') {
        const res = await api.agents.create(payload);
        if (res.error) setError(res.error);
        else { onDone(); return; }
      } else if (agentId) {
        const res = await api.agents.update(agentId, payload);
        if (res.error) setError(res.error);
        else { setMessage('Saved'); }
      }
    } catch (e) {
      setError(String(e));
    }
    setSaving(false);
  };

  const groupedTools = useMemo(() => {
    const byTier: Record<number, ToolMeta[]> = { 1: [], 2: [], 3: [] };
    for (const t of Object.values(tools)) {
      byTier[t.tier] = byTier[t.tier] || [];
      byTier[t.tier].push(t);
    }
    return byTier;
  }, [tools]);

  const toggleTool = (id: string) => {
    const cur = new Set(draft.tools || []);
    if (cur.has(id)) cur.delete(id); else cur.add(id);
    setDraft(d => ({ ...d, tools: Array.from(cur) }));
  };

  const toggleContextField = (path: string) => {
    const cur = new Set(draft.context_fields || []);
    if (cur.has(path)) cur.delete(path); else cur.add(path);
    setDraft(d => ({ ...d, context_fields: Array.from(cur) }));
  };

  const loadMemory = async (page: number) => {
    if (!agentId) return;
    const data = await api.agents.memory(agentId, page, 20);
    setMemory(data.entries);
    setMemTotal(data.total);
    setMemPage(data.page);
  };

  const deleteMemEntry = async (index: number) => {
    if (!agentId) return;
    try {
      await api.agents.deleteMemoryEntry(agentId, index);
      await loadMemory(memPage);
    } catch {}
  };

  const clearMemory = async () => {
    if (!agentId) return;
    await api.agents.clearMemory(agentId);
    await loadMemory(1);
  };

  const deleteAgent = async () => {
    if (!agentId) return;
    if (!window.confirm(`Delete agent "${draft.name}"? This cannot be undone.`)) return;
    try {
      await api.agents.remove(agentId);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="agent-config-overlay" onClick={onCancel}>
      <div className="agent-config-modal" onClick={e => e.stopPropagation()}>
        <div className="agent-config-header">
          <h2>{mode === 'create' ? 'New Agent' : draft.name || 'Agent'}</h2>
          <button className="icon-btn" onClick={onCancel} data-tooltip="Close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {mode === 'edit' && (
          <div className="agent-tabs">
            {(['definition', 'tools', 'memory', 'history'] as Tab[]).map(t => (
              <button key={t} className={`agent-tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
        )}

        <div className="agent-config-body">
          {tab === 'definition' || mode === 'create' ? (
            <div className="agent-form">
              {mode === 'create' && (
                <label className="agent-field">Name
                  <input value={draft.name || ''} onChange={e => setDraft({ ...draft, name: e.target.value })} placeholder="my-agent" autoFocus />
                </label>
              )}
              <label className="agent-field">System Prompt
                <textarea rows={4} value={draft.system_prompt || ''} onChange={e => setDraft({ ...draft, system_prompt: e.target.value })} placeholder="You are a helpful agent that..." />
              </label>
              <div className="agent-form-grid cols-2">
                <div className="agent-field">
                  <span className="agent-field-label">Model</span>
                  <ModelPicker value={draft.model || ''} onChange={v => setDraft({ ...draft, model: v })} />
                </div>
                <label className="agent-field">Run Mode
                  <select value={draft.run_mode || 'on_demand'} onChange={e => setDraft({ ...draft, run_mode: e.target.value as AgentDefinition['run_mode'] })}>
                    <option value="on_demand">On Demand</option>
                    <option value="scheduled">Scheduled</option>
                    <option value="watcher">Watcher</option>
                  </select>
                </label>
              </div>
              {draft.run_mode === 'scheduled' && (
                <label className="agent-field">Cron Schedule
                  <input value={draft.schedule || ''} placeholder="*/15 * * * *" onChange={e => setDraft({ ...draft, schedule: e.target.value })} />
                </label>
              )}
              {draft.run_mode === 'watcher' && (
                <label className="agent-field">Watcher Pattern (glob)
                  <input value={draft.watcher_pattern || ''} placeholder="*.md" onChange={e => setDraft({ ...draft, watcher_pattern: e.target.value })} />
                </label>
              )}

              <div className="agent-field">
                <span className="agent-field-label">Workspace Context (PaliSpaces the agent can see)</span>
                <div className="agent-context-fields">
                  {fields.length === 0 && <span className="agents-empty">No workspaces added yet.</span>}
                  {fields.map(path => (
                    <label key={path} className="agent-tool-check">
                      <input
                        type="checkbox"
                        checked={(draft.context_fields || []).includes(path)}
                        onChange={() => toggleContextField(path)}
                      />
                      <span className="agent-tool-name">{path.split(/[\\/]/).filter(Boolean).pop()}</span>
                      <span className="agent-tool-desc" title={path}>{path}</span>
                    </label>
                  ))}
                </div>
              </div>

              <details className="agent-advanced">
                <summary>Advanced</summary>
                <div className="agent-form-grid cols-3">
                  <label className="agent-field">Temperature
                    <input type="number" step="0.1" min="0" max="2" value={draft.temperature ?? 0.2} onChange={e => setDraft({ ...draft, temperature: parseFloat(e.target.value) })} />
                  </label>
                  <label className="agent-field">Context Budget
                    <input type="number" value={draft.context_budget ?? 8000} onChange={e => setDraft({ ...draft, context_budget: parseInt(e.target.value) || 0 })} />
                  </label>
                  <label className="agent-field">Max Iterations
                    <input type="number" min="1" value={draft.max_iterations ?? 8} onChange={e => setDraft({ ...draft, max_iterations: parseInt(e.target.value) || 1 })} />
                  </label>
                  <label className="agent-field">Tier Policy
                    <select value={draft.tier_policy || 'tier1+2'} onChange={e => setDraft({ ...draft, tier_policy: e.target.value as AgentDefinition['tier_policy'] })}>
                      <option value="tier1">Tier 1</option>
                      <option value="tier1+2">Tier 1 + 2</option>
                      <option value="all">All (incl. Tier 3)</option>
                    </select>
                  </label>
                  <label className="agent-field">Memory Scope
                    <select value={draft.memory_scope || 'none'} onChange={e => setDraft({ ...draft, memory_scope: e.target.value as AgentDefinition['memory_scope'] })}>
                      <option value="none">None</option>
                      <option value="session">Session</option>
                      <option value="field">Field</option>
                    </select>
                  </label>
                  <label className="agent-field">Visibility
                    <select value={draft.visibility || 'field'} onChange={e => setDraft({ ...draft, visibility: e.target.value as AgentDefinition['visibility'] })}>
                      <option value="field">Field</option>
                      <option value="global">Global</option>
                    </select>
                  </label>
                </div>
                <div className="agent-form-grid cols-2">
                  <label className="agent-field">Human-in-Loop Threshold
                    <input type="number" step="0.1" min="0" max="1" value={draft.human_in_loop_threshold ?? 0} onChange={e => setDraft({ ...draft, human_in_loop_threshold: parseFloat(e.target.value) })} />
                  </label>
                  <div className="agent-form-checks">
                    <label><input type="checkbox" checked={!!draft.write_access} onChange={e => setDraft({ ...draft, write_access: e.target.checked })} /> Write Access</label>
                    <label><input type="checkbox" checked={!!draft.shell_access} onChange={e => setDraft({ ...draft, shell_access: e.target.checked })} /> Shell Access</label>
                    {mode === 'edit' && (
                      <label><input type="checkbox" checked={!!draft.enabled} onChange={e => setDraft({ ...draft, enabled: e.target.checked })} /> Enabled</label>
                    )}
                  </div>
                </div>
              </details>

              <div className="agent-form-actions">
                <button className="action-btn primary" onClick={save} disabled={saving}>{saving ? 'Saving...' : (mode === 'create' ? 'Create Agent' : 'Save Changes')}</button>
                <button className="action-btn ghost" onClick={onCancel}>Cancel</button>
                <span className="agent-form-msg">{message}</span>
                {error && <span className="agent-form-msg error">{error}</span>}
                {mode === 'edit' && (
                  <button className="action-btn danger-btn compact" onClick={deleteAgent}>Delete</button>
                )}
              </div>
            </div>
          ) : null}

          {tab === 'tools' && (
            <div className="agent-tools">
              {[1, 2, 3].map(tier => (
                <div key={tier} className="agent-tool-tier">
                  <h4>Tier {tier}</h4>
                  <div className="agent-tool-grid">
                    {(groupedTools[tier] || []).map(t => (
                      <label key={t.id} className={`agent-tool-check${t.requires_approval ? ' needs-approval' : ''}`}>
                        <input type="checkbox" checked={(draft.tools || []).includes(t.id)} onChange={() => toggleTool(t.id)} />
                        <span className="agent-tool-name">{t.id}</span>
                        <span className="agent-tool-desc">{t.description}</span>
                        {t.requires_approval && <span className="agent-tool-badge">approval</span>}
                      </label>
                    ))}
                  </div>
                </div>
              ))}
              <div className="agent-form-actions">
                <button className="action-btn" onClick={save} disabled={saving}>{saving ? 'Saving...' : 'Save Tools'}</button>
              </div>
            </div>
          )}

          {tab === 'memory' && (
            <div className="agent-memory">
              <div className="agent-memory-header">
                <span>{memTotal} entries</span>
                <button className="action-btn danger-btn compact" onClick={clearMemory}>Clear All</button>
              </div>
              {memory.map((e, i) => (
                <div key={i} className="agent-memory-entry">
                  <div className="agent-memory-meta">
                    <span className={`mem-type mem-${e.type}`}>{e.type}</span>
                    <span className="mem-time">{new Date(e.timestamp).toLocaleString()}</span>
                  </div>
                  <div className="mem-content">{e.content}</div>
                  <button className="icon-btn" title="Delete entry" onClick={() => deleteMemEntry((memPage - 1) * 20 + i)}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              ))}
              {memory.length === 0 && <div className="agents-empty">No memory entries.</div>}
              {memTotal > 20 && (
                <div className="agent-memory-pager">
                  <button className="icon-btn" disabled={memPage <= 1} onClick={() => loadMemory(memPage - 1)}>Prev</button>
                  <span>{memPage}</span>
                  <button className="icon-btn" disabled={memPage * 20 >= memTotal} onClick={() => loadMemory(memPage + 1)}>Next</button>
                </div>
              )}
            </div>
          )}

          {tab === 'history' && (
            <div className="agent-history">
              {history.slice().reverse().map((r, i) => (
                <div key={i} className="agent-history-entry">
                  <div className="agent-history-meta">
                    <span className={`agent-status ${r.status}`}>{r.status}</span>
                    <span className="mem-time">{fmtTime(r.timestamp)} · {r.duration}s</span>
                  </div>
                  <div className="agent-history-input">{r.input}</div>
                  <div className="agent-history-output">{r.output}</div>
                </div>
              ))}
              {history.length === 0 && <div className="agents-empty">No run history yet.</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Chat Thread ─────────────────────────────────────────────────── */

function AgentChatThread({
  messages, agentSeed, agentId,
}: {
  messages: ChatMessage[];
  agentSeed: string;
  agentId: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="agent-chat-messages" ref={scrollRef}>
      {messages.length === 0 && (
        <div className="agent-chat-empty">Send a message to start working with this agent.</div>
      )}
      {messages.map((msg, i) => (
        <ChatMessageItem key={i} msg={msg} agentSeed={agentSeed} agentId={agentId} />
      ))}
    </div>
  );
}

function ChatMessageItem({
  msg, agentSeed, agentId,
}: {
  msg: ChatMessage;
  agentSeed: string;
  agentId: string;
}) {
  if (msg.role === 'user') {
    return (
      <div className="agent-msg user">
        <div className="agent-msg-bubble user">
          <span className="agent-msg-text">{msg.content}</span>
          <span className="agent-msg-meta">
            <span className="agent-msg-time">{fmtClock(msg.timestamp)}</span>
            <svg className="msg-tick" width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
              <path d="M9.5 16.5 5 12l1.4-1.4 3.1 3.1 8-8L19 7.1l-9.5 9.4z" />
              <path d="M9.5 20.5 5 16l1.4-1.4 3.1 3.1 8-8L19 10.1l-9.5 10.4z" />
            </svg>
          </span>
        </div>
      </div>
    );
  }
  return (
    <div className="agent-msg agent">
      <AgentAvatar seed={agentSeed} thinking={msg.pending} size={30} />
      <div className="agent-msg-body">
        {msg.steps.length > 0 && (
          <details className="agent-msg-chain">
            <summary>Reasoning ({msg.steps.length} steps)</summary>
            <div className="agent-msg-chain-body">
              {msg.steps.map((s, i) => <StepItem key={i} ev={s} />)}
            </div>
          </details>
        )}
        {msg.pending && !msg.content && !msg.error && (
          <div className="agent-thinking">
            <AgentAvatar seed={agentSeed} thinking size={26} />
            <span className="agent-thinking-text">typing…</span>
          </div>
        )}
        {msg.content && (
          <div className="agent-msg-bubble agent">
            <div className="agent-msg-rich" dangerouslySetInnerHTML={{ __html: formatMarkdown(msg.content) }} />
            <span className="agent-msg-meta">
              <span className="agent-msg-time">{fmtClock(msg.timestamp)}</span>
            </span>
          </div>
        )}
        {msg.error && <div className="agent-msg-error">{msg.error}</div>}
        {msg.waiting && <ApprovalCard agentId={agentId} tool={msg.waiting.tool} args={msg.waiting.args} />}
      </div>
    </div>
  );
}

function StepItem({ ev }: { ev: StepEvent }) {
  const [open, setOpen] = useState(false);
  switch (ev.type) {
    case 'agent:thought':
      return <div className="agent-step-thought">{String(ev.text || '')}</div>;
    case 'agent:tool_call':
      return (
        <div className="agent-step-toolcall" onClick={() => setOpen(!open)}>
          <span className="tool-pill">{String(ev.tool)}</span>
          <span className="tool-args-toggle">{open ? 'hide' : 'show'} args</span>
          {open && <pre>{JSON.stringify(ev.args, null, 2)}</pre>}
        </div>
      );
    case 'agent:tool_result':
      return (
        <div className="agent-step-toolresult" onClick={() => setOpen(!open)}>
          <span className="tool-result-label">tool result {open ? '-' : '+'}</span>
          {open && <pre>{String(ev.result || '').slice(0, 2000)}</pre>}
        </div>
      );
    case 'agent:waiting_for_human':
      return <div className="agent-step-waiting">waiting for human approval</div>;
    default:
      return null;
  }
}

function ApprovalCard({
  agentId, tool, args,
}: {
  agentId: string;
  tool: string;
  args: unknown;
}) {
  const [correction, setCorrection] = useState('');
  return (
    <div className="agent-waiting-card">
      <div className="agent-waiting-title">Awaiting approval — {tool}</div>
      {args != null && <pre>{JSON.stringify(args, null, 2)}</pre>}
      <input value={correction} placeholder="Optional correction..." onChange={e => setCorrection(e.target.value)} />
      <div className="agent-waiting-btns">
        <button className="action-btn" onClick={() => api.agents.approve(agentId, true)}>Approve</button>
        <button className="action-btn danger-btn" onClick={() => api.agents.approve(agentId, false, correction)}>Reject</button>
      </div>
    </div>
  );
}

/* ── Chat Input ──────────────────────────────────────────────────── */

function AgentChatInput({
  agentId, agentName, onSend, onStop, disabled,
}: {
  agentId: string;
  agentName: string;
  onSend: (agentId: string, text: string) => void;
  onStop: (agentId: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState('');
  const taRef = useRef<HTMLTextAreaElement>(null);

  const adjustHeight = () => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  };

  useEffect(() => { adjustHeight(); }, [value]);

  const send = () => {
    if (!value.trim() || disabled) return;
    onSend(agentId, value.trim());
    setValue('');
    requestAnimationFrame(() => { taRef.current?.focus(); adjustHeight(); });
  };

  return (
    <div className="agent-chat-input">
      <textarea
        ref={taRef}
        rows={1}
        placeholder={`Message ${agentName}...`}
        value={value}
        onChange={e => { setValue(e.target.value); adjustHeight(); }}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
      />
      {disabled ? (
        <button className="agent-chat-stop" onClick={() => onStop(agentId)} data-tooltip="Stop">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <rect x="4" y="4" width="16" height="16" rx="2" ry="2" />
          </svg>
        </button>
      ) : (
        <button className="agent-chat-send" onClick={send} disabled={!value.trim()} data-tooltip="Send">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="19" x2="12" y2="5" />
            <polyline points="5 12 12 5 19 12" />
          </svg>
        </button>
      )}
    </div>
  );
}
