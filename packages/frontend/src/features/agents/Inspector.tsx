import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { api } from '../../api';
import { useConfirm } from '../../components/ConfirmDialog';
import CronEditor from '../../components/CronEditor';
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
import {
  Badge,
  Button,
  Chip,
  EmptyState,
  Field,
  SegmentedControl,
  Select,
  Spinner,
  Tabs,
  TextArea,
  TextInput,
  Toggle,
} from '../../ui/primitives';
import ModelPicker from './ModelPicker';
import { fmtTime, type InspectorTab } from './types';

const PAGE_SIZE = 20;

export default function Inspector({
  agent,
  onSaved,
  onDeleted,
  onClose,
}: {
  agent: AgentListItem;
  onSaved: () => void;
  onDeleted: () => void;
  onClose: () => void;
}) {
  const confirm = useConfirm();
  const [tab, setTab] = useState<InspectorTab>('definition');
  const [draft, setDraft] = useState<Partial<AgentDefinition>>(agent);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const [openTrace, setOpenTrace] = useState<string | null>(null);
  const [traceData, setTraceData] = useState<AgentReasoningEvent[]>([]);
  const [traceLoading, setTraceLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const [tools, setTools] = useState<Record<string, ToolMeta>>({});
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [toolQuery, setToolQuery] = useState('');

  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [memTotal, setMemTotal] = useState(0);
  const [memPage, setMemPage] = useState(1);
  const [history, setHistory] = useState<RunRecord[]>([]);

  // Reset the form only when a different agent is selected — refreshes that
  // re-fetch the same agent (new object identity) must not discard edits.
  const lastAgentId = useRef(agent.id);
  useEffect(() => {
    if (lastAgentId.current === agent.id) return;
    lastAgentId.current = agent.id;
    setDraft(agent);
    setDirty(false);
    setMessage('');
    setError('');
    setTab('definition');
  }, [agent]);

  const loadMemory = useCallback(
    async (page: number) => {
      const data = await api.agents.memory(agent.id, page, PAGE_SIZE);
      setMemory(data.entries);
      setMemTotal(data.total);
      setMemPage(data.page);
    },
    [agent.id],
  );

  const loadHistory = useCallback(async () => {
    const data = await api.agents.history(agent.id);
    setHistory(data.history || []);
  }, [agent.id]);

  useEffect(() => {
    void loadMemory(1);
    void loadHistory();
  }, [loadMemory, loadHistory]);

  useEffect(() => {
    api.agents
      .tools()
      .then((d) => setTools(d.tools || {}))
      .catch(() => {});
    api.agents
      .skills()
      .then((d) => setSkills(d.skills || []))
      .catch(() => {});
  }, []);

  const patch = (p: Partial<AgentDefinition>) => {
    setDraft((d) => ({ ...d, ...p }));
    setDirty(true);
    setMessage('');
  };

  const toggleTool = (id: string) => {
    const cur = new Set(draft.tools || []);
    if (cur.has(id)) cur.delete(id);
    else cur.add(id);
    patch({ tools: Array.from(cur) });
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

  const save = async () => {
    setSaving(true);
    setError('');
    setMessage('');
    const payload = {
      ...draft,
      schedule: draft.schedule || null,
      watcher_pattern: draft.watcher_pattern || null,
    };
    try {
      const res = await api.agents.update(agent.id, payload);
      if (res.error) setError(res.error);
      else {
        setDirty(false);
        setMessage('Saved');
        onSaved();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setSaving(false);
  };

  const remove = async () => {
    const ok = await confirm(`Delete agent "${agent.name}"? This cannot be undone.`, {
      title: 'Delete Agent',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.agents.remove(agent.id);
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const loadTrace = async (runId: string) => {
    if (openTrace === runId) {
      setOpenTrace(null);
      return;
    }
    setOpenTrace(runId);
    setTraceLoading(true);
    setTraceData([]);
    try {
      const rec = await api.agents.run(agent.id, runId);
      setTraceData(rec.trace || []);
    } catch {
      setTraceData([]);
    }
    setTraceLoading(false);
  };

  const webhookUrl = `${typeof window !== 'undefined' ? window.location.origin : ''}/api/agents/hooks/${agent.webhook_token || draft.webhook_token || ''}`;

  const deleteMemEntry = async (index: number) => {
    try {
      await api.agents.deleteMemoryEntry(agent.id, index);
      await loadMemory(memPage);
    } catch {
      // ignore
    }
  };

  const clearMemory = async () => {
    await api.agents.clearMemory(agent.id);
    await loadMemory(1);
  };

  return (
    <aside className="ax-inspector">
      <div className="ax-inspector__head">
        <div className="ax-inspector__title">
          <span>{agent.name}</span>
          {!agent.enabled && <Badge tone="muted">disabled</Badge>}
        </div>
        <button type="button" className="ui-icon-btn" onClick={onClose} title="Hide inspector" aria-label="Hide inspector">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      <Tabs<InspectorTab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'definition', label: 'Definition' },
          { id: 'tools', label: 'Tools & skills', count: (draft.tools || []).length },
          { id: 'memory', label: 'Memory', count: memTotal },
          { id: 'history', label: 'History', count: history.length },
        ]}
      />

      <div className="ax-inspector__body">
        {tab === 'definition' && (
          <div className="ax-form">
            <section className="ax-form__section">
              <h4 className="ax-form__title">Identity</h4>
              <Field label="Name">
                <TextInput value={draft.name || ''} onChange={(e) => patch({ name: e.target.value })} />
              </Field>
              <Field label="System prompt">
                <TextArea
                  rows={5}
                  value={draft.system_prompt || ''}
                  onChange={(e) => patch({ system_prompt: e.target.value })}
                  placeholder="You are a helpful agent that…"
                />
              </Field>
            </section>

            <section className="ax-form__section">
              <h4 className="ax-form__title">Model &amp; behavior</h4>
              <Field label="Model">
                <ModelPicker value={draft.model || ''} onChange={(v) => patch({ model: v })} />
              </Field>
              <Field label={`Temperature · ${(draft.temperature ?? 0.2).toFixed(1)}`} hint="Low is precise, high is creative.">
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
              <Field label="Run mode">
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
              </Field>
              {draft.run_mode === 'webhook' && (
                <Field
                  label="Webhook URL"
                  hint={'POST { "input": "…" } to this URL to trigger the agent.'}
                >
                  <div className="ax-copy-row">
                    <TextInput readOnly value={webhookUrl} onFocus={(e) => e.target.select()} />
                    <Button
                      size="sm"
                      onClick={() => {
                        void navigator.clipboard
                          .writeText(webhookUrl)
                          .then(() => {
                            setCopied(true);
                            setTimeout(() => setCopied(false), 1500);
                          })
                          .catch(() => {});
                      }}
                    >
                      {copied ? 'Copied' : 'Copy'}
                    </Button>
                  </div>
                </Field>
              )}
              {draft.run_mode === 'scheduled' && (
                <Field label="Schedule">
                  <CronEditor value={draft.schedule || ''} onChange={(v) => patch({ schedule: v })} />
                </Field>
              )}
              {draft.run_mode === 'watcher' && (
                <Field label="Watcher pattern (glob)" hint="The agent runs whenever a matching file changes.">
                  <TextInput
                    value={draft.watcher_pattern || ''}
                    placeholder="*.md"
                    onChange={(e) => patch({ watcher_pattern: e.target.value })}
                  />
                </Field>
              )}
              {draft.run_mode === 'on_demand' && (
                <Field label="Max steps" hint="Tool steps before the agent is forced to answer.">
                  <TextInput
                    type="number"
                    min={1}
                    value={draft.max_iterations ?? 15}
                    onChange={(e) => patch({ max_iterations: parseInt(e.target.value) || 1 })}
                  />
                </Field>
              )}
            </section>

            <section className="ax-form__section">
              <h4 className="ax-form__title">Capabilities &amp; access</h4>
              <div className="ax-form__grid">
                <Field label="Tier policy">
                  <Select
                    value={draft.tier_policy || 'tier1+2'}
                    onChange={(e) => patch({ tier_policy: e.target.value as AgentDefinition['tier_policy'] })}
                  >
                    <option value="tier1">Tier 1 — read-only</option>
                    <option value="tier1+2">Tier 1 + 2 — write &amp; execute</option>
                    <option value="all">All — incl. tier 3</option>
                  </Select>
                </Field>
                <Field label="Memory scope">
                  <Select
                    value={draft.memory_scope || 'field'}
                    onChange={(e) => patch({ memory_scope: e.target.value as AgentDefinition['memory_scope'] })}
                  >
                    <option value="none">None</option>
                    <option value="session">Session</option>
                    <option value="field">Global</option>
                  </Select>
                </Field>
              </div>
              <Toggle
                title="Enabled"
                description="Disabled agents stay configured but cannot run."
                checked={!!draft.enabled}
                onChange={(v) => patch({ enabled: v })}
              />
              <p className="ax-tier__sub">
                Tool permissions, skills and write/shell/self-critique gates are on the
                “Tools &amp; skills” tab.
              </p>
            </section>

            <details className="ax-advanced">
              <summary>Advanced</summary>
              <div className="ax-form__grid">
                <Field label="Context budget">
                  <TextInput
                    type="number"
                    value={draft.context_budget ?? 8000}
                    onChange={(e) => patch({ context_budget: parseInt(e.target.value) || 0 })}
                  />
                </Field>
                <Field label="Human-in-loop threshold">
                  <TextInput
                    type="number"
                    step="0.1"
                    min="0"
                    max="1"
                    value={draft.human_in_loop_threshold ?? 0}
                    onChange={(e) => patch({ human_in_loop_threshold: parseFloat(e.target.value) })}
                  />
                </Field>
              </div>
            </details>

            <div className="ax-form__footer">
              <Button variant="danger" size="sm" onClick={remove}>
                Delete
              </Button>
              <div className="ax-form__footer-right">
                {dirty && <span className="ax-unsaved">Unsaved changes</span>}
                {!dirty && message && <span className="ax-saved">{message}</span>}
                {error && <span className="ax-error-text">{error}</span>}
                <Button variant="primary" size="sm" disabled={saving || !dirty} onClick={save}>
                  {saving ? 'Saving…' : 'Save'}
                </Button>
              </div>
            </div>
          </div>
        )}

        {tab === 'tools' && (
          <div className="ax-tools">
            <section className="ax-form__section">
              <h4 className="ax-form__title">Gates</h4>
              <Toggle
                title="Write access"
                description="Create or modify files in the workspace."
                checked={!!draft.write_access}
                onChange={(v) => patch({ write_access: v })}
              />
              <Toggle
                title="Shell access"
                description="Run sandboxed shell commands (tier 3)."
                checked={!!draft.shell_access}
                onChange={(v) => patch({ shell_access: v })}
              />
              <Toggle
                title="Self-critique"
                description="Run a reflection pass that reviews and improves the answer."
                checked={!!draft.self_critique}
                onChange={(v) => patch({ self_critique: v })}
              />
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
              return (
                <div key={tier} className="ax-tier">
                  <div className="ax-tier__head">
                    <span className="ax-tier__name">Tier {tier}</span>
                    <span className="ax-tier__sub">
                      {tier === 1
                        ? 'Read-only and safe'
                        : tier === 2
                          ? 'Writes or executes — may ask for approval'
                          : 'Privileged system access'}
                    </span>
                  </div>
                  {items.length === 0 ? (
                    <div className="ax-tier__empty">
                      {toolQuery ? 'No tools match.' : 'No tools registered.'}
                    </div>
                  ) : (
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
                  )}
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

            <div className="ax-form__footer">
              <div className="ax-form__footer-right">
                {dirty && <span className="ax-unsaved">Unsaved changes</span>}
                {!dirty && message && <span className="ax-saved">{message}</span>}
                {error && <span className="ax-error-text">{error}</span>}
                <Button variant="primary" size="sm" disabled={saving || !dirty} onClick={save}>
                  {saving ? 'Saving…' : 'Save'}
                </Button>
              </div>
            </div>
          </div>
        )}

        {tab === 'memory' && (
          <div className="ax-memory">
            <div className="ax-memory__bar">
              <Chip>{memTotal} {memTotal === 1 ? 'entry' : 'entries'}</Chip>
              <Button variant="danger" size="sm" disabled={memTotal === 0} onClick={clearMemory}>
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
                    onClick={() => deleteMemEntry((memPage - 1) * PAGE_SIZE + i)}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
                <div className="ax-mem__content">{e.content}</div>
              </div>
            ))}
            {memTotal > PAGE_SIZE && (
              <div className="ax-pager">
                <Button size="sm" disabled={memPage <= 1} onClick={() => loadMemory(memPage - 1)}>
                  Prev
                </Button>
                <span>
                  Page {memPage} of {Math.ceil(memTotal / PAGE_SIZE)}
                </span>
                <Button
                  size="sm"
                  disabled={memPage * PAGE_SIZE >= memTotal}
                  onClick={() => loadMemory(memPage + 1)}
                >
                  Next
                </Button>
              </div>
            )}
          </div>
        )}

        {tab === 'history' && (
          <div className="ax-history">
            {history.length === 0 && (
              <EmptyState
                title="No runs yet"
                description="Every run — manual, scheduled or watcher-triggered — is recorded here."
              />
            )}
            {history.map((r, i) => (
              <div key={r.run_id || i} className="ax-run">
                <div className="ax-run__meta">
                  <Badge tone={r.status === 'success' ? 'success' : r.status === 'error' ? 'danger' : 'muted'}>
                    {r.status}
                  </Badge>
                  <span>{r.duration}s</span>
                  {r.usage && (
                    <span>
                      {r.usage.prompt_tokens + r.usage.completion_tokens}
                      {' '}tokens
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
                  onClick={() => loadTrace(r.run_id)}
                >
                  {openTrace === r.run_id ? 'Hide trace' : 'View trace'}
                </button>
                {openTrace === r.run_id && (
                  <div className="ax-run__trace">
                    {traceLoading && <span className="ax-run__trace-empty">Loading…</span>}
                    {!traceLoading && traceData.length === 0 && (
                      <span className="ax-run__trace-empty">No trace recorded.</span>
                    )}
                    {!traceLoading &&
                      traceData.map((ev, j) => (
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
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {saving && <Spinner className="ax-inspector__saving" size={14} />}
    </aside>
  );
}
