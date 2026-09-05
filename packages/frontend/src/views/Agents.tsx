import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUp, Square } from 'lucide-react';
import { api } from '../api';
import { formatMarkdown } from '../utils/markdown';
import AgentAvatar from '../components/AgentAvatar';
import CronEditor from '../components/CronEditor';
import { Button } from '../components/ui/button';
import { useConfirm } from '../components/ConfirmDialog';
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

const TAB_META: { id: Tab; label: string; icon: string }[] = [
  { id: 'definition', label: 'Definition', icon: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2|M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8' },
  { id: 'tools', label: 'Tools', icon: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z' },
  { id: 'memory', label: 'Memory', icon: 'M21 5c0 1.66-4 3-9 3S3 6.66 3 5s4-3 9-3 9 1.34 9 3|M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5|M21 12c0 1.66-4 3-9 3s-9-1.34-9-3' },
  { id: 'history', label: 'History', icon: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20|M12 6v6l4 2' },
];

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
  visibility: 'global',
  run_mode: 'on_demand',
  schedule: '',
  watcher_pattern: '',
  max_iterations: 15,
  human_in_loop_threshold: 0.0,
  write_access: false,
  shell_access: false,
  enabled: true,
};

function fmtTime(ts?: number): string {
  if (!ts) return 'never';
  return new Date(ts * 1000).toLocaleString();
}

export default function Agents() {
  const { selectedAgentId, setSelectedAgentId } = useApp();
  const confirm = useConfirm();
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

  // Right-click "Info" in the sidebar opens this agent's config modal.
  useEffect(() => {
    const onOpenConfig = (e: Event) => {
      const agentId = (e as CustomEvent).detail?.agentId as string | undefined;
      if (agentId) {
        setSelectedAgentId(agentId);
        setShowConfig(true);
      }
    };
    window.addEventListener('palimind:open-agent-config', onOpenConfig);
    return () => window.removeEventListener('palimind:open-agent-config', onOpenConfig);
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

  // Deletions from the sidebar context menu refresh the list here too.
  useEffect(() => {
    const onChanged = () => refresh();
    window.addEventListener('palimind:agents-changed', onChanged);
    return () => window.removeEventListener('palimind:agents-changed', onChanged);
  }, [refresh]);

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
    const ok = await confirm('Clear this conversation? The chat log on disk will be deleted.', {
      title: 'Clear Conversation',
      confirmLabel: 'Clear',
      danger: true,
    });
    if (!ok) return;
    try { await api.agents.clearChat(agentId); } catch {}
    setMessagesByAgent(prev => ({ ...prev, [agentId]: [] }));
  }, [confirm]);

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
            <AgentAvatar seed={agentSeed} size={38} />
            <div className="agent-chat-header-info">
              <h2>{selected.name}</h2>
              <span className={`agent-chat-status${agentWorking ? ' working' : ''}`}>
                <span className="agent-chat-status-dot" />
                {agentWorking ? 'active now' : 'online'}
              </span>
            </div>
            <div className="agent-chat-sub">
              <span className="cfg-chip">{selected.model || 'default model'}</span>
              <span className="cfg-chip">{selected.tools.length} tools</span>
              {selected.run_mode !== 'on_demand' && (
                <span className="cfg-chip">{(selected.run_mode || '').replace('_', ' ')}</span>
              )}
              {!selected.enabled && <span className="cfg-chip chip-off">disabled</span>}
            </div>
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
        <div className="agents-detail-empty">
          <div className="agents-empty-title">No agent selected</div>
          <div className="agents-empty-sub">
            Pick an agent from the sidebar to start chatting, or create a new one for a custom task.
          </div>
          <button className="action-btn primary" onClick={() => setCreating(true)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            Create Agent
          </button>
        </div>
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
  const [toolQuery, setToolQuery] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [dirty, setDirty] = useState(false);
  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [memTotal, setMemTotal] = useState(0);
  const [memPage, setMemPage] = useState(1);
  const [history, setHistory] = useState<RunRecord[]>([]);
  const [fields, setFields] = useState<string[]>([]);
  const confirm = useConfirm();

  const patch = (p: Partial<AgentDefinition>) => {
    setDraft(d => ({ ...d, ...p }));
    setDirty(true);
  };

  useEffect(() => {
    api.fields.list().then(d => setFields(d.fields || [])).catch(() => {});
  }, []);

  useEffect(() => {
    api.agents.tools().then(d => setTools(d.tools || {})).catch(() => {});
  }, []);

  const agentId = agent?.id;

  // Fetch memory + history once when opened so tab badges show live counts
  // even before their tab is visited.
  useEffect(() => {
    if (mode !== 'edit' || !agentId) return;
    api.agents.memory(agentId, 1, 20)
      .then(d => { setMemory(d.entries); setMemTotal(d.total); setMemPage(d.page); })
      .catch(() => {});
    api.agents.history(agentId).then(d => setHistory(d.history || [])).catch(() => {});
  }, [mode, agentId]);

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
        else { setMessage('Saved'); setDirty(false); }
      }
    } catch (e) {
      setError(String(e));
    }
    setSaving(false);
  };

  const requestClose = useCallback(async () => {
    if (!dirty) { onCancel(); return; }
    const ok = await confirm('You have unsaved changes — discard them?', {
      title: 'Unsaved Changes',
      confirmLabel: 'Discard',
      danger: true,
    });
    if (ok) onCancel();
  }, [dirty, confirm, onCancel]);

  // Esc closes (with discard guard); Ctrl/Cmd+S saves.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        void requestClose();
      } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        if (!saving && mode === 'edit') void save();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const groupedTools = useMemo(() => {
    const byTier: Record<number, ToolMeta[]> = { 1: [], 2: [], 3: [] };
    const q = toolQuery.trim().toLowerCase();
    for (const t of Object.values(tools)) {
      if (q && !t.id.toLowerCase().includes(q) && !t.description.toLowerCase().includes(q)) continue;
      byTier[t.tier] = byTier[t.tier] || [];
      byTier[t.tier].push(t);
    }
    return byTier;
  }, [tools, toolQuery]);

  const toggleTool = (id: string) => {
    const cur = new Set(draft.tools || []);
    if (cur.has(id)) cur.delete(id); else cur.add(id);
    setDraft(d => ({ ...d, tools: Array.from(cur) }));
    setDirty(true);
  };

  const toggleContextField = (path: string) => {
    const cur = new Set(draft.context_fields || []);
    if (cur.has(path)) cur.delete(path); else cur.add(path);
    setDraft(d => ({ ...d, context_fields: Array.from(cur) }));
    setDirty(true);
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
    const ok = await confirm(`Delete agent "${draft.name}"? This cannot be undone.`, {
      title: 'Delete Agent',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.agents.remove(agentId);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const agentSeed = mode === 'edit' && agent
    ? (agent.color_seed || agent.id + agent.name)
    : `new-agent-${draft.name || 'agent'}`;

  const showFooter = mode === 'create' || tab === 'definition' || tab === 'tools';
  const footerLabel = tab === 'tools'
    ? (saving ? 'Saving...' : 'Save Tools')
    : (saving ? 'Saving...' : (mode === 'create' ? 'Create Agent' : 'Save Changes'));

  return (
    <div className="agent-config-overlay" onClick={requestClose}>
      <div className="agent-config-modal" role="dialog" aria-modal="true" onClick={e => e.stopPropagation()}>
        <div className="agent-config-header">
          <div className="agent-config-heading">
            <AgentAvatar seed={agentSeed} size={36} />
            <div className="agent-config-heading-text">
              <h2>{mode === 'create' ? 'New Agent' : (draft.name || 'Agent')}</h2>
              <span className="agent-config-sub">
                {mode === 'create' ? (
                  'Create a custom agent'
                ) : (
                  <>
                    <span className="cfg-chip">{draft.model || 'default model'}</span>
                    <span className="cfg-chip">{(draft.tools || []).length} tools</span>
                    <span className="cfg-chip">{(draft.run_mode || 'on_demand').replace('_', ' ')}</span>
                    {!draft.enabled && <span className="cfg-chip chip-off">disabled</span>}
                  </>
                )}
              </span>
            </div>
          </div>
          <button className="icon-btn" onClick={requestClose} data-tooltip="Close (Esc)">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {mode === 'edit' && (
          <div className="agent-tabs" role="tablist">
            {TAB_META.map(m => {
              const count =
                m.id === 'tools' ? (draft.tools || []).length
                : m.id === 'memory' ? memTotal
                : m.id === 'history' ? history.length
                : null;
              return (
                <button
                  key={m.id}
                  role="tab"
                  aria-selected={tab === m.id}
                  className={`agent-tab${tab === m.id ? ' active' : ''}`}
                  onClick={() => setTab(m.id)}
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    {m.icon.split('|').map((d, i) => <path key={i} d={d} />)}
                  </svg>
                  {m.label}
                  {count != null && count > 0 && <span className="tab-count">{count}</span>}
                </button>
              );
            })}
          </div>
        )}

        <div className="agent-config-body">
          {tab === 'definition' || mode === 'create' ? (
            <div className="agent-form">
              <section className="agent-config-section">
                <h4 className="agent-section-title">Identity &amp; Persona</h4>
                <label className="agent-field">Name
                  <input value={draft.name || ''} onChange={e => patch({ name: e.target.value })} placeholder="my-agent" autoFocus />
                </label>
                <label className="agent-field">System Prompt
                  <textarea rows={5} value={draft.system_prompt || ''} onChange={e => patch({ system_prompt: e.target.value })} placeholder="You are a helpful agent that..." />
                </label>
              </section>

              <section className="agent-config-section">
                <h4 className="agent-section-title">Model &amp; Behavior</h4>
                <div className="agent-form-grid cols-2">
                  <div className="agent-field">
                    <span className="agent-field-label">Model</span>
                    <ModelPicker value={draft.model || ''} onChange={v => patch({ model: v })} />
                  </div>
                  <div className="agent-field">
                    <span className="agent-field-label">
                      Temperature
                      <span className="range-value">{(draft.temperature ?? 0.2).toFixed(1)}</span>
                    </span>
                    <input
                      type="range"
                      className="range-input"
                      min={0}
                      max={2}
                      step={0.1}
                      value={draft.temperature ?? 0.2}
                      onChange={e => patch({ temperature: parseFloat(e.target.value) })}
                    />
                    <span className="agent-field-hint">Low is precise and repeatable · high is creative.</span>
                  </div>
                </div>
                <div className="agent-field">
                  <span className="agent-field-label">Run Mode</span>
                  <div className="segmented" role="radiogroup" aria-label="Run mode">
                    {([
                      ['on_demand', 'On Demand'],
                      ['scheduled', 'Scheduled'],
                      ['watcher', 'Watcher'],
                    ] as const).map(([val, label]) => (
                      <button
                        type="button"
                        key={val}
                        role="radio"
                        aria-checked={draft.run_mode === val}
                        className={`segment-btn${draft.run_mode === val ? ' active' : ''}`}
                        onClick={() => patch({ run_mode: val })}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                {draft.run_mode === 'scheduled' ? (
                  <div className="agent-field">
                    <span className="agent-field-label">Schedule</span>
                    <CronEditor value={draft.schedule || ''} onChange={v => patch({ schedule: v })} />
                  </div>
                ) : draft.run_mode === 'watcher' ? (
                  <label className="agent-field">Watcher Pattern (glob)
                    <input value={draft.watcher_pattern || ''} placeholder="*.md" onChange={e => patch({ watcher_pattern: e.target.value })} />
                    <span className="agent-field-hint">The agent triggers whenever a matching file changes.</span>
                  </label>
                ) : (
                  <div className="agent-form-grid cols-2">
                    <label className="agent-field">Max Steps (iterations)
                      <input type="number" min="1" value={draft.max_iterations ?? 15} onChange={e => patch({ max_iterations: parseInt(e.target.value) || 1 })} />
                      <span className="agent-field-hint">Tool steps the agent may take before it is forced to answer.</span>
                    </label>
                  </div>
                )}
              </section>

              <section className="agent-config-section">
                <h4 className="agent-section-title">Capabilities &amp; Access</h4>
                <div className="agent-form-grid cols-2">
                  <label className="agent-field">Tier Policy
                    <select value={draft.tier_policy || 'tier1+2'} onChange={e => patch({ tier_policy: e.target.value as AgentDefinition['tier_policy'] })}>
                      <option value="tier1">Tier 1 — read-only</option>
                      <option value="tier1+2">Tier 1 + 2 — write &amp; execute</option>
                      <option value="all">All — incl. Tier 3 privileged</option>
                    </select>
                  </label>
                  <label className="agent-field">Memory Scope
                    <select value={draft.memory_scope || 'none'} onChange={e => patch({ memory_scope: e.target.value as AgentDefinition['memory_scope'] })}>
                      <option value="none">None</option>
                      <option value="session">Session</option>
                      <option value="field">Global</option>
                    </select>
                  </label>
                </div>
                <div className="agent-field">
                  <span className="agent-field-label">Workspace Context — Knowledge Bases the agent can see</span>
                  <div className="context-chips">
                    {fields.length === 0 && <span className="agents-empty">No workspaces added yet.</span>}
                    {fields.map(path => {
                      const on = (draft.context_fields || []).includes(path);
                      return (
                        <button
                          type="button"
                          key={path}
                          title={path}
                          className={`context-chip${on ? ' on' : ''}`}
                          onClick={() => toggleContextField(path)}
                        >
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                          {path.split(/[\\/]/).filter(Boolean).pop()}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="toggle-stack">
                  <label className="toggle-row">
                    <span className="toggle-info">
                      <span className="toggle-title">Write Access</span>
                      <span className="toggle-desc">Allow this agent to create or modify files in its workspaces.</span>
                    </span>
                    <input type="checkbox" checked={!!draft.write_access} onChange={e => patch({ write_access: e.target.checked })} />
                    <span className="switch" aria-hidden="true" />
                  </label>
                  <label className="toggle-row">
                    <span className="toggle-info">
                      <span className="toggle-title">Shell Access</span>
                      <span className="toggle-desc">Allow running shell commands (Tier 3 tools, sandboxed).</span>
                    </span>
                    <input type="checkbox" checked={!!draft.shell_access} onChange={e => patch({ shell_access: e.target.checked })} />
                    <span className="switch" aria-hidden="true" />
                  </label>
                  {mode === 'edit' && (
                    <label className="toggle-row">
                      <span className="toggle-info">
                        <span className="toggle-title">Enabled</span>
                        <span className="toggle-desc">Disabled agents stay configured but cannot be run.</span>
                      </span>
                      <input type="checkbox" checked={!!draft.enabled} onChange={e => patch({ enabled: e.target.checked })} />
                      <span className="switch" aria-hidden="true" />
                    </label>
                  )}
                </div>
              </section>

              <details className="agent-advanced">
                <summary>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                  Advanced
                </summary>
                <div className="agent-form-grid cols-3">
                  <label className="agent-field">Context Budget
                    <input type="number" value={draft.context_budget ?? 8000} onChange={e => patch({ context_budget: parseInt(e.target.value) || 0 })} />
                  </label>
                  <label className="agent-field">Human-in-Loop Threshold
                    <input type="number" step="0.1" min="0" max="1" value={draft.human_in_loop_threshold ?? 0} onChange={e => patch({ human_in_loop_threshold: parseFloat(e.target.value) })} />
                  </label>
                </div>
              </details>
            </div>
          ) : null}

          {tab === 'tools' && (
            <div className="agent-tools">
              <div className="tools-toolbar">
                <input
                  className="tools-search"
                  type="text"
                  placeholder="Search tools..."
                  value={toolQuery}
                  onChange={e => setToolQuery(e.target.value)}
                />
                <span className="tools-count">{(draft.tools || []).length} selected</span>
                <button
                  type="button"
                  className="tool-clear"
                  disabled={(draft.tools || []).length === 0}
                  onClick={() => { setDraft(d => ({ ...d, tools: [] })); setDirty(true); }}
                >
                  Clear
                </button>
              </div>
              {[1, 2, 3].map(tier => {
                const items = groupedTools[tier] || [];
                return (
                  <div key={tier} className="agent-tool-tier">
                    <div className="agent-tool-tier-head">
                      <h4>Tier {tier}</h4>
                      <span className="agent-tool-tier-sub">
                        {tier === 1 ? 'Read-only and safe' : tier === 2 ? 'Writes or executes — may ask for approval' : 'Privileged system access'}
                      </span>
                    </div>
                    {items.length === 0 ? (
                      <div className="agent-tools-tier-empty">
                        {toolQuery ? 'No tools match this search.' : 'No tools registered in this tier.'}
                      </div>
                    ) : (
                      <div className="agent-tool-grid">
                        {items.map(t => (
                          <label
                            key={t.id}
                            className={`agent-tool-check${(draft.tools || []).includes(t.id) ? ' selected' : ''}${t.requires_approval ? ' needs-approval' : ''}`}
                          >
                            <input type="checkbox" checked={(draft.tools || []).includes(t.id)} onChange={() => toggleTool(t.id)} />
                            <span className="agent-tool-name">{t.id}</span>
                            <span className="agent-tool-desc">{t.description}</span>
                            {t.requires_approval && <span className="agent-tool-badge">approval</span>}
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {tab === 'memory' && (
            <div className="agent-memory">
              <div className="agent-memory-header">
                <span className="tools-count">{memTotal} {memTotal === 1 ? 'entry' : 'entries'}</span>
                <button className="action-btn danger-btn compact" onClick={clearMemory} disabled={memTotal === 0}>Clear All</button>
              </div>
              {memory.map((e, i) => (
                <div key={i} className="agent-memory-entry">
                  <div className="agent-memory-meta">
                    <span className={`mem-type mem-${e.type}`}>{e.type}</span>
                    <span className="mem-time">{new Date(e.timestamp).toLocaleString()}</span>
                  </div>
                  <div className="mem-content">{e.content}</div>
                  <button className="icon-btn entry-delete" title="Delete entry" onClick={() => deleteMemEntry((memPage - 1) * 20 + i)}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              ))}
              {memory.length === 0 && (
                <div className="agent-tab-empty">
                  <span className="agent-tab-empty-title">No memory entries</span>
                  <span className="agent-tab-empty-sub">What this agent learns while working will show up here.</span>
                </div>
              )}
              {memTotal > 20 && (
                <div className="agent-memory-pager">
                  <button className="pager-btn" disabled={memPage <= 1} onClick={() => loadMemory(memPage - 1)}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6" /></svg>
                    Prev
                  </button>
                  <span className="pager-page">Page {memPage} of {Math.ceil(memTotal / 20)}</span>
                  <button className="pager-btn" disabled={memPage * 20 >= memTotal} onClick={() => loadMemory(memPage + 1)}>
                    Next
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6" /></svg>
                  </button>
                </div>
              )}
            </div>
          )}

          {tab === 'history' && (
            <div className="agent-history">
              {history.slice().reverse().map((r, i) => (
                <div key={r.run_id || i} className="agent-history-entry">
                  <div className="agent-history-meta">
                    <span className={`agent-status ${r.status}`}>{r.status}</span>
                    <span className="hist-duration">{r.duration}s</span>
                    <span className="mem-time">{fmtTime(r.timestamp)}</span>
                  </div>
                  <div className="agent-history-input">{r.input}</div>
                  <details className="agent-history-output-wrap">
                    <summary>Output</summary>
                    <div className="agent-history-output">{r.output}</div>
                  </details>
                </div>
              ))}
              {history.length === 0 && (
                <div className="agent-tab-empty">
                  <span className="agent-tab-empty-title">No runs yet</span>
                  <span className="agent-tab-empty-sub">Every run — manual, scheduled or watcher-triggered — is recorded here.</span>
                </div>
              )}
            </div>
          )}
        </div>

        {showFooter && (
          <div className="agent-config-footer">
            <div className="agent-config-footer-msg">
              {dirty && (
                <span className="agent-unsaved">
                  <span className="agent-unsaved-dot" />
                  Unsaved changes
                </span>
              )}
              {!dirty && message && <span className="agent-form-msg">{message}</span>}
              {error && <span className="agent-form-msg error">{error}</span>}
              {!dirty && !message && !error && (
                <span className="agent-footer-hint">
                  {mode === 'edit' ? 'Ctrl+S save · Esc close' : 'Esc to cancel'}
                </span>
              )}
            </div>
            <div className="agent-config-footer-actions">
              {mode === 'edit' && tab === 'definition' && (
                <button className="action-btn danger-btn compact" onClick={deleteAgent}>Delete</button>
              )}
              <button className="action-btn ghost" onClick={requestClose}>Cancel</button>
              <button
                className="action-btn primary"
                onClick={save}
                disabled={saving || (mode === 'edit' && !dirty)}
                title={mode === 'edit' ? 'Ctrl+S' : undefined}
              >
                {footerLabel}
              </button>
            </div>
          </div>
        )}
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
          <span className="agent-thinking-text">working</span>
        )}
        {msg.content && (
          <div className="agent-msg-bubble agent">
            <div className="agent-msg-rich" dangerouslySetInnerHTML={{ __html: formatMarkdown(msg.content) }} />
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
          {open && <pre>{String(ev.result || '')}</pre>}
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
      <div className="agent-input-pill">
        <textarea
          ref={taRef}
          rows={1}
          placeholder={`Message ${agentName}...`}
          value={value}
          onChange={e => { setValue(e.target.value); adjustHeight(); }}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
        />
        <div className="agent-input-footer">
          <span className="agent-input-hint">Enter to send · Shift+Enter for new line</span>
          <Button
            type="button"
            variant="default"
            size="icon"
            className={`send-btn${disabled ? ' animating-stop' : ''}`}
            disabled={!disabled && !value.trim()}
            onClick={() => {
              if (disabled) onStop(agentId);
              else send();
            }}
            title={disabled ? 'Stop generation' : 'Send message'}
          >
            {disabled ? (
              <Square className="stop-icon" aria-hidden="true" />
            ) : (
              <ArrowUp className="send-icon" aria-hidden="true" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
