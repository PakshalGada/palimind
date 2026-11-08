import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Clock,
  Copy,
  FileText,
  MessageSquareX,
  Play,
  Shield,
  Trash2,
  User,
  Wrench,
  X,
} from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../AppContext';
import AgentAvatar from '../../components/AgentAvatar';
import CronEditor from '../../components/CronEditor';
import { useConfirm } from '../../components/ConfirmDialog';
import type {
  AgentDefinition,
  AgentListItem,
  AgentReasoningEvent,
  MemoryEntry,
  RunRecord,
  SkillMeta,
  ToolMeta,
} from '../../types';
import { formatMarkdown } from '../../utils/markdown';
import { stepsFromTrace } from '../../components/activity/adaptRun';
import { formatToolDuration } from '../../components/activity/model';
import { Icon } from '../../components/activity/icons';
import { getToolDefinition } from '../../components/activity/toolRegistry';
import ToolPlayground from './ToolPlayground';
import {
  Badge,
  Button,
  Chip,
  EmptyState,
  Field,
  SegmentedControl,
  Select,
  Spinner,
  TextArea,
  TextInput,
  Toggle,
} from '../../ui/primitives';
import AvatarCustomizer from './AvatarCustomizer';
import ModelPicker from './ModelPicker';
import { fmtTime, type InspectorSection } from './types';
import {
  AUTONOMY_OPTIONS,
  KNOWLEDGE_OPTIONS,
  MEMORY_OPTIONS,
  PERSONALITY_PRESETS,
  SHELL_TOOLS,
  WRITE_TOOLS,
  composeSystemPrompt,
  defaultKnowledgeScope,
  slugify,
  uniqueHandle,
} from './options';

const PAGE_SIZE = 20;

const SECTIONS: { id: InspectorSection; label: string; icon: typeof User }[] = [
  { id: 'identity', label: 'Identity', icon: User },
  { id: 'instructions', label: 'Instructions', icon: FileText },
  { id: 'capabilities', label: 'Capabilities', icon: Wrench },
  { id: 'autonomy', label: 'Autonomy', icon: Shield },
  { id: 'schedule', label: 'Schedule', icon: Clock },
  { id: 'knowledge', label: 'Knowledge & memory', icon: BookOpen },
  { id: 'runs', label: 'Runs & memory', icon: Activity },
  { id: 'danger', label: 'Danger zone', icon: AlertTriangle },
];

function tierTone(tier: number): 'success' | 'warn' | 'danger' {
  if (tier >= 3) return 'danger';
  if (tier === 2) return 'warn';
  return 'success';
}

function tierRisk(tier: number): string {
  if (tier >= 3) return 'high risk';
  if (tier === 2) return 'medium';
  return 'safe';
}

function RunTraceTimeline({ trace }: { trace: AgentReasoningEvent[] }) {
  const steps = stepsFromTrace(trace);

  if (steps.length === 0) {
    return <span className="ax-run__trace-empty">No tool calls recorded.</span>;
  }

  return (
    <div className="assistant-ui-elements ax-run__timeline">
      <details open>
        <summary>
          {steps.length} tool step{steps.length === 1 ? '' : 's'}
        </summary>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, paddingTop: 4 }}>
          {steps.map((step) => {
            const definition = getToolDefinition(step.name);
            return (
              <div key={step.id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                <Icon name={definition.icon} size={13} />
                <span>{definition.done}</span>
                {step.status === 'error' && <span style={{ color: 'var(--act-error)' }}>Failed</span>}
                {step.durationMs != null && (
                  <span className="act-tabular" style={{ marginInlineStart: 'auto', opacity: 0.6 }}>
                    {formatToolDuration(step.durationMs)}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </details>
      <details className="ax-run__raw">
        <summary>Raw trace</summary>
        {trace.map((ev, j) => (
          <div key={j} className={`ax-trace-step ax-trace-step--${ev.type.replace(':', '-')}`}>
            <span className="ax-trace-step__type">{ev.type.replace('agent:', '')}</span>
            <span className="ax-trace-step__text">
              {ev.type === 'agent:tool_call'
                ? `${ev.tool}(${JSON.stringify(ev.args ?? {})})`
                : ev.type === 'agent:tool_result'
                  ? String(ev.result ?? '')
                  : ev.type === 'agent:thought'
                    ? ev.text
                    : 'text' in ev
                      ? String(ev.text)
                      : ''}
            </span>
          </div>
        ))}
      </details>
    </div>
  );
}

export default function Inspector({
  agent,
  onSaved,
  onDeleted,
  onClose,
  initialSection = 'identity',
}: {
  agent: AgentListItem;
  onSaved: () => void;
  onDeleted: () => void;
  onClose: () => void;
  initialSection?: InspectorSection;
}) {
  const { addToast, setSelectedAgentId, refreshSessions } = useApp();
  const confirm = useConfirm();

  const [section, setSection] = useState<InspectorSection>(initialSection);
  const [draft, setDraft] = useState<Partial<AgentDefinition>>(agent);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [handleTouched, setHandleTouched] = useState(false);

  const [tools, setTools] = useState<Record<string, ToolMeta>>({});
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [fieldPaths, setFieldPaths] = useState<string[]>([]);
  const [otherAgents, setOtherAgents] = useState<AgentListItem[]>([]);
  const [toolQuery, setToolQuery] = useState('');

  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [memTotal, setMemTotal] = useState(0);
  const [memPage, setMemPage] = useState(1);
  const [history, setHistory] = useState<RunRecord[]>([]);
  const [openTrace, setOpenTrace] = useState<string | null>(null);
  const [traceData, setTraceData] = useState<AgentReasoningEvent[]>([]);
  const [traceLoading, setTraceLoading] = useState(false);
  const traceReqRef = useRef<string | null>(null);

  // Reset only when switching agents; refreshes of the same agent keep edits.
  useEffect(() => {
    setDraft(agent);
    setDirty(false);
    setMessage('');
    setError('');
    setSection(initialSection);
    setHandleTouched(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent.id]);

  const loadMemory = useCallback(
    async (page: number) => {
      try {
        let data = await api.agents.memory(agent.id, page, PAGE_SIZE);
        // Deleting the last entry on the last page leaves that page empty.
        if (data.entries.length === 0 && data.total > 0 && page > 1) {
          data = await api.agents.memory(agent.id, Math.ceil(data.total / PAGE_SIZE), PAGE_SIZE);
        }
        setMemory(data.entries);
        setMemTotal(data.total);
        setMemPage(data.page);
      } catch {
        // best effort
      }
    },
    [agent.id],
  );

  const loadHistory = useCallback(async () => {
    try {
      const data = await api.agents.history(agent.id);
      setHistory(data.history || []);
    } catch {
      // best effort
    }
  }, [agent.id]);

  useEffect(() => {
    void loadMemory(1);
    void loadHistory();
  }, [loadMemory, loadHistory]);

  useEffect(() => {
    if (section !== 'runs') return;
    void loadMemory(1);
    void loadHistory();
  }, [section, loadMemory, loadHistory]);

  useEffect(() => {
    api.agents
      .tools()
      .then((d) => setTools(d.tools || {}))
      .catch(() => {});
    api.agents
      .skills()
      .then((d) => setSkills(d.skills || []))
      .catch(() => {});
    api.fields
      .list()
      .then((d) => setFieldPaths(d.fields || []))
      .catch(() => {});
    api.agents
      .list()
      .then((d) => setOtherAgents(d.agents || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') void requestClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty]);

  const patch = (p: Partial<AgentDefinition>) => {
    setDraft((d) => ({ ...d, ...p }));
    setDirty(true);
    setMessage('');
    setError('');
  };

  const existingHandles = useMemo(
    () => otherAgents.filter((a) => a.id !== agent.id).map((a) => a.name),
    [otherAgents, agent.id],
  );

  const displayName = (draft.display_name || draft.name || '').trim();
  const handle = (draft.name || '').trim();
  const scope = draft.knowledge_scope || defaultKnowledgeScope();
  const autonomy = draft.autonomy_level || 'semi';
  const memoryMode = draft.memory_mode || 'private';
  const isSharedMemory = memoryMode === 'shared';

  const changeDisplayName = (value: string) => {
    const next: Partial<AgentDefinition> = { display_name: value };
    if (!handleTouched) next.name = uniqueHandle(value, existingHandles);
    patch(next);
  };

  const changeHandle = (value: string) => {
    setHandleTouched(true);
    patch({ name: slugify(value) === 'agent' && !value.trim() ? '' : value.toLowerCase().replace(/[^\w-]+/g, '-').slice(0, 64) });
  };

  const setScope = (p: Partial<AgentDefinition['knowledge_scope']>) =>
    patch({ knowledge_scope: { ...scope, ...p } });

  const toggleExtraField = (path: string) => {
    const cur = new Set(scope.extra_fields || []);
    if (cur.has(path)) cur.delete(path);
    else cur.add(path);
    setScope({ extra_fields: Array.from(cur) });
  };

  const toggleTool = (id: string) => {
    const cur = new Set(draft.tools || []);
    if (cur.has(id)) cur.delete(id);
    else cur.add(id);
    const selected = Array.from(cur)
      .map((toolId) => tools[toolId])
      .filter(Boolean);
    const hasTier3 = selected.some((t) => t.tier >= 3);
    const hasTier2 = selected.some((t) => t.tier >= 2);
    const requiresWrite = selected.some((t) => WRITE_TOOLS.includes(t.id));
    const requiresShell = selected.some((t) => SHELL_TOOLS.includes(t.id));
    const next: Partial<AgentDefinition> = { tools: Array.from(cur) };
    if (requiresWrite) next.write_access = true;
    if (requiresShell) next.shell_access = true;
    if (hasTier3) {
      next.write_access = true;
      next.shell_access = true;
      next.tier_policy = 'all';
    } else if (hasTier2 && (draft.tier_policy === 'tier1' || !draft.tier_policy)) {
      next.tier_policy = 'tier1+2';
    }
    patch(next);
  };

  const toggleSkill = (id: string) => {
    const cur = new Set(draft.skills || []);
    if (cur.has(id)) cur.delete(id);
    else cur.add(id);
    patch({ skills: Array.from(cur) });
  };

  const groupedTools = useMemo(() => {
    const byTier: Record<number, ToolMeta[]> = { 1: [], 2: [], 3: [] };
    const q = toolQuery.trim().toLowerCase();
    for (const t of Object.values(tools)) {
      if (q && !t.id.toLowerCase().includes(q) && !t.description.toLowerCase().includes(q)) continue;
      (byTier[t.tier] ||= []).push(t);
    }
    return byTier;
  }, [tools, toolQuery]);

  const selectedTools = useMemo(
    () => (draft.tools || []).map((id) => tools[id]).filter(Boolean),
    [draft.tools, tools],
  );

  const approvalTools = useMemo(() => {
    if (autonomy === 'off') return [];
    return (draft.tools || [])
      .map((id) => tools[id])
      .filter(Boolean)
      .filter((t) => {
        if (autonomy === 'supervised') return true;
        if (autonomy === 'high') return t.tier >= 3;
        return t.tier >= 2 || t.requires_approval;
      });
  }, [autonomy, draft.tools, tools]);

  const blockedTools = useMemo(() => {
    return (draft.tools || [])
      .map((id) => tools[id])
      .filter(Boolean)
      .filter((t) => {
        if (t.tier >= 3 && draft.tier_policy !== 'all') return true;
        if (t.tier === 2 && (draft.tier_policy === 'tier1' || !draft.tier_policy)) return true;
        if (['write_file', 'search_replace'].includes(t.id) && !draft.write_access) return true;
        if (['run_python', 'run_shell'].includes(t.id) && !draft.shell_access) return true;
        return false;
      });
  }, [draft.tools, draft.tier_policy, draft.write_access, draft.shell_access, tools]);

  const requestClose = async () => {
    if (dirty) {
      const ok = await confirm('Discard unsaved changes?', {
        title: 'Discard changes',
        confirmLabel: 'Discard',
        danger: true,
      });
      if (!ok) return;
    }
    onClose();
  };

  const save = async () => {
    if (!/^[\w-]{1,64}$/.test(handle)) {
      setError('Handle must be 1–64 characters: letters, digits, underscore or dash.');
      setSection('identity');
      return;
    }
    if (!displayName) {
      setError('Display name is required.');
      setSection('identity');
      return;
    }
    if (scope.mode === 'project' && !scope.primary_field) {
      setError('Choose a primary knowledge base for the project scope.');
      setSection('knowledge');
      return;
    }
    if (draft.run_mode === 'scheduled' && !draft.schedule) {
      setError('Set a cron schedule before saving a scheduled agent.');
      setSection('schedule');
      return;
    }
    if (draft.run_mode === 'watcher' && !draft.watcher_pattern) {
      setError('Set a watcher pattern before saving a watcher agent.');
      setSection('schedule');
      return;
    }
    setSaving(true);
    setError('');
    setMessage('');
    const payload: Partial<AgentDefinition> = {
      ...draft,
      name: handle,
      display_name: displayName,
      system_prompt: composeSystemPrompt(draft),
      knowledge_scope: scope,
      schedule: draft.run_mode === 'scheduled' ? draft.schedule || null : null,
      watcher_pattern: draft.run_mode === 'watcher' ? draft.watcher_pattern || null : null,
    };
    try {
      const res = await api.agents.update(agent.id, payload);
      if (res.error) setError(res.error);
      else {
        setDirty(false);
        setMessage('Saved');
        onSaved();
        addToast('Agent settings saved');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setSaving(false);
  };

  const remove = async () => {
    const ok = await confirm(
      `Delete agent "${displayName || handle}"? This removes its memory, chats and run history.`,
      { title: 'Delete agent', confirmLabel: 'Delete', danger: true },
    );
    if (!ok) return;
    try {
      await api.agents.remove(agent.id);
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const clearChat = async () => {
    const ok = await confirm('Clear this agent’s entire conversation history?', {
      title: 'Clear conversation',
      confirmLabel: 'Clear',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.agents.clearSessions(agent.id);
      await refreshSessions();
      addToast('Conversation cleared');
    } catch {
      setError('Could not clear the conversation.');
    }
  };

  const clearMemory = async () => {
    const extra = isSharedMemory
      ? 'This clears the shared memory pool for every agent using it. '
      : '';
    const ok = await confirm(`${extra}Clear all memory entries?`, {
      title: 'Clear memory',
      confirmLabel: 'Clear',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.agents.clearMemory(agent.id);
      await loadMemory(1);
    } catch {
      setError('Could not clear memory.');
    }
  };

  const runNow = async () => {
    try {
      await api.agents.runNow(agent.id);
      addToast('Agent run started');
      onSaved();
    } catch {
      addToast('Could not start the agent run');
    }
  };

  const duplicate = async () => {
    try {
      const res = await api.agents.duplicate(agent);
      if (res.error) {
        setError(res.error);
        return;
      }
      addToast('Agent duplicated');
      onSaved();
      if (res.id) setSelectedAgentId(res.id);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const loadTrace = async (runId: string) => {
    if (openTrace === runId) {
      traceReqRef.current = null;
      setOpenTrace(null);
      return;
    }
    traceReqRef.current = runId;
    setOpenTrace(runId);
    setTraceLoading(true);
    setTraceData([]);
    let trace: AgentReasoningEvent[] = [];
    try {
      const rec = await api.agents.run(agent.id, runId);
      trace = rec.trace || [];
    } catch {
      trace = [];
    }
    // A slower response for a previously opened run must not overwrite this one.
    if (traceReqRef.current !== runId) return;
    setTraceData(trace);
    setTraceLoading(false);
  };

  const deleteMemEntry = async (index: number) => {
    try {
      await api.agents.deleteMemoryEntry(agent.id, index);
      await loadMemory(memPage);
    } catch {
      // ignore
    }
  };

  const clearHistory = async () => {
    const ok = await confirm('Delete all recorded runs for this agent?', {
      title: 'Clear run history',
      confirmLabel: 'Clear',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.agents.clearHistory(agent.id);
      setHistory([]);
    } catch {
      setError('Could not clear run history.');
    }
  };

  const webhookUrl = `${typeof window !== 'undefined' ? window.location.origin : ''}/api/agents/hooks/${agent.webhook_token || draft.webhook_token || ''}`;
  const status = agent.running
    ? `Working · ${agent.active_runs || 1} run${(agent.active_runs || 1) === 1 ? '' : 's'}`
    : !agent.enabled
      ? 'Disabled'
      : draft.run_mode === 'scheduled'
        ? 'Scheduled'
        : draft.run_mode === 'watcher'
          ? 'Watcher'
          : draft.run_mode === 'webhook'
            ? 'Webhook'
            : 'Idle';

  return (
    <div className="am-overlay" onMouseDown={() => void requestClose()}>
      <div
        className="am-panel ax-settings"
        role="dialog"
        aria-modal="true"
        aria-label={`${displayName || handle} settings`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* hero */}
        <header className="ax-settings__hero">
          <AgentAvatar
            config={draft.avatar_config}
            type={draft.avatar_type === 'upload' ? 'upload' : 'bot'}
            upload={draft.avatar_upload}
            size={64}
          />
          <div className="ax-settings__hero-id">
            <div className="ax-settings__hero-name">{displayName || 'Untitled agent'}</div>
            <div className="ax-settings__hero-handle">
              @{handle || 'handle'}
              {draft.title ? ` · ${draft.title}` : ''}
            </div>
            <div className="ax-settings__hero-meta">
              <Badge tone={agent.running ? 'accent' : agent.enabled ? 'muted' : 'warn'}>{status}</Badge>
              {dirty && <span className="ax-unsaved">Unsaved changes</span>}
            </div>
          </div>
          <div className="ax-settings__hero-actions">
            <Button size="sm" onClick={() => void runNow()}>
              <Play size={13} /> Run now
            </Button>
            <Button size="sm" onClick={() => void duplicate()}>
              <Copy size={13} /> Duplicate
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => patch({ enabled: !draft.enabled })}
              title={draft.enabled ? 'Disable agent' : 'Enable agent'}
            >
              {draft.enabled ? 'Disable' : 'Enable'}
            </Button>
            <button className="ui-icon-btn" onClick={() => void requestClose()} aria-label="Close settings">
              <X size={16} />
            </button>
          </div>
        </header>

        <div className="ax-settings__body">
          <nav className="ax-settings__rail" aria-label="Agent settings sections">
            {SECTIONS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                className={`ax-settings__rail-btn${section === id ? ' is-active' : ''}`}
                onClick={() => setSection(id)}
              >
                <Icon size={14} />
                <span>{label}</span>
              </button>
            ))}
          </nav>

          <div className="ax-settings__content">
            {section === 'identity' && (
              <div className="ax-form">
                <div className="ax-form__grid">
                  <Field label="Display name" hint="Shown in lists and chat.">
                    <TextInput
                      value={draft.display_name || ''}
                      onChange={(e) => changeDisplayName(e.target.value)}
                      autoFocus
                    />
                  </Field>
                  <Field label="Handle" hint="Unique @mention and filename. Lowercase, no spaces.">
                    <TextInput
                      value={draft.name || ''}
                      onChange={(e) => changeHandle(e.target.value)}
                    />
                  </Field>
                </div>
                <Field label="Title / role">
                  <TextInput
                    value={draft.title || ''}
                    onChange={(e) => patch({ title: e.target.value })}
                    placeholder="Research Analyst"
                  />
                </Field>
                <Field label="Short description" hint="1–2 sentences shown in lists.">
                  <TextArea
                    rows={2}
                    value={draft.description || ''}
                    onChange={(e) => patch({ description: e.target.value })}
                  />
                </Field>
                <details className="ax-advanced" open>
                  <summary>Avatar</summary>
                  <AvatarCustomizer value={draft} onChange={(p) => patch(p)} />
                </details>
                <Field label="Personality / style">
                  <div className="ax-chips">
                    {PERSONALITY_PRESETS.map((p) => (
                      <button
                        key={p}
                        type="button"
                        className={`ax-pickchip${draft.personality_style === p ? ' is-on' : ''}`}
                        onClick={() => patch({ personality_style: draft.personality_style === p ? '' : p })}
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                  <TextArea
                    rows={3}
                    value={draft.personality_style || ''}
                    onChange={(e) => patch({ personality_style: e.target.value })}
                  />
                </Field>
              </div>
            )}

            {section === 'instructions' && (
              <div className="ax-form">
                <Field label="Primary goal / standing mission">
                  <TextArea
                    rows={3}
                    value={draft.goal || ''}
                    onChange={(e) => patch({ goal: e.target.value })}
                  />
                </Field>
                <Field label="Custom instructions" hint="Detailed behavior, constraints and output format.">
                  <TextArea
                    rows={8}
                    value={draft.custom_instructions || ''}
                    onChange={(e) => patch({ custom_instructions: e.target.value })}
                  />
                </Field>
                <Field label="Effective system prompt" hint="Composed from goal + instructions + personality + description.">
                  <pre className="ax-settings__prompt">{composeSystemPrompt(draft) || 'No instructions yet.'}</pre>
                </Field>
                <div className="ax-form__grid">
                  <Field label="Model" hint="Empty uses the workspace default.">
                    <ModelPicker value={draft.model || ''} onChange={(v) => patch({ model: v })} />
                  </Field>
                  <Field label={`Temperature · ${(draft.temperature ?? 0.2).toFixed(1)}`}>
                    <input
                      type="range"
                      className="ax-range"
                      min={0}
                      max={2}
                      step={0.1}
                      value={draft.temperature ?? 0.2}
                      onChange={(e) => patch({ temperature: parseFloat(e.target.value) })}
                    />
                  </Field>
                </div>
                <Field label="Reasoning effort">
                  <Select
                    value={draft.reasoning_effort || 'auto'}
                    onChange={(e) =>
                      patch({ reasoning_effort: e.target.value as AgentDefinition['reasoning_effort'] })
                    }
                  >
                    <option value="off">Off</option>
                    <option value="auto">Auto — adaptive</option>
                    <option value="minimal">Minimal</option>
                    <option value="standard">Standard</option>
                    <option value="high">High</option>
                    <option value="max">Max</option>
                  </Select>
                </Field>
                <Field label="Planning mode">
                  <SegmentedControl<AgentDefinition['planning_mode']>
                    value={(draft.planning_mode || 'off') as AgentDefinition['planning_mode']}
                    onChange={(v) => patch({ planning_mode: v })}
                    options={[
                      { value: 'off', label: 'Off' },
                      { value: 'review', label: 'Review' },
                      { value: 'auto', label: 'Auto' },
                    ]}
                  />
                </Field>
                <Field label="Success criteria" hint="Used by verification and goal tracking.">
                  <TextArea
                    rows={2}
                    value={draft.success_criteria || ''}
                    onChange={(e) => patch({ success_criteria: e.target.value })}
                  />
                </Field>
                <details className="ax-advanced">
                  <summary>Advanced</summary>
                  <div className="ax-form__grid">
                    <Field label="Context budget">
                      <TextInput
                        type="number"
                        min={1000}
                        max={200000}
                        value={draft.context_budget ?? 8000}
                        onChange={(e) => patch({ context_budget: parseInt(e.target.value) || 1000 })}
                      />
                    </Field>
                    <Field label="Orchestration">
                      <Select
                        value={draft.orchestration || 'off'}
                        onChange={(e) =>
                          patch({ orchestration: e.target.value as AgentDefinition['orchestration'] })
                        }
                      >
                        <option value="off">Off — single agent</option>
                        <option value="fan_out">Fan-out</option>
                        <option value="arena">Arena</option>
                      </Select>
                    </Field>
                  </div>
                  {draft.orchestration && draft.orchestration !== 'off' && (
                    <Field label="Parallel agents" hint="Maximum 8.">
                      <TextInput
                        type="number"
                        min={1}
                        max={8}
                        value={draft.orchestration_agents ?? 0}
                        onChange={(e) =>
                          patch({
                            orchestration_agents: Math.max(0, Math.min(8, parseInt(e.target.value) || 0)),
                          })
                        }
                      />
                    </Field>
                  )}
                </details>
              </div>
            )}

            {section === 'capabilities' && (
              <div className="ax-tools">
                <section className="ax-form__section">
                  <h4 className="ax-form__title">Tool pack</h4>
                  <Field label="Pack" hint="Narrows which tools this agent may call. Auto allows every tier-appropriate tool.">
                    <Select
                      value={draft.tool_pack || 'auto'}
                      onChange={(e) => patch({ tool_pack: e.target.value as AgentDefinition['tool_pack'] })}
                    >
                      <option value="auto">Auto — all tier-appropriate tools</option>
                      <option value="research">Research</option>
                      <option value="code">Code</option>
                      <option value="data">Data</option>
                      <option value="web">Web</option>
                      <option value="desktop">Computer use — desktop tools</option>
                      <option value="custom">Custom — only pinned tools</option>
                    </Select>
                  </Field>
                  <h4 className="ax-form__title">Access gates</h4>
                  <Toggle
                    title="Write access"
                    description="Create or modify files in the primary knowledge base."
                    checked={!!draft.write_access}
                    onChange={(v) => patch({ write_access: v })}
                  />
                  <Toggle
                    title="Shell access"
                    description="Run sandboxed Python and shell commands."
                    checked={!!draft.shell_access}
                    onChange={(v) => patch({ shell_access: v })}
                  />
                  <Toggle
                    title="Desktop access"
                    description="Observe Linux apps through the accessibility tree."
                    checked={!!draft.desktop_access}
                    onChange={(v) =>
                      patch(v ? { desktop_access: true } : { desktop_access: false, desktop_control: false })
                    }
                  />
                  <Toggle
                    title="Desktop control"
                    description="Click, type and launch apps; mutating actions need approval."
                    checked={!!draft.desktop_control}
                    onChange={(v) => patch(v ? { desktop_control: true, desktop_access: true } : { desktop_control: false })}
                  />
                  <Toggle
                    title="Self-critique"
                    description="Run a reflection pass that reviews and improves the answer."
                    checked={!!draft.self_critique}
                    onChange={(v) => patch({ self_critique: v })}
                  />
                  <Field label="Tier policy">
                    <Select
                      value={draft.tier_policy || 'tier1+2'}
                      onChange={(e) => patch({ tier_policy: e.target.value as AgentDefinition['tier_policy'] })}
                    >
                      <option value="tier1">Tier 1 — read-only</option>
                      <option value="tier1+2">Tier 1 + 2 — write &amp; execute</option>
                      <option value="all">All — including tier 3</option>
                    </Select>
                  </Field>
                  {blockedTools.length > 0 && (
                    <div className="ax-settings__warning">
                      <AlertTriangle size={14} />
                      <span>
                        {blockedTools.length} selected tool{blockedTools.length === 1 ? '' : 's'} would be
                        blocked by the current gates: {blockedTools.map((t) => t.id).join(', ')}
                      </span>
                    </div>
                  )}
                  {selectedTools.length > 0 && (
                    <Field
                      label="Always allow"
                      hint="These tools skip the approval prompt. Tier and access gates still apply."
                    >
                      <div className="ax-chips">
                        {selectedTools.map((t) => {
                          const on = (draft.always_allow_tools || []).includes(t.id);
                          return (
                            <button
                              key={t.id}
                              type="button"
                              className={`ax-pickchip${on ? ' is-on' : ''}`}
                              onClick={() => {
                                const cur = new Set(draft.always_allow_tools || []);
                                if (cur.has(t.id)) cur.delete(t.id);
                                else cur.add(t.id);
                                patch({ always_allow_tools: Array.from(cur) });
                              }}
                            >
                              {t.id}
                            </button>
                          );
                        })}
                      </div>
                    </Field>
                  )}
                  {selectedTools.length > 0 && (
                    <Field
                      label="Tool policies"
                      hint="Allow skips approval, Ask uses the normal gate, Deny blocks the tool entirely."
                    >
                      <div className="ax-policy-list">
                        {selectedTools.slice(0, 40).map((t) => {
                          const value = (draft.tool_policies || {})[t.id] || 'ask';
                          return (
                            <label key={t.id} className="ax-policy-row">
                              <span>{t.id}</span>
                              <select
                                value={value}
                                onChange={(event) => {
                                  const next = { ...(draft.tool_policies || {}) };
                                  const chosen = event.target.value as 'allow' | 'ask' | 'deny';
                                  if (chosen === 'ask') delete next[t.id];
                                  else next[t.id] = chosen;
                                  patch({ tool_policies: next });
                                }}
                              >
                                <option value="allow">Allow</option>
                                <option value="ask">Ask</option>
                                <option value="deny">Deny</option>
                              </select>
                            </label>
                          );
                        })}
                      </div>
                    </Field>
                  )}
                </section>

                <div className="ax-tools__bar">
                  <TextInput
                    placeholder="Search tools…"
                    value={toolQuery}
                    onChange={(e) => setToolQuery(e.target.value)}
                  />
                  <Chip>{(draft.tools || []).length} selected</Chip>
                </div>

                {[1, 2, 3].map((tier) => {
                  const items = groupedTools[tier] || [];
                  if (items.length === 0) return null;
                  return (
                    <div key={tier} className="ax-tier">
                      <div className="ax-tier__head">
                        <span className="ax-tier__name">
                          Tier {tier} <Badge tone={tierTone(tier)}>{tierRisk(tier)}</Badge>
                        </span>
                      </div>
                      <div className="ax-tool-grid">
                        {items.map((t) => {
                          const on = (draft.tools || []).includes(t.id);
                          return (
                            <button
                              type="button"
                              key={t.id}
                              className={`ax-tool${on ? ' is-on' : ''}`}
                              onClick={() => toggleTool(t.id)}
                              title={t.description}
                            >
                              <span className="ax-tool__top">
                                <span className="ax-tool__name">{t.id}</span>
                                {t.requires_approval && <Badge tone="warn">approval</Badge>}
                              </span>
                              <span className="ax-tool__desc">{t.description}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}

                <section className="ax-form__section">
                  <h4 className="ax-form__title">Skills</h4>
                  {skills.length === 0 && <div className="ax-tier__empty">No skills available.</div>}
                  <div className="ax-skill-grid">
                    {skills.map((s) => {
                      const on = (draft.skills || []).includes(s.id);
                      return (
                        <button
                          type="button"
                          key={s.id}
                          className={`ax-skill${on ? ' is-on' : ''}`}
                          onClick={() => toggleSkill(s.id)}
                          title={s.instructions}
                        >
                          <span className="ax-skill__top">
                            <span className="ax-skill__name">{s.name}</span>
                            {s.tools.length > 0 && <Badge tone="muted">{s.tools.length} tools</Badge>}
                          </span>
                          <span className="ax-skill__desc">{s.description}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>

                <ToolPlayground agentId={draft.id} tools={tools} />
              </div>
            )}

            {section === 'autonomy' && (
              <div className="ax-form">
                <section className="ax-form__section">
                  <h4 className="ax-form__title">How much should this agent ask?</h4>
                  <div className="ax-option-list">
                    {AUTONOMY_OPTIONS.map((o) => {
                      const Icon = o.icon;
                      return (
                        <button
                          key={o.value}
                          type="button"
                          className={`ax-option${autonomy === o.value ? ' is-on' : ''}`}
                          onClick={() => patch({ autonomy_level: o.value })}
                        >
                          <Icon size={16} className="ax-option__icon" />
                          <span className="ax-option__body">
                            <span className="ax-option__title">{o.title}</span>
                            <span className="ax-option__desc">{o.desc}</span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <div className="ax-settings__hint">
                    {approvalTools.length === 0
                      ? autonomy === 'off'
                        ? 'No approval prompts will be shown.'
                        : 'No selected tool requires approval at this level.'
                      : `Will ask before: ${approvalTools.map((t) => t.id).join(', ')}`}
                  </div>
                </section>
              </div>
            )}

            {section === 'schedule' && (
              <div className="ax-form">
                <section className="ax-form__section">
                  <h4 className="ax-form__title">Trigger</h4>
                  <SegmentedControl
                    value={draft.run_mode || 'on_demand'}
                    onChange={(v) => patch({ run_mode: v })}
                    options={[
                      { value: 'on_demand', label: 'On demand' },
                      { value: 'scheduled', label: 'Scheduled' },
                      { value: 'watcher', label: 'Watcher' },
                      { value: 'webhook', label: 'Webhook' },
                    ]}
                  />
                  {draft.run_mode === 'scheduled' && (
                    <Field label="Cron schedule">
                      <CronEditor value={draft.schedule || ''} onChange={(v) => patch({ schedule: v })} />
                    </Field>
                  )}
                  {draft.run_mode === 'watcher' && (
                    <Field label="Watcher pattern" hint="Glob relative to the primary knowledge base.">
                      <TextInput
                        value={draft.watcher_pattern || ''}
                        placeholder="*.md"
                        onChange={(e) => patch({ watcher_pattern: e.target.value })}
                      />
                    </Field>
                  )}
                  {draft.run_mode === 'webhook' && (
                    <Field label="Webhook URL" hint='POST { "input": "…" } to this URL.'>
                      <TextInput
                        readOnly
                        value={webhookUrl}
                        onFocus={(e) => e.target.select()}
                      />
                    </Field>
                  )}
                </section>
                <div className="ax-form__grid">
                  <Field label="Max steps per run">
                    <TextInput
                      type="number"
                      min={1}
                      max={200}
                      value={draft.max_iterations ?? 15}
                      onChange={(e) => patch({ max_iterations: parseInt(e.target.value) || 1 })}
                    />
                  </Field>
                  <Field label="Max concurrent runs" hint="1–16.">
                    <TextInput
                      type="number"
                      min={1}
                      max={16}
                      value={draft.max_concurrent_runs ?? 1}
                      onChange={(e) =>
                        patch({ max_concurrent_runs: Math.max(1, Math.min(16, parseInt(e.target.value) || 1)) })
                      }
                    />
                  </Field>
                </div>
                <Toggle
                  title="Enabled"
                  description="Disabled agents stay configured but cannot run."
                  checked={!!draft.enabled}
                  onChange={(v) => patch({ enabled: v })}
                />
              </div>
            )}

            {section === 'knowledge' && (
              <div className="ax-form">
                <section className="ax-form__section">
                  <h4 className="ax-form__title">Knowledge scope</h4>
                  <div className="ax-option-list">
                    {KNOWLEDGE_OPTIONS.map((o) => (
                      <button
                        key={o.value}
                        type="button"
                        className={`ax-option${scope.mode === o.value ? ' is-on' : ''}`}
                        onClick={() => setScope({ mode: o.value })}
                      >
                        <span className="ax-option__radio" aria-hidden />
                        <span className="ax-option__body">
                          <span className="ax-option__title">{o.title}</span>
                          <span className="ax-option__desc">{o.desc}</span>
                        </span>
                      </button>
                    ))}
                  </div>

                  {scope.mode === 'all' && (
                    <Field
                      label="Primary knowledge base (writes)"
                      hint="Optional. Defaults to the active knowledge base if left empty."
                    >
                      <Select
                        value={scope.primary_field}
                        onChange={(e) => setScope({ primary_field: e.target.value })}
                      >
                        <option value="">Active knowledge base</option>
                        {fieldPaths.map((p) => (
                          <option key={p} value={p}>
                            {p}
                          </option>
                        ))}
                      </Select>
                    </Field>
                  )}

                  {scope.mode === 'project' && (
                    <>
                      <Field label="Primary knowledge base" hint="Writes go here when write access is on.">
                        <Select
                          value={scope.primary_field}
                          onChange={(e) => setScope({ primary_field: e.target.value })}
                        >
                          <option value="">Choose a knowledge base…</option>
                          {fieldPaths.map((p) => (
                            <option key={p} value={p}>
                              {p}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      <div className="ax-form__section">
                        <h4 className="ax-form__title">Read-only extras</h4>
                        {fieldPaths.length === 0 ? (
                          <div className="ax-tier__empty">No knowledge bases configured.</div>
                        ) : (
                          <div className="ax-scope-list">
                            {fieldPaths
                              .filter((p) => p !== scope.primary_field)
                              .map((p) => {
                                const on = (scope.extra_fields || []).includes(p);
                                return (
                                  <label key={p} className={`ax-scope${on ? ' is-on' : ''}`}>
                                    <input type="checkbox" checked={on} onChange={() => toggleExtraField(p)} />
                                    <span className="ax-scope__path">{p}</span>
                                  </label>
                                );
                              })}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                  {scope.mode === 'all' && (
                    <div className="ax-settings__hint">
                      Reads every configured knowledge base. Writes go to the primary base only.
                    </div>
                  )}
                </section>

                <section className="ax-form__section">
                  <h4 className="ax-form__title">Memory</h4>
                  <div className="ax-option-list">
                    {MEMORY_OPTIONS.map((o) => (
                      <button
                        key={o.value}
                        type="button"
                        className={`ax-option${memoryMode === o.value ? ' is-on' : ''}`}
                        onClick={() => patch({ memory_mode: o.value })}
                      >
                        <span className="ax-option__radio" aria-hidden />
                        <span className="ax-option__body">
                          <span className="ax-option__title">{o.title}</span>
                          <span className="ax-option__desc">{o.desc}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                  {isSharedMemory && (
                    <div className="ax-settings__warning">
                      <AlertTriangle size={14} />
                      <span>This agent shares one memory pool with every other shared-memory agent.</span>
                    </div>
                  )}
                </section>
              </div>
            )}

            {section === 'runs' && (
              <div className="ax-form">
                <section className="ax-form__section">
                  <div className="ax-settings__subhead">
                    <h4 className="ax-form__title">Memory · {memTotal}</h4>
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={memTotal === 0}
                      onClick={() => void clearMemory()}
                    >
                      Clear all
                    </Button>
                  </div>
                  {memory.length === 0 && (
                    <EmptyState
                      title="No memory yet"
                      description="What this agent learns while working will appear here."
                    />
                  )}
                  {memory.map((e, i) => (
                    <div key={`${e.timestamp}-${i}`} className="ax-mem">
                      <div className="ax-mem__meta">
                        <Badge tone={e.type === 'error' ? 'danger' : 'accent'}>{e.type}</Badge>
                        <span className="ax-mem__time">{new Date(e.timestamp).toLocaleString()}</span>
                        <button
                          type="button"
                          className="ui-icon-btn"
                          title="Delete entry"
                          aria-label="Delete entry"
                          onClick={() => void deleteMemEntry((memPage - 1) * PAGE_SIZE + i)}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                      <div className="ax-mem__content">{e.content}</div>
                    </div>
                  ))}
                  {memTotal > PAGE_SIZE && (
                    <div className="ax-pager">
                      <Button size="sm" disabled={memPage <= 1} onClick={() => void loadMemory(memPage - 1)}>
                        Prev
                      </Button>
                      <span>
                        Page {memPage} of {Math.ceil(memTotal / PAGE_SIZE)}
                      </span>
                      <Button
                        size="sm"
                        disabled={memPage * PAGE_SIZE >= memTotal}
                        onClick={() => void loadMemory(memPage + 1)}
                      >
                        Next
                      </Button>
                    </div>
                  )}
                </section>

                <section className="ax-form__section">
                  <div className="ax-settings__subhead">
                    <h4 className="ax-form__title">Runs · {history.length}</h4>
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={history.length === 0}
                      onClick={() => void clearHistory()}
                    >
                      Clear history
                    </Button>
                  </div>
                  {history.length === 0 && (
                    <EmptyState
                      title="No runs yet"
                      description="Manual, scheduled and watcher runs are recorded here."
                    />
                  )}
                  {history.map((r, i) => (
                    <div key={r.run_id || i} className="ax-run">
                      <div className="ax-run__meta">
                        <Badge
                          tone={
                            r.status === 'success'
                              ? 'success'
                              : r.status === 'error'
                                ? 'danger'
                                : 'muted'
                          }
                        >
                          {r.status}
                        </Badge>
                        <span>{r.duration}s</span>
                        {r.usage && (
                          <span>
                            {r.usage.prompt_tokens + r.usage.completion_tokens} tokens
                          </span>
                        )}
                        <span className="ax-run__time">{fmtTime(r.timestamp)}</span>
                      </div>
                      <div className="ax-run__input">{r.input}</div>
                      <details className="ax-run__output">
                        <summary>Output</summary>
                        <div
                          className="ax-run__rich"
                          dangerouslySetInnerHTML={{ __html: formatMarkdown(r.output) }}
                        />
                      </details>
                      <button
                        type="button"
                        className="ax-run__trace-btn"
                        onClick={() => void loadTrace(r.run_id)}
                      >
                        {openTrace === r.run_id ? 'Hide trace' : 'View trace'}
                      </button>
                      {openTrace === r.run_id && (
                        <div className="ax-run__trace">
                          {traceLoading && <span className="ax-run__trace-empty">Loading…</span>}
                          {!traceLoading && traceData.length === 0 && (
                            <span className="ax-run__trace-empty">No trace recorded.</span>
                          )}
                          {!traceLoading && traceData.length > 0 && (
                            <RunTraceTimeline trace={traceData} />
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </section>
              </div>
            )}

            {section === 'danger' && (
              <div className="ax-form">
                <section className="ax-form__section">
                  <h4 className="ax-form__title">Conversation</h4>
                  <p className="ax-tier__sub">
                    Clears the agent’s chat sessions. Its memory and workspace are kept.
                  </p>
                  <Button variant="danger" size="sm" onClick={() => void clearChat()}>
                    <MessageSquareX size={13} /> Clear conversation
                  </Button>
                </section>
                <section className="ax-form__section">
                  <h4 className="ax-form__title">Memory</h4>
                  <p className="ax-tier__sub">
                    {isSharedMemory
                      ? 'This clears the shared memory pool used by every shared-memory agent.'
                      : 'Clears the memory entries for this agent.'}
                  </p>
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={memTotal === 0}
                    onClick={() => void clearMemory()}
                  >
                    Clear memory
                  </Button>
                </section>
                <section className="ax-form__section">
                  <h4 className="ax-form__title">Delete agent</h4>
                  <p className="ax-tier__sub">
                    Removes the definition, memory, chats, sessions, run history and queued work.
                    This cannot be undone.
                  </p>
                  <Button variant="danger" size="sm" onClick={() => void remove()}>
                    <Trash2 size={13} /> Delete agent
                  </Button>
                </section>
              </div>
            )}
          </div>
        </div>

        <footer className="ax-settings__foot">
          <div className="ax-settings__foot-status">
            {error && <span className="ax-error-text">{error}</span>}
            {!error && message && <span className="ax-saved">{message}</span>}
          </div>
          <div className="ax-settings__foot-actions">
            <Button size="sm" disabled={!dirty || saving} onClick={() => {
              setDraft(agent);
              setDirty(false);
              setError('');
              setMessage('');
              setHandleTouched(true);
            }}>
              Discard
            </Button>
            <Button variant="primary" size="sm" disabled={saving || !dirty} onClick={() => void save()}>
              {saving ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </footer>
        {saving && <Spinner className="ax-inspector__saving" size={14} />}
      </div>
    </div>
  );
}
