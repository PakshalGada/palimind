import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Sparkles,
} from 'lucide-react';
import { api } from '../../api';
import AgentAvatar from '../../components/AgentAvatar';
import CronEditor from '../../components/CronEditor';
import type { AgentDefinition, AgentListItem, SkillMeta, ToolMeta } from '../../types';
import {
  Badge,
  Button,
  Chip,
  Field,
  Modal,
  SegmentedControl,
  Select,
  TextArea,
  TextInput,
  Toggle,
} from '../../ui/primitives';
import AvatarCustomizer from './AvatarCustomizer';
import ModelPicker from './ModelPicker';
import { EMPTY_DEF } from './types';
import {
  AGENT_TEMPLATES,
  AUTONOMY_OPTIONS,
  KNOWLEDGE_OPTIONS,
  MEMORY_OPTIONS,
  PERSONALITY_PRESETS,
  composeSystemPrompt,
  defaultKnowledgeScope,
  uniqueHandle,
  SHELL_TOOLS,
  WRITE_TOOLS,
} from './options';

const STEPS = [
  { label: 'Identity', blurb: 'Who is this agent?' },
  { label: 'Instructions', blurb: 'What is it here to do?' },
  { label: 'Capabilities', blurb: 'What can it use?' },
  { label: 'Behavior', blurb: 'How independent is it?' },
  { label: 'Knowledge', blurb: 'What can it reach?' },
  { label: 'Review', blurb: 'Confirm and create' },
] as const;

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

export default function AgentWizard({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id?: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Partial<AgentDefinition>>(EMPTY_DEF);
  const [tools, setTools] = useState<Record<string, ToolMeta>>({});
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [fieldPaths, setFieldPaths] = useState<string[]>([]);
  const [allAgents, setAllAgents] = useState<AgentListItem[]>([]);
  const [toolQuery, setToolQuery] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [handleTouched, setHandleTouched] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const body = contentRef.current?.closest('.ui-modal__body') as HTMLElement | null;
    if (body) body.scrollTop = 0;
  }, [step, error]);

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setDraft({ ...EMPTY_DEF });
    setError('');
    setToolQuery('');
    setHandleTouched(false);
  }, [open]);

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
      .then((d) => setAllAgents(d.agents || []))
      .catch(() => {});
  }, []);

  const patch = (p: Partial<AgentDefinition>) => setDraft((d) => ({ ...d, ...p }));

  const existingHandles = useMemo(() => allAgents.map((a) => a.name), [allAgents]);
  const displayName = (draft.display_name || '').trim();
  const handle = (draft.name || '').trim();
  const handleValid = /^[\w-]{1,64}$/.test(handle);
  const scope = draft.knowledge_scope || defaultKnowledgeScope();
  const autonomy = draft.autonomy_level || 'semi';
  const memoryMode = draft.memory_mode || 'private';
  const runMode = draft.run_mode || 'on_demand';

  const changeDisplayName = (value: string) => {
    const next: Partial<AgentDefinition> = { display_name: value };
    if (!handleTouched && value.trim()) next.name = uniqueHandle(value, existingHandles);
    patch(next);
  };

  const changeHandle = (value: string) => {
    setHandleTouched(true);
    patch({ name: value.toLowerCase().replace(/[^\w-]+/g, '-').slice(0, 64) });
  };

  const applyTemplate = (templateId: string) => {
    const template = AGENT_TEMPLATES.find((t) => t.id === templateId);
    if (!template) return;
    const label =
      template.id === 'blank'
        ? draft.display_name || ''
        : template.config.display_name || template.name;
    setDraft({
      ...EMPTY_DEF,
      ...template.config,
      display_name: label,
      name: label ? uniqueHandle(label, existingHandles) : '',
    });
    setHandleTouched(false);
    setError('');
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

  const setScope = (p: Partial<AgentDefinition['knowledge_scope']>) =>
    patch({ knowledge_scope: { ...scope, ...p } });

  const toggleExtraField = (path: string) => {
    const cur = new Set(scope.extra_fields || []);
    if (cur.has(path)) cur.delete(path);
    else cur.add(path);
    setScope({ extra_fields: Array.from(cur) });
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
  const skillTools = useMemo(() => {
    const ids = new Set<string>();
    for (const skillId of draft.skills || []) {
      const skill = skills.find((s) => s.id === skillId);
      for (const tool of skill?.tools || []) ids.add(tool);
    }
    return ids;
  }, [draft.skills, skills]);
  const blockedTools = useMemo(
    () =>
      selectedTools.filter((t) => {
        if (t.tier >= 3 && draft.tier_policy !== 'all') return true;
        if (t.tier === 2 && (draft.tier_policy === 'tier1' || !draft.tier_policy)) return true;
        if (['write_file', 'search_replace'].includes(t.id) && !draft.write_access) return true;
        if (['run_python', 'run_shell'].includes(t.id) && !draft.shell_access) return true;
        return false;
      }),
    [selectedTools, draft.tier_policy, draft.write_access, draft.shell_access],
  );
  const approvalTools = useMemo(() => {
    if (autonomy === 'off') return [];
    return selectedTools.filter((t) => {
      if (autonomy === 'supervised') return true;
      if (autonomy === 'high') return t.tier >= 3;
      return t.tier >= 2 || t.requires_approval;
    });
  }, [autonomy, selectedTools]);

  const validateStep = (index: number): string => {
    if (index === 0) {
      if (!displayName) return 'Give your agent a display name.';
      if (!handleValid) return 'Handle must be 1–64 letters, digits, dashes or underscores.';
      if (existingHandles.some((n) => n.toLowerCase() === handle.toLowerCase()))
        return `The handle @${handle} is already taken.`;
    }
    if (index === 3) {
      if (runMode === 'scheduled' && !draft.schedule) return 'Choose a cron schedule.';
      if (runMode === 'watcher' && !draft.watcher_pattern) return 'Set a watcher pattern.';
    }
    if (index === 4 && scope.mode === 'project' && !scope.primary_field) {
      return 'Choose a primary knowledge base for the project scope.';
    }
    return '';
  };

  const next = () => {
    setError('');
    setStep((s) => Math.min(STEPS.length - 1, s + 1));
  };

  const back = () => {
    setError('');
    setStep((s) => Math.max(0, s - 1));
  };

  const create = async () => {
    for (let i = 0; i < STEPS.length - 1; i++) {
      const problem = validateStep(i);
      if (problem) {
        setError(problem);
        setStep(i);
        return;
      }
    }
    setSaving(true);
    setError('');
    const payload: Partial<AgentDefinition> = {
      ...draft,
      name: handle,
      display_name: displayName,
      system_prompt: composeSystemPrompt(draft),
      knowledge_scope: scope,
      schedule: runMode === 'scheduled' ? draft.schedule || null : null,
      watcher_pattern: runMode === 'watcher' ? draft.watcher_pattern || null : null,
    };
    try {
      const res = await api.agents.create(payload);
      if (res.error) setError(res.error);
      else onCreated(res.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setSaving(false);
  };

  const footer = (
    <div className="ax-wizard__foot">
      <div className="ax-wizard__progress">
        <div className="ax-wizard__segments">
          {STEPS.map((s, i) => (
            <button
              key={s.label}
              type="button"
              className={`ax-wizard__seg${i <= step ? ' is-on' : ''}`}
              onClick={() => {
                setError('');
                setStep(i);
              }}
              title={s.label}
              aria-label={`Go to ${s.label}`}
            />
          ))}
        </div>
        <span className="ax-wizard__step-label">
          {step + 1}/{STEPS.length} · {STEPS[step].label}
        </span>
      </div>
      <div className="ax-wizard__actions">
        {step > 0 && (
          <Button size="sm" onClick={back}>
            <ChevronLeft size={13} /> Back
          </Button>
        )}
        {step < STEPS.length - 1 ? (
          <Button variant="primary" size="sm" onClick={next}>
            Next <ChevronRight size={13} />
          </Button>
        ) : (
          <Button variant="primary" size="sm" disabled={saving} onClick={() => void create()}>
            <Sparkles size={13} /> {saving ? 'Creating…' : 'Create agent'}
          </Button>
        )}
      </div>
    </div>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create an agent"
      subtitle={`${STEPS[step].label} — ${STEPS[step].blurb}`}
      width={780}
      footer={footer}
    >
      <div ref={contentRef}>
        {error && (
          <div className="ax-settings__warning ax-wizard__banner" role="alert">
            <AlertTriangle size={14} />
            <span>{error}</span>
          </div>
        )}
      {step === 0 && (
        <div className="ax-form">
          <section className="ax-form__section">
            <h4 className="ax-form__title">Start from a template</h4>
            <div className="ax-template-grid">
              {AGENT_TEMPLATES.map((template) => (
                <button
                  key={template.id}
                  type="button"
                  className={`ax-template${draft.title === template.config.title && template.id !== 'blank' ? ' is-on' : ''}`}
                  onClick={() => applyTemplate(template.id)}
                >
                  <span className="ax-template__name">{template.name}</span>
                  <span className="ax-template__tag">{template.tagline}</span>
                </button>
              ))}
            </div>
          </section>

          <div className="ax-form__grid">
            <Field label="Display name" hint="Shown in lists and chat. Spaces are fine.">
              <TextInput
                value={draft.display_name || ''}
                placeholder="Research Analyst"
                onChange={(e) => changeDisplayName(e.target.value)}
                autoFocus
              />
            </Field>
            <Field label="Handle" hint="Unique @mention. Auto-generated from the display name.">
              <TextInput
                value={draft.name || ''}
                placeholder="research-analyst"
                onChange={(e) => changeHandle(e.target.value)}
              />
            </Field>
          </div>
          {handle && !handleValid && (
            <div className="ax-error-text">Handle must be 1–64 letters, digits, dashes or underscores.</div>
          )}

          <Field label="Title / role" hint="e.g. Research Analyst, Code Reviewer.">
            <TextInput
              value={draft.title || ''}
              onChange={(e) => patch({ title: e.target.value })}
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

          <Field label="Personality / style" hint="Pick a preset or write your own.">
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

      {step === 1 && (
        <div className="ax-form">
          <Field label="Primary goal / standing mission">
            <TextArea
              rows={3}
              value={draft.goal || ''}
              onChange={(e) => patch({ goal: e.target.value })}
              placeholder="Keep me ahead of AI research and send a concise brief every morning."
            />
          </Field>
          <Field label="Custom instructions" hint="Detailed behavior, constraints and output format.">
            <TextArea
              rows={8}
              value={draft.custom_instructions || ''}
              onChange={(e) => patch({ custom_instructions: e.target.value })}
              placeholder="You are a rigorous research analyst. Always cite sources and flag uncertainty…"
            />
          </Field>
          <Field label="Effective system prompt" hint="Preview of what the agent will receive.">
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
          <details className="ax-advanced">
            <summary>Advanced</summary>
            <div className="ax-form__grid">
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
            </div>
            <Field label="Success criteria">
              <TextArea
                rows={2}
                value={draft.success_criteria || ''}
                onChange={(e) => patch({ success_criteria: e.target.value })}
              />
            </Field>
          </details>
        </div>
      )}

      {step === 2 && (
        <div className="ax-tools">
          <div className="ax-tools__bar">
            <TextInput
              placeholder="Search tools…"
              value={toolQuery}
              onChange={(e) => setToolQuery(e.target.value)}
            />
            <Chip>
              {(draft.tools || []).length} selected
              {skillTools.size > 0 ? ` + ${skillTools.size} from skills` : ''}
            </Chip>
          </div>

          <section className="ax-form__section">
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
          </section>

          {skills.length > 0 && (
            <div className="ax-tier">
              <div className="ax-tier__head">
                <span className="ax-tier__name">Skills</span>
                <span className="ax-tier__sub">Reusable behavior bundles</span>
              </div>
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
            </div>
          )}

          {[1, 2, 3].map((tier) => {
            const items = groupedTools[tier] || [];
            if (items.length === 0) return null;
            return (
              <div key={tier} className="ax-tier">
                <div className="ax-tier__head">
                  <span className="ax-tier__name">
                    Tier {tier} <Badge tone={tierTone(tier)}>{tierRisk(tier)}</Badge>
                  </span>
                  <span className="ax-tier__sub">
                    {tier === 1
                      ? 'Read-only and safe'
                      : tier === 2
                        ? 'Writes or executes — may ask for approval'
                        : 'Privileged system access'}
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
        </div>
      )}

      {step === 3 && (
        <div className="ax-form">
          <section className="ax-form__section">
            <h4 className="ax-form__title">Autonomy level</h4>
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

          <section className="ax-form__section">
            <h4 className="ax-form__title">Trigger</h4>
            <SegmentedControl
              value={runMode}
              onChange={(v) => patch({ run_mode: v })}
              options={[
                { value: 'on_demand', label: 'On demand' },
                { value: 'scheduled', label: 'Scheduled' },
                { value: 'watcher', label: 'Watcher' },
                { value: 'webhook', label: 'Webhook' },
              ]}
            />
            {runMode === 'scheduled' && (
              <Field label="Cron schedule">
                <CronEditor value={draft.schedule || ''} onChange={(v) => patch({ schedule: v })} />
              </Field>
            )}
            {runMode === 'watcher' && (
              <Field label="Watcher pattern" hint="Glob relative to the primary knowledge base.">
                <TextInput
                  value={draft.watcher_pattern || ''}
                  placeholder="*.md"
                  onChange={(e) => patch({ watcher_pattern: e.target.value })}
                />
              </Field>
            )}
            {runMode === 'webhook' && (
              <div className="ax-settings__hint">
                A webhook URL will be available in the agent’s settings after creation.
              </div>
            )}
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
              <Field label="Max concurrent runs">
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
          </section>
        </div>
      )}

      {step === 4 && (
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
            {scope.mode === 'project' && (
              <>
                <Field label="Primary knowledge base">
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
              <>
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
                <div className="ax-settings__hint">
                  Reads every configured knowledge base. Writes go to the primary base only.
                </div>
              </>
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
            {memoryMode === 'shared' && (
              <div className="ax-settings__warning">
                <AlertTriangle size={14} />
                <span>This agent will share one memory pool with every other shared-memory agent.</span>
              </div>
            )}
          </section>
        </div>
      )}

      {step === 5 && (
        <div className="ax-review">
          <div className="ax-review__hero">
            <AgentAvatar
              config={draft.avatar_config}
              type={draft.avatar_type === 'upload' ? 'upload' : 'bot'}
              upload={draft.avatar_upload}
              size={72}
            />
            <div className="ax-review__hero-body">
              <div className="ax-review__name">{displayName || 'Untitled agent'}</div>
              <div className="ax-review__title">
                {draft.title || 'No role set'} · @{handle || 'handle'}
              </div>
              {draft.description && <div className="ax-review__desc">{draft.description}</div>}
            </div>
          </div>

          <div className="ax-review__grid">
            <div className="ax-review__row">
              <span className="ax-review__label">Tools</span>
              <div className="ax-review__value">
                {(draft.tools || []).length === 0 ? (
                  <span className="ax-review__muted">None selected</span>
                ) : (
                  <div className="ax-review__tags">
                    {(draft.tools || []).map((id) => {
                      const t = tools[id];
                      return (
                        <span key={id} className="ax-review__tag">
                          <span>{id}</span>
                          {t && <Badge tone={tierTone(t.tier)}>{tierRisk(t.tier)}</Badge>}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Autonomy</span>
              <span className="ax-review__value">
                {AUTONOMY_OPTIONS.find((o) => o.value === autonomy)?.title}
                {approvalTools.length > 0 ? ` · asks for ${approvalTools.length} tool${approvalTools.length === 1 ? '' : 's'}` : ''}
              </span>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Memory</span>
              <span className="ax-review__value">
                {MEMORY_OPTIONS.find((o) => o.value === memoryMode)?.title}
              </span>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Knowledge</span>
              <span className="ax-review__value">
                {KNOWLEDGE_OPTIONS.find((o) => o.value === scope.mode)?.title}
                {scope.mode === 'project' && scope.primary_field ? ` · ${scope.primary_field}` : ''}
                {scope.extra_fields.length > 0 ? ` · +${scope.extra_fields.length} read-only` : ''}
              </span>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Trigger</span>
              <span className="ax-review__value">
                {runMode}
                {runMode === 'scheduled' && draft.schedule ? ` · ${draft.schedule}` : ''}
                {runMode === 'watcher' && draft.watcher_pattern ? ` · ${draft.watcher_pattern}` : ''}
              </span>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Limits</span>
              <span className="ax-review__value">
                {draft.max_concurrent_runs ?? 1} concurrent · {draft.max_iterations ?? 15} steps/run
              </span>
            </div>
            <div className="ax-review__row">
              <span className="ax-review__label">Model</span>
              <span className="ax-review__value">{draft.model || 'workspace default'}</span>
            </div>
          </div>

          {blockedTools.length > 0 && (
            <div className="ax-settings__warning">
              <AlertTriangle size={14} />
              <span>
                {blockedTools.length} selected tool{blockedTools.length === 1 ? '' : 's'} will be
                blocked by the current gates. Go back to Capabilities to fix the access.
              </span>
            </div>
          )}

          <div className="ax-form__section">
            <h4 className="ax-form__title">Effective system prompt</h4>
            <pre className="ax-settings__prompt">{composeSystemPrompt(draft) || 'No instructions yet.'}</pre>
          </div>
        </div>
      )}
      </div>
    </Modal>
  );
}
